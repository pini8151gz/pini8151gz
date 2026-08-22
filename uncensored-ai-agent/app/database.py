import aiosqlite
import json
from datetime import datetime
from typing import List, Dict, Optional
import os

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "chats.db")


async def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                last_activity TEXT NOT NULL
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL,
                telegram_message_id INTEGER,
                FOREIGN KEY (session_id) REFERENCES sessions (session_id)
            )
        """)
        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_messages_session 
            ON messages(session_id)
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)
        await db.commit()


async def create_session(session_id: str):
    now = datetime.utcnow().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR IGNORE INTO sessions (session_id, created_at, last_activity) VALUES (?, ?, ?)",
            (session_id, now, now)
        )
        await db.commit()


async def add_message(session_id: str, role: str, content: str, telegram_message_id: Optional[int] = None) -> int:
    now = datetime.utcnow().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            """INSERT INTO messages (session_id, role, content, created_at, telegram_message_id)
               VALUES (?, ?, ?, ?, ?)""",
            (session_id, role, content, now, telegram_message_id)
        )
        await db.execute(
            "UPDATE sessions SET last_activity = ? WHERE session_id = ?",
            (now, session_id)
        )
        await db.commit()
        return cursor.lastrowid


async def get_messages(session_id: str) -> List[Dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """SELECT id, role, content, created_at 
               FROM messages 
               WHERE session_id = ? 
               ORDER BY id ASC""",
            (session_id,)
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


async def get_session_by_telegram_msg(telegram_message_id: int) -> Optional[str]:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT session_id FROM messages WHERE telegram_message_id = ?",
            (telegram_message_id,)
        )
        row = await cursor.fetchone()
        return row[0] if row else None


async def update_telegram_message_id(message_db_id: int, telegram_message_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE messages SET telegram_message_id = ? WHERE id = ?",
            (telegram_message_id, message_db_id)
        )
        await db.commit()


async def get_setting(key: str) -> Optional[str]:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT value FROM settings WHERE key = ?", (key,))
        row = await cursor.fetchone()
        return row[0] if row else None


async def set_setting(key: str, value: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value)
        )
        await db.commit()
