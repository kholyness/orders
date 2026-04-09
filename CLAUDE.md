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
- **`Actual` sheet** — active orders (columns: id, date, name, item, details, price, deadline, status, photo, note, model, article, type)
- **`Archive` sheet** — completed orders (same schema, status = 'Отдано')
- Each order gets a Google Drive folder created automatically on creation

### Backend API (Google Apps Script)
- `doGet(e)` — handles read requests: `getOrders`, `getArchive`, `getStats`
- `doPost(e)` — dual-purpose: handles Mini App write requests (when `data.action` is present) AND Telegram Bot webhook messages
- Mini App write actions: `createOrder`, `updateOrder`, `updateStatus`, `archiveOrder`
- Telegram bot commands: `/new`, `/work`, `/buy`, `/money`, `/week`, `/models [month]`, plus status updates like `в работе 42`

### Frontend State
- Single global `state` object: `{ orders: [], archive: [], activeTab: 'orders' }`
- Three tabs: Orders (📋), Stats (📊), Clients (👤)
- Bottom sheet pattern for detail/edit views
- All UI is rendered imperatively via `innerHTML`

### Key Constants (index.html)
```js
const SCRIPT_URL = '...'; // Google Apps Script deployed URL
const MODELS = [...];     // Available product models for dropdown
const STATUS_ORDER = ['В работе','Очередь','Пауза','Готово']; // Display order
```

### Key Constants (google-apps-script.js)
```js
const TOKEN = '...';           // Telegram Bot token
const SHEET_ID = ...;          // Google Sheets ID (auto-detected)
const PARENT_FOLDER_ID = '...'; // Google Drive folder for order subfolders
const MY_CHAT_ID = '...';      // Chat ID for scheduled reports
```

## Scheduled Triggers (Apps Script)
- `sendMondayReport()` — weekly work summary (configure in Apps Script triggers)
- `sendMonthlyStats()` — monthly income summary (configure in Apps Script triggers)
- `setWebhook()` — run once to register Telegram webhook URL
