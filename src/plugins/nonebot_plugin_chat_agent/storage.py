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
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS chat_agent_log_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_file TEXT NOT NULL,
                source_line INTEGER NOT NULL,
                source_hash TEXT NOT NULL,
                log_time_text TEXT,
                event_time INTEGER,
                bot_id TEXT,
                adapter TEXT,
                message_id INTEGER,
                message_type TEXT,
                sub_type TEXT,
                group_id TEXT,
                group_name TEXT,
                user_id TEXT,
                nickname TEXT,
                group_card TEXT,
                role TEXT,
                plain_text TEXT NOT NULL,
                raw_message TEXT,
                at_qqs_json TEXT,
                reply_id TEXT,
                has_at INTEGER NOT NULL DEFAULT 0,
                has_reply INTEGER NOT NULL DEFAULT 0,
                imported_at TEXT NOT NULL,
                UNIQUE(source_file, source_line, source_hash)
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_chat_agent_log_messages_user_id
            ON chat_agent_log_messages(user_id)
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_chat_agent_log_messages_group_id
            ON chat_agent_log_messages(group_id)
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_chat_agent_log_messages_message_id
            ON chat_agent_log_messages(message_id)
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_chat_agent_log_messages_event_time
            ON chat_agent_log_messages(event_time)
            """
        )
        conn.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_chat_agent_log_messages_unique_message
            ON chat_agent_log_messages(adapter, bot_id, message_id)
            WHERE message_id IS NOT NULL AND message_id != 0
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS chat_agent_log_import_files (
                file_path TEXT PRIMARY KEY,
                file_size INTEGER,
                mtime REAL,
                sha256 TEXT,
                imported_at TEXT,
                message_count INTEGER NOT NULL DEFAULT 0,
                skipped_count INTEGER NOT NULL DEFAULT 0,
                status TEXT,
                error TEXT
            )
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


def _insert_log_message_sync(db_path: Path, row: dict) -> bool:
    _ensure_parent(db_path)
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.execute(
            """
            INSERT OR IGNORE INTO chat_agent_log_messages (
                source_file, source_line, source_hash, log_time_text, event_time, bot_id, adapter,
                message_id, message_type, sub_type, group_id, group_name, user_id, nickname, group_card,
                role, plain_text, raw_message, at_qqs_json, reply_id, has_at, has_reply, imported_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                row.get("source_file", ""),
                int(row.get("source_line", 0) or 0),
                row.get("source_hash", ""),
                row.get("log_time_text"),
                row.get("event_time"),
                row.get("bot_id"),
                row.get("adapter"),
                row.get("message_id"),
                row.get("message_type"),
                row.get("sub_type"),
                row.get("group_id"),
                row.get("group_name"),
                row.get("user_id"),
                row.get("nickname"),
                row.get("group_card"),
                row.get("role"),
                row.get("plain_text", ""),
                row.get("raw_message"),
                row.get("at_qqs_json"),
                row.get("reply_id"),
                int(row.get("has_at", 0) or 0),
                int(row.get("has_reply", 0) or 0),
                row.get("imported_at", datetime.now(timezone.utc).isoformat()),
            ),
        )
        conn.commit()
        inserted = bool(cur.rowcount)
        if inserted:
            return True

        if (
            str(row.get("parse_source", "")) == "event_repr"
            and row.get("message_id") not in (None, 0, "0", "")
            and str(row.get("adapter", "")).strip()
            and str(row.get("bot_id", "")).strip()
        ):
            conn.execute(
                """
                UPDATE chat_agent_log_messages
                SET
                    group_name = CASE WHEN (group_name IS NULL OR group_name='') AND ? != '' THEN ? ELSE group_name END,
                    nickname = CASE WHEN (nickname IS NULL OR nickname='') AND ? != '' THEN ? ELSE nickname END,
                    group_card = CASE WHEN (group_card IS NULL OR group_card='') AND ? != '' THEN ? ELSE group_card END,
                    role = CASE WHEN (role IS NULL OR role='') AND ? != '' THEN ? ELSE role END,
                    raw_message = CASE WHEN (raw_message IS NULL OR raw_message='') AND ? != '' THEN ? ELSE raw_message END,
                    at_qqs_json = CASE WHEN (at_qqs_json IS NULL OR at_qqs_json='' OR at_qqs_json='[]') AND ? != '' THEN ? ELSE at_qqs_json END,
                    reply_id = CASE WHEN (reply_id IS NULL OR reply_id='') AND ? != '' THEN ? ELSE reply_id END,
                    has_at = CASE WHEN (has_at IS NULL OR has_at=0) AND ? != 0 THEN ? ELSE has_at END,
                    has_reply = CASE WHEN (has_reply IS NULL OR has_reply=0) AND ? != 0 THEN ? ELSE has_reply END,
                    event_time = CASE WHEN (event_time IS NULL OR event_time=0) AND ? IS NOT NULL AND ? != 0 THEN ? ELSE event_time END,
                    sub_type = CASE WHEN (sub_type IS NULL OR sub_type='') AND ? != '' THEN ? ELSE sub_type END,
                    group_id = CASE WHEN (group_id IS NULL OR group_id='') AND ? != '' THEN ? ELSE group_id END,
                    user_id = CASE WHEN (user_id IS NULL OR user_id='') AND ? != '' THEN ? ELSE user_id END,
                    plain_text = CASE WHEN (plain_text IS NULL OR plain_text='') AND ? != '' THEN ? ELSE plain_text END
                WHERE adapter=? AND bot_id=? AND message_id=?
                """,
                (
                    row.get("group_name", ""), row.get("group_name", ""),
                    row.get("nickname", ""), row.get("nickname", ""),
                    row.get("group_card", ""), row.get("group_card", ""),
                    row.get("role", ""), row.get("role", ""),
                    row.get("raw_message", ""), row.get("raw_message", ""),
                    row.get("at_qqs_json", ""), row.get("at_qqs_json", ""),
                    row.get("reply_id", ""), row.get("reply_id", ""),
                    int(row.get("has_at", 0) or 0), int(row.get("has_at", 0) or 0),
                    int(row.get("has_reply", 0) or 0), int(row.get("has_reply", 0) or 0),
                    row.get("event_time"), row.get("event_time"), row.get("event_time"),
                    row.get("sub_type", ""), row.get("sub_type", ""),
                    row.get("group_id", ""), row.get("group_id", ""),
                    row.get("user_id", ""), row.get("user_id", ""),
                    row.get("plain_text", ""), row.get("plain_text", ""),
                    str(row.get("adapter", "")).strip(),
                    str(row.get("bot_id", "")).strip(),
                    int(row.get("message_id")),
                ),
            )
            conn.commit()
        return False
    finally:
        conn.close()


def _upsert_log_import_file_sync(db_path: Path, row: dict) -> None:
    _ensure_parent(db_path)
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """
            INSERT INTO chat_agent_log_import_files (
                file_path, file_size, mtime, sha256, imported_at, message_count, skipped_count, status, error
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(file_path) DO UPDATE SET
                file_size=excluded.file_size,
                mtime=excluded.mtime,
                sha256=excluded.sha256,
                imported_at=excluded.imported_at,
                message_count=excluded.message_count,
                skipped_count=excluded.skipped_count,
                status=excluded.status,
                error=excluded.error
            """,
            (
                row.get("file_path", ""),
                row.get("file_size"),
                row.get("mtime"),
                row.get("sha256"),
                row.get("imported_at", datetime.now(timezone.utc).isoformat()),
                int(row.get("message_count", 0) or 0),
                int(row.get("skipped_count", 0) or 0),
                row.get("status"),
                row.get("error"),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def _get_log_import_file_sync(db_path: Path, file_path: str) -> dict | None:
    if not db_path.exists():
        return None
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.execute(
            """
            SELECT
                file_path, file_size, mtime, sha256, imported_at,
                message_count, skipped_count, status, error
            FROM chat_agent_log_import_files
            WHERE file_path = ?
            LIMIT 1
            """,
            (str(file_path),),
        )
        row = cur.fetchone()
        if not row:
            return None
        return {
            "file_path": row[0],
            "file_size": row[1],
            "mtime": row[2],
            "sha256": row[3],
            "imported_at": row[4],
            "message_count": row[5],
            "skipped_count": row[6],
            "status": row[7],
            "error": row[8],
        }
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


async def insert_log_message(config, row: dict) -> bool:
    return await asyncio.to_thread(_insert_log_message_sync, config.chat_agent_db_path, row)


async def upsert_log_import_file(config, row: dict) -> None:
    await asyncio.to_thread(_upsert_log_import_file_sync, config.chat_agent_db_path, row)


async def get_log_import_file(config, file_path: str) -> dict | None:
    return await asyncio.to_thread(_get_log_import_file_sync, config.chat_agent_db_path, str(file_path))
