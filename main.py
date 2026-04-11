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
    asyncio.create_task(scheduled_tasks_loop())


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


# ── Write handlers ────────────────────────────────────────────────────────────

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


# ── Purchase handlers ─────────────────────────────────────────────────────────

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
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = os.path.join(folder, f"{prefix}_{order_id}_{ts}.jpg")
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


# ── Bot message handler ───────────────────────────────────────────────────────

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

        if re.match(r"^\d+$|^\d{4}-\d{3}$", text) and photo:
            ok = await save_photo_to_order(text, photo, "Процесс")
            await send_message(chat_id,
                f"📸 Фото сохранено в <b>#{text}</b>" if ok else "❌ Не найден.")
            return

    except Exception as e:
        await send_message(chat_id, f"⚠️ Ошибка: {e}")


# ── Scheduled tasks loop ──────────────────────────────────────────────────────

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
        if now.day == 1:  # First day of month
            await send_monthly_stats()


# ── Bot polling loop ──────────────────────────────────────────────────────────

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
