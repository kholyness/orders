# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Moroska Orders is a Telegram Mini App for managing craft orders. It consists of two parts:

1. **`index.html`** — the frontend Mini App (single HTML file, vanilla JS, no build step)
2. **`google-apps-script.js`** — the backend deployed as a Google Apps Script Web App

There is no package manager, no build system, and no tests. Development is purely editing these two files.

## Deployment

**Frontend:** `index.html` is served as a Telegram Mini App. To update, modify the file and redeploy via your Telegram bot configuration.

**Backend:** `google-apps-script.js` must be manually copied into the Google Apps Script editor at script.google.com and deployed as a new Web App version. The deployed URL is hardcoded in `index.html` as `SCRIPT_URL`.

After redeploying the Apps Script, update `SCRIPT_URL` in `index.html` if the URL changes.

## Architecture

### Data Layer (Google Sheets)
- **`Actual` sheet** — active orders (17 columns: №, ID заказа, Дата создания, Имя, Username, ID клиента, Изделие, Модель, Артикул, Тип, Детали, Цена, Срок, Статус, Фото, Заметка, Комментарий)
- **`Archive` sheet** — completed orders (same schema, Статус = 'Отдано')
- **ID заказа** format: `DDMM-XXX` where DDMM = creation date (day+month), XXX = last 3 digits of client Telegram ID (or row № padded to 3 if no client ID)
- **№** — sequential row counter (separate from ID заказа)
- **Заметка** — master's internal notes; **Комментарий** — client's comment from the shop bot
- Each order gets a Google Drive folder created automatically on creation; `photo` column stores the folder URL

### Backend API (Google Apps Script)
- `doGet(e)` — handles read requests: `getOrders`, `getArchive`, `getStats`
- `doPost(e)` — dual-purpose: routes to `handleMiniAppPost` when `data.action` is present, otherwise handles Telegram Bot webhook
- Mini App write actions: `createOrder`, `updateOrder`, `updateStatus`, `archiveOrder`
  - `updateStatus` with `status = 'Отдано'` automatically calls `moveToArchive`
- Telegram bot commands: `/new`, `/work`, `/buy`, `/money`, `/week`, `/models [month]`
- Telegram status updates: `в работе 42`, `пауза 42`, `готово 42`, `отдано 42` (moves to archive)
- Telegram photo handling: sending a photo with a plain order number saves it to that order's Drive folder

### Authentication (Mini App)
All Mini App write requests go through `validateInitData(data.initData)`:
- Verifies the Telegram `initData` HMAC-SHA256 signature using the bot TOKEN
- Additionally checks that the user ID in `initData` matches `MY_CHAT_ID` (owner-only access)
- Returns `{ error: 'Unauthorized' }` on failure

### Frontend State
- Single global `state` object: `{ orders: [], archive: [], activeTab: 'orders' }`
- Three tabs: Orders (📋), Stats (📊), Clients (👤)
- Bottom sheet pattern for detail/edit views
- All UI is rendered imperatively via `innerHTML`
- Status changes trigger haptic feedback via `tg.HapticFeedback`

### Key UI Interactions
- **Status badge** on each order card is tappable — opens a popup to change status directly from the list
- **Order detail** opens on card tap (not on status badge tap)
- **Edit form** includes a native date picker for the deadline field
- **Note indicator** shown on card when the order has a note

### Key Constants (index.html)
```js
const SCRIPT_URL = '...'; // Google Apps Script deployed URL
const MODELS = ['Lada','Larna','Verbena','Ilma','ролл','тарелочка','мусорничка','чехол пяльца','чехол рама','Taloma','Tala','Loboda'];
const STATUS_ORDER = ['В работе','Очередь','Пауза','Готово']; // Display order
```

### Key Constants (google-apps-script.js)
```js
const TOKEN = '...';            // Telegram Bot token
const SHEET_ID = ...;           // Google Sheets ID (auto-detected via getActiveSpreadsheet)
const PARENT_FOLDER_ID = '...'; // Google Drive folder for order subfolders
const MY_CHAT_ID = '...';       // Owner's chat ID — used for auth and scheduled reports
```

### Bot Report Functions
- `/work` — lists active orders by status (В работе / Очередь / Готово)
- `/buy` — lists orders where details contain "купить" or "нет в наличии"
- `/money` — total income from the Archive sheet
- `/week` — orders with deadlines within the next 7 days
- `/models [month]` — model popularity stats, optionally filtered by month (e.g. `/models апр`)

## Scheduled Triggers (Apps Script)
- `sendMondayReport()` — weekly work summary (configure in Apps Script triggers)
- `sendMonthlyStats()` — monthly income summary (configure in Apps Script triggers)
- `setWebhook()` — run once to register Telegram webhook URL
