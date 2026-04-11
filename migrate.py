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
