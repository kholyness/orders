# Moroska Mini App — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Telegram Mini App for personal order management, backed by Google Sheets via Apps Script.

**Architecture:** Single `index.html` (Vanilla JS + HTML/CSS) on Netlify. The existing Google Apps Script is extended with `doGet` for reading and new `doPost` action handlers for writing. Frontend makes `fetch()` calls to the Apps Script URL.

**Tech Stack:** Vanilla JS, HTML5, CSS3 (Telegram CSS vars), Google Apps Script, Google Sheets, Netlify.

---

## File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `index.html` | Modify (full rewrite) | Entire frontend: HTML shell, all CSS, all JS (tabs, API, sheets) |
| `google-apps-script.js` | Create (reference only — paste into script.google.com) | Full updated Apps Script with doGet + new doPost actions |

---

## Task 1: Prepare Google Sheets (manual steps)

**Files:**
- No code files — changes made directly in Google Sheets UI

- [ ] **Step 1: Rename sheets**

  In Google Sheets (https://docs.google.com/spreadsheets/d/1ampBYsbwc4DyqWAVKCCu5YtuPYeCLu8sItBM7wY00Mk/):
  - Right-click the "В работе" tab → Rename → type `Actual`
  - Right-click the "Архив" tab → Rename → type `Archive`

- [ ] **Step 2: Add new column headers to Actual sheet**

  In the `Actual` sheet, row 1:
  - Cell L1: type `Артикул`
  - Cell M1: type `Тип`

- [ ] **Step 3: Add new column headers to Archive sheet**

  In the `Archive` sheet, row 1:
  - Cell L1: type `Артикул`
  - Cell M1: type `Тип`

- [ ] **Step 4: Verify structure**

  Both sheets should now have headers in row 1:
  `ID | Дата создания | Имя | Изделие | Детали | Цена | Срок | Статус | Фото | Заметка | Модель | Артикул | Тип`

---

## Task 2: Updated Google Apps Script

**Files:**
- Create: `google-apps-script.js` (reference file — paste content into script.google.com)

- [ ] **Step 1: Create reference file**

  Create `google-apps-script.js` at the project root with the full updated script below.
  This is the complete replacement for the current script — paste it into the Apps Script editor.

```javascript
const TOKEN = '8702600937:AAFeUmvzqHj6iHSsj9krohdMcbtQBXfp_V8';
const SHEET_ID = SpreadsheetApp.getActiveSpreadsheet().getId();
const PARENT_FOLDER_ID = '1Yk4GZbivKwP0ARci4phheiTJX5lBMdRf';
const MY_CHAT_ID = '266696995';

// ─── MINI APP: READ ENDPOINTS ───────────────────────────────────────────────

function doGet(e) {
  const action = (e.parameter && e.parameter.action) || '';
  const ss = SpreadsheetApp.openById(SHEET_ID);
  const mainSheet = ss.getSheetByName('Actual');
  const archiveSheet = ss.getSheetByName('Archive');

  let result;
  if (action === 'getOrders') {
    result = { orders: sheetToObjects(mainSheet) };
  } else if (action === 'getArchive') {
    result = { orders: sheetToObjects(archiveSheet) };
  } else if (action === 'getStats') {
    result = buildStats(mainSheet, archiveSheet);
  } else {
    result = { error: 'Unknown action: ' + action };
  }

  return ContentService
    .createTextOutput(JSON.stringify(result))
    .setMimeType(ContentService.MimeType.JSON);
}

function sheetToObjects(sheet) {
  const rows = sheet.getDataRange().getValues();
  if (rows.length < 2) return [];
  const keys = ['id','date','name','item','details','price','deadline','status','photo','note','model','article','type'];
  return rows.slice(1)
    .filter(r => r[0] !== '' && r[0] !== null)
    .map(row => {
      const obj = {};
      keys.forEach((k, i) => {
        let val = row[i] !== undefined ? row[i] : '';
        if (val instanceof Date) {
          val = Utilities.formatDate(val, 'GMT+2', 'dd.MM.yyyy');
        }
        obj[k] = String(val);
      });
      return obj;
    });
}

function buildStats(mainSheet, archiveSheet) {
  const active = sheetToObjects(mainSheet);
  const archived = sheetToObjects(archiveSheet);
  const all = active.concat(archived);

  // Income from archive
  const income = archived.reduce((sum, r) => sum + (parseFloat(r.price) || 0), 0);

  // Type counts across all
  let typeOrder = 0, typeStock = 0;
  all.forEach(r => {
    if (r.type === 'Наличие') typeStock++;
    else typeOrder++;
  });

  // Model counts across all
  const modelCounts = {};
  all.forEach(r => {
    const m = r.model || 'Не указана';
    if (m && m !== 'Не указана') modelCounts[m] = (modelCounts[m] || 0) + 1;
  });
  const topModels = Object.entries(modelCounts)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 5)
    .map(([name, count]) => ({ name, count }));

  // Deadlines within next 7 days (from active only)
  const today = new Date();
  const nextWeek = new Date(); nextWeek.setDate(today.getDate() + 7);
  const upcomingDeadlines = active.filter(r => {
    if (!r.deadline) return false;
    const parts = r.deadline.split('.');
    if (parts.length < 3) return false;
    const d = new Date(parts[2], parts[1] - 1, parts[0]);
    return d >= today && d <= nextWeek;
  }).map(r => ({ id: r.id, name: r.name, deadline: r.deadline }));

  return {
    activeCount: active.length,
    archiveCount: archived.length,
    typeOrder,
    typeStock,
    income,
    topModels,
    upcomingDeadlines,
  };
}

// ─── MINI APP: WRITE ENDPOINTS ──────────────────────────────────────────────

function handleMiniAppPost(data) {
  const ss = SpreadsheetApp.openById(SHEET_ID);
  const mainSheet = ss.getSheetByName('Actual');
  const archiveSheet = ss.getSheetByName('Archive');
  let result;

  if (data.action === 'createOrder') {
    result = createOrderFromApp(data, mainSheet);
  } else if (data.action === 'updateOrder') {
    result = updateOrderFromApp(data, mainSheet);
  } else if (data.action === 'updateStatus') {
    const ok = updateStatusInSheet(data.id, data.status, mainSheet);
    if (data.status === 'Отдано') {
      moveToArchive(data.id, mainSheet, archiveSheet);
    }
    result = { success: ok };
  } else if (data.action === 'archiveOrder') {
    result = { success: moveToArchive(data.id, mainSheet, archiveSheet) };
  } else {
    result = { error: 'Unknown mini app action: ' + data.action };
  }

  return ContentService
    .createTextOutput(JSON.stringify(result))
    .setMimeType(ContentService.MimeType.JSON);
}

function createOrderFromApp(data, sheet) {
  const id = sheet.getLastRow() < 2
    ? 1
    : parseInt(sheet.getRange(sheet.getLastRow(), 1).getValue()) + 1;

  const folder = DriveApp.getFolderById(PARENT_FOLDER_ID)
    .createFolder('#' + id + '_' + (data.name || 'Заказ'));

  const dateOnly = Utilities.formatDate(new Date(), 'GMT+2', 'dd.MM.yyyy');
  sheet.appendRow([
    id,
    dateOnly,
    data.name || '',
    data.item || '',
    data.details || '',
    data.price || '',
    data.deadline || '',
    'Очередь',
    folder.getUrl(),
    data.comment || '',
    data.model || '',
    data.article || '',
    data.type || 'Заказ',
  ]);

  return { success: true, id: id, folderUrl: folder.getUrl() };
}

function updateOrderFromApp(data, sheet) {
  const rows = sheet.getDataRange().getValues();
  const fieldMap = {
    name: 3, item: 4, details: 5, price: 6,
    deadline: 7, status: 8, note: 10, model: 11,
    article: 12, type: 13,
  };
  for (let i = 1; i < rows.length; i++) {
    if (String(rows[i][0]) === String(data.id)) {
      Object.entries(fieldMap).forEach(([key, col]) => {
        if (data[key] !== undefined) sheet.getRange(i + 1, col).setValue(data[key]);
      });
      return { success: true };
    }
  }
  return { success: false, error: 'Not found' };
}

// ─── MAIN ENTRY POINT ───────────────────────────────────────────────────────

function doPost(e) {
  let data;
  try { data = JSON.parse(e.postData.contents); } catch (err) { return; }

  // Mini App requests have an `action` field
  if (data.action) {
    return handleMiniAppPost(data);
  }

  // ── Telegram Bot ──────────────────────────────────────────────────────────
  if (!data.message) return;

  const chatId = data.message.chat.id;
  const text = (data.message.text || data.message.caption || '').trim();
  const photo = data.message.photo;

  try {
    const ss = SpreadsheetApp.openById(SHEET_ID);
    const mainSheet = ss.getSheetByName('Actual');
    const archiveSheet = ss.getSheetByName('Archive') || ss.insertSheet('Archive');

    if (text === '/new' || text === '/start') {
      const modelsList = 'Lada, Larna, Verbena, Ilma, ролл, тарелочка, мусорничка, чехол пяльца, чехол рама, Taloma, Tala, Loboda';
      const msg = '🧶 <b>Шаблон Moroska:</b>\n\nНовый заказ\nИмя: \nИзделие: \nМодель: \nДетали: \nЦена: \nСрок: \nКомментарий: \n\n💡 <b>Твои модели:</b>\n<i>' + modelsList + '</i>';
      sendMsg(chatId, msg);
      return;
    }

    if (text.toLowerCase() === '/work') { sendMsg(chatId, getWorkReport(mainSheet)); return; }
    if (text.toLowerCase() === '/buy') { sendMsg(chatId, getBuyReport(mainSheet)); return; }
    if (text.toLowerCase() === '/money') { sendMsg(chatId, getMoneyReport(archiveSheet)); return; }
    if (text.toLowerCase() === '/week') { sendMsg(chatId, getWeekReport(mainSheet)); return; }

    if (text.toLowerCase().startsWith('/models')) {
      const arg = text.split(' ')[1];
      sendMsg(chatId, getModelsStat(mainSheet, archiveSheet, arg));
      return;
    }

    const statusMatch = text.toLowerCase().match(/^(в работе|пауза|готово|отдано)\s+(\d+)$/);
    if (statusMatch) {
      const label = statusMatch[1];
      const id = statusMatch[2];
      const finalStatus = label.charAt(0).toUpperCase() + label.slice(1);
      if (label === 'отдано') {
        const res = moveToArchive(id, mainSheet, archiveSheet);
        sendMsg(chatId, res ? '📦 Заказ <b>#' + id + '</b> перенесен в архив!' : '❌ Не найден.');
      } else {
        const res = updateStatusInSheet(id, finalStatus, mainSheet);
        if (res && photo) savePhotoToFolder(id, photo, mainSheet, finalStatus);
        sendMsg(chatId, res ? '✅ <b>#' + id + '</b> статус: ' + finalStatus : '❌ Не найден.');
      }
      return;
    }

    if (text.toLowerCase().includes('новый заказ')) {
      addNewOrder(chatId, text, photo, mainSheet);
      return;
    }

    if (text.match(/^\d+$/) && photo) {
      const res = savePhotoToFolder(text, photo, mainSheet, 'Процесс');
      sendMsg(chatId, res ? '📸 Фото сохранено в <b>#' + text + '</b>' : '❌ Не найден.');
      return;
    }

  } catch (err) {
    sendMsg(chatId, '⚠️ Ошибка: ' + err.message);
  }
}

// ─── BOT REPORT FUNCTIONS (unchanged) ───────────────────────────────────────

function getWorkReport(sheet) {
  const rows = sheet.getDataRange().getValues();
  let inWork = [], queue = [], ready = [];
  rows.slice(1).forEach(row => {
    if (!row[0]) return;
    const status = (row[7] || '').toString().toLowerCase();
    const line = '• <b>#' + row[0] + '</b> ' + row[2] + ' — <i>' + row[3] + '</i> <a href="' + row[8] + '">[Папка]</a>';
    if (status === 'в работе') inWork.push(line);
    else if (status === 'готово') ready.push(line);
    else queue.push(line);
  });
  return '🔵 <b>В РАБОТЕ:</b>\n' + (inWork.join('\n') || '<i>пусто</i>') + '\n\n' +
         '⚪ <b>ОЧЕРЕДЬ:</b>\n' + (queue.join('\n') || '<i>пусто</i>') + '\n\n' +
         '🟢 <b>ГОТОВО:</b>\n' + (ready.join('\n') || '<i>пусто</i>');
}

function getWeekReport(sheet) {
  const rows = sheet.getDataRange().getValues();
  let list = [];
  const today = new Date();
  const nextWeek = new Date(); nextWeek.setDate(today.getDate() + 7);
  rows.slice(1).forEach(row => {
    let d = row[6];
    if (d instanceof Date && d <= nextWeek && d >= today) {
      let line = '📅 <b>#' + row[0] + '</b> — ' + row[2] + ' — <i>' + (row[3] || '') + '</i> <a href="' + row[8] + '">[Папка]</a>\n';
      line += '      └ <b>Срок: ' + d.toLocaleDateString('ru-RU') + '</b>';
      list.push(line);
    }
  });
  return list.length > 0 ? '🗓 <b>ПЛАН НА НЕДЕЛЮ:</b>\n\n' + list.join('\n\n') : '🏖 Дедлайнов нет!';
}

function getModelsStat(mainSheet, archiveSheet, monthArg) {
  let stats = {};
  const now = new Date();
  let targetMonth = null;
  if (monthArg) {
    const months = { 'янв':0,'фев':1,'мар':2,'апр':3,'май':4,'июн':5,'июл':6,'авг':7,'сен':8,'окт':9,'ноя':10,'дек':11,'01':0,'02':1,'03':2,'04':3,'05':4,'06':5,'07':6,'08':7,'09':8,'10':9,'11':10,'12':11 };
    for (let key in months) { if (monthArg.toLowerCase().startsWith(key)) { targetMonth = months[key]; break; } }
  }
  [mainSheet, archiveSheet].forEach(s => {
    s.getDataRange().getValues().slice(1).forEach(row => {
      let date = row[1];
      let model = row[10] ? String(row[10]).trim() : '';
      if (!model || model === 'Не указана') return;
      let orderDate = (date instanceof Date) ? date : new Date(date.split('.')[2], date.split('.')[1]-1, date.split('.')[0]);
      if (targetMonth !== null) {
        if (orderDate.getMonth() === targetMonth && orderDate.getFullYear() === now.getFullYear())
          stats[model] = (stats[model] || 0) + 1;
      } else { stats[model] = (stats[model] || 0) + 1; }
    });
  });
  let sorted = Object.entries(stats).sort((a,b) => b[1]-a[1]);
  let title = targetMonth !== null ? '📊 СТАТИСТИКА ЗА ' + monthArg.toUpperCase() : '📊 РЕЙТИНГ МОДЕЛЕЙ (ВСЕ)';
  let msg = title + ':\n\n';
  if (sorted.length === 0) return '❌ Нет данных за этот период.';
  sorted.forEach(item => { msg += '• ' + item[0] + ': <b>' + item[1] + ' шт.</b>\n'; });
  return msg;
}

function addNewOrder(chatId, text, photo, sheet) {
  const lines = text.split('\n');
  let d = { name:'Имя', item:'Изделие', model:'Не указана', details:'', price:'0', deadline:'', comment:'' };
  lines.forEach(l => {
    const val = l.split(':')[1]?.trim();
    if (l.includes('Имя:')) d.name = val;
    if (l.includes('Изделие:')) d.item = val;
    if (l.includes('Модель:')) d.model = val;
    if (l.includes('Детали:')) d.details = val;
    if (l.includes('Цена:')) d.price = val;
    if (l.includes('Срок:')) d.deadline = val;
    if (l.includes('Комментарий:')) d.comment = val;
  });
  const id = sheet.getLastRow() < 2 ? 1 : parseInt(sheet.getRange(sheet.getLastRow(), 1).getValue()) + 1;
  const folder = DriveApp.getFolderById(PARENT_FOLDER_ID).createFolder('#' + id + '_' + d.name);
  if (photo) saveFileToDrive(photo[photo.length-1].file_id, 'Эскиз_' + id, folder);
  const dateOnly = Utilities.formatDate(new Date(), 'GMT+2', 'dd.MM.yyyy');
  sheet.appendRow([id, dateOnly, d.name, d.item, d.details, d.price, d.deadline, 'Очередь', folder.getUrl(), d.comment, d.model, '', '']);
  sendMsg(chatId, '✅ Заказ <b>#' + id + '</b> добавлен!\nМодель: <b>' + d.model + '</b>');
}

function updateStatusInSheet(id, status, sheet) {
  const rows = sheet.getDataRange().getValues();
  for (let i = 1; i < rows.length; i++) {
    if (String(rows[i][0]) === String(id)) { sheet.getRange(i + 1, 8).setValue(status); return true; }
  }
  return false;
}

function moveToArchive(id, mainSheet, archiveSheet) {
  const rows = mainSheet.getDataRange().getValues();
  for (let i = 1; i < rows.length; i++) {
    if (String(rows[i][0]) === String(id)) {
      const data = mainSheet.getRange(i + 1, 1, 1, 13).getValues()[0];
      data[7] = 'Отдано';
      archiveSheet.appendRow(data);
      mainSheet.deleteRow(i + 1);
      return true;
    }
  }
  return false;
}

function savePhotoToFolder(id, photo, sheet, prefix) {
  const rows = sheet.getDataRange().getValues();
  for (let i = 1; i < rows.length; i++) {
    if (String(rows[i][0]) === String(id)) {
      const fId = rows[i][8].split('id=')[1] || rows[i][8].split('folders/')[1];
      const folder = DriveApp.getFolderById(fId);
      saveFileToDrive(photo[photo.length-1].file_id, prefix + '_' + id, folder);
      return true;
    }
  }
  return false;
}

function saveFileToDrive(fId, name, folder) {
  const res = UrlFetchApp.fetch('https://api.telegram.org/bot' + TOKEN + '/getFile?file_id=' + fId);
  const path = JSON.parse(res.getContentText()).result.file_path;
  const blob = UrlFetchApp.fetch('https://api.telegram.org/file/bot' + TOKEN + '/' + path).getBlob().setName(name);
  folder.createFile(blob);
}

function sendMsg(chatId, text) {
  UrlFetchApp.fetch('https://api.telegram.org/bot' + TOKEN + '/sendMessage', {
    method: 'post', contentType: 'application/json',
    payload: JSON.stringify({ chat_id: chatId, text: String(text), parse_mode: 'HTML', disable_web_page_preview: true })
  });
}

function getBuyReport(sheet) {
  const rows = sheet.getDataRange().getValues();
  let list = [];
  rows.slice(1).forEach(row => {
    let det = String(row[4] || '').toLowerCase();
    if (det.includes('купить') || det.includes('нет в наличии')) {
      list.push('🛒 <b>#' + row[0] + '</b> (' + row[2] + ')\n      └ ' + row[4]);
    }
  });
  return list.length > 0 ? list.join('\n') : '✅ Все в наличии!';
}

function getMoneyReport(archiveSheet) {
  const rows = archiveSheet.getDataRange().getValues();
  let total = 0;
  for (let i = 1; i < rows.length; i++) { let p = parseFloat(rows[i][5]); if (!isNaN(p)) total += p; }
  return '💰 <b>Общий доход:</b> ' + total + ' RSD';
}

// ─── TRIGGERS ───────────────────────────────────────────────────────────────

function sendMondayReport() {
  const ss = SpreadsheetApp.openById(SHEET_ID);
  sendMsg(MY_CHAT_ID, '🚀 <b>ПОНЕДЕЛЬНИК: ПЛАН MOROSKA</b>\n\n' + getWorkReport(ss.getSheetByName('Actual')));
}

function sendMonthlyStats() {
  const ss = SpreadsheetApp.openById(SHEET_ID);
  const archived = ss.getSheetByName('Archive').getDataRange().getValues().slice(1);
  const income = archived.reduce((sum, row) => sum + (parseFloat(row[5]) || 0), 0);
  sendMsg(MY_CHAT_ID, '📊 <b>ИТОГИ МЕСЯЦА</b>\n✅ Завершено: <b>' + archived.length + '</b>\n💰 Доход: <b>' + income + ' RSD</b>');
}

function setWebhook() {
  const url = 'https://script.google.com/macros/s/AKfycbxMpD14ZU_6c2VrllFKWMB-52SIu1ClWVo79XhiT_ebXlx9In6OaxfRjDJomJuCGPvv/exec';
  UrlFetchApp.fetch('https://api.telegram.org/bot' + TOKEN + '/setWebhook?url=' + url);
}
```

- [ ] **Step 2: Paste into Apps Script editor**

  1. Open https://script.google.com and open the script linked to your spreadsheet
  2. Select all existing code and replace with the content of `google-apps-script.js`
  3. Click **Save** (Ctrl+S)

- [ ] **Step 3: Deploy new version**

  1. Click **Deploy** → **Manage deployments**
  2. Click the edit pencil on the existing deployment
  3. Under "Version" choose **New version**
  4. Click **Deploy**
  5. Copy the deployment URL — it should be the same as before: `https://script.google.com/macros/s/AKfycbxMpD14ZU_6c2VrllFKWMB-52SIu1ClWVo79XhiT_ebXlx9In6OaxfRjDJomJuCGPvv/exec`

- [ ] **Step 4: Test the doGet endpoint**

  Open this URL in your browser (replace with your actual deployment URL):
  ```
  https://script.google.com/macros/s/AKfycbxMpD14ZU_6c2VrllFKWMB-52SIu1ClWVo79XhiT_ebXlx9In6OaxfRjDJomJuCGPvv/exec?action=getOrders
  ```
  Expected: JSON response `{"orders": [...]}` with your current orders (or `{"orders": []}` if Actual is empty)

- [ ] **Step 5: Commit the reference file**

  ```bash
  git add google-apps-script.js
  git commit -m "feat: add updated Apps Script with doGet and mini app endpoints"
  ```

---

## Task 3: HTML Shell + CSS + Navigation

**Files:**
- Modify: `index.html` (full rewrite)

- [ ] **Step 1: Replace index.html with the app shell**

  Replace the entire contents of `index.html` with:

```html
<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0" />
  <title>Moroska Orders</title>
  <script src="https://telegram.org/js/telegram-web-app.js"></script>
  <style>
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

    :root {
      --bg: var(--tg-theme-bg-color, #ffffff);
      --bg-secondary: var(--tg-theme-secondary-bg-color, #f0f0f0);
      --text: var(--tg-theme-text-color, #000000);
      --hint: var(--tg-theme-hint-color, #999999);
      --link: var(--tg-theme-link-color, #2481cc);
      --accent: var(--tg-theme-button-color, #2481cc);
      --accent-text: var(--tg-theme-button-text-color, #ffffff);
      --tab-height: 56px;
      --sheet-radius: 16px;
    }

    body {
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
      background: var(--bg);
      color: var(--text);
      height: 100dvh;
      display: flex;
      flex-direction: column;
      overflow: hidden;
    }

    /* ── Main content area ── */
    #app {
      flex: 1;
      overflow-y: auto;
      -webkit-overflow-scrolling: touch;
      padding-bottom: 8px;
    }

    .tab-content { display: none; padding: 16px 16px 0; }
    .tab-content.active { display: block; }

    /* ── Tab bar ── */
    #tab-bar {
      height: var(--tab-height);
      display: flex;
      background: var(--bg);
      border-top: 1px solid var(--bg-secondary);
      flex-shrink: 0;
    }

    .tab-btn {
      flex: 1;
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      gap: 2px;
      background: none;
      border: none;
      color: var(--hint);
      font-size: 10px;
      cursor: pointer;
      transition: color 0.15s;
    }

    .tab-btn.active { color: var(--accent); }
    .tab-btn .tab-icon { font-size: 22px; line-height: 1; }

    /* ── Cards ── */
    .card {
      background: var(--bg-secondary);
      border-radius: 12px;
      padding: 12px 14px;
      margin-bottom: 10px;
      cursor: pointer;
      transition: opacity 0.1s;
      display: flex;
      align-items: center;
      justify-content: space-between;
    }
    .card:active { opacity: 0.7; }
    .card-main { flex: 1; }
    .card-id { font-size: 12px; color: var(--hint); margin-bottom: 2px; }
    .card-title { font-size: 15px; font-weight: 500; }
    .card-subtitle { font-size: 13px; color: var(--hint); margin-top: 2px; }
    .card-chevron { color: var(--hint); font-size: 18px; margin-left: 8px; }

    /* ── Status badge ── */
    .status-badge {
      display: inline-block;
      font-size: 11px;
      font-weight: 600;
      padding: 2px 8px;
      border-radius: 20px;
      margin-bottom: 12px;
    }
    .status-В.работе { background: #2481cc22; color: #2481cc; }
    .status-Очередь { background: #99999922; color: var(--hint); }
    .status-Пауза { background: #ff990022; color: #ff9900; }
    .status-Готово { background: #22c55e22; color: #22c55e; }
    .status-Отдано { background: #22c55e22; color: #22c55e; }

    /* ── Section headers ── */
    .section-header {
      font-size: 13px;
      font-weight: 600;
      color: var(--hint);
      text-transform: uppercase;
      letter-spacing: 0.05em;
      margin: 16px 0 8px;
    }
    .section-header:first-child { margin-top: 0; }

    /* ── Primary button ── */
    .btn-primary {
      display: block;
      width: 100%;
      padding: 14px;
      background: var(--accent);
      color: var(--accent-text);
      border: none;
      border-radius: 12px;
      font-size: 16px;
      font-weight: 600;
      cursor: pointer;
      text-align: center;
      transition: opacity 0.15s;
    }
    .btn-primary:active { opacity: 0.8; }

    .btn-secondary {
      display: block;
      width: 100%;
      padding: 12px;
      background: var(--bg-secondary);
      color: var(--text);
      border: none;
      border-radius: 12px;
      font-size: 15px;
      cursor: pointer;
      text-align: center;
      margin-top: 8px;
    }

    .btn-danger {
      display: block;
      width: 100%;
      padding: 12px;
      background: #ff3b3022;
      color: #ff3b30;
      border: none;
      border-radius: 12px;
      font-size: 15px;
      font-weight: 500;
      cursor: pointer;
      text-align: center;
      margin-top: 8px;
    }

    /* ── Overlay + Bottom sheet ── */
    #overlay {
      position: fixed; inset: 0;
      background: rgba(0,0,0,0.4);
      z-index: 100;
      opacity: 0;
      transition: opacity 0.25s;
      pointer-events: none;
    }
    #overlay.visible { opacity: 1; pointer-events: all; }

    #sheet {
      position: fixed;
      bottom: 0; left: 0; right: 0;
      background: var(--bg);
      border-radius: var(--sheet-radius) var(--sheet-radius) 0 0;
      z-index: 101;
      max-height: 90dvh;
      overflow-y: auto;
      transform: translateY(100%);
      transition: transform 0.3s cubic-bezier(0.32, 0.72, 0, 1);
      padding: 0 16px 32px;
    }
    #sheet.visible { transform: translateY(0); }

    .sheet-handle {
      width: 36px; height: 4px;
      background: var(--bg-secondary);
      border-radius: 2px;
      margin: 12px auto 16px;
    }

    /* ── Form fields ── */
    .field-group { margin-bottom: 14px; }
    .field-label { font-size: 13px; color: var(--hint); margin-bottom: 4px; }

    .field-input, .field-select, .field-textarea {
      width: 100%;
      padding: 10px 12px;
      background: var(--bg-secondary);
      border: none;
      border-radius: 10px;
      font-size: 15px;
      color: var(--text);
      outline: none;
      font-family: inherit;
    }
    .field-textarea { resize: none; min-height: 72px; }
    .field-select { appearance: none; -webkit-appearance: none; }

    /* ── Type toggle ── */
    .type-toggle { display: flex; gap: 8px; }
    .type-option {
      flex: 1; padding: 10px; text-align: center;
      background: var(--bg-secondary);
      border: 2px solid transparent;
      border-radius: 10px;
      cursor: pointer;
      font-size: 14px;
      font-weight: 500;
      transition: all 0.15s;
    }
    .type-option.selected { border-color: var(--accent); color: var(--accent); background: var(--bg); }

    /* ── Stats blocks ── */
    .stats-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-bottom: 14px; }
    .stat-card {
      background: var(--bg-secondary);
      border-radius: 12px;
      padding: 14px 12px;
      text-align: center;
    }
    .stat-value { font-size: 28px; font-weight: 700; color: var(--accent); }
    .stat-label { font-size: 12px; color: var(--hint); margin-top: 2px; }
    .stat-card.full { grid-column: 1 / -1; }

    .model-row {
      display: flex; align-items: center; justify-content: space-between;
      padding: 8px 0;
      border-bottom: 1px solid var(--bg-secondary);
    }
    .model-row:last-child { border-bottom: none; }

    /* ── Search ── */
    .search-wrap { position: relative; margin-bottom: 14px; }
    .search-input {
      width: 100%;
      padding: 10px 12px 10px 36px;
      background: var(--bg-secondary);
      border: none; border-radius: 10px;
      font-size: 15px; color: var(--text);
      outline: none; font-family: inherit;
    }
    .search-icon {
      position: absolute; left: 10px; top: 50%;
      transform: translateY(-50%);
      color: var(--hint); font-size: 16px;
    }

    /* ── Empty state ── */
    .empty {
      text-align: center; color: var(--hint);
      padding: 40px 16px; font-size: 15px;
    }

    /* ── Detail view ── */
    .detail-row {
      display: flex; align-items: flex-start;
      padding: 10px 0;
      border-bottom: 1px solid var(--bg-secondary);
    }
    .detail-row:last-of-type { border-bottom: none; }
    .detail-key { font-size: 13px; color: var(--hint); width: 100px; flex-shrink: 0; padding-top: 1px; }
    .detail-val { font-size: 15px; flex: 1; }
    .detail-link { color: var(--link); text-decoration: none; font-size: 15px; }

    /* ── Loading ── */
    .loading { text-align: center; padding: 40px; color: var(--hint); }
  </style>
</head>
<body>

<div id="app">
  <div id="tab-orders" class="tab-content active"></div>
  <div id="tab-stats" class="tab-content"></div>
  <div id="tab-clients" class="tab-content"></div>
</div>

<nav id="tab-bar">
  <button class="tab-btn active" data-tab="orders">
    <span class="tab-icon">📋</span>
    <span>Заказы</span>
  </button>
  <button class="tab-btn" data-tab="stats">
    <span class="tab-icon">📊</span>
    <span>Статистика</span>
  </button>
  <button class="tab-btn" data-tab="clients">
    <span class="tab-icon">👤</span>
    <span>Клиенты</span>
  </button>
</nav>

<div id="overlay"></div>
<div id="sheet"><div class="sheet-handle"></div><div id="sheet-content"></div></div>

<script>
// ── Constants ────────────────────────────────────────────────────────────────
const SCRIPT_URL = 'REPLACE_WITH_YOUR_APPS_SCRIPT_URL';
const MODELS = ['Lada','Larna','Verbena','Ilma','ролл','тарелочка','мусорничка','чехол пяльца','чехол рама','Taloma','Tala','Loboda'];
const STATUS_ORDER = ['В работе','Очередь','Пауза','Готово'];

// ── State ────────────────────────────────────────────────────────────────────
const state = {
  orders: [],
  archive: [],
  activeTab: 'orders',
  loading: false,
};

// ── Telegram WebApp init ─────────────────────────────────────────────────────
const tg = window.Telegram.WebApp;
tg.expand();
tg.disableVerticalSwipes();

// ── API ──────────────────────────────────────────────────────────────────────
async function apiGet(action) {
  const url = SCRIPT_URL + '?action=' + action + '&t=' + Date.now();
  const res = await fetch(url, { redirect: 'follow' });
  return res.json();
}

async function apiPost(data) {
  const res = await fetch(SCRIPT_URL, {
    method: 'POST',
    body: JSON.stringify(data),
    redirect: 'follow',
  });
  return res.json();
}

// ── Data loading ─────────────────────────────────────────────────────────────
async function loadData() {
  const [ordersRes, archiveRes] = await Promise.all([
    apiGet('getOrders'),
    apiGet('getArchive'),
  ]);
  state.orders = ordersRes.orders || [];
  state.archive = archiveRes.orders || [];
}

// ── Navigation ───────────────────────────────────────────────────────────────
document.getElementById('tab-bar').addEventListener('click', e => {
  const btn = e.target.closest('.tab-btn');
  if (!btn) return;
  const tab = btn.dataset.tab;
  switchTab(tab);
});

function switchTab(tab) {
  state.activeTab = tab;
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.toggle('active', b.dataset.tab === tab));
  document.querySelectorAll('.tab-content').forEach(c => c.classList.toggle('active', c.id === 'tab-' + tab));
  renderActiveTab();
}

function renderActiveTab() {
  if (state.activeTab === 'orders') renderOrders();
  if (state.activeTab === 'stats') renderStats();
  if (state.activeTab === 'clients') renderClients();
}

// ── Bottom sheet ──────────────────────────────────────────────────────────────
const overlay = document.getElementById('overlay');
const sheet = document.getElementById('sheet');
const sheetContent = document.getElementById('sheet-content');

function openSheet(html) {
  sheetContent.innerHTML = html;
  overlay.classList.add('visible');
  sheet.classList.add('visible');
}

function closeSheet() {
  overlay.classList.remove('visible');
  sheet.classList.remove('visible');
}

overlay.addEventListener('click', closeSheet);

// ── ORDERS TAB ───────────────────────────────────────────────────────────────
function renderOrders() {
  const el = document.getElementById('tab-orders');
  if (!state.orders.length) {
    el.innerHTML = '<button class="btn-primary" id="btn-new-order">＋ Новый заказ</button><div class="empty">Заказов пока нет</div>';
    document.getElementById('btn-new-order').onclick = openNewOrderForm;
    return;
  }

  const grouped = {};
  STATUS_ORDER.forEach(s => { grouped[s] = []; });
  state.orders.forEach(o => {
    const s = o.status || 'Очередь';
    if (!grouped[s]) grouped[s] = [];
    grouped[s].push(o);
  });

  let html = '<button class="btn-primary" id="btn-new-order">＋ Новый заказ</button>';
  STATUS_ORDER.forEach(status => {
    const orders = grouped[status];
    if (!orders.length) return;
    html += '<div class="section-header">' + status + '</div>';
    orders.forEach(o => {
      html += `
        <div class="card" data-id="${o.id}">
          <div class="card-main">
            <div class="card-id">#${o.id} · ${o.date || ''}</div>
            <div class="card-title">${o.name || '—'}</div>
            <div class="card-subtitle">${o.model || o.item || '—'}${o.article ? ' · ' + o.article : ''}</div>
          </div>
          <div class="card-chevron">›</div>
        </div>`;
    });
  });

  el.innerHTML = html;
  document.getElementById('btn-new-order').onclick = openNewOrderForm;
  el.querySelectorAll('.card').forEach(card => {
    card.onclick = () => openOrderDetail(card.dataset.id, state.orders);
  });
}

// ── ORDER DETAIL SHEET ───────────────────────────────────────────────────────
function openOrderDetail(id, source) {
  const order = source.find(o => String(o.id) === String(id));
  if (!order) return;
  renderOrderDetail(order, false);
}

function renderOrderDetail(order, editing) {
  const isReady = order.status === 'Готово';
  const statusOptions = ['Очередь','В работе','Пауза','Готово']
    .map(s => `<option value="${s}" ${order.status === s ? 'selected' : ''}>${s}</option>`)
    .join('');
  const modelOptions = ['', ...MODELS]
    .map(m => `<option value="${m}" ${order.model === m ? 'selected' : ''}>${m || '— выбрать —'}</option>`)
    .join('');

  const fieldHtml = (label, key, value, type = 'text') => {
    if (!editing) {
      return value ? `<div class="detail-row"><div class="detail-key">${label}</div><div class="detail-val">${value}</div></div>` : '';
    }
    return `<div class="field-group"><div class="field-label">${label}</div><input class="field-input" type="${type}" name="${key}" value="${value || ''}"></div>`;
  };

  let html = `<h2 style="font-size:18px;font-weight:700;margin-bottom:16px">#${order.id} ${order.name || ''}</h2>`;

  if (!editing) {
    html += `
      <div class="detail-row"><div class="detail-key">Изделие</div><div class="detail-val">${order.item || '—'}</div></div>
      ${order.article ? `<div class="detail-row"><div class="detail-key">Артикул</div><div class="detail-val">${order.article}</div></div>` : ''}
      ${order.model ? `<div class="detail-row"><div class="detail-key">Модель</div><div class="detail-val">${order.model}</div></div>` : ''}
      ${order.type ? `<div class="detail-row"><div class="detail-key">Тип</div><div class="detail-val">${order.type}</div></div>` : ''}
      ${order.details ? `<div class="detail-row"><div class="detail-key">Детали</div><div class="detail-val">${order.details}</div></div>` : ''}
      ${order.price ? `<div class="detail-row"><div class="detail-key">Цена</div><div class="detail-val">${order.price} RSD</div></div>` : ''}
      ${order.deadline ? `<div class="detail-row"><div class="detail-key">Срок</div><div class="detail-val">${order.deadline}</div></div>` : ''}
      ${order.note ? `<div class="detail-row"><div class="detail-key">Заметка</div><div class="detail-val">${order.note}</div></div>` : ''}
      <div style="margin:16px 0">
        <div class="field-label">Статус</div>
        <select class="field-select" id="status-select">${statusOptions}</select>
      </div>
      ${order.photo ? `<a class="detail-link" href="${order.photo}" target="_blank">📁 Открыть папку Drive</a>` : ''}
      <button class="btn-secondary" id="btn-edit-order">Редактировать</button>
      ${isReady ? '<button class="btn-danger" id="btn-archive-order">Перенести в архив</button>' : ''}
    `;
  } else {
    html += `
      ${fieldHtml('Имя', 'name', order.name)}
      ${fieldHtml('Изделие', 'item', order.item)}
      ${fieldHtml('Артикул', 'article', order.article)}
      <div class="field-group">
        <div class="field-label">Модель</div>
        <select class="field-select" name="model">${modelOptions}</select>
      </div>
      <div class="field-group">
        <div class="field-label">Тип</div>
        <div class="type-toggle">
          <div class="type-option ${order.type !== 'Наличие' ? 'selected' : ''}" data-val="Заказ">Заказ</div>
          <div class="type-option ${order.type === 'Наличие' ? 'selected' : ''}" data-val="Наличие">Наличие</div>
        </div>
        <input type="hidden" name="type" value="${order.type || 'Заказ'}">
      </div>
      ${fieldHtml('Детали', 'details', order.details)}
      ${fieldHtml('Цена', 'price', order.price, 'number')}
      ${fieldHtml('Срок', 'deadline', order.deadline)}
      ${fieldHtml('Заметка', 'note', order.note)}
      <button class="btn-primary" id="btn-save-order" style="margin-top:8px">Сохранить</button>
      <button class="btn-secondary" id="btn-cancel-edit">Отмена</button>
    `;
  }

  openSheet(html);

  if (!editing) {
    const statusSelect = document.getElementById('status-select');
    if (statusSelect) {
      statusSelect.onchange = async () => {
        const newStatus = statusSelect.value;
        await apiPost({ action: 'updateStatus', id: order.id, status: newStatus });
        order.status = newStatus;
        await refreshOrders();
        renderOrderDetail(order, false);
      };
    }

    const btnEdit = document.getElementById('btn-edit-order');
    if (btnEdit) btnEdit.onclick = () => renderOrderDetail(order, true);

    const btnArchive = document.getElementById('btn-archive-order');
    if (btnArchive) {
      btnArchive.onclick = async () => {
        await apiPost({ action: 'archiveOrder', id: order.id });
        await refreshOrders();
        closeSheet();
        renderOrders();
      };
    }
  } else {
    // Type toggle
    sheetContent.querySelectorAll('.type-option').forEach(opt => {
      opt.onclick = () => {
        sheetContent.querySelectorAll('.type-option').forEach(o => o.classList.remove('selected'));
        opt.classList.add('selected');
        sheetContent.querySelector('input[name="type"]').value = opt.dataset.val;
      };
    });

    document.getElementById('btn-cancel-edit').onclick = () => renderOrderDetail(order, false);

    document.getElementById('btn-save-order').onclick = async () => {
      const inputs = sheetContent.querySelectorAll('[name]');
      const data = { action: 'updateOrder', id: order.id };
      inputs.forEach(inp => { data[inp.name] = inp.value; });
      await apiPost(data);
      Object.assign(order, data);
      await refreshOrders();
      renderOrderDetail(order, false);
      renderOrders();
    };
  }
}

// ── NEW ORDER FORM ───────────────────────────────────────────────────────────
function openNewOrderForm() {
  const modelOptions = ['', ...MODELS]
    .map(m => `<option value="${m}">${m || '— выбрать —'}</option>`)
    .join('');

  const html = `
    <h2 style="font-size:18px;font-weight:700;margin-bottom:16px">Новый заказ</h2>
    <div class="field-group"><div class="field-label">Имя</div><input class="field-input" name="name" placeholder="Имя клиента"></div>
    <div class="field-group"><div class="field-label">Изделие</div><input class="field-input" name="item" placeholder="Название изделия"></div>
    <div class="field-group"><div class="field-label">Артикул</div><input class="field-input" name="article" placeholder="Необязательно"></div>
    <div class="field-group">
      <div class="field-label">Модель</div>
      <select class="field-select" name="model">${modelOptions}</select>
    </div>
    <div class="field-group">
      <div class="field-label">Тип</div>
      <div class="type-toggle">
        <div class="type-option selected" data-val="Заказ">Заказ</div>
        <div class="type-option" data-val="Наличие">Наличие</div>
      </div>
      <input type="hidden" name="type" value="Заказ">
    </div>
    <div class="field-group"><div class="field-label">Детали</div><textarea class="field-textarea" name="details" placeholder="Размер, цвет, материал..."></textarea></div>
    <div class="field-group"><div class="field-label">Цена (RSD)</div><input class="field-input" name="price" type="number" placeholder="0"></div>
    <div class="field-group"><div class="field-label">Срок</div><input class="field-input" name="deadline" type="date"></div>
    <div class="field-group"><div class="field-label">Комментарий</div><input class="field-input" name="comment" placeholder="Необязательно"></div>
    <button class="btn-primary" id="btn-submit-order" style="margin-top:8px">Добавить заказ</button>
    <button class="btn-secondary" id="btn-cancel-new">Отмена</button>
  `;

  openSheet(html);

  sheetContent.querySelectorAll('.type-option').forEach(opt => {
    opt.onclick = () => {
      sheetContent.querySelectorAll('.type-option').forEach(o => o.classList.remove('selected'));
      opt.classList.add('selected');
      sheetContent.querySelector('input[name="type"]').value = opt.dataset.val;
    };
  });

  document.getElementById('btn-cancel-new').onclick = closeSheet;

  document.getElementById('btn-submit-order').onclick = async () => {
    const btn = document.getElementById('btn-submit-order');
    btn.disabled = true;
    btn.textContent = 'Добавляем...';

    const inputs = sheetContent.querySelectorAll('[name]');
    const data = { action: 'createOrder' };
    inputs.forEach(inp => { data[inp.name] = inp.value; });

    // Format deadline from yyyy-mm-dd to dd.MM.yyyy
    if (data.deadline) {
      const parts = data.deadline.split('-');
      if (parts.length === 3) data.deadline = parts[2] + '.' + parts[1] + '.' + parts[0];
    }

    await apiPost(data);
    await refreshOrders();
    closeSheet();
    renderOrders();
  };
}

// ── STATS TAB ────────────────────────────────────────────────────────────────
async function renderStats() {
  const el = document.getElementById('tab-stats');
  el.innerHTML = '<div class="loading">Загрузка...</div>';

  let stats;
  try {
    stats = await apiGet('getStats');
  } catch (e) {
    el.innerHTML = '<div class="empty">Ошибка загрузки</div>';
    return;
  }

  const topModels = (stats.topModels || [])
    .map((m, i) => `<div class="model-row"><span>${i+1}. ${m.name}</span><b>${m.count} шт</b></div>`)
    .join('') || '<div style="color:var(--hint);font-size:14px">Нет данных</div>';

  const deadlines = (stats.upcomingDeadlines || [])
    .map(d => `<div class="model-row"><span>#${d.id} ${d.name}</span><b>${d.deadline}</b></div>`)
    .join('') || '<div style="color:var(--hint);font-size:14px">Дедлайнов нет 🏖</div>';

  el.innerHTML = `
    <div class="section-header">Заказы</div>
    <div class="stats-grid">
      <div class="stat-card"><div class="stat-value">${stats.activeCount || 0}</div><div class="stat-label">Активных</div></div>
      <div class="stat-card"><div class="stat-value">${stats.archiveCount || 0}</div><div class="stat-label">В архиве</div></div>
    </div>

    <div class="section-header">Типы</div>
    <div class="stats-grid">
      <div class="stat-card"><div class="stat-value">${stats.typeOrder || 0}</div><div class="stat-label">На заказ</div></div>
      <div class="stat-card"><div class="stat-value">${stats.typeStock || 0}</div><div class="stat-label">Из наличия</div></div>
    </div>

    <div class="section-header">Доход (архив)</div>
    <div class="stats-grid">
      <div class="stat-card full"><div class="stat-value">${(stats.income || 0).toLocaleString('ru')} RSD</div><div class="stat-label">Общий доход</div></div>
    </div>

    <div class="section-header">Топ моделей</div>
    <div style="background:var(--bg-secondary);border-radius:12px;padding:8px 12px;margin-bottom:14px">${topModels}</div>

    <div class="section-header">Дедлайны на этой неделе</div>
    <div style="background:var(--bg-secondary);border-radius:12px;padding:8px 12px;margin-bottom:14px">${deadlines}</div>
  `;
}

// ── CLIENTS TAB ──────────────────────────────────────────────────────────────
function renderClients(filter = '') {
  const el = document.getElementById('tab-clients');
  const all = state.orders.concat(state.archive);

  const clientMap = {};
  all.forEach(o => {
    const name = (o.name || '').trim();
    if (!name) return;
    if (!clientMap[name]) clientMap[name] = [];
    clientMap[name].push(o);
  });

  let clients = Object.entries(clientMap)
    .map(([name, orders]) => ({ name, orders }))
    .sort((a, b) => b.orders.length - a.orders.length);

  if (filter) {
    clients = clients.filter(c => c.name.toLowerCase().includes(filter.toLowerCase()));
  }

  let html = `
    <div class="search-wrap">
      <span class="search-icon">🔍</span>
      <input class="search-input" id="client-search" placeholder="Поиск по имени" value="${filter}">
    </div>
  `;

  if (!clients.length) {
    html += '<div class="empty">Клиентов не найдено</div>';
  } else {
    clients.forEach(c => {
      const count = c.orders.length;
      html += `
        <div class="card" data-client="${c.name}">
          <div class="card-main">
            <div class="card-title">${c.name}</div>
            <div class="card-subtitle">${count} ${declOrders(count)}</div>
          </div>
          <div class="card-chevron">›</div>
        </div>`;
    });
  }

  el.innerHTML = html;

  document.getElementById('client-search').oninput = e => renderClients(e.target.value);

  el.querySelectorAll('.card[data-client]').forEach(card => {
    card.onclick = () => openClientDetail(card.dataset.client);
  });
}

function declOrders(n) {
  if (n % 10 === 1 && n % 100 !== 11) return 'заказ';
  if ([2,3,4].includes(n % 10) && ![12,13,14].includes(n % 100)) return 'заказа';
  return 'заказов';
}

function openClientDetail(name) {
  const all = state.orders.concat(state.archive);
  const orders = all.filter(o => (o.name || '').trim() === name);
  const totalSpent = state.archive
    .filter(o => (o.name || '').trim() === name)
    .reduce((sum, o) => sum + (parseFloat(o.price) || 0), 0);

  const rows = orders
    .sort((a, b) => parseInt(b.id) - parseInt(a.id))
    .map(o => `
      <div class="card" data-id="${o.id}" data-source="${state.archive.find(a => a.id === o.id) ? 'archive' : 'orders'}">
        <div class="card-main">
          <div class="card-id">#${o.id} · ${o.date || ''}</div>
          <div class="card-title">${o.model || o.item || '—'}</div>
          <div class="card-subtitle">${o.status}${o.price ? ' · ' + o.price + ' RSD' : ''}</div>
        </div>
        <div class="card-chevron">›</div>
      </div>`)
    .join('');

  const html = `
    <h2 style="font-size:18px;font-weight:700;margin-bottom:4px">${name}</h2>
    <div style="color:var(--hint);font-size:13px;margin-bottom:16px">${orders.length} ${declOrders(orders.length)} · ${totalSpent.toLocaleString('ru')} RSD</div>
    ${rows || '<div class="empty">Нет заказов</div>'}
  `;

  openSheet(html);

  sheetContent.querySelectorAll('.card[data-id]').forEach(card => {
    card.onclick = () => {
      const source = card.dataset.source === 'archive' ? state.archive : state.orders;
      openOrderDetail(card.dataset.id, source);
    };
  });
}

// ── Helpers ───────────────────────────────────────────────────────────────────
async function refreshOrders() {
  const res = await apiGet('getOrders');
  state.orders = res.orders || [];
}

// ── Init ──────────────────────────────────────────────────────────────────────
async function init() {
  document.getElementById('tab-orders').innerHTML = '<div class="loading">Загрузка...</div>';
  try {
    await loadData();
  } catch (e) {
    document.getElementById('tab-orders').innerHTML = '<div class="empty">Ошибка загрузки данных</div>';
    return;
  }
  renderOrders();
}

init();
</script>
</body>
</html>
```

- [ ] **Step 2: Set your Apps Script URL**

  In `index.html`, find this line:
  ```javascript
  const SCRIPT_URL = 'REPLACE_WITH_YOUR_APPS_SCRIPT_URL';
  ```
  Replace with your actual deployment URL, e.g.:
  ```javascript
  const SCRIPT_URL = 'https://script.google.com/macros/s/AKfycbxMpD14ZU_6c2VrllFKWMB-52SIu1ClWVo79XhiT_ebXlx9In6OaxfRjDJomJuCGPvv/exec';
  ```

- [ ] **Step 3: Test in browser**

  Open `index.html` directly in a browser (file:// or local server).
  Expected: App shell loads, 3 tabs visible at bottom, "Загрузка..." appears then orders list (or "Заказов пока нет" if sheet is empty).

  > Note: API calls will fail from file:// due to CORS — this is normal. Use a local server: `npx serve .` then open `http://localhost:3000`

- [ ] **Step 4: Commit**

  ```bash
  git add index.html
  git commit -m "feat: build Moroska Mini App — full frontend with 3 tabs"
  ```

---

## Task 4: Deploy to Netlify and test in Telegram

**Files:**
- No new files — push existing changes

- [ ] **Step 1: Push to git**

  ```bash
  git push origin master
  ```

  Netlify will auto-deploy. Wait ~1 minute, then open https://moroskaorder.netlify.app/ — the app should load.

- [ ] **Step 2: Configure Telegram Mini App**

  In Telegram, open [@BotFather](https://t.me/BotFather):
  1. Send `/mybots` → select your bot
  2. **Bot Settings** → **Menu Button** → **Configure menu button**
  3. Set URL: `https://moroskaorder.netlify.app/`
  4. Set button text: `Заказы`

- [ ] **Step 3: Test in Telegram**

  Open your bot in Telegram → tap the Menu button.
  Expected:
  - App opens full-screen
  - Orders tab loads with your existing orders from Actual sheet
  - Tap any order → detail sheet slides up with correct data
  - Tap "＋ Новый заказ" → form sheet slides up with all fields

- [ ] **Step 4: Test creating an order**

  Fill in the new order form with test data and submit.
  Expected:
  - Button shows "Добавляем..."
  - New order appears in the Actual sheet in Google Sheets
  - Orders list refreshes showing the new order with status "Очередь"
  - Google Drive folder was created

- [ ] **Step 5: Test status change**

  Open an order detail → change the status dropdown.
  Expected: Status updates immediately in Google Sheets.

- [ ] **Step 6: Test archive**

  Change an order's status to "Готово" → "Перенести в архив" button appears → tap it.
  Expected: Order moves from Actual to Archive sheet, disappears from orders list.

- [ ] **Step 7: Test Statistics tab**

  Tap the Statistics tab.
  Expected: All stat blocks load with correct numbers matching your sheets.

- [ ] **Step 8: Test Clients tab**

  Tap the Clients tab.
  Expected: Client list shows unique names with order counts. Search filters correctly. Tapping a client shows their order history.

- [ ] **Step 9: Verify Telegram bot still works**

  In Telegram chat, send `/work` to your bot.
  Expected: Bot responds with the work report (bot commands still function).

- [ ] **Step 10: Final commit**

  ```bash
  git add .
  git commit -m "deploy: Moroska Mini App live on Netlify"
  ```

---

## Self-Review Notes

- **Spec coverage:** All 3 tabs implemented ✓. Order CRUD ✓. Status change ✓. Archive ✓. Stats all 5 blocks ✓. Clients with search and detail ✓. New columns Артикул + Тип ✓.
- **Placeholders:** `REPLACE_WITH_YOUR_APPS_SCRIPT_URL` is intentional — user must fill it in with their actual URL (Step 2 of Task 3).
- **Type consistency:** All API functions use same field names (`id`, `name`, `item`, `article`, `type`, etc.) consistently across doGet/doPost/frontend.
- **CORS note:** Apps Script POST with no Content-Type header (sends as text/plain) avoids preflight — this is the correct approach for browser→Apps Script.
- **Sheet rename:** Task 1 must be done before Task 2, and Task 2 before Task 4 — order matters.
