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
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS chat_agent_memories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                session_type TEXT NOT NULL,
                user_id TEXT,
                memory_type TEXT NOT NULL,
                content TEXT NOT NULL,
                keywords TEXT,
                importance INTEGER NOT NULL DEFAULT 3,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_chat_agent_memories_session
            ON chat_agent_memories(session_id, memory_type, id)
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


def _prune_session_messages_sync(db_path: Path, session_id: str, max_rows: int) -> None:
    if max_rows <= 0:
        return
    _ensure_parent(db_path)
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """
            DELETE FROM chat_agent_messages
            WHERE session_id = ?
            AND id NOT IN (
                SELECT id FROM chat_agent_messages
                WHERE session_id = ?
                ORDER BY id DESC
                LIMIT ?
            )
            """,
            (session_id, session_id, max_rows),
        )
        conn.commit()
    finally:
        conn.close()


def _save_memory_sync(db_path: Path, session_info: dict, memory_type: str, content: str, keywords: str | None, importance: int) -> None:
    _ensure_parent(db_path)
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """
            INSERT INTO chat_agent_memories
            (session_id, session_type, user_id, memory_type, content, keywords, importance, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session_info["session_id"],
                session_info["session_type"],
                session_info.get("user_id"),
                memory_type,
                content,
                keywords,
                importance,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def _load_memories_sync(db_path: Path, session_id: str, limit: int) -> list[dict]:
    if limit <= 0:
        return []
    if not db_path.exists():
        return []
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.execute(
            """
            SELECT memory_type, content, keywords, importance
            FROM chat_agent_memories
            WHERE session_id = ?
            ORDER BY importance DESC, id DESC
            LIMIT ?
            """,
            (session_id, limit),
        )
        rows = cursor.fetchall()
    finally:
        conn.close()
    return [
        {
            "memory_type": memory_type,
            "content": content,
            "keywords": keywords,
            "importance": importance,
        }
        for memory_type, content, keywords, importance in rows
    ]


def _prune_memories_sync(db_path: Path, max_rows: int) -> None:
    if max_rows <= 0:
        return
    _ensure_parent(db_path)
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """
            DELETE FROM chat_agent_memories
            WHERE id NOT IN (
                SELECT id FROM chat_agent_memories
                ORDER BY id DESC
                LIMIT ?
            )
            """,
            (max_rows,),
        )
        conn.commit()
    finally:
        conn.close()


async def init_storage(config) -> None:
    await asyncio.to_thread(_init_storage_sync, config.chat_agent_db_path)


def build_session_info(event) -> dict:
    if getattr(event, "group_id", None) is not None:
        nickname = getattr(event.sender, "card", None) or getattr(event.sender, "nickname", None)
        return {
            "session_type": "group",
            "session_id": f"group:{event.group_id}",
            "group_id": str(event.group_id),
            "group_name": str(getattr(event, "group_name", "") or ""),
            "group_card": str(getattr(event.sender, "card", None) or nickname or ""),
            "user_id": str(event.user_id),
            "nickname": nickname,
            "raw_nickname": getattr(event.sender, "nickname", None),
        }
    return {
        "session_type": "private",
        "session_id": f"private:{event.user_id}",
        "group_id": None,
        "group_name": "",
        "group_card": "",
        "user_id": str(event.user_id),
        "nickname": getattr(event.sender, "nickname", None),
        "raw_nickname": getattr(event.sender, "nickname", None),
    }


async def save_message(config, session_info: dict, role: str, content: str) -> None:
    await asyncio.to_thread(_save_message_sync, config.chat_agent_db_path, session_info, role, content)
    max_rows = int(getattr(config, "chat_agent_history_max_rows_per_session", 200))
    await asyncio.to_thread(_prune_session_messages_sync, config.chat_agent_db_path, session_info["session_id"], max_rows)


async def load_recent_messages(config, session_id: str, limit: int) -> list[dict]:
    return await asyncio.to_thread(_load_recent_messages_sync, config.chat_agent_db_path, session_id, limit)


async def save_memory(config, session_info: dict, memory: dict) -> None:
    memory_type = str(memory.get("memory_type", "correction") or "correction")
    if memory_type != "praise":
        memory_type = "correction"
    content = str(memory.get("content", "")).strip()
    if memory_type == "correction" and content and not content.startswith("用户纠正："):
        content = (
            f"用户纠正：{content}\n"
            "使用规则：以后遇到相关问题时，应优先遵守这条纠正，不要重复原错误。"
        )
    await asyncio.to_thread(
        _save_memory_sync,
        config.chat_agent_db_path,
        session_info,
        memory_type,
        content,
        memory.get("keywords"),
        int(memory.get("importance", 3)),
    )
    max_rows = int(getattr(config, "chat_agent_memory_max_rows", 500))
    await asyncio.to_thread(_prune_memories_sync, config.chat_agent_db_path, max_rows)


async def load_memories(config, session_id: str, limit: int) -> list[dict]:
    return await asyncio.to_thread(_load_memories_sync, config.chat_agent_db_path, session_id, limit)
