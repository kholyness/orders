const TOKEN = 'YOUR_TELEGRAM_BOT_TOKEN';
const SHEET_ID = SpreadsheetApp.getActiveSpreadsheet().getId();
const PARENT_FOLDER_ID = 'YOUR_GOOGLE_DRIVE_FOLDER_ID';
const MY_CHAT_ID = 'YOUR_TELEGRAM_CHAT_ID';
const ALLOWED_CHAT_IDS = [MY_CHAT_ID]; // add more IDs here: ['123456', '789012']

// ─── MINI APP: READ ENDPOINTS ───────────────────────────────────────────────

function doGet(e) {
  const action = (e.parameter && e.parameter.action) || '';
  const ss = SpreadsheetApp.openById(SHEET_ID);
  const mainSheet = ss.getSheetByName('Actual');
  const archiveSheet = ss.getSheetByName('Archive');

  // Write actions — params sent individually in URL
  const writeActions = ['createOrder', 'updateOrder', 'updateStatus', 'archiveOrder', 'createPurchase', 'updatePurchase', 'updatePurchaseStatus'];
  if (writeActions.indexOf(action) !== -1) {
    return handleMiniAppPost(e.parameter);
  }

  let result;
  if (action === 'getOrders') {
    result = { orders: sheetToObjects(mainSheet) };
  } else if (action === 'getArchive') {
    result = { orders: sheetToObjects(archiveSheet) };
  } else if (action === 'getStats') {
    result = buildStats(mainSheet, archiveSheet);
  } else if (action === 'getPurchases') {
    const purchaseSheet = ss.getSheetByName('Purchase');
    result = { purchases: purchaseSheetToObjects(purchaseSheet) };
  } else if (action === 'auth') {
    if (!validateInitData(e.parameter.initData)) return jsonOut({ error: 'Unauthorized' });
    result = { token: generateSessionToken() };
  } else {
    result = { error: 'Unknown action: ' + action };
  }

  return jsonOut(result);
}

function jsonOut(obj) {
  return ContentService
    .createTextOutput(JSON.stringify(obj))
    .setMimeType(ContentService.MimeType.JSON);
}

function purchaseSheetToObjects(sheet) {
  if (!sheet) return [];
  const rows = sheet.getDataRange().getValues();
  if (rows.length < 2) return [];
  const keys = ['date','item','quantity','price','orderId','orderName','status','note'];
  return rows.slice(1)
    .map((row, i) => {
      const obj = { rowIndex: i + 1 };
      keys.forEach((k, j) => {
        let val = row[j] !== undefined ? row[j] : '';
        if (val instanceof Date) val = Utilities.formatDate(val, 'GMT+2', 'dd.MM.yyyy');
        obj[k] = String(val);
      });
      return obj;
    })
    .filter(obj => obj.item !== '');
}

function sheetToObjects(sheet) {
  const rows = sheet.getDataRange().getValues();
  if (rows.length < 2) return [];
  const keys = ['rowNum','id','date','name','username','clientId','item','model','article','type','details','price','deadline','status','photo','note','comment'];
  return rows.slice(1)
    .filter(r => r[1] !== '' && r[1] !== null)
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

// ─── SESSION TOKENS ─────────────────────────────────────────────────────────

function generateSessionToken() {
  // Time-based token: valid for current and previous hour, no storage needed
  const window = Math.floor(Date.now() / 3600000);
  const raw = Utilities.computeHmacSha256Signature(
    Utilities.newBlob(String(window)).getBytes(),
    Utilities.newBlob(TOKEN).getBytes()
  );
  return Utilities.base64Encode(raw).replace(/[+/=]/g, '').slice(0, 20);
}

function validateToken(token) {
  if (!token) return false;
  const window = Math.floor(Date.now() / 3600000);
  const cur = generateSessionToken();
  // Also accept previous hour's token (handles edge case at hour boundary)
  const prevRaw = Utilities.computeHmacSha256Signature(
    Utilities.newBlob(String(window - 1)).getBytes(),
    Utilities.newBlob(TOKEN).getBytes()
  );
  const prev = Utilities.base64Encode(prevRaw).replace(/[+/=]/g, '').slice(0, 20);
  return token === cur || token === prev;
}

// ─── MINI APP AUTH ──────────────────────────────────────────────────────────

function validateInitData(initData) {
  if (!initData) return false;
  const params = new URLSearchParams(initData);
  const hash = params.get('hash');
  if (!hash) return false;
  params.delete('hash');

  // Build check string: sorted key=value pairs joined by \n
  const checkArr = [];
  params.forEach(function(value, key) { checkArr.push(key + '=' + value); });
  checkArr.sort();
  const checkString = checkArr.join('\n');

  // secret_key = HMAC-SHA256(message=TOKEN, key="WebAppData")
  const secretKey = Utilities.computeHmacSha256Signature(TOKEN, 'WebAppData');
  // GAS V8: byte array needs base64 round-trip to work as HMAC key
  const secretKeyBytes = Utilities.base64Decode(Utilities.base64Encode(secretKey));
  const dataBytes = Utilities.newBlob(checkString).getBytes();
  const expected = Utilities.computeHmacSha256Signature(dataBytes, secretKeyBytes);

  // Convert byte arrays to hex
  function toHex(bytes) {
    return bytes.map(function(b) {
      return ('0' + (b & 0xFF).toString(16)).slice(-2);
    }).join('');
  }

  if (toHex(expected) !== hash) return false;

  // Check that the request comes from the owner
  try {
    const user = JSON.parse(params.get('user') || '{}');
    if (!ALLOWED_CHAT_IDS.map(String).includes(String(user.id))) return false;
  } catch (e) {
    return false;
  }

  return true;
}

// ─── MINI APP: WRITE ENDPOINTS ──────────────────────────────────────────────

function handleMiniAppPost(data) {
  if (!validateToken(data.token)) {
    return jsonOut({ error: 'Unauthorized' });
  }
  const ss = SpreadsheetApp.openById(SHEET_ID);
  const mainSheet = ss.getSheetByName('Actual');
  const archiveSheet = ss.getSheetByName('Archive');
  let result;

  try {
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
    } else if (data.action === 'createPurchase') {
      result = createPurchase(data, getOrCreatePurchaseSheet(ss));
    } else if (data.action === 'updatePurchase') {
      result = updatePurchase(data, getOrCreatePurchaseSheet(ss));
    } else if (data.action === 'deletePurchase') {
      result = deletePurchase(data, getOrCreatePurchaseSheet(ss));
    } else if (data.action === 'togglePurchaseStatus') {
      result = togglePurchaseStatus(data, getOrCreatePurchaseSheet(ss));
    } else {
      result = { error: 'Unknown mini app action: ' + data.action };
    }
  } catch (err) {
    return jsonOut({ error: err.message });
  }

  return jsonOut(result);
}

function createOrderFromApp(data, sheet) {
  const rowNum = sheet.getLastRow() < 2 ? 1 : sheet.getLastRow();

  // Extract clientId from data or from initData
  let clientId = data.clientId || '';
  if (!clientId && data.initData) {
    try {
      const params = new URLSearchParams(data.initData);
      const user = JSON.parse(params.get('user') || '{}');
      clientId = String(user.id || '');
    } catch(e) {}
  }

  const dateNow = new Date();
  const ddmm = Utilities.formatDate(dateNow, 'GMT+2', 'ddMM');
  const suffix = clientId.length >= 3 ? clientId.slice(-3) : String(rowNum).padStart(3, '0');
  const id = ddmm + '-' + suffix;

  const folder = DriveApp.getFolderById(PARENT_FOLDER_ID)
    .createFolder('#' + id + '_' + (data.name || 'Заказ'));

  const dateOnly = Utilities.formatDate(dateNow, 'GMT+2', 'dd.MM.yyyy');
  sheet.appendRow([
    rowNum,
    id,
    dateOnly,
    data.name || '',
    data.username || '',
    clientId,
    data.item || '',
    data.model || '',
    data.article || '',
    data.type || 'Заказ',
    data.details || '',
    data.price || '',
    data.deadline || '',
    'Очередь',
    folder.getUrl(),
    '',
    data.comment || '',
  ]);

  return { success: true, id: id, folderUrl: folder.getUrl() };
}

function updateOrderFromApp(data, sheet) {
  const rows = sheet.getDataRange().getValues();
  const fieldMap = {
    name: 4, username: 5, clientId: 6, item: 7, model: 8,
    article: 9, type: 10, details: 11, price: 12,
    deadline: 13, status: 14, note: 16, comment: 17,
  };
  for (let i = 1; i < rows.length; i++) {
    if (String(rows[i][1]) === String(data.id)) {
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
      const msg = '🧶 <b>Шаблон Moroska:</b>\n\nНовый заказ\nИмя: \nUsername: \nИзделие: \nМодель: \nДетали: \nЦена: \nСрок: \nКомментарий: \n\n💡 <b>Твои модели:</b>\n<i>' + modelsList + '</i>';
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
    if (!row[1]) return;
    const status = (row[13] || '').toString().toLowerCase();
    const line = '• <b>#' + row[1] + '</b> ' + row[3] + ' — <i>' + row[6] + '</i> <a href="' + row[14] + '">[Папка]</a>';
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
    let d = row[12];
    if (d instanceof Date && d <= nextWeek && d >= today) {
      let line = '📅 <b>#' + row[1] + '</b> — ' + row[3] + ' — <i>' + (row[6] || '') + '</i> <a href="' + row[14] + '">[Папка]</a>\n';
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
      let date = row[2];
      let model = row[7] ? String(row[7]).trim() : '';
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
  let d = { name:'Имя', username:'', item:'Изделие', model:'Не указана', details:'', price:'0', deadline:'', comment:'' };
  lines.forEach(l => {
    const val = l.split(':')[1]?.trim();
    if (l.includes('Имя:')) d.name = val;
    if (l.includes('Username:')) d.username = val;
    if (l.includes('Изделие:')) d.item = val;
    if (l.includes('Модель:')) d.model = val;
    if (l.includes('Детали:')) d.details = val;
    if (l.includes('Цена:')) d.price = val;
    if (l.includes('Срок:')) d.deadline = val;
    if (l.includes('Комментарий:')) d.comment = val;
  });
  const rowNum = sheet.getLastRow() < 2 ? 1 : sheet.getLastRow();
  const dateNow = new Date();
  const ddmm = Utilities.formatDate(dateNow, 'GMT+2', 'ddMM');
  const id = ddmm + '-' + String(rowNum).padStart(3, '0');
  const folder = DriveApp.getFolderById(PARENT_FOLDER_ID).createFolder('#' + id + '_' + d.name);
  if (photo) saveFileToDrive(photo[photo.length-1].file_id, 'Эскиз_' + id, folder);
  const dateOnly = Utilities.formatDate(dateNow, 'GMT+2', 'dd.MM.yyyy');
  sheet.appendRow([rowNum, id, dateOnly, d.name, d.username, '', d.item, d.model, '', 'Заказ', d.details, d.price, d.deadline, 'Очередь', folder.getUrl(), '', d.comment]);
  sendMsg(chatId, '✅ Заказ <b>#' + id + '</b> добавлен!\nМодель: <b>' + d.model + '</b>');
}

function getOrCreatePurchaseSheet(ss) {
  let sheet = ss.getSheetByName('Purchase');
  if (!sheet) {
    sheet = ss.insertSheet('Purchase');
    sheet.appendRow(['date','item','quantity','price','orderId','orderName','status','note']);
  }
  return sheet;
}

function createPurchase(data, sheet) {
  const dateOnly = Utilities.formatDate(new Date(), 'GMT+2', 'dd.MM.yyyy');
  sheet.appendRow([
    dateOnly,
    data.item || '',
    data.quantity || '',
    data.price || '',
    data.orderId || '',
    data.orderName || '',
    data.status || 'Купить',
    data.note || '',
  ]);
  return { success: true };
}

function updatePurchase(data, sheet) {
  const rowNum = parseInt(data.rowIndex) + 1;
  if (!rowNum || rowNum < 2) return { success: false, error: 'Invalid row' };
  const fields = ['date','item','quantity','price','orderId','orderName','status','note'];
  fields.forEach((key, i) => {
    if (data[key] !== undefined) sheet.getRange(rowNum, i + 1).setValue(data[key]);
  });
  return { success: true };
}

function deletePurchase(data, sheet) {
  const rowNum = parseInt(data.rowIndex) + 1;
  if (!rowNum || rowNum < 2) return { success: false, error: 'Invalid row' };
  sheet.deleteRow(rowNum);
  return { success: true };
}

function togglePurchaseStatus(data, sheet) {
  const rowNum = parseInt(data.rowIndex) + 1;
  if (!rowNum || rowNum < 2) return { success: false, error: 'Invalid row' };
  const current = sheet.getRange(rowNum, 7).getValue();
  const newStatus = current === 'Куплено' ? 'Купить' : 'Куплено';
  sheet.getRange(rowNum, 7).setValue(newStatus);
  return { success: true, newStatus };
}

function updateStatusInSheet(id, status, sheet) {
  const rows = sheet.getDataRange().getValues();
  for (let i = 1; i < rows.length; i++) {
    if (String(rows[i][1]) === String(id)) { sheet.getRange(i + 1, 14).setValue(status); return true; }
  }
  return false;
}

function moveToArchive(id, mainSheet, archiveSheet) {
  const rows = mainSheet.getDataRange().getValues();
  for (let i = 1; i < rows.length; i++) {
    if (String(rows[i][1]) === String(id)) {
      const data = mainSheet.getRange(i + 1, 1, 1, 17).getValues()[0];
      data[13] = 'Отдано';
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
    if (String(rows[i][1]) === String(id)) {
      const fId = (rows[i][14].split('id=')[1] || rows[i][14].split('folders/')[1] || '').split('?')[0];
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
    let det = String(row[10] || '').toLowerCase();
    if (det.includes('купить') || det.includes('нет в наличии')) {
      list.push('🛒 <b>#' + row[1] + '</b> (' + row[3] + ')\n      └ ' + row[10]);
    }
  });
  return list.length > 0 ? list.join('\n') : '✅ Все в наличии!';
}

function getMoneyReport(archiveSheet) {
  const rows = archiveSheet.getDataRange().getValues();
  let total = 0;
  for (let i = 1; i < rows.length; i++) { let p = parseFloat(rows[i][11]); if (!isNaN(p)) total += p; }
  return '💰 <b>Общий доход:</b> ' + total + ' RSD';
}

// ─── TRIGGERS ───────────────────────────────────────────────────────────────

function sendMondayReport() {
  const ss = SpreadsheetApp.openById(SHEET_ID);
  const mainSheet = ss.getSheetByName('Actual');
  const weekReport = getWeekReport(mainSheet);
  const msg = '🚀 <b>ПОНЕДЕЛЬНИК: ПЛАН MOROSKA</b>\n\n' +
              getWorkReport(mainSheet) +
              '\n\n──────────────────\n\n' +
              weekReport;
  sendMsg(MY_CHAT_ID, msg);
}

function sendDeadlineReminder() {
  const ss = SpreadsheetApp.openById(SHEET_ID);
  const rows = ss.getSheetByName('Actual').getDataRange().getValues();
  const today = new Date();
  const target = new Date(); target.setDate(today.getDate() + 7);
  const targetStr = target.toLocaleDateString('ru-RU');

  const list = [];
  rows.slice(1).forEach(row => {
    if (!row[1]) return;
    let d = row[12];
    if (!(d instanceof Date)) {
      const parts = String(d).split('.');
      if (parts.length === 3) d = new Date(parts[2], parts[1] - 1, parts[0]);
      else return;
    }
    const dStr = d.toLocaleDateString('ru-RU');
    if (dStr === targetStr) {
      list.push('📅 <b>#' + row[1] + '</b> ' + row[3] + ' — <i>' + (row[6] || '') + '</i>\n      └ Срок: <b>' + dStr + '</b>');
    }
  });

  if (list.length > 0) {
    sendMsg(MY_CHAT_ID, '⏰ <b>ДЕДЛАЙН ЧЕРЕЗ 7 ДНЕЙ:</b>\n\n' + list.join('\n\n'));
  }
}

function sendMonthlyStats() {
  const ss = SpreadsheetApp.openById(SHEET_ID);
  const archived = ss.getSheetByName('Archive').getDataRange().getValues().slice(1);
  const income = archived.reduce((sum, row) => sum + (parseFloat(row[11]) || 0), 0);
  sendMsg(MY_CHAT_ID, '📊 <b>ИТОГИ МЕСЯЦА</b>\n✅ Завершено: <b>' + archived.length + '</b>\n💰 Доход: <b>' + income + ' RSD</b>');
}

function setWebhook() {
  const url = 'YOUR_APPS_SCRIPT_DEPLOYED_URL';
  UrlFetchApp.fetch('https://api.telegram.org/bot' + TOKEN + '/setWebhook?url=' + url);
}
