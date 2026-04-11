# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Moroska Orders is a Telegram Mini App for managing craft orders. It consists of:

1. **`index.html`** — frontend Mini App (single HTML file, vanilla JS, no build step)
2. **`main.py`** — Python/FastAPI backend: REST API for the Mini App + Telegram bot (long polling) + scheduled tasks
3. **`sheets.py`** — async wrappers around gspread for reading/writing Google Sheets
4. **`auth.py`** — Telegram initData HMAC validation + hourly token generation for write auth

There is no package manager or build system for the frontend. Backend dependencies: `fastapi`, `uvicorn[standard]`, `httpx`, `python-dotenv`, `gspread`, `google-auth`.

## Deployment

**Frontend:** `index.html` is served as a Telegram Mini App. To update, modify the file and redeploy via your Telegram bot configuration.

**Backend:** Runs as a systemd service (`deploy/moroska.service`) behind nginx (`deploy/nginx.conf`). To deploy: push changes, restart the service. The deployed URL is hardcoded in `index.html` as `SCRIPT_URL`.

## Versioning

`index.html` has an `APP_VERSION` constant (near the top of the `<script>` section) displayed as a small label above the tab bar (bottom-right corner). **Bump this version string every time you deploy a change to the Mini App** so it's easy to confirm which version is actually running in the Telegram WebView.

Use simple semver: `1.0.0` → `1.0.1` for patches, `1.1.0` for new features. No tooling needed — just edit the string manually.

## Architecture

### Data Layer (Google Sheets via gspread)
- **`Actual` sheet** — active orders (17 columns: №, ID заказа, Дата создания, Имя, Username, ID клиента, Изделие, Модель, Артикул, Тип, Детали, Цена, Срок, Статус, Фото, Заметка, Комментарий)
- **`Archive` sheet** — completed orders (same schema, Статус = 'Отдано')
- **`Purchase` sheet** — purchase list (8 columns: date, item, quantity, price, orderId, orderName, status, note); status values: `Купить` / `Куплено`
- **ID заказа** format: `DDMM-XXX` where DDMM = creation date (day+month), XXX = last 3 digits of client Telegram ID (or row № padded to 3 if no client ID)
- **№** — sequential row counter (separate from ID заказа)
- **Заметка** — master's internal notes; **Комментарий** — client's comment from the shop bot
- **Фото** — storage reference for order photos: either a local folder path (`uploads/<order_id>/`) or a Drive folder reference (`drive:<folder_id>`) when Google Drive is configured

### Backend API (main.py — FastAPI)

Single `GET /` endpoint, action selected via `?action=` query param.

**Auth flow:**
1. Mini App calls `?action=auth&initData=<telegram_init_data>` — backend validates HMAC signature and user whitelist, returns a short-lived token (valid ~2 hours)
2. Write actions use `?token=<token>` — validated via `validate_token()` in `auth.py`

**Read actions** (no auth):
- `getOrders`, `getArchive`, `getStats`, `getPurchases`

**Write actions** (require `token`):
- Orders: `createOrder`, `updateOrder`, `updateStatus`, `archiveOrder`
  - `updateStatus` with `status = 'Отдано'` automatically calls `move_to_archive`
- Purchases: `createPurchase`, `updatePurchase`, `deletePurchase`, `togglePurchaseStatus`

### Telegram Bot (main.py — long polling)
Bot runs as an async polling loop inside the same FastAPI process (`bot_polling_loop()`). Commands:
- `/new` or `/start` — prints a new-order template
- `/work` — active orders by status
- `/buy` — orders where details contain "купить" or "нет в наличии"
- `/money` — total income from Archive
- `/week` — orders with deadlines within 7 days
- `/models [month]` — model popularity stats, optionally filtered by month (e.g. `/models апр`)

Text status updates: `в работе <id>`, `пауза <id>`, `готово <id>`, `отдано <id>` (moves to archive)

Photo handling — two flows supported:
- **One-step:** send a photo with caption matching `^\d+$` or `^\d{4}-\d{3}$` — saves immediately.
- **Two-step (Mini App flow):** Mini App calls `addPhoto(order.id)` → opens bot chat via `tg.openTelegramLink` with order ID pre-filled as text (`?text=DDMM-XXX`). User taps Send → bot stores the order ID in `_pending_photo` (in-memory dict) and replies asking for a photo → user sends photo (no caption needed) → bot saves it. Note: `_pending_photo` is not persisted — state is lost on server restart.

### Authentication (auth.py)
- `validate_init_data(init_data)` — verifies Telegram HMAC-SHA256 signature and checks user ID against `ALLOWED_CHAT_IDS` (from env var)
- `generate_token()` / `validate_token(token)` — HMAC-based hourly sliding window token (valid for current and previous hour)

### Frontend State (index.html)
- Single global `state` object: `{ orders: [], archive: [], activeTab: 'orders' }`
- Three tabs: Orders (📋), Stats (📊), Clients (👤)
- Bottom sheet pattern for detail/edit views
- All UI rendered imperatively via `innerHTML`
- Status changes trigger haptic feedback via `tg.HapticFeedback`
- On load: calls `auth` action with `initData`, stores token in memory for subsequent write calls

### Key UI Interactions
- **Status badge** on each order card is tappable — opens a popup to change status directly from the list
- **Order detail** opens on card tap (not on status badge tap)
- **Edit form** includes a native date picker for the deadline field
- **Note indicator** shown on card when the order has a note
- **"Добавить фото"** button calls `addPhoto(order.id)` → opens the bot chat via `tg.openTelegramLink` with the order ID pre-filled in the text box (`?text=DDMM-XXX`). User taps Send, bot asks for a photo, user sends it. See two-step photo flow in the Bot section above.

### Key Constants (index.html)
```js
const SCRIPT_URL = '...'; // Backend URL (FastAPI server)
const BOT_USERNAME = 'MoroskaOrder_bot'; // Telegram bot @username without @
const MODELS = ['Lada','Larna','Verbena','Ilma','ролл','тарелочка','мусорничка','чехол пяльца','чехол рама','Taloma','Tala','Loboda'];
const STATUS_ORDER = ['В работе','Очередь','Пауза','Готово']; // Display order
```

### Key Env Vars (.env)
```
TOKEN=             # Telegram Bot token
MY_CHAT_ID=        # Owner's chat ID — used for scheduled reports
ALLOWED_CHAT_IDS=  # Comma-separated chat IDs allowed to use the Mini App and bot
SHEET_ID=          # Google Sheets spreadsheet ID
GOOGLE_CREDS_FILE= # Path to service account credentials JSON (default: credentials.json)
UPLOAD_DIR=        # Local folder for order photos (default: uploads, used when DRIVE_FOLDER_ID is not set)
DRIVE_FOLDER_ID=   # Google Drive parent folder ID — if set, order subfolders and photos go to Drive instead of local disk
```

## Logging & Debugging

`main.py` uses Python's standard `logging` module (`logging.basicConfig(level=INFO)`). Logs are written to stdout and captured by systemd.

To watch logs live on the server:
```bash
journalctl -u moroska -f
```

Each incoming bot message is logged at INFO level:
```
2026-04-11 12:00:01 INFO bot msg chat=123456 text='0411-123' has_photo=False
```

Messages from unknown `chat_id`s are logged at WARNING. Unhandled exceptions include a full traceback via `logger.exception`.

## Scheduled Tasks (main.py)
Run daily at 09:00 inside `scheduled_tasks_loop()`:
- Monday: `send_monday_report()` — work summary + upcoming deadlines
- Daily: `send_deadline_reminder()` — alerts if any order has a deadline exactly 7 days away
- 1st of month: `send_monthly_stats()` — archive count + total income
