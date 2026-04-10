# Python Backend Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace Google Apps Script backend with a Python FastAPI server on Ubuntu, keeping `index.html` unchanged except for `SCRIPT_URL`.

**Architecture:** Single `main.py` FastAPI app with async SQLite via `aiosqlite`. Auth and DB init in separate modules. Telegram bot runs as an asyncio background task in polling mode alongside the web server.

**Tech Stack:** Python 3.11+, FastAPI, uvicorn, aiosqlite, httpx, python-dotenv. SQLite database. Datasette for GUI.

> **Note on testing:** This project has no test framework. Each task verifies with `curl` against a running dev server (`uvicorn main:app --reload`).

---

## File Map

| File | Responsibility |
|------|---------------|
| `requirements.txt` | Python dependencies |
| `.env.example` | Environment variable template |
| `db.py` | SQLite init, CREATE TABLE |
| `auth.py` | initData HMAC validation, session token gen/validate |
| `main.py` | FastAPI app, all endpoints, bot polling loop |
| `migrate.py` | One-time CSV → SQLite import |
| `index.html` | Frontend — only `SCRIPT_URL` changes |
| `deploy/moroska.service` | systemd unit for uvicorn |
| `deploy/datasette.service` | systemd unit for Datasette GUI |
| `deploy/nginx.conf` | nginx reverse proxy config snippet |

---

## Task 1: Foundation — requirements.txt, .env.example, db.py, auth.py

**Files:**
- Create: `requirements.txt`
- Create: `.env.example`
- Create: `db.py`
- Create: `auth.py`

- [ ] **Step 1.1: Create requirements.txt**

```
fastapi
uvicorn[standard]
aiosqlite
httpx
python-dotenv
```

- [ ] **Step 1.2: Create .env.example**

```
TOKEN=your_telegram_bot_token
MY_CHAT_ID=your_telegram_chat_id
ALLOWED_CHAT_IDS=your_telegram_chat_id
DB_PATH=orders.db
UPLOAD_DIR=uploads
```

- [ ] **Step 1.3: Create db.py**

```python
import os
import aiosqlite

DB_PATH = os.getenv("DB_PATH", "orders.db")

_ORDER_COLS = """
    id TEXT PRIMARY KEY,
    row_num INTEGER,
    date TEXT,
    name TEXT,
    username TEXT,
    client_id TEXT,
    item TEXT,
    model TEXT,
    article TEXT,
    type TEXT DEFAULT 'Заказ',
    details TEXT,
    price TEXT,
    deadline TEXT,
    status TEXT DEFAULT 'Очередь',
    photo TEXT,
    note TEXT,
    comment TEXT
"""

async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(f"CREATE TABLE IF NOT EXISTS orders ({_ORDER_COLS})")
        await db.execute(f"CREATE TABLE IF NOT EXISTS archive ({_ORDER_COLS.replace(\"DEFAULT 'Очередь'\", \"DEFAULT 'Отдано'\")})")
        await db.execute("""
            CREATE TABLE IF NOT EXISTS purchases (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT,
                item TEXT,
                quantity TEXT,
                price TEXT,
                order_id TEXT,
                order_name TEXT,
                status TEXT DEFAULT 'Купить',
                note TEXT
            )
        """)
        await db.commit()
```

- [ ] **Step 1.4: Create auth.py**

```python
import hashlib
import hmac
import json
import math
import os
import re
import time
from urllib.parse import parse_qsl

TOKEN = os.getenv("TOKEN", "")
ALLOWED_CHAT_IDS = [s.strip() for s in os.getenv("ALLOWED_CHAT_IDS", "").split(",") if s.strip()]


def validate_init_data(init_data: str) -> bool:
    if not init_data:
        return False
    params = dict(parse_qsl(init_data, keep_blank_values=True))
    hash_val = params.pop("hash", None)
    if not hash_val:
        return False

    check_string = "\n".join(f"{k}={v}" for k, v in sorted(params.items()))
    # secret_key = HMAC-SHA256(key="WebAppData", msg=TOKEN)
    secret_key = hmac.new(b"WebAppData", TOKEN.encode(), hashlib.sha256).digest()
    expected = hmac.new(secret_key, check_string.encode(), hashlib.sha256).hexdigest()

    if expected != hash_val:
        return False

    try:
        user = json.loads(params.get("user", "{}"))
        if str(user.get("id", "")) not in ALLOWED_CHAT_IDS:
            return False
    except (json.JSONDecodeError, KeyError):
        return False

    return True


def _raw_token(window: int) -> str:
    import base64
    raw = hmac.new(TOKEN.encode(), str(window).encode(), hashlib.sha256).digest()
    b64 = base64.b64encode(raw).decode()
    return re.sub(r"[+/=]", "", b64)[:20]


def generate_token() -> str:
    window = math.floor(time.time() / 3600)
    return _raw_token(window)


def validate_token(token: str) -> bool:
    if not token:
        return False
    window = math.floor(time.time() / 3600)
    return token in (_raw_token(window), _raw_token(window - 1))
```

- [ ] **Step 1.5: Install dependencies and verify imports**

```bash
pip install -r requirements.txt
python -c "from db import init_db; from auth import validate_init_data, generate_token, validate_token; print('OK')"
```

Expected output: `OK`

- [ ] **Step 1.6: Commit**

```bash
git add requirements.txt .env.example db.py auth.py
git commit -m "feat: add foundation — db schema and auth module"
```

---

## Task 2: FastAPI App — Read Endpoints

**Files:**
- Create: `main.py`

- [ ] **Step 2.1: Create main.py with app shell and read endpoints**

```python
import asyncio
import os
import re
from datetime import datetime, timedelta

import aiosqlite
import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from auth import generate_token, validate_init_data, validate_token
from db import DB_PATH, init_db

load_dotenv()

TOKEN = os.getenv("TOKEN", "")
MY_CHAT_ID = os.getenv("MY_CHAT_ID", "")
UPLOAD_DIR = os.getenv("UPLOAD_DIR", "uploads")

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.on_event("startup")
async def on_startup():
    await init_db()
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    asyncio.create_task(bot_polling_loop())


# ── Row helpers ───────────────────────────────────────────────────────────────

def row_to_order(row) -> dict:
    keys = ["id", "row_num", "date", "name", "username", "client_id",
            "item", "model", "article", "type", "details", "price",
            "deadline", "status", "photo", "note", "comment"]
    d = dict(zip(keys, row))
    return {
        "id": d["id"] or "",
        "rowNum": str(d["row_num"] or ""),
        "date": d["date"] or "",
        "name": d["name"] or "",
        "username": d["username"] or "",
        "clientId": d["client_id"] or "",
        "item": d["item"] or "",
        "model": d["model"] or "",
        "article": d["article"] or "",
        "type": d["type"] or "",
        "details": d["details"] or "",
        "price": d["price"] or "",
        "deadline": d["deadline"] or "",
        "status": d["status"] or "",
        "photo": d["photo"] or "",
        "note": d["note"] or "",
        "comment": d["comment"] or "",
    }


def row_to_purchase(row) -> dict:
    keys = ["id", "date", "item", "quantity", "price", "order_id", "order_name", "status", "note"]
    d = dict(zip(keys, row))
    return {
        "rowIndex": d["id"],
        "date": d["date"] or "",
        "item": d["item"] or "",
        "quantity": d["quantity"] or "",
        "price": d["price"] or "",
        "orderId": d["order_id"] or "",
        "orderName": d["order_name"] or "",
        "status": d["status"] or "",
        "note": d["note"] or "",
    }


def today_str() -> str:
    return datetime.now().strftime("%d.%m.%Y")


# ── Main router ───────────────────────────────────────────────────────────────

@app.get("/")
async def handle(request: Request):
    p = dict(request.query_params)
    action = p.get("action", "")

    if action == "auth":
        if not validate_init_data(p.get("initData", "")):
            return JSONResponse({"error": "Unauthorized"})
        return JSONResponse({"token": generate_token()})

    if action == "getOrders":
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute("SELECT * FROM orders ORDER BY rowid") as cur:
                rows = await cur.fetchall()
        return JSONResponse({"orders": [row_to_order(r) for r in rows]})

    if action == "getArchive":
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute("SELECT * FROM archive ORDER BY rowid") as cur:
                rows = await cur.fetchall()
        return JSONResponse({"orders": [row_to_order(r) for r in rows]})

    if action == "getPurchases":
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute("SELECT * FROM purchases ORDER BY id") as cur:
                rows = await cur.fetchall()
        return JSONResponse({"purchases": [row_to_purchase(r) for r in rows]})

    if action == "getStats":
        return JSONResponse(await build_stats())

    write_actions = {
        "createOrder", "updateOrder", "updateStatus", "archiveOrder",
        "createPurchase", "updatePurchase", "deletePurchase", "togglePurchaseStatus",
    }
    if action in write_actions:
        if not validate_token(p.get("token", "")):
            return JSONResponse({"error": "Unauthorized"})
        return JSONResponse(await handle_write(action, p))

    return JSONResponse({"error": f"Unknown action: {action}"})


async def build_stats() -> dict:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT * FROM orders") as cur:
            active = [row_to_order(r) for r in await cur.fetchall()]
        async with db.execute("SELECT * FROM archive") as cur:
            archived = [row_to_order(r) for r in await cur.fetchall()]

    all_orders = active + archived

    def to_float(s):
        try:
            return float(s)
        except (ValueError, TypeError):
            return 0.0

    income = sum(to_float(r["price"]) for r in archived)
    type_order = sum(1 for r in all_orders if r["type"] != "Наличие")
    type_stock = sum(1 for r in all_orders if r["type"] == "Наличие")

    model_counts: dict[str, int] = {}
    for r in all_orders:
        m = r["model"]
        if m and m != "Не указана":
            model_counts[m] = model_counts.get(m, 0) + 1
    top_models = sorted(model_counts.items(), key=lambda x: -x[1])[:5]

    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    next_week = today + timedelta(days=7)
    upcoming = []
    for r in active:
        if not r["deadline"]:
            continue
        parts = r["deadline"].split(".")
        if len(parts) != 3:
            continue
        try:
            d = datetime(int(parts[2]), int(parts[1]), int(parts[0]))
            if today <= d <= next_week:
                upcoming.append({"id": r["id"], "name": r["name"], "deadline": r["deadline"]})
        except ValueError:
            pass

    return {
        "activeCount": len(active),
        "archiveCount": len(archived),
        "typeOrder": type_order,
        "typeStock": type_stock,
        "income": income,
        "topModels": [{"name": n, "count": c} for n, c in top_models],
        "upcomingDeadlines": upcoming,
    }


# ── Placeholder so the file is importable before write handlers are added ────

async def handle_write(action: str, p: dict) -> dict:
    return {"error": "Not implemented yet"}


async def bot_polling_loop():
    pass  # implemented in Task 5
```

- [ ] **Step 2.2: Start dev server and verify read endpoints**

```bash
cp .env.example .env
# fill in TOKEN and MY_CHAT_ID in .env
uvicorn main:app --reload
```

In a second terminal:

```bash
curl "http://localhost:8000/?action=getOrders"
# expected: {"orders":[]}

curl "http://localhost:8000/?action=getPurchases"
# expected: {"purchases":[]}

curl "http://localhost:8000/?action=getStats"
# expected: {"activeCount":0,"archiveCount":0,"typeOrder":0,"typeStock":0,"income":0.0,"topModels":[],"upcomingDeadlines":[]}
```

- [ ] **Step 2.3: Commit**

```bash
git add main.py
git commit -m "feat: FastAPI shell with read endpoints"
```

---

## Task 3: Write Endpoints — Orders

**Files:**
- Modify: `main.py` — replace `handle_write` stub and add order write functions

- [ ] **Step 3.1: Replace `handle_write` and add order functions**

Replace the stub `handle_write` and `bot_polling_loop` in `main.py` with:

```python
async def handle_write(action: str, p: dict) -> dict:
    if action == "createOrder":
        return await create_order(p)
    if action == "updateOrder":
        return await update_order(p)
    if action == "updateStatus":
        ok = await update_status(p["id"], p.get("status", ""))
        if p.get("status") == "Отдано":
            await move_to_archive(p["id"])
        return {"success": ok}
    if action == "archiveOrder":
        return {"success": await move_to_archive(p["id"])}
    if action == "createPurchase":
        return await create_purchase(p)
    if action == "updatePurchase":
        return await update_purchase(p)
    if action == "deletePurchase":
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("DELETE FROM purchases WHERE id = ?", (int(p["rowIndex"]),))
            await db.commit()
        return {"success": True}
    if action == "togglePurchaseStatus":
        return await toggle_purchase_status(int(p["rowIndex"]))
    return {"error": f"Unknown action: {action}"}


async def create_order(p: dict) -> dict:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT COUNT(*) FROM orders") as cur:
            count = (await cur.fetchone())[0]

    row_num = count + 1
    client_id = p.get("clientId", "") or p.get("client_id", "")
    now = datetime.now()
    ddmm = now.strftime("%d%m")
    suffix = client_id[-3:] if len(client_id) >= 3 else str(row_num).zfill(3)
    order_id = f"{ddmm}-{suffix}"

    photo_dir = os.path.join(UPLOAD_DIR, order_id)
    os.makedirs(photo_dir, exist_ok=True)

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT INTO orders
               (id, row_num, date, name, username, client_id, item, model,
                article, type, details, price, deadline, status, photo, note, comment)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (order_id, row_num, now.strftime("%d.%m.%Y"),
             p.get("name", ""), p.get("username", ""), client_id,
             p.get("item", ""), p.get("model", ""), p.get("article", ""),
             p.get("type", "Заказ"), p.get("details", ""),
             p.get("price", ""), p.get("deadline", ""),
             "Очередь", photo_dir, "", p.get("comment", ""))
        )
        await db.commit()

    return {"success": True, "id": order_id, "folderUrl": photo_dir}


async def update_order(p: dict) -> dict:
    field_map = {
        "name": "name", "username": "username", "clientId": "client_id",
        "item": "item", "model": "model", "article": "article",
        "type": "type", "details": "details", "price": "price",
        "deadline": "deadline", "status": "status",
        "note": "note", "comment": "comment",
    }
    updates = [(field_map[k], p[k]) for k in field_map if k in p]
    if not updates:
        return {"success": True}
    sql = "UPDATE orders SET " + ", ".join(f"{col}=?" for col, _ in updates) + " WHERE id=?"
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(sql, [v for _, v in updates] + [p["id"]])
        await db.commit()
    return {"success": True}


async def update_status(order_id: str, status: str) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("UPDATE orders SET status=? WHERE id=?", (status, order_id))
        await db.commit()
        return cur.rowcount > 0


async def move_to_archive(order_id: str) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT * FROM orders WHERE id=?", (order_id,)) as cur:
            row = await cur.fetchone()
        if not row:
            return False
        vals = list(row)
        vals[13] = "Отдано"  # status is index 13
        await db.execute(
            """INSERT OR REPLACE INTO archive
               (id, row_num, date, name, username, client_id, item, model,
                article, type, details, price, deadline, status, photo, note, comment)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            vals
        )
        await db.execute("DELETE FROM orders WHERE id=?", (order_id,))
        await db.commit()
    return True


async def bot_polling_loop():
    pass  # implemented in Task 5
```

- [ ] **Step 3.2: Verify order write endpoints**

With the dev server running:

```bash
# Get a session token (use real initData from Telegram, or test with a known-valid token)
# For local testing, generate token directly:
python -c "from auth import generate_token; print(generate_token())"
# copy the output as TOKEN_VALUE

curl "http://localhost:8000/?action=createOrder&token=TOKEN_VALUE&name=TestName&item=TestItem&model=Lada&type=Заказ&price=100&clientId=123456789"
# expected: {"success":true,"id":"DDMM-789","folderUrl":"uploads/DDMM-789"}

curl "http://localhost:8000/?action=getOrders"
# expected: {"orders":[{...the order you just created...}]}

curl "http://localhost:8000/?action=updateStatus&token=TOKEN_VALUE&id=DDMM-789&status=В+работе"
# expected: {"success":true}

curl "http://localhost:8000/?action=archiveOrder&token=TOKEN_VALUE&id=DDMM-789"
# expected: {"success":true}

curl "http://localhost:8000/?action=getOrders"
# expected: {"orders":[]}

curl "http://localhost:8000/?action=getArchive"
# expected: {"orders":[{...archived order...}]}
```

- [ ] **Step 3.3: Commit**

```bash
git add main.py
git commit -m "feat: add order write endpoints (createOrder, updateOrder, updateStatus, archiveOrder)"
```

---

## Task 4: Write Endpoints — Purchases

**Files:**
- Modify: `main.py` — add purchase write functions (before `bot_polling_loop`)

- [ ] **Step 4.1: Add purchase write functions to main.py**

Add these functions before `bot_polling_loop`:

```python
async def create_purchase(p: dict) -> dict:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT INTO purchases (date, item, quantity, price, order_id, order_name, status, note)
               VALUES (?,?,?,?,?,?,?,?)""",
            (today_str(), p.get("item", ""), p.get("quantity", ""),
             p.get("price", ""), p.get("orderId", ""), p.get("orderName", ""),
             p.get("status", "Купить"), p.get("note", ""))
        )
        await db.commit()
    return {"success": True}


async def update_purchase(p: dict) -> dict:
    field_map = {
        "date": "date", "item": "item", "quantity": "quantity",
        "price": "price", "orderId": "order_id", "orderName": "order_name",
        "status": "status", "note": "note",
    }
    updates = [(field_map[k], p[k]) for k in field_map if k in p]
    if not updates:
        return {"success": True}
    sql = "UPDATE purchases SET " + ", ".join(f"{col}=?" for col, _ in updates) + " WHERE id=?"
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(sql, [v for _, v in updates] + [int(p["rowIndex"])])
        await db.commit()
    return {"success": True}


async def toggle_purchase_status(row_id: int) -> dict:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT status FROM purchases WHERE id=?", (row_id,)) as cur:
            row = await cur.fetchone()
        if not row:
            return {"success": False, "error": "Not found"}
        new_status = "Купить" if row[0] == "Куплено" else "Куплено"
        await db.execute("UPDATE purchases SET status=? WHERE id=?", (new_status, row_id))
        await db.commit()
    return {"success": True, "newStatus": new_status}
```

- [ ] **Step 4.2: Verify purchase endpoints**

```bash
python -c "from auth import generate_token; print(generate_token())"
# copy as TOKEN_VALUE

curl "http://localhost:8000/?action=createPurchase&token=TOKEN_VALUE&item=Нитки&quantity=2&price=300&orderId=0101-001&orderName=TestName"
# expected: {"success":true}

curl "http://localhost:8000/?action=getPurchases"
# expected: {"purchases":[{"rowIndex":1,"item":"Нитки",...}]}

curl "http://localhost:8000/?action=togglePurchaseStatus&token=TOKEN_VALUE&rowIndex=1"
# expected: {"success":true,"newStatus":"Куплено"}

curl "http://localhost:8000/?action=deletePurchase&token=TOKEN_VALUE&rowIndex=1"
# expected: {"success":true}
```

- [ ] **Step 4.3: Commit**

```bash
git add main.py
git commit -m "feat: add purchase write endpoints"
```

---

## Task 5: Telegram Bot Polling

**Files:**
- Modify: `main.py` — replace `bot_polling_loop` stub and add all bot handler functions

- [ ] **Step 5.1: Add bot helpers and report functions to main.py**

Replace `async def bot_polling_loop(): pass` with the full implementation below.

Add these functions (paste after `toggle_purchase_status`):

```python
# ── Bot helpers ───────────────────────────────────────────────────────────────

async def send_message(chat_id, text: str):
    async with httpx.AsyncClient() as client:
        await client.post(
            f"https://api.telegram.org/bot{TOKEN}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": "HTML",
                  "disable_web_page_preview": True},
            timeout=10,
        )


async def download_photo(file_id: str, dest_path: str):
    async with httpx.AsyncClient() as client:
        r = await client.get(f"https://api.telegram.org/bot{TOKEN}/getFile?file_id={file_id}")
        file_path = r.json()["result"]["file_path"]
        photo_bytes = (await client.get(f"https://api.telegram.org/file/bot{TOKEN}/{file_path}")).content
    with open(dest_path, "wb") as f:
        f.write(photo_bytes)


async def save_photo_to_order(order_id: str, photo: list, prefix: str) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT photo FROM orders WHERE id=?", (order_id,)) as cur:
            row = await cur.fetchone()
    if not row:
        return False
    folder = row[0] or os.path.join(UPLOAD_DIR, order_id)
    os.makedirs(folder, exist_ok=True)
    file_id = photo[-1]["file_id"]
    dest = os.path.join(folder, f"{prefix}_{order_id}.jpg")
    await download_photo(file_id, dest)
    return True


# ── Bot report functions ──────────────────────────────────────────────────────

async def get_work_report() -> str:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT * FROM orders ORDER BY rowid") as cur:
            rows = [row_to_order(r) for r in await cur.fetchall()]
    in_work, queue, ready = [], [], []
    for r in rows:
        line = f"• <b>#{r['id']}</b> {r['name']} — <i>{r['item']}</i>"
        s = r["status"].lower()
        if s == "в работе":
            in_work.append(line)
        elif s == "готово":
            ready.append(line)
        else:
            queue.append(line)
    return (
        "🔵 <b>В РАБОТЕ:</b>\n" + ("\n".join(in_work) or "<i>пусто</i>") + "\n\n"
        "⚪ <b>ОЧЕРЕДЬ:</b>\n" + ("\n".join(queue) or "<i>пусто</i>") + "\n\n"
        "🟢 <b>ГОТОВО:</b>\n" + ("\n".join(ready) or "<i>пусто</i>")
    )


async def get_buy_report() -> str:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT * FROM orders") as cur:
            rows = [row_to_order(r) for r in await cur.fetchall()]
    items = [
        f"🛒 <b>#{r['id']}</b> ({r['name']})\n      └ {r['details']}"
        for r in rows
        if "купить" in r["details"].lower() or "нет в наличии" in r["details"].lower()
    ]
    return "\n".join(items) if items else "✅ Все в наличии!"


async def get_money_report() -> str:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT price FROM archive") as cur:
            prices = [r[0] for r in await cur.fetchall()]
    total = sum(float(p) for p in prices if p and p.replace(".", "").replace("-", "").isdigit())
    return f"💰 <b>Общий доход:</b> {total:.0f} RSD"


async def get_week_report() -> str:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT * FROM orders") as cur:
            rows = [row_to_order(r) for r in await cur.fetchall()]
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    next_week = today + timedelta(days=7)
    items = []
    for r in rows:
        if not r["deadline"]:
            continue
        parts = r["deadline"].split(".")
        if len(parts) != 3:
            continue
        try:
            d = datetime(int(parts[2]), int(parts[1]), int(parts[0]))
            if today <= d <= next_week:
                items.append(
                    f"📅 <b>#{r['id']}</b> — {r['name']} — <i>{r['item']}</i>\n"
                    f"      └ <b>Срок: {r['deadline']}</b>"
                )
        except ValueError:
            pass
    return "🗓 <b>ПЛАН НА НЕДЕЛЮ:</b>\n\n" + "\n\n".join(items) if items else "🏖 Дедлайнов нет!"


async def get_models_stat(month_arg: str | None) -> str:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT model, date FROM orders") as cur:
            active = await cur.fetchall()
        async with db.execute("SELECT model, date FROM archive") as cur:
            archived = await cur.fetchall()

    month_map = {
        "янв": 1, "фев": 2, "мар": 3, "апр": 4, "май": 5, "июн": 6,
        "июл": 7, "авг": 8, "сен": 9, "окт": 10, "ноя": 11, "дек": 12,
        **{str(i).zfill(2): i for i in range(1, 13)},
    }
    target_month = None
    if month_arg:
        for key, val in month_map.items():
            if month_arg.lower().startswith(key):
                target_month = val
                break

    now = datetime.now()
    counts: dict[str, int] = {}
    for model, date_str in (active + archived):
        if not model or model == "Не указана":
            continue
        if target_month is not None:
            parts = (date_str or "").split(".")
            if len(parts) == 3:
                try:
                    if int(parts[1]) != target_month or int(parts[2]) != now.year:
                        continue
                except ValueError:
                    continue
        counts[model] = counts.get(model, 0) + 1

    sorted_counts = sorted(counts.items(), key=lambda x: -x[1])
    title = f"📊 СТАТИСТИКА ЗА {month_arg.upper()}" if target_month else "📊 РЕЙТИНГ МОДЕЛЕЙ (ВСЕ)"
    if not sorted_counts:
        return "❌ Нет данных за этот период."
    lines = "\n".join(f"• {name}: <b>{cnt} шт.</b>" for name, cnt in sorted_counts)
    return f"{title}:\n\n{lines}"


async def add_new_order_from_bot(chat_id, text: str, photo: list | None):
    lines = text.split("\n")
    d = {"name": "Имя", "username": "", "item": "Изделие", "model": "Не указана",
         "details": "", "price": "0", "deadline": "", "comment": ""}
    for line in lines:
        if ":" not in line:
            continue
        key, _, val = line.partition(":")
        val = val.strip()
        mapping = {
            "имя": "name", "username": "username", "изделие": "item",
            "модель": "model", "детали": "details", "цена": "price",
            "срок": "deadline", "комментарий": "comment",
        }
        for ru, en in mapping.items():
            if ru in key.lower():
                d[en] = val
    result = await create_order(d)
    order_id = result.get("id", "?")
    if photo:
        await save_photo_to_order(order_id, photo, "Эскиз")
    await send_message(chat_id, f"✅ Заказ <b>#{order_id}</b> добавлен!\nМодель: <b>{d['model']}</b>")


# ── Scheduled report helpers ──────────────────────────────────────────────────

async def send_monday_report():
    work = await get_work_report()
    week = await get_week_report()
    await send_message(MY_CHAT_ID, f"🚀 <b>ПОНЕДЕЛЬНИК: ПЛАН MOROSKA</b>\n\n{work}\n\n──────────────────\n\n{week}")


async def send_deadline_reminder():
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT * FROM orders") as cur:
            rows = [row_to_order(r) for r in await cur.fetchall()]
    target = (datetime.now() + timedelta(days=7)).strftime("%d.%m.%Y")
    items = [
        f"📅 <b>#{r['id']}</b> {r['name']} — <i>{r['item']}</i>\n      └ Срок: <b>{r['deadline']}</b>"
        for r in rows if r["deadline"] == target
    ]
    if items:
        await send_message(MY_CHAT_ID, "⏰ <b>ДЕДЛАЙН ЧЕРЕЗ 7 ДНЕЙ:</b>\n\n" + "\n\n".join(items))


async def send_monthly_stats():
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT price FROM archive") as cur:
            prices = [r[0] for r in await cur.fetchall()]
        async with db.execute("SELECT COUNT(*) FROM archive") as cur:
            count = (await cur.fetchone())[0]
    total = sum(float(p) for p in prices if p and p.replace(".", "").replace("-", "").isdigit())
    await send_message(MY_CHAT_ID,
        f"📊 <b>ИТОГИ МЕСЯЦА</b>\n✅ Завершено: <b>{count}</b>\n💰 Доход: <b>{total:.0f} RSD</b>")


# ── Bot polling loop ──────────────────────────────────────────────────────────

async def handle_bot_message(msg: dict):
    chat_id = msg["chat"]["id"]
    text = (msg.get("text") or msg.get("caption") or "").strip()
    photo = msg.get("photo")

    try:
        if text in ("/new", "/start"):
            models = "Lada, Larna, Verbena, Ilma, ролл, тарелочка, мусорничка, чехол пяльца, чехол рама, Taloma, Tala, Loboda"
            await send_message(chat_id,
                f"🧶 <b>Шаблон Moroska:</b>\n\nНовый заказ\nИмя: \nUsername: \nИзделие: \nМодель: \n"
                f"Детали: \nЦена: \nСрок: \nКомментарий: \n\n💡 <b>Твои модели:</b>\n<i>{models}</i>")
            return

        if text.lower() == "/work":
            await send_message(chat_id, await get_work_report())
            return
        if text.lower() == "/buy":
            await send_message(chat_id, await get_buy_report())
            return
        if text.lower() == "/money":
            await send_message(chat_id, await get_money_report())
            return
        if text.lower() == "/week":
            await send_message(chat_id, await get_week_report())
            return
        if text.lower().startswith("/models"):
            arg = text.split(" ")[1] if " " in text else None
            await send_message(chat_id, await get_models_stat(arg))
            return

        status_match = re.match(r"^(в работе|пауза|готово|отдано)\s+(\S+)$", text.lower())
        if status_match:
            label, order_id = status_match.group(1), status_match.group(2)
            final_status = {"в работе": "В работе", "пауза": "Пауза",
                            "готово": "Готово", "отдано": "Отдано"}[label]
            if label == "отдано":
                ok = await move_to_archive(order_id)
                await send_message(chat_id,
                    f"📦 Заказ <b>#{order_id}</b> перенесен в архив!" if ok else "❌ Не найден.")
            else:
                ok = await update_status(order_id, final_status)
                if ok and photo:
                    await save_photo_to_order(order_id, photo, final_status)
                await send_message(chat_id,
                    f"✅ <b>#{order_id}</b> статус: {final_status}" if ok else "❌ Не найден.")
            return

        if "новый заказ" in text.lower():
            await add_new_order_from_bot(chat_id, text, photo)
            return

        if re.match(r"^\d+$", text) and photo:
            ok = await save_photo_to_order(text, photo, "Процесс")
            await send_message(chat_id,
                f"📸 Фото сохранено в <b>#{text}</b>" if ok else "❌ Не найден.")
            return

    except Exception as e:
        await send_message(chat_id, f"⚠️ Ошибка: {e}")


async def scheduled_tasks_loop():
    """Fires Monday report and deadline reminder daily at 09:00."""
    while True:
        now = datetime.now()
        next_run = now.replace(hour=9, minute=0, second=0, microsecond=0)
        if now >= next_run:
            next_run = next_run + timedelta(days=1)
        await asyncio.sleep((next_run - now).total_seconds())
        now = datetime.now()
        if now.weekday() == 0:  # Monday
            await send_monday_report()
        await send_deadline_reminder()
        # First day of month
        if now.day == 1:
            await send_monthly_stats()


async def bot_polling_loop():
    offset = 0
    async with httpx.AsyncClient(timeout=40) as client:
        while True:
            try:
                resp = await client.get(
                    f"https://api.telegram.org/bot{TOKEN}/getUpdates",
                    params={"offset": offset, "timeout": 30},
                )
                for update in resp.json().get("result", []):
                    offset = update["update_id"] + 1
                    if msg := update.get("message"):
                        asyncio.create_task(handle_bot_message(msg))
            except Exception:
                await asyncio.sleep(5)
```

Also update `on_startup` to launch the scheduled task:

```python
@app.on_event("startup")
async def on_startup():
    await init_db()
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    asyncio.create_task(bot_polling_loop())
    asyncio.create_task(scheduled_tasks_loop())
```

- [ ] **Step 5.2: Verify bot polling starts**

Restart the dev server and watch logs:

```bash
uvicorn main:app --reload
```

Expected in logs: no errors on startup. Send `/work` to the bot in Telegram — should get a response listing active orders.

- [ ] **Step 5.3: Commit**

```bash
git add main.py
git commit -m "feat: Telegram bot polling with all commands and scheduled reports"
```

---

## Task 6: Migration Script

**Files:**
- Create: `migrate.py`

- [ ] **Step 6.1: Create migrate.py**

```python
"""
One-time migration from Google Sheets CSV exports to SQLite.

Usage:
    python migrate.py --orders Actual.csv --archive Archive.csv --purchases Purchase.csv

Export CSVs from Google Sheets: File → Download → CSV (one sheet at a time).
"""
import argparse
import asyncio
import csv
import os

import aiosqlite
from dotenv import load_dotenv

load_dotenv()

from db import DB_PATH, init_db

ORDER_FIELDS = [
    "id", "row_num", "date", "name", "username", "client_id",
    "item", "model", "article", "type", "details", "price",
    "deadline", "status", "photo", "note", "comment",
]


async def import_orders(csv_path: str, table: str):
    with open(csv_path, encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        next(reader)  # skip header
        rows = [r for r in reader if len(r) >= 2 and r[1].strip()]  # skip empty id

    cols = ", ".join(ORDER_FIELDS)
    placeholders = ", ".join("?" * len(ORDER_FIELDS))
    async with aiosqlite.connect(DB_PATH) as db:
        for row in rows:
            # Pad or trim to 17 columns
            vals = (row + [""] * 17)[:17]
            await db.execute(
                f"INSERT OR IGNORE INTO {table} ({cols}) VALUES ({placeholders})",
                vals,
            )
        await db.commit()
    print(f"Imported {len(rows)} rows into {table}")


PURCHASE_FIELDS = ["date", "item", "quantity", "price", "order_id", "order_name", "status", "note"]


async def import_purchases(csv_path: str):
    with open(csv_path, encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        next(reader)  # skip header
        rows = [r for r in reader if len(r) >= 2 and r[1].strip()]

    async with aiosqlite.connect(DB_PATH) as db:
        for row in rows:
            vals = (row + [""] * 8)[:8]
            await db.execute(
                "INSERT INTO purchases (date, item, quantity, price, order_id, order_name, status, note) VALUES (?,?,?,?,?,?,?,?)",
                vals,
            )
        await db.commit()
    print(f"Imported {len(rows)} rows into purchases")


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--orders", help="Actual.csv path")
    parser.add_argument("--archive", help="Archive.csv path")
    parser.add_argument("--purchases", help="Purchase.csv path")
    args = parser.parse_args()

    await init_db()

    if args.orders:
        await import_orders(args.orders, "orders")
    if args.archive:
        await import_orders(args.archive, "archive")
    if args.purchases:
        await import_purchases(args.purchases)

    print("Migration complete.")


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 6.2: Test migration with a sample CSV**

Create `test_orders.csv`:
```
№,ID заказа,Дата создания,Имя,Username,ID клиента,Изделие,Модель,Артикул,Тип,Детали,Цена,Срок,Статус,Фото,Заметка,Комментарий
1,0101-001,01.01.2025,Анна,,123456789,Сумка,Lada,,Заказ,Детали тест,2000,15.02.2025,Готово,,Заметка,
```

```bash
python migrate.py --orders test_orders.csv
# expected: Imported 1 rows into orders

curl "http://localhost:8000/?action=getOrders"
# expected: {"orders":[{"id":"0101-001","name":"Анна",...}]}

rm test_orders.csv
```

- [ ] **Step 6.3: Commit**

```bash
git add migrate.py
git commit -m "feat: add CSV migration script"
```

---

## Task 7: Frontend Update

**Files:**
- Modify: `index.html` — update `SCRIPT_URL` and bump `APP_VERSION`

- [ ] **Step 7.1: Update SCRIPT_URL and APP_VERSION in index.html**

In `index.html`, find and update these two lines (around line 457–458):

```js
const APP_VERSION = '1.1.0';
const SCRIPT_URL = 'https://your-ubuntu-domain.com';
```

Replace `your-ubuntu-domain.com` with the actual domain configured in nginx.

- [ ] **Step 7.2: Verify end-to-end in Telegram**

Open the Mini App in Telegram. Confirm:
- Orders list loads (no console errors)
- Auth succeeds (no "DEBUG: sessionToken is null" alert)
- Creating a new order works

- [ ] **Step 7.3: Commit**

```bash
git add index.html
git commit -m "feat: switch SCRIPT_URL to Python backend, bump to 1.1.0"
```

---

## Task 8: Deployment Config

**Files:**
- Create: `deploy/moroska.service`
- Create: `deploy/datasette.service`
- Create: `deploy/nginx.conf`

- [ ] **Step 8.1: Create systemd unit for the FastAPI server**

`deploy/moroska.service`:
```ini
[Unit]
Description=Moroska Orders API
After=network.target

[Service]
User=ubuntu
WorkingDirectory=/home/ubuntu/moroska
EnvironmentFile=/home/ubuntu/moroska/.env
ExecStart=/home/ubuntu/moroska/.venv/bin/uvicorn main:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

- [ ] **Step 8.2: Create systemd unit for Datasette**

`deploy/datasette.service`:
```ini
[Unit]
Description=Datasette GUI for Moroska orders.db
After=network.target

[Service]
User=ubuntu
WorkingDirectory=/home/ubuntu/moroska
ExecStart=/home/ubuntu/moroska/.venv/bin/datasette /home/ubuntu/moroska/orders.db --host 127.0.0.1 --port 8001
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

- [ ] **Step 8.3: Create nginx config snippet**

`deploy/nginx.conf`:
```nginx
server {
    listen 443 ssl;
    server_name your-domain.com;

    # SSL — managed by certbot, it will fill these in
    ssl_certificate     /etc/letsencrypt/live/your-domain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/your-domain.com/privkey.pem;

    location / {
        proxy_pass         http://127.0.0.1:8000;
        proxy_set_header   Host $host;
        proxy_set_header   X-Real-IP $remote_addr;
        proxy_read_timeout 60s;
    }
}

server {
    listen 80;
    server_name your-domain.com;
    return 301 https://$host$request_uri;
}
```

- [ ] **Step 8.4: Server setup commands (run on Ubuntu)**

```bash
# 1. Copy project files to server
scp -r . ubuntu@your-server:/home/ubuntu/moroska/

# 2. On the server: create venv and install deps
cd /home/ubuntu/moroska
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# 3. Install and enable systemd services
sudo cp deploy/moroska.service /etc/systemd/system/
sudo cp deploy/datasette.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable moroska datasette
sudo systemctl start moroska datasette

# 4. Set up nginx + HTTPS
sudo apt install nginx certbot python3-certbot-nginx -y
sudo cp deploy/nginx.conf /etc/nginx/sites-available/moroska
sudo ln -s /etc/nginx/sites-available/moroska /etc/nginx/sites-enabled/
sudo certbot --nginx -d your-domain.com
sudo systemctl reload nginx

# 5. Verify
sudo systemctl status moroska
curl https://your-domain.com/?action=getOrders
```

- [ ] **Step 8.5: Access Datasette GUI via SSH tunnel**

```bash
# From your laptop:
ssh -L 8001:localhost:8001 ubuntu@your-server
# Then open http://localhost:8001 in browser
```

- [ ] **Step 8.6: Commit**

```bash
git add deploy/
git commit -m "feat: add systemd service files and nginx config"
```

---

## Done

At this point:
- FastAPI server handles all Mini App GET requests
- Telegram bot runs in polling mode in the same process
- SQLite stores all data; Datasette provides GUI
- `index.html` points to the new server
- Old Google Apps Script can be left as-is or deleted
