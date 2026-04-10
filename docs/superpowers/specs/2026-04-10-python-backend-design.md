# Moroska Orders — Python Backend Migration

**Date:** 2026-04-10  
**Status:** Approved

## Overview

Replace the Google Apps Script backend with a Python FastAPI server deployed on an existing Ubuntu (AWS micro) instance. Keep `index.html` unchanged — only `SCRIPT_URL` is updated. Replace Google Sheets + Google Drive with SQLite (local file) + local file storage.

## Architecture

```
Telegram WebView
  └── index.html (Netlify, HTTPS)
        └── GET requests → https://yourdomain.com/?action=...
              └── FastAPI (uvicorn :8000, behind nginx)
                    ├── SQLite (orders.db)
                    ├── uploads/ (photo files)
                    └── Telegram Bot (polling, async task)

Datasette (:8001, localhost only)
  └── SSH tunnel from laptop → web GUI for orders.db
```

**Server file layout:**
```
/home/ubuntu/moroska/
├── main.py            # FastAPI app + bot polling loop
├── db.py              # SQLite init, CREATE TABLE
├── auth.py            # initData validation, session token
├── migrate.py         # one-time CSV → SQLite migration
├── .env               # TOKEN, MY_CHAT_ID, ALLOWED_CHAT_IDS, UPLOAD_DIR
├── orders.db          # SQLite database (not in git)
├── uploads/           # photo storage: uploads/{order_id}/{filename}
└── requirements.txt
```

## Database Schema

```sql
CREATE TABLE IF NOT EXISTS orders (
    id          TEXT PRIMARY KEY,   -- format: DDMM-XXX
    row_num     INTEGER,
    date        TEXT,               -- dd.MM.yyyy
    name        TEXT,
    username    TEXT,
    client_id   TEXT,
    item        TEXT,
    model       TEXT,
    article     TEXT,
    type        TEXT DEFAULT 'Заказ',
    details     TEXT,
    price       TEXT,
    deadline    TEXT,               -- dd.MM.yyyy
    status      TEXT DEFAULT 'Очередь',
    photo       TEXT,               -- relative path: uploads/{id}/
    note        TEXT,
    comment     TEXT
);

CREATE TABLE IF NOT EXISTS archive (
    -- identical columns to orders, status always 'Отдано'
    id TEXT PRIMARY KEY, row_num INTEGER, date TEXT, name TEXT,
    username TEXT, client_id TEXT, item TEXT, model TEXT, article TEXT,
    type TEXT, details TEXT, price TEXT, deadline TEXT,
    status TEXT DEFAULT 'Отдано', photo TEXT, note TEXT, comment TEXT
);

CREATE TABLE IF NOT EXISTS purchases (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    date        TEXT,
    item        TEXT,
    quantity    TEXT,
    price       TEXT,
    order_id    TEXT,
    order_name  TEXT,
    status      TEXT DEFAULT 'Купить',
    note        TEXT
);
```

`rowIndex` sent by the frontend maps directly to `purchases.id`.

## API Endpoints

Single FastAPI route handles all Mini App requests:

```
GET /?action=<action>&<params>
```

### Read endpoints (no auth required)
| action | response |
|--------|----------|
| `getOrders` | `{ orders: [...] }` |
| `getArchive` | `{ orders: [...] }` |
| `getPurchases` | `{ purchases: [...] }` |
| `getStats` | `{ activeCount, archiveCount, typeOrder, typeStock, income, topModels, upcomingDeadlines }` |

### Auth
| action | params | response |
|--------|--------|----------|
| `auth` | `initData` | `{ token: "..." }` or `{ error: "Unauthorized" }` |

### Write endpoints (require `token` param)
| action | key params |
|--------|-----------|
| `createOrder` | `name, item, model, article, type, details, price, deadline, username, clientId, comment` |
| `updateOrder` | `id` + any updatable fields |
| `updateStatus` | `id, status` (status=Отдано triggers move to archive) |
| `archiveOrder` | `id` |
| `createPurchase` | `item, quantity, price, orderId, orderName, note` |
| `updatePurchase` | `rowIndex` + any fields |
| `deletePurchase` | `rowIndex` |
| `togglePurchaseStatus` | `rowIndex` |

No webhook endpoint — bot runs in **polling mode** exclusively (no HTTPS dependency for the bot, no registration needed).

## Authentication

Same algorithm as the GAS implementation, ported to Python `hmac`:

1. **initData validation:** HMAC-SHA256 of sorted `key=value` pairs, key = `HMAC-SHA256(TOKEN, "WebAppData")`. Check user ID against `ALLOWED_CHAT_IDS`.
2. **Session token:** `HMAC-SHA256(str(hour_window), TOKEN)`, base64-encoded, 20 chars. Valid for current hour and previous hour (handles boundary edge case).
3. Write requests pass `token=` param; server validates before executing.

## Photo Storage

- On `createOrder`: directory `uploads/{order_id}/` is created.
- `photo` column in DB stores the relative path `uploads/{order_id}/`.
- Photos sent via Telegram bot: downloaded from Telegram API using `getFile`, saved as `uploads/{order_id}/{prefix}_{order_id}.jpg`.
- Frontend `photo` field (previously a Google Drive URL) now contains the local path. The frontend only uses it as a link — update the frontend to point to `{SCRIPT_URL}/photo/{order_id}` if viewing photos is needed (out of scope for this migration).

## Telegram Bot

Runs as an asyncio background task inside the same FastAPI process (polling mode via `httpx` + manual long-polling loop, or `python-telegram-bot` library in polling mode).

Commands ported from GAS 1-to-1:
- `/work` — active orders by status
- `/buy` — orders with "купить"/"нет в наличии" in details
- `/money` — total income from archive
- `/week` — orders with deadlines in next 7 days
- `/models [month]` — model popularity stats
- `/new` — order template message
- Text status updates: `в работе 42`, `пауза 42`, `готово 42`, `отдано 42`
- Photo + order number → save to uploads

Scheduled reports (`sendMondayReport`, `sendDeadlineReminder`, `sendMonthlyStats`) — implemented as `asyncio` tasks with time-based triggers inside the bot loop.

## CORS

```python
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
```

Required for Telegram WebView to reach the API.

## Deployment

**Dependencies (`requirements.txt`):**
```
fastapi
uvicorn[standard]
aiosqlite
python-dotenv
httpx
```

**systemd services:**
- `moroska.service` — `uvicorn main:app --host 0.0.0.0 --port 8000`
- `datasette.service` — `datasette /home/ubuntu/moroska/orders.db --host 127.0.0.1 --port 8001`

**nginx** — reverse proxy `:443 → :8000`, SSL via Let's Encrypt (certbot). One-time setup.

**Datasette GUI** — accessed via SSH tunnel:
```bash
ssh -L 8001:localhost:8001 ubuntu@your-server
# then open http://localhost:8001 in browser
```

## Data Migration

`migrate.py` reads CSV exports from Google Sheets (Actual, Archive, Purchase tabs) and inserts rows into SQLite. Run once before switching `SCRIPT_URL` in `index.html`.

## Frontend Change

Only one line changes in `index.html`:
```js
const SCRIPT_URL = 'https://yourdomain.com';
```
