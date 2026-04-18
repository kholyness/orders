import asyncio
import logging
import os
import re
from datetime import datetime, timedelta

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

import sheets
from auth import ALLOWED_CHAT_IDS, generate_token, validate_init_data, validate_token

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

TOKEN = os.getenv("TOKEN", "")
MY_CHAT_ID = os.getenv("MY_CHAT_ID", "")

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.on_event("startup")
async def on_startup():
    asyncio.create_task(bot_polling_loop())
    asyncio.create_task(scheduled_tasks_loop())


# ── Row helpers ────────────────────────────────────────────────────────────────
# Sheets column order: №, ID заказа, Дата, Имя, Username, ID клиента,
# Изделие, Модель, Артикул, Тип, Детали, Цена, Срок, Статус, Фото, Заметка, Комментарий

def row_to_order(row) -> dict:
    row = list(row)
    while len(row) < 18:
        row.append("")
    return {
        "rowNum": row[0] or "",
        "id": row[1] or "",
        "date": row[2] or "",
        "name": row[3] or "",
        "username": row[4] or "",
        "clientId": row[5] or "",
        "item": row[6] or "",
        "model": row[7] or "",
        "article": row[8] or "",
        "type": row[9] or "",
        "details": row[10] or "",
        "price": row[11] or "",
        "deadline": row[12] or "",
        "status": row[13] or "",
        "note": row[15] or "",
        "comment": row[16] or "",
        "closedDate": row[17] or "",
    }


def row_to_purchase(row, row_index: int) -> dict:
    row = list(row)
    while len(row) < 8:
        row.append("")
    return {
        "rowIndex": row_index,
        "date": row[0] or "",
        "item": row[1] or "",
        "quantity": row[2] or "",
        "price": row[3] or "",
        "orderId": row[4] or "",
        "orderName": row[5] or "",
        "status": row[6] or "",
        "note": row[7] or "",
    }


def today_str() -> str:
    return datetime.now().strftime("%d.%m.%Y")


# ── Main router ────────────────────────────────────────────────────────────────

@app.get("/")
async def handle(request: Request):
    p = dict(request.query_params)
    action = p.get("action", "")

    if action == "auth":
        if not validate_init_data(p.get("initData", "")):
            return JSONResponse({"error": "Unauthorized"})
        return JSONResponse({"token": generate_token()})

    if action == "getOrders":
        rows = await sheets.get_orders()
        return JSONResponse({"orders": [row_to_order(r) for r in rows]})

    if action == "getArchive":
        rows = await sheets.get_archive()
        return JSONResponse({"orders": [row_to_order(r) for r in rows]})

    if action == "getPurchases":
        purchases = await sheets.get_purchases()
        return JSONResponse({"purchases": [row_to_purchase(row, idx) for idx, row in purchases]})

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
    active_rows, archived_rows = await asyncio.gather(sheets.get_orders(), sheets.get_archive())
    active = [row_to_order(r) for r in active_rows]
    archived = [row_to_order(r) for r in archived_rows]
    all_orders = active + archived

    def to_float(s):
        try:
            return float(str(s).replace('\xa0', '').replace(' ', '').replace(',', '.'))
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

    monthly: dict[str, dict] = {}
    for r in archived:
        parts = (r["closedDate"] or r["date"]).split(".")
        if len(parts) == 3:
            try:
                mo, yr = int(parts[1]), int(parts[2])
                key = f"{mo:02d}.{yr}"
                if key not in monthly:
                    monthly[key] = {"month": mo, "year": yr, "count": 0, "income": 0.0}
                monthly[key]["count"] += 1
                monthly[key]["income"] += to_float(r["price"])
            except (ValueError, IndexError):
                pass
    monthly_list = sorted(monthly.values(), key=lambda x: (x["year"], x["month"]))

    return {
        "activeCount": len(active),
        "archiveCount": len(archived),
        "typeOrder": type_order,
        "typeStock": type_stock,
        "income": income,
        "topModels": [{"name": n, "count": c} for n, c in top_models],
        "upcomingDeadlines": upcoming,
        "byMonth": monthly_list,
    }


# ── Write handlers ─────────────────────────────────────────────────────────────

async def handle_write(action: str, p: dict) -> dict:
    if action == "createOrder":
        return await create_order(p)
    if action == "updateOrder":
        return await update_order(p)
    if action == "updateStatus":
        ok = await sheets.update_order(p["id"], {13: p.get("status", "")})
        if p.get("status") == "Отдано":
            await sheets.move_to_archive(p["id"])
        if p.get("status") in ("Готово", "Отдано"):
            await sheets.delete_purchases_for_order(p["id"])
        return {"success": ok}
    if action == "archiveOrder":
        await sheets.delete_purchases_for_order(p["id"])
        return {"success": await sheets.move_to_archive(p["id"])}
    if action == "createPurchase":
        return await create_purchase(p)
    if action == "updatePurchase":
        return await update_purchase(p)
    if action == "deletePurchase":
        await sheets.delete_purchase(int(p["rowIndex"]))
        return {"success": True}
    if action == "togglePurchaseStatus":
        return await toggle_purchase_status(int(p["rowIndex"]))
    return {"error": f"Unknown action: {action}"}


async def create_order(p: dict) -> dict:
    count = await sheets.count_orders()
    row_num = count + 1
    client_id = p.get("clientId", "") or p.get("client_id", "")
    now = datetime.now()
    ddmm = now.strftime("%d%m")
    suffix = client_id[-3:] if len(client_id) >= 3 else str(row_num).zfill(3)
    order_id = f"{ddmm}-{suffix}"

    row = [
        str(row_num),
        order_id,
        now.strftime("%d.%m.%Y"),
        p.get("name", ""),
        p.get("username", ""),
        client_id,
        p.get("item", ""),
        p.get("model", ""),
        p.get("article", ""),
        p.get("type", "Заказ"),
        p.get("details", ""),
        p.get("price", ""),
        p.get("deadline", ""),
        "Очередь",
        "",
        "",
        p.get("comment", ""),
    ]
    await sheets.append_order(row)
    return {"success": True, "id": order_id}


async def update_order(p: dict) -> dict:
    col_updates = {
        sheets.ORDER_FIELD_COL[k]: p[k]
        for k in sheets.ORDER_FIELD_COL
        if k in p
    }
    if not col_updates:
        return {"success": True}
    sheet_name = "Archive" if p.get("sheet") == "archive" else "Actual"
    ok = await sheets.update_order(p["id"], col_updates, sheet_name)
    return {"success": ok}


async def create_purchase(p: dict) -> dict:
    row = [
        today_str(),
        p.get("item", ""),
        p.get("quantity", ""),
        p.get("price", ""),
        p.get("orderId", ""),
        p.get("orderName", ""),
        p.get("status", "Купить"),
        p.get("note", ""),
    ]
    await sheets.append_purchase(row)
    return {"success": True}


async def update_purchase(p: dict) -> dict:
    col_updates = {
        sheets.PURCHASE_FIELD_COL[k]: p[k]
        for k in sheets.PURCHASE_FIELD_COL
        if k in p
    }
    if not col_updates:
        return {"success": True}
    ok = await sheets.update_purchase(int(p["rowIndex"]), col_updates)
    return {"success": ok}


async def toggle_purchase_status(row_num: int) -> dict:
    current = await sheets.get_purchase_status(row_num)
    if current is None:
        return {"success": False, "error": "Not found"}
    new_status = "Купить" if current == "Куплено" else "Куплено"
    await sheets.update_purchase(row_num, {sheets.PURCHASE_FIELD_COL["status"]: new_status})
    return {"success": True, "newStatus": new_status}


# ── Bot helpers ────────────────────────────────────────────────────────────────

async def send_message(chat_id, text: str):
    async with httpx.AsyncClient() as client:
        await client.post(
            f"https://api.telegram.org/bot{TOKEN}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": "HTML",
                  "disable_web_page_preview": True},
            timeout=10,
        )


# ── Bot report functions ───────────────────────────────────────────────────────

async def get_work_report() -> str:
    rows = await sheets.get_orders()
    orders = [row_to_order(r) for r in rows]
    in_work, queue, ready = [], [], []
    for r in orders:
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
    rows = await sheets.get_orders()
    orders = [row_to_order(r) for r in rows]
    items = [
        f"🛒 <b>#{r['id']}</b> ({r['name']})\n      └ {r['details']}"
        for r in orders
        if "купить" in r["details"].lower() or "нет в наличии" in r["details"].lower()
    ]
    return "\n".join(items) if items else "✅ Все в наличии!"


async def get_money_report() -> str:
    rows = await sheets.get_archive()
    prices = [row_to_order(r)["price"] for r in rows]
    total = sum(float(p) for p in prices if p and p.replace(".", "").replace("-", "").isdigit())
    return f"💰 <b>Общий доход:</b> {total:.0f} RSD"


async def get_week_report() -> str:
    rows = await sheets.get_orders()
    orders = [row_to_order(r) for r in rows]
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    next_week = today + timedelta(days=7)
    items = []
    for r in orders:
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
    active_rows, archived_rows = await asyncio.gather(sheets.get_orders(), sheets.get_archive())
    all_rows = [(r[7], r[2]) for r in active_rows] + [(r[7], r[2]) for r in archived_rows]

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
    for model, date_str in all_rows:
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


async def add_new_order_from_bot(chat_id, text: str):
    lines = text.split("\n")
    d = {"name": "Имя", "username": "", "clientId": "", "item": "Изделие", "model": "Не указана",
         "details": "", "price": "0", "deadline": "", "comment": "", "note": ""}
    for line in lines:
        if ":" not in line:
            continue
        key, _, val = line.partition(":")
        val = val.strip()
        mapping = {
            "имя": "name", "username": "username", "id клиента": "clientId",
            "изделие": "item", "модель": "model", "детали": "details",
            "цена": "price", "срок": "deadline", "комментарий": "comment",
            "заметка": "note",
        }
        for ru, en in mapping.items():
            if ru in key.lower():
                d[en] = val
    result = await create_order(d)
    order_id = result.get("id", "?")
    await send_message(chat_id, f"✅ Заказ <b>#{order_id}</b> добавлен!\nМодель: <b>{d['model']}</b>")


# ── Scheduled report helpers ───────────────────────────────────────────────────

async def send_monday_report():
    work = await get_work_report()
    week = await get_week_report()
    await send_message(MY_CHAT_ID, f"🚀 <b>ПОНЕДЕЛЬНИК: ПЛАН MOROSKA</b>\n\n{work}\n\n──────────────────\n\n{week}")


async def send_deadline_reminder():
    rows = await sheets.get_orders()
    orders = [row_to_order(r) for r in rows]
    target = (datetime.now() + timedelta(days=7)).strftime("%d.%m.%Y")
    items = [
        f"📅 <b>#{r['id']}</b> {r['name']} — <i>{r['item']}</i>\n      └ Срок: <b>{r['deadline']}</b>"
        for r in orders if r["deadline"] == target
    ]
    if items:
        await send_message(MY_CHAT_ID, "⏰ <b>ДЕДЛАЙН ЧЕРЕЗ 7 ДНЕЙ:</b>\n\n" + "\n\n".join(items))


async def send_monthly_stats():
    rows = await sheets.get_archive()
    prices = [row_to_order(r)["price"] for r in rows]
    total = sum(float(p) for p in prices if p and p.replace(".", "").replace("-", "").isdigit())
    count = len(rows)
    await send_message(MY_CHAT_ID,
        f"📊 <b>ИТОГИ МЕСЯЦА</b>\n✅ Завершено: <b>{count}</b>\n💰 Доход: <b>{total:.0f} RSD</b>")


# ── Bot message handler ────────────────────────────────────────────────────────

async def handle_bot_message(msg: dict):
    chat_id = msg["chat"]["id"]
    if str(chat_id) not in ALLOWED_CHAT_IDS:
        logger.warning("ignored message from unknown chat_id=%s", chat_id)
        return
    text = (msg.get("text") or "").strip()
    logger.info("bot msg chat=%s text=%r", chat_id, text)

    try:
        # Forwarded message — pre-fill order template with client info
        forward_from = msg.get("forward_from")
        forward_origin = msg.get("forward_origin")
        if forward_from or forward_origin:
            name, username, client_id = "", "", ""
            if forward_from:
                name = f"{forward_from.get('first_name', '')} {forward_from.get('last_name', '')}".strip()
                username = forward_from.get("username", "")
                client_id = str(forward_from.get("id", ""))
            elif forward_origin:
                if forward_origin.get("type") == "user":
                    u = forward_origin.get("sender_user", {})
                    name = f"{u.get('first_name', '')} {u.get('last_name', '')}".strip()
                    username = u.get("username", "")
                    client_id = str(u.get("id", ""))
                elif forward_origin.get("type") == "hidden_user":
                    name = forward_origin.get("sender_user_name", "")
            username_str = f"@{username}" if username else ""
            models = "Слинг Verbena, Кроссбоди Lada, Кроссбоди Larna, Шоппер Tala, Шоппер Taloma, Рюкзак L, Брелок Ilma, Ролл для вышивки, Чехол на пяльца, Ловушка для ниток, Корзинка Loboda, Тарелочка, Мешочки для упаковки"
            await send_message(chat_id,
                f"👤 <b>{name}</b>{' / ' + username_str if username_str else ''}\n\n"
                f"Заполни и отправь:\n\n"
                f"Новый заказ\nИмя: {name}\nUsername: {username_str}\nID клиента: {client_id}\n"
                f"Изделие: \nМодель: \nДетали: \nЦена: \nСрок: \nКомментарий: \nЗаметка: \n\n"
                f"💡 <b>Модели:</b> <i>{models}</i>")
            return

        if text in ("/new", "/start"):
            models = "Слинг Verbena, Кроссбоди Lada, Кроссбоди Larna, Шоппер Tala, Шоппер Taloma, Рюкзак L, Брелок Ilma, Ролл для вышивки, Чехол на пяльца, Ловушка для ниток, Корзинка Loboda, Тарелочка, Мешочки для упаковки"
            await send_message(chat_id,
                f"🧶 <b>Шаблон Moroska:</b>\n\nНовый заказ\nИмя: \nUsername: \nИзделие: \nМодель: \n"
                f"Детали: \nЦена: \nСрок: \nКомментарий: \nЗаметка: \n\n💡 <b>Твои модели:</b>\n<i>{models}</i>")
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
                ok = await sheets.move_to_archive(order_id)
                await sheets.delete_purchases_for_order(order_id)
                await send_message(chat_id,
                    f"📦 Заказ <b>#{order_id}</b> перенесен в архив!" if ok else "❌ Не найден.")
            else:
                ok = await sheets.update_order(order_id, {13: final_status})
                if label == "готово":
                    await sheets.delete_purchases_for_order(order_id)
                await send_message(chat_id,
                    f"✅ <b>#{order_id}</b> статус: {final_status}" if ok else "❌ Не найден.")
            return

        if "новый заказ" in text.lower():
            await add_new_order_from_bot(chat_id, text)
            return

    except Exception as e:
        logger.exception("unhandled error in handle_bot_message chat=%s", chat_id)
        await send_message(chat_id, f"⚠️ Ошибка: {e}")


# ── Scheduled tasks loop ───────────────────────────────────────────────────────

async def scheduled_tasks_loop():
    while True:
        now = datetime.now()
        next_run = now.replace(hour=9, minute=0, second=0, microsecond=0)
        if now >= next_run:
            next_run = next_run + timedelta(days=1)
        await asyncio.sleep((next_run - now).total_seconds())
        now = datetime.now()
        if now.weekday() == 0:
            await send_monday_report()
        await send_deadline_reminder()
        if now.day == 1:
            await send_monthly_stats()


# ── Bot polling loop ───────────────────────────────────────────────────────────

def _task_error_handler(task: asyncio.Task) -> None:
    if not task.cancelled() and task.exception():
        logger.exception("unhandled exception in bot task", exc_info=task.exception())


async def bot_polling_loop():
    offset = 0
    async with httpx.AsyncClient(timeout=40) as client:
        while True:
            try:
                resp = await client.get(
                    f"https://api.telegram.org/bot{TOKEN}/getUpdates",
                    params={"offset": offset, "timeout": 30},
                )
                if resp.status_code == 409:
                    logger.warning("bot polling 409 Conflict — another instance is running, retrying in 5s")
                    await asyncio.sleep(5)
                    continue
                if resp.status_code != 200:
                    logger.warning("bot polling HTTP %s, retrying in 5s", resp.status_code)
                    await asyncio.sleep(5)
                    continue
                for update in resp.json().get("result", []):
                    offset = update["update_id"] + 1
                    if msg := update.get("message"):
                        task = asyncio.create_task(handle_bot_message(msg))
                        task.add_done_callback(_task_error_handler)
            except Exception:
                logger.exception("bot polling error, retrying in 5s")
                await asyncio.sleep(5)
