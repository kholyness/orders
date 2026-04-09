# Drag-to-Status: Вертикальный канбан

**Date:** 2026-04-09  
**Status:** Approved

## Суть

Пользователь может изменить статус заказа, перетащив карточку в другую секцию на вкладке "Заказы". Секции расположены вертикально в порядке `STATUS_ORDER`.

## Взаимодействие

1. Нажать и начать тянуть карточку — drag активируется после порога 10px
2. Появляется ghost-карточка (полупрозрачная, `opacity: 0.85`, `scale: 1.03`), следует за пальцем
3. На месте оригинала — placeholder с пунктирной рамкой того же размера
4. Все 4 секции видны: пустые показывают блок с заголовком статуса и пунктирной drop-зоной внутри
5. Секция под ghost — подсвечивается лёгким фоном
6. `pointerup`:
   - статус изменился → вызов `apiPost({ action: 'updateStatus', id, status })`, карточка перемещается
   - статус не изменился → карточка возвращается на место
7. Тап без движения (< 10px) — по-прежнему открывает детали заказа

## Состояние

```js
const dragState = {
  active: false,
  orderId: null,
  sourceStatus: null,
  ghost: null,        // DOM-элемент ghost
  offsetX: 0,        // смещение пальца относительно карточки
  offsetY: 0,
};
```

## Изменения в коде (`index.html`)

### `renderOrders()`
- Если `dragState.active === true` — показывать все 4 секции из `STATUS_ORDER`, включая пустые (с drop-зоной)
- Иначе — текущее поведение (пустые секции скрыты)

### Привязка событий на `.card`
- `pointerdown` — начало отслеживания drag
- `onclick` сохраняется: если движения не было — открывает детали

### Drag-логика (отдельные функции)
- `onPointerDown(e, order)` — запоминает start position, orderId, sourceStatus
- `onPointerMove(e)` — если `> 10px`: создаёт ghost, скрывает оригинал, ставит `dragState.active = true`, перерисовывает секции
- `onPointerUp(e)` — определяет секцию под пальцем, вызывает API при смене статуса, убирает ghost, перерисовывает

### Ghost
- Клон `.card` с `position: fixed`, `pointer-events: none`, `z-index: 1000`
- Позиционируется через `left/top` в `onPointerMove`

### Drop-зона (пустая секция)
```html
<div class="section-header">Пауза</div>
<div class="drop-zone"></div>
```
```css
.drop-zone {
  border: 2px dashed #ccc;
  border-radius: 12px;
  height: 60px;
  margin-bottom: 8px;
}
.drop-zone.drag-over {
  border-color: #6c8ebf;
  background: rgba(108,142,191,0.08);
}
```

## Ограничения

- Только вкладка "Заказы" (не Архив)
- Drag не должен мешать скроллу страницы — используем `e.preventDefault()` только после активации drag (порог 10px)
- `touch-action: pan-y` на карточках до активации drag
