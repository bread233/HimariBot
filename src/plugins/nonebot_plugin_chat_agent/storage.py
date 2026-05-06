from __future__ import annotations

import asyncio
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


def _ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def _init_storage_sync(db_path: Path) -> None:
    _ensure_parent(db_path)
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS chat_agent_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                session_type TEXT NOT NULL,
                group_id TEXT,
                user_id TEXT NOT NULL,
                nickname TEXT,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_chat_agent_messages_session_created
            ON chat_agent_messages(session_id, created_at)
            """
        )
        conn.commit()
    finally:
        conn.close()


def _save_message_sync(db_path: Path, session_info: dict, role: str, content: str) -> None:
    _ensure_parent(db_path)
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """
            INSERT INTO chat_agent_messages
            (session_id, session_type, group_id, user_id, nickname, role, content, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session_info["session_id"],
                session_info["session_type"],
                session_info.get("group_id"),
                session_info["user_id"],
                session_info.get("nickname"),
                role,
                content,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def _load_recent_messages_sync(db_path: Path, session_id: str, limit: int) -> list[dict]:
    if limit <= 0:
        return []
    if not db_path.exists():
        return []
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.execute(
            """
            SELECT role, content, nickname
            FROM chat_agent_messages
            WHERE session_id = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (session_id, limit),
        )
        rows = cursor.fetchall()
    finally:
        conn.close()
    rows.reverse()
    return [{"role": role, "content": content, "nickname": nickname} for role, content, nickname in rows]


async def init_storage(config) -> None:
    await asyncio.to_thread(_init_storage_sync, config.chat_agent_db_path)


def build_session_info(event) -> dict:
    if getattr(event, "group_id", None) is not None:
        nickname = getattr(event.sender, "card", None) or getattr(event.sender, "nickname", None)
        return {
            "session_type": "group",
            "session_id": f"group:{event.group_id}",
            "group_id": str(event.group_id),
            "user_id": str(event.user_id),
            "nickname": nickname,
        }
    return {
        "session_type": "private",
        "session_id": f"private:{event.user_id}",
        "group_id": None,
        "user_id": str(event.user_id),
        "nickname": getattr(event.sender, "nickname", None),
    }


async def save_message(config, session_info: dict, role: str, content: str) -> None:
    await asyncio.to_thread(_save_message_sync, config.chat_agent_db_path, session_info, role, content)


async def load_recent_messages(config, session_id: str, limit: int) -> list[dict]:
    return await asyncio.to_thread(_load_recent_messages_sync, config.chat_agent_db_path, session_id, limit)
