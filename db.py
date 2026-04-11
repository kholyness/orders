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
        archive_cols = _ORDER_COLS.replace("DEFAULT 'Очередь'", "DEFAULT 'Отдано'")
        await db.execute(f"CREATE TABLE IF NOT EXISTS archive ({archive_cols})")
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
