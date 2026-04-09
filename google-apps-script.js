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
  const url = 'https://script.google.com/macros/s/AKfycbwV7rrPwgIcErQNQgdpiGMzTciqToDKwVOv2qk-Fi2j1QQx-4rNaDz5p1xdmrht7Uau/exec';
  UrlFetchApp.fetch('https://api.telegram.org/bot' + TOKEN + '/setWebhook?url=' + url);
}
