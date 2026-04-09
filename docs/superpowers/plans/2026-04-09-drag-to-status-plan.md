# Implementation Plan: Drag-to-Status

Spec: `docs/superpowers/specs/2026-04-09-drag-to-status-design.md`

## Steps

### 1. CSS — добавить стили для drag

В `<style>` добавить:

```css
/* Drop zone (пустая секция во время drag) */
.drop-zone {
  border: 2px dashed #ccc;
  border-radius: 12px;
  height: 60px;
  margin-bottom: 8px;
  transition: border-color 0.15s, background 0.15s;
}
.drop-zone.drag-over {
  border-color: #6c8ebf;
  background: rgba(108,142,191,0.08);
}

/* Секция, выделенная как цель drop */
.status-section.drag-over .section-header {
  color: #6c8ebf;
}

/* Placeholder на месте перетаскиваемой карточки */
.card-placeholder {
  height: 72px; /* примерная высота .card */
  border: 2px dashed #ccc;
  border-radius: 12px;
  margin-bottom: 8px;
}

/* Ghost-карточка */
#drag-ghost {
  position: fixed;
  pointer-events: none;
  z-index: 1000;
  opacity: 0.85;
  transform: scale(1.03);
  box-shadow: 0 8px 24px rgba(0,0,0,0.18);
  width: var(--ghost-width);
}
```

---

### 2. JS — добавить `dragState`

После `const state = ...` добавить:

```js
const dragState = {
  active: false,
  orderId: null,
  sourceStatus: null,
  ghost: null,
  startX: 0,
  startY: 0,
  offsetX: 0,
  offsetY: 0,
};
```

---

### 3. JS — три функции drag

```js
function startDrag(e, order, cardEl) {
  const rect = cardEl.getBoundingClientRect();
  dragState.orderId = order.id;
  dragState.sourceStatus = order.status || 'Очередь';
  dragState.startX = e.clientX;
  dragState.startY = e.clientY;
  dragState.offsetX = e.clientX - rect.left;
  dragState.offsetY = e.clientY - rect.top;

  // Ghost
  const ghost = cardEl.cloneNode(true);
  ghost.id = 'drag-ghost';
  ghost.style.setProperty('--ghost-width', rect.width + 'px');
  ghost.style.left = (e.clientX - dragState.offsetX) + 'px';
  ghost.style.top  = (e.clientY - dragState.offsetY) + 'px';
  document.body.appendChild(ghost);
  dragState.ghost = ghost;

  // Placeholder
  const ph = document.createElement('div');
  ph.className = 'card-placeholder';
  ph.style.height = rect.height + 'px';
  cardEl.replaceWith(ph);
  dragState.placeholder = ph;

  dragState.active = true;
  renderOrders(); // перерисовать, чтобы показать пустые секции
  document.addEventListener('pointermove', onDragMove);
  document.addEventListener('pointerup', onDragEnd);
}

function onDragMove(e) {
  if (!dragState.active) return;
  dragState.ghost.style.left = (e.clientX - dragState.offsetX) + 'px';
  dragState.ghost.style.top  = (e.clientY - dragState.offsetY) + 'px';

  // Подсветить секцию под пальцем
  document.querySelectorAll('.status-section').forEach(sec => {
    const r = sec.getBoundingClientRect();
    const over = e.clientX >= r.left && e.clientX <= r.right &&
                 e.clientY >= r.top  && e.clientY <= r.bottom;
    sec.classList.toggle('drag-over', over);
    const dz = sec.querySelector('.drop-zone');
    if (dz) dz.classList.toggle('drag-over', over);
  });
}

async function onDragEnd(e) {
  if (!dragState.active) return;
  document.removeEventListener('pointermove', onDragMove);
  document.removeEventListener('pointerup', onDragEnd);

  // Найти целевую секцию
  let targetStatus = null;
  document.querySelectorAll('.status-section').forEach(sec => {
    if (sec.classList.contains('drag-over')) {
      targetStatus = sec.dataset.status;
    }
  });

  // Убрать ghost
  dragState.ghost.remove();
  dragState.ghost = null;
  dragState.active = false;

  if (targetStatus && targetStatus !== dragState.sourceStatus) {
    const order = state.orders.find(o => String(o.id) === String(dragState.orderId));
    if (order) {
      order.status = targetStatus;
      renderOrders();
      await apiPost({ action: 'updateStatus', id: order.id, status: targetStatus });
    }
  } else {
    renderOrders();
  }

  dragState.orderId = null;
  dragState.sourceStatus = null;
}
```

---

### 4. JS — изменить `renderOrders()`

**4a.** Заменить `if (!list.length) return;` на логику с drop-зоной:

```js
STATUS_ORDER.forEach(status => {
  const list = grouped[status];
  if (!list.length && !dragState.active) return; // скрывать пустые только не во время drag

  html += `<div class="status-section" data-status="${status}">`;
  html += `<div class="section-header">${status}</div>`;

  if (!list.length) {
    html += `<div class="drop-zone"></div>`;
  } else {
    list.forEach(o => {
      // ... существующий код карточки без изменений ...
    });
  }

  html += `</div>`;
});
```

**4b.** Обернуть каждую секцию в `<div class="status-section" data-status="...">`.

**4c.** Изменить привязку событий — добавить `pointerdown` с порогом:

```js
el.querySelectorAll('.card[data-id]').forEach(card => {
  let moved = false;
  card.addEventListener('pointerdown', e => {
    moved = false;
    const startX = e.clientX, startY = e.clientY;
    const order = state.orders.find(o => String(o.id) === String(card.dataset.id));

    function onMove(ev) {
      if (Math.abs(ev.clientX - startX) > 10 || Math.abs(ev.clientY - startY) > 10) {
        moved = true;
        card.removeEventListener('pointermove', onMove);
        card.removeEventListener('pointerup', onUp);
        startDrag(e, order, card);
      }
    }
    function onUp() {
      card.removeEventListener('pointermove', onMove);
      card.removeEventListener('pointerup', onUp);
      if (!moved) openOrderDetail(card.dataset.id, state.orders);
    }

    card.addEventListener('pointermove', onMove);
    card.addEventListener('pointerup', onUp);
  });
});
```

---

### 5. Проверить вручную

- [ ] Тап — открывает детали
- [ ] Drag — ghost следует за пальцем
- [ ] Пустые секции видны при drag
- [ ] Секция подсвечивается при наведении
- [ ] Статус меняется, API вызывается
- [ ] Отпустить на той же секции — ничего не меняется
- [ ] Скролл страницы не сломан
