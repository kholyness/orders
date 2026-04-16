import asyncio
import os

import gspread
from google.oauth2.service_account import Credentials

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
]
CREDS_FILE = os.getenv("GOOGLE_CREDS_FILE", "credentials.json")
SHEET_ID = os.getenv("SHEET_ID", "")

_spreadsheet = None


def _get_ws(name: str):
    global _spreadsheet
    if _spreadsheet is None:
        creds = Credentials.from_service_account_file(CREDS_FILE, scopes=SCOPES)
        gc = gspread.authorize(creds)
        _spreadsheet = gc.open_by_key(SHEET_ID)
    return _spreadsheet.worksheet(name)


# Order columns (0-based): №, ID заказа, Дата, Имя, Username, ID клиента,
# Изделие, Модель, Артикул, Тип, Детали, Цена, Срок, Статус, Фото, Заметка, Комментарий
ORDER_FIELD_COL = {
    "name": 3, "username": 4, "clientId": 5,
    "item": 6, "model": 7, "article": 8,
    "type": 9, "details": 10, "price": 11,
    "deadline": 12, "status": 13,
    "note": 15, "comment": 16, "closedDate": 17,
}

# Purchase columns (0-based): date, item, quantity, price, orderId, orderName, status, note
PURCHASE_FIELD_COL = {
    "date": 0, "item": 1, "quantity": 2, "price": 3,
    "orderId": 4, "orderName": 5, "status": 6, "note": 7,
}


def _pad(row: list, length: int) -> list:
    row = list(row)
    while len(row) < length:
        row.append("")
    return row


# ── Sync implementations ───────────────────────────────────────────────────────

def _get_orders_sync() -> list:
    rows = _get_ws("Actual").get_all_values()
    return rows[1:] if len(rows) > 1 else []


def _get_archive_sync() -> list:
    rows = _get_ws("Archive").get_all_values()
    return rows[1:] if len(rows) > 1 else []


def _count_orders_sync() -> int:
    nums = []
    for sheet_name in ("Actual", "Archive"):
        rows = _get_ws(sheet_name).get_all_values()
        for row in rows[1:]:
            if row and row[0].strip():
                try:
                    nums.append(int(float(row[0].strip())))
                except ValueError:
                    pass
    return max(nums) if nums else 0


def _find_order_row_sync(order_id: str, sheet_name: str = "Actual"):
    """Returns (ws, row_num) or (ws, None). Row num is 1-based."""
    ws = _get_ws(sheet_name)
    try:
        cell = ws.find(order_id, in_column=2)
        return ws, cell.row
    except gspread.exceptions.CellNotFound:
        return ws, None


def _append_order_sync(row: list):
    _get_ws("Actual").append_row(row, value_input_option="USER_ENTERED")


def _update_order_sync(order_id: str, col_updates: dict, sheet_name: str = "Actual") -> bool:
    """col_updates: {col_0based: value}"""
    ws, row_num = _find_order_row_sync(order_id, sheet_name)
    if row_num is None:
        return False
    row = _pad(ws.row_values(row_num), 18)
    for col, val in col_updates.items():
        row[col] = val
    ws.update(f"A{row_num}:R{row_num}", [row])
    return True


def _move_to_archive_sync(order_id: str) -> bool:
    from datetime import datetime as _dt
    ws_orders, row_num = _find_order_row_sync(order_id)
    if row_num is None:
        return False
    row = _pad(ws_orders.row_values(row_num), 18)
    row[13] = "Отдано"
    row[17] = _dt.now().strftime("%d.%m.%Y")
    _get_ws("Archive").append_row(row, value_input_option="USER_ENTERED")
    ws_orders.delete_rows(row_num)
    return True


def _get_purchases_sync() -> list:
    """Returns list of (sheet_row_num, row_data)."""
    rows = _get_ws("Purchase").get_all_values()
    if len(rows) <= 1:
        return []
    return [(i + 2, row) for i, row in enumerate(rows[1:])]


def _append_purchase_sync(row: list):
    _get_ws("Purchase").append_row(row, value_input_option="USER_ENTERED")


def _update_purchase_sync(row_num: int, col_updates: dict) -> bool:
    ws = _get_ws("Purchase")
    row = _pad(ws.row_values(row_num), 8)
    for col, val in col_updates.items():
        row[col] = val
    ws.update(f"A{row_num}:H{row_num}", [row])
    return True


def _get_purchase_status_sync(row_num: int) -> str | None:
    row = _get_ws("Purchase").row_values(row_num)
    return row[6] if len(row) > 6 else None


def _delete_purchase_sync(row_num: int):
    _get_ws("Purchase").delete_rows(row_num)


def _delete_purchases_for_order_sync(order_id: str):
    ws = _get_ws("Purchase")
    rows = ws.get_all_values()
    to_delete = [
        i + 2
        for i, row in enumerate(rows[1:])
        if _pad(row, 8)[4].strip() == str(order_id).strip()
    ]
    for row_num in reversed(to_delete):
        ws.delete_rows(row_num)


# ── Async wrappers ─────────────────────────────────────────────────────────────

async def get_orders() -> list:
    return await asyncio.to_thread(_get_orders_sync)

async def get_archive() -> list:
    return await asyncio.to_thread(_get_archive_sync)

async def count_orders() -> int:
    return await asyncio.to_thread(_count_orders_sync)

async def append_order(row: list):
    await asyncio.to_thread(_append_order_sync, row)

async def update_order(order_id: str, col_updates: dict, sheet_name: str = "Actual") -> bool:
    return await asyncio.to_thread(_update_order_sync, order_id, col_updates, sheet_name)

async def move_to_archive(order_id: str) -> bool:
    return await asyncio.to_thread(_move_to_archive_sync, order_id)

async def get_purchases() -> list:
    return await asyncio.to_thread(_get_purchases_sync)

async def append_purchase(row: list):
    await asyncio.to_thread(_append_purchase_sync, row)

async def update_purchase(row_num: int, col_updates: dict) -> bool:
    return await asyncio.to_thread(_update_purchase_sync, row_num, col_updates)

async def get_purchase_status(row_num: int) -> str | None:
    return await asyncio.to_thread(_get_purchase_status_sync, row_num)

async def delete_purchase(row_num: int):
    await asyncio.to_thread(_delete_purchase_sync, row_num)

async def delete_purchases_for_order(order_id: str):
    await asyncio.to_thread(_delete_purchases_for_order_sync, order_id)
