from __future__ import annotations

import asyncio
import json
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
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS chat_agent_user_daily_summaries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                summary_key TEXT NOT NULL UNIQUE,
                summary_date TEXT NOT NULL,
                user_id TEXT NOT NULL,
                group_id TEXT,
                group_name TEXT,
                nickname TEXT,
                group_card TEXT,
                message_count INTEGER NOT NULL DEFAULT 0,
                first_event_time INTEGER,
                last_event_time INTEGER,
                first_log_time_text TEXT,
                last_log_time_text TEXT,
                sample_messages_json TEXT,
                keywords_json TEXT,
                summary_text TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                source_message_count INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_chat_agent_user_daily_summaries_user_id
            ON chat_agent_user_daily_summaries(user_id)
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_chat_agent_user_daily_summaries_group_id
            ON chat_agent_user_daily_summaries(group_id)
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_chat_agent_user_daily_summaries_date
            ON chat_agent_user_daily_summaries(summary_date)
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_chat_agent_user_daily_summaries_content_hash
            ON chat_agent_user_daily_summaries(content_hash)
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS chat_agent_user_style_profiles (
                profile_key TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                group_id TEXT NOT NULL DEFAULT '',
                message_count INTEGER NOT NULL DEFAULT 0,
                peer_reply_count INTEGER NOT NULL DEFAULT 0,
                sample_messages_json TEXT NOT NULL DEFAULT '[]',
                sample_peer_replies_json TEXT NOT NULL DEFAULT '[]',
                user_style_text TEXT NOT NULL DEFAULT '',
                peer_response_style_text TEXT NOT NULL DEFAULT '',
                recommended_bot_style TEXT NOT NULL DEFAULT '',
                content_hash TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS chat_agent_skills (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                key TEXT NOT NULL UNIQUE,
                title TEXT NOT NULL DEFAULT '',
                description TEXT NOT NULL DEFAULT '',
                intent_kinds TEXT NOT NULL DEFAULT '',
                trigger_terms TEXT NOT NULL DEFAULT '',
                negative_terms TEXT NOT NULL DEFAULT '',
                group_ids TEXT NOT NULL DEFAULT '',
                priority REAL NOT NULL DEFAULT 1.0,
                content TEXT NOT NULL DEFAULT '',
                enabled INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS chat_agent_skill_proposals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                proposal_key TEXT NOT NULL UNIQUE,
                title TEXT NOT NULL DEFAULT '',
                description TEXT NOT NULL DEFAULT '',
                intent_kinds TEXT NOT NULL DEFAULT '',
                trigger_terms TEXT NOT NULL DEFAULT '',
                negative_terms TEXT NOT NULL DEFAULT '',
                group_ids TEXT NOT NULL DEFAULT '',
                priority REAL NOT NULL DEFAULT 1.0,
                content TEXT NOT NULL DEFAULT '',
                source_type TEXT NOT NULL DEFAULT '',
                source_ref TEXT NOT NULL DEFAULT '',
                evidence_samples_json TEXT NOT NULL DEFAULT '[]',
                status TEXT NOT NULL DEFAULT 'pending',
                confidence REAL NOT NULL DEFAULT 0.0,
                hit_count INTEGER NOT NULL DEFAULT 0,
                success_count INTEGER NOT NULL DEFAULT 0,
                failure_count INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                reviewed_at TEXT DEFAULT NULL,
                reviewed_by TEXT NOT NULL DEFAULT '',
                review_note TEXT NOT NULL DEFAULT ''
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


def _list_enabled_chat_agent_skills_sync(db_path: Path, group_id: str | None = None) -> list[dict]:
    if not db_path.exists():
        return []
    gid = str(group_id or "").strip()
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.execute(
            """
            SELECT
                key, title, description, intent_kinds, trigger_terms, negative_terms,
                group_ids, priority, content
            FROM chat_agent_skills
            WHERE enabled = 1
            ORDER BY id ASC
            LIMIT 200
            """
        )
        rows = cur.fetchall()
    except sqlite3.OperationalError:
        return []
    finally:
        conn.close()

    out: list[dict] = []
    for row in rows:
        group_ids_text = str(row[6] or "").strip()
        if gid:
            if group_ids_text:
                csv = "," + group_ids_text.replace(" ", "") + ","
                if f",{gid}," not in csv:
                    continue
        else:
            if group_ids_text:
                continue
        out.append(
            {
                "key": row[0],
                "title": row[1],
                "description": row[2],
                "intent_kinds": row[3],
                "trigger_terms": row[4],
                "negative_terms": row[5],
                "group_ids": row[6],
                "priority": row[7],
                "content": row[8],
            }
        )
    return out


async def list_enabled_chat_agent_skills(config, group_id: str | None = None) -> list[dict]:
    return await asyncio.to_thread(_list_enabled_chat_agent_skills_sync, config.chat_agent_db_path, group_id)


def _validate_skill_key(key: str) -> bool:
    if not key:
        return False
    for ch in key:
        if not (ch.isalnum() or ch in {"_", "-", "."}):
            return False
    return True


_RESERVED_BUILTIN_SKILL_KEYS = {
    "official_current_fact_resolver",
    "lightweight_definition_answer",
    "evidence_route_question",
}


def _upsert_chat_agent_skill_sync(db_path: Path, row: dict) -> None:
    _init_storage_sync(db_path)
    key = str(row.get("key", "") or "").strip()
    if not _validate_skill_key(key):
        raise ValueError("invalid skill key")
    title = str(row.get("title", "") or "").strip()
    description = str(row.get("description", "") or "").strip()
    intent_kinds = str(row.get("intent_kinds", "") or "").strip()
    trigger_terms = str(row.get("trigger_terms", "") or "").strip()
    negative_terms = str(row.get("negative_terms", "") or "").strip()
    group_ids = str(row.get("group_ids", "") or "").strip()
    content = str(row.get("content", "") or "").strip()
    if not content and not description:
        raise ValueError("content or description is required")
    if not intent_kinds and not trigger_terms:
        raise ValueError("intent_kinds or trigger_terms is required")
    if len(title) > 120:
        raise ValueError("title too long")
    if len(description) > 300:
        raise ValueError("description too long")
    if len(content) > 600:
        raise ValueError("content too long")
    try:
        priority = float(row.get("priority", 1.0) or 1.0)
    except Exception as e:
        raise ValueError("invalid priority") from e
    enabled = 0 if not bool(int(row.get("enabled", 1) or 0)) else 1

    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """
            INSERT INTO chat_agent_skills
            (key, title, description, intent_kinds, trigger_terms, negative_terms, group_ids, priority, content, enabled, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(key) DO UPDATE SET
                title=excluded.title,
                description=excluded.description,
                intent_kinds=excluded.intent_kinds,
                trigger_terms=excluded.trigger_terms,
                negative_terms=excluded.negative_terms,
                group_ids=excluded.group_ids,
                priority=excluded.priority,
                content=excluded.content,
                enabled=excluded.enabled,
                updated_at=CURRENT_TIMESTAMP
            """,
            (
                key,
                title,
                description,
                intent_kinds,
                trigger_terms,
                negative_terms,
                group_ids,
                priority,
                content,
                enabled,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def _set_chat_agent_skill_enabled_sync(db_path: Path, key: str, enabled: bool) -> bool:
    _init_storage_sync(db_path)
    skey = str(key or "").strip()
    if not _validate_skill_key(skey):
        return False
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.execute(
            """
            UPDATE chat_agent_skills
            SET enabled=?, updated_at=CURRENT_TIMESTAMP
            WHERE key=?
            """,
            (1 if enabled else 0, skey),
        )
        conn.commit()
        return bool(cur.rowcount)
    finally:
        conn.close()


def _get_chat_agent_skill_sync(db_path: Path, key: str) -> dict | None:
    if not db_path.exists():
        return None
    skey = str(key or "").strip()
    if not _validate_skill_key(skey):
        return None
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.execute(
            """
            SELECT id, key, title, description, intent_kinds, trigger_terms, negative_terms,
                   group_ids, priority, content, enabled, created_at, updated_at
            FROM chat_agent_skills
            WHERE key = ?
            LIMIT 1
            """,
            (skey,),
        )
        row = cur.fetchone()
        if not row:
            return None
        return {
            "id": row[0],
            "key": row[1],
            "title": row[2],
            "description": row[3],
            "intent_kinds": row[4],
            "trigger_terms": row[5],
            "negative_terms": row[6],
            "group_ids": row[7],
            "priority": row[8],
            "content": row[9],
            "enabled": row[10],
            "created_at": row[11],
            "updated_at": row[12],
        }
    except sqlite3.OperationalError:
        return None
    finally:
        conn.close()


def _list_chat_agent_skills_sync(db_path: Path, include_disabled: bool = False) -> list[dict]:
    if not db_path.exists():
        return []
    conn = sqlite3.connect(db_path)
    try:
        where_sql = "" if include_disabled else "WHERE enabled = 1"
        cur = conn.execute(
            f"""
            SELECT id, key, title, description, intent_kinds, trigger_terms, negative_terms,
                   group_ids, priority, content, enabled, created_at, updated_at
            FROM chat_agent_skills
            {where_sql}
            ORDER BY id ASC
            LIMIT 200
            """
        )
        rows = cur.fetchall()
        out = []
        for row in rows:
            out.append(
                {
                    "id": row[0],
                    "key": row[1],
                    "title": row[2],
                    "description": row[3],
                    "intent_kinds": row[4],
                    "trigger_terms": row[5],
                    "negative_terms": row[6],
                    "group_ids": row[7],
                    "priority": row[8],
                    "content": row[9],
                    "enabled": row[10],
                    "created_at": row[11],
                    "updated_at": row[12],
                }
            )
        return out
    except sqlite3.OperationalError:
        return []
    finally:
        conn.close()


async def upsert_chat_agent_skill(config, row: dict) -> None:
    await asyncio.to_thread(_upsert_chat_agent_skill_sync, config.chat_agent_db_path, row)


async def set_chat_agent_skill_enabled(config, key: str, enabled: bool) -> bool:
    return await asyncio.to_thread(_set_chat_agent_skill_enabled_sync, config.chat_agent_db_path, key, enabled)


async def get_chat_agent_skill(config, key: str) -> dict | None:
    return await asyncio.to_thread(_get_chat_agent_skill_sync, config.chat_agent_db_path, key)


async def list_chat_agent_skills(config, include_disabled: bool = False) -> list[dict]:
    return await asyncio.to_thread(_list_chat_agent_skills_sync, config.chat_agent_db_path, include_disabled)


def _normalize_evidence_samples(value: object) -> str:
    samples: list[str] = []
    if isinstance(value, list):
        raw_list = value
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            raw_list = []
        else:
            parsed = json.loads(text)
            if not isinstance(parsed, list):
                raise ValueError("evidence_samples_json must be a JSON list")
            raw_list = parsed
    elif value is None:
        raw_list = []
    else:
        raise ValueError("invalid evidence_samples_json")
    for item in raw_list[:5]:
        s = str(item or "").strip()
        if s:
            samples.append(s[:300])
    return json.dumps(samples, ensure_ascii=False)


def _upsert_chat_agent_skill_proposal_sync(db_path: Path, row: dict) -> None:
    _init_storage_sync(db_path)
    proposal_key = str(row.get("proposal_key", "") or "").strip()
    if not _validate_skill_key(proposal_key):
        raise ValueError("invalid proposal key")
    if proposal_key in _RESERVED_BUILTIN_SKILL_KEYS:
        raise ValueError(f"Cannot use reserved builtin skill key: {proposal_key}")

    title = str(row.get("title", "") or "").strip()
    description = str(row.get("description", "") or "").strip()
    intent_kinds = str(row.get("intent_kinds", "") or "").strip()
    trigger_terms = str(row.get("trigger_terms", "") or "").strip()
    negative_terms = str(row.get("negative_terms", "") or "").strip()
    group_ids = str(row.get("group_ids", "") or "").strip()
    content = str(row.get("content", "") or "").strip()
    source_type = str(row.get("source_type", "") or "").strip()[:80]
    source_ref = str(row.get("source_ref", "") or "").strip()[:200]
    status = str(row.get("status", "pending") or "pending").strip().lower()
    if status not in {"pending", "approved", "rejected", "archived"}:
        raise ValueError("invalid proposal status")
    reviewed_by = str(row.get("reviewed_by", "") or "").strip()[:80]
    review_note = str(row.get("review_note", "") or "").strip()[:300]

    if len(title) > 120:
        raise ValueError("title too long")
    if len(description) > 300:
        raise ValueError("description too long")
    if len(content) > 600:
        raise ValueError("content too long")
    if not content and not description:
        raise ValueError("content or description is required")
    if not intent_kinds and not trigger_terms:
        raise ValueError("intent_kinds or trigger_terms is required")

    try:
        priority = float(row.get("priority", 1.0) or 1.0)
    except Exception as e:
        raise ValueError("invalid priority") from e
    try:
        confidence = float(row.get("confidence", 0.0) or 0.0)
    except Exception as e:
        raise ValueError("invalid confidence") from e
    confidence = max(0.0, min(1.0, confidence))
    hit_count = max(0, int(row.get("hit_count", 0) or 0))
    success_count = max(0, int(row.get("success_count", 0) or 0))
    failure_count = max(0, int(row.get("failure_count", 0) or 0))
    evidence_samples_json = _normalize_evidence_samples(row.get("evidence_samples_json", []))

    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """
            INSERT INTO chat_agent_skill_proposals (
                proposal_key, title, description, intent_kinds, trigger_terms, negative_terms, group_ids,
                priority, content, source_type, source_ref, evidence_samples_json, status, confidence,
                hit_count, success_count, failure_count, updated_at, reviewed_at, reviewed_by, review_note
            ) VALUES (
                ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, CURRENT_TIMESTAMP, NULL, ?, ?
            )
            ON CONFLICT(proposal_key) DO UPDATE SET
                title=excluded.title,
                description=excluded.description,
                intent_kinds=excluded.intent_kinds,
                trigger_terms=excluded.trigger_terms,
                negative_terms=excluded.negative_terms,
                group_ids=excluded.group_ids,
                priority=excluded.priority,
                content=excluded.content,
                source_type=excluded.source_type,
                source_ref=excluded.source_ref,
                evidence_samples_json=excluded.evidence_samples_json,
                status=excluded.status,
                confidence=excluded.confidence,
                hit_count=excluded.hit_count,
                success_count=excluded.success_count,
                failure_count=excluded.failure_count,
                updated_at=CURRENT_TIMESTAMP,
                reviewed_by=excluded.reviewed_by,
                review_note=excluded.review_note
            """,
            (
                proposal_key,
                title,
                description,
                intent_kinds,
                trigger_terms,
                negative_terms,
                group_ids,
                priority,
                content,
                source_type,
                source_ref,
                evidence_samples_json,
                status,
                confidence,
                hit_count,
                success_count,
                failure_count,
                reviewed_by,
                review_note,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def _get_chat_agent_skill_proposal_sync(db_path: Path, proposal_key: str) -> dict | None:
    if not db_path.exists():
        return None
    pkey = str(proposal_key or "").strip()
    if not _validate_skill_key(pkey):
        return None
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.execute(
            """
            SELECT id, proposal_key, title, description, intent_kinds, trigger_terms, negative_terms, group_ids,
                   priority, content, source_type, source_ref, evidence_samples_json, status, confidence,
                   hit_count, success_count, failure_count, created_at, updated_at, reviewed_at, reviewed_by, review_note
            FROM chat_agent_skill_proposals
            WHERE proposal_key=?
            LIMIT 1
            """,
            (pkey,),
        )
        row = cur.fetchone()
        if not row:
            return None
        return {
            "id": row[0],
            "proposal_key": row[1],
            "title": row[2],
            "description": row[3],
            "intent_kinds": row[4],
            "trigger_terms": row[5],
            "negative_terms": row[6],
            "group_ids": row[7],
            "priority": row[8],
            "content": row[9],
            "source_type": row[10],
            "source_ref": row[11],
            "evidence_samples_json": row[12],
            "status": row[13],
            "confidence": row[14],
            "hit_count": row[15],
            "success_count": row[16],
            "failure_count": row[17],
            "created_at": row[18],
            "updated_at": row[19],
            "reviewed_at": row[20],
            "reviewed_by": row[21],
            "review_note": row[22],
        }
    except sqlite3.OperationalError:
        return None
    finally:
        conn.close()


def _list_chat_agent_skill_proposals_sync(db_path: Path, status: str | None = "pending", limit: int = 100) -> list[dict]:
    if not db_path.exists():
        return []
    lim = max(1, min(500, int(limit or 100)))
    where_sql = ""
    params: tuple = ()
    if status is not None:
        s = str(status or "").strip().lower()
        if s not in {"pending", "approved", "rejected", "archived"}:
            return []
        where_sql = "WHERE status = ?"
        params = (s,)
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.execute(
            f"""
            SELECT id, proposal_key, title, description, intent_kinds, trigger_terms, negative_terms, group_ids,
                   priority, content, source_type, source_ref, evidence_samples_json, status, confidence,
                   hit_count, success_count, failure_count, created_at, updated_at, reviewed_at, reviewed_by, review_note
            FROM chat_agent_skill_proposals
            {where_sql}
            ORDER BY id DESC
            LIMIT ?
            """,
            params + (lim,),
        )
        rows = cur.fetchall()
        out = []
        for row in rows:
            out.append(
                {
                    "id": row[0],
                    "proposal_key": row[1],
                    "title": row[2],
                    "description": row[3],
                    "intent_kinds": row[4],
                    "trigger_terms": row[5],
                    "negative_terms": row[6],
                    "group_ids": row[7],
                    "priority": row[8],
                    "content": row[9],
                    "source_type": row[10],
                    "source_ref": row[11],
                    "evidence_samples_json": row[12],
                    "status": row[13],
                    "confidence": row[14],
                    "hit_count": row[15],
                    "success_count": row[16],
                    "failure_count": row[17],
                    "created_at": row[18],
                    "updated_at": row[19],
                    "reviewed_at": row[20],
                    "reviewed_by": row[21],
                    "review_note": row[22],
                }
            )
        return out
    except sqlite3.OperationalError:
        return []
    finally:
        conn.close()


def _set_chat_agent_skill_proposal_status_sync(
    db_path: Path,
    proposal_key: str,
    status: str,
    reviewed_by: str = "",
    review_note: str = "",
) -> bool:
    _init_storage_sync(db_path)
    pkey = str(proposal_key or "").strip()
    if not _validate_skill_key(pkey):
        return False
    s = str(status or "").strip().lower()
    if s not in {"pending", "approved", "rejected", "archived"}:
        return False
    rb = str(reviewed_by or "").strip()[:80]
    rn = str(review_note or "").strip()[:300]
    conn = sqlite3.connect(db_path)
    try:
        if s == "pending":
            cur = conn.execute(
                """
                UPDATE chat_agent_skill_proposals
                SET status=?, updated_at=CURRENT_TIMESTAMP, reviewed_at=NULL, reviewed_by=?, review_note=?
                WHERE proposal_key=?
                """,
                (s, rb, rn, pkey),
            )
        else:
            cur = conn.execute(
                """
                UPDATE chat_agent_skill_proposals
                SET status=?, updated_at=CURRENT_TIMESTAMP, reviewed_at=CURRENT_TIMESTAMP, reviewed_by=?, review_note=?
                WHERE proposal_key=?
                """,
                (s, rb, rn, pkey),
            )
        conn.commit()
        return bool(cur.rowcount)
    finally:
        conn.close()


async def upsert_chat_agent_skill_proposal(config, row: dict) -> None:
    await asyncio.to_thread(_upsert_chat_agent_skill_proposal_sync, config.chat_agent_db_path, row)


async def get_chat_agent_skill_proposal(config, proposal_key: str) -> dict | None:
    return await asyncio.to_thread(_get_chat_agent_skill_proposal_sync, config.chat_agent_db_path, proposal_key)


async def list_chat_agent_skill_proposals(config, status: str | None = "pending", limit: int = 100) -> list[dict]:
    return await asyncio.to_thread(_list_chat_agent_skill_proposals_sync, config.chat_agent_db_path, status, limit)


async def set_chat_agent_skill_proposal_status(
    config,
    proposal_key: str,
    status: str,
    reviewed_by: str = "",
    review_note: str = "",
) -> bool:
    return await asyncio.to_thread(
        _set_chat_agent_skill_proposal_status_sync,
        config.chat_agent_db_path,
        proposal_key,
        status,
        reviewed_by,
        review_note,
    )


def _upsert_user_daily_summary_sync(db_path: Path, row: dict) -> None:
    _ensure_parent(db_path)
    conn = sqlite3.connect(db_path)
    try:
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            """
            INSERT INTO chat_agent_user_daily_summaries (
                summary_key, summary_date, user_id, group_id, group_name, nickname, group_card,
                message_count, first_event_time, last_event_time, first_log_time_text, last_log_time_text,
                sample_messages_json, keywords_json, summary_text, content_hash, source_message_count,
                created_at, updated_at
            ) VALUES (
                ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?,
                ?, ?
            )
            ON CONFLICT(summary_key) DO UPDATE SET
                summary_date=excluded.summary_date,
                user_id=excluded.user_id,
                group_id=excluded.group_id,
                group_name=excluded.group_name,
                nickname=excluded.nickname,
                group_card=excluded.group_card,
                message_count=excluded.message_count,
                first_event_time=excluded.first_event_time,
                last_event_time=excluded.last_event_time,
                first_log_time_text=excluded.first_log_time_text,
                last_log_time_text=excluded.last_log_time_text,
                sample_messages_json=excluded.sample_messages_json,
                keywords_json=excluded.keywords_json,
                summary_text=excluded.summary_text,
                content_hash=excluded.content_hash,
                source_message_count=excluded.source_message_count,
                updated_at=excluded.updated_at
            """,
            (
                row.get("summary_key", ""),
                row.get("summary_date", ""),
                row.get("user_id", ""),
                row.get("group_id"),
                row.get("group_name"),
                row.get("nickname"),
                row.get("group_card"),
                int(row.get("message_count", 0) or 0),
                row.get("first_event_time"),
                row.get("last_event_time"),
                row.get("first_log_time_text"),
                row.get("last_log_time_text"),
                row.get("sample_messages_json"),
                row.get("keywords_json"),
                row.get("summary_text", ""),
                row.get("content_hash", ""),
                int(row.get("source_message_count", 0) or 0),
                row.get("created_at", now),
                row.get("updated_at", now),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def _get_user_daily_summary_sync(db_path: Path, summary_key: str) -> dict | None:
    if not db_path.exists():
        return None
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.execute(
            """
            SELECT
                id, summary_key, summary_date, user_id, group_id, group_name, nickname, group_card,
                message_count, first_event_time, last_event_time, first_log_time_text, last_log_time_text,
                sample_messages_json, keywords_json, summary_text, content_hash, source_message_count,
                created_at, updated_at
            FROM chat_agent_user_daily_summaries
            WHERE summary_key = ?
            LIMIT 1
            """,
            (str(summary_key),),
        )
        row = cur.fetchone()
        if not row:
            return None
        return {
            "id": row[0],
            "summary_key": row[1],
            "summary_date": row[2],
            "user_id": row[3],
            "group_id": row[4],
            "group_name": row[5],
            "nickname": row[6],
            "group_card": row[7],
            "message_count": row[8],
            "first_event_time": row[9],
            "last_event_time": row[10],
            "first_log_time_text": row[11],
            "last_log_time_text": row[12],
            "sample_messages_json": row[13],
            "keywords_json": row[14],
            "summary_text": row[15],
            "content_hash": row[16],
            "source_message_count": row[17],
            "created_at": row[18],
            "updated_at": row[19],
        }
    except sqlite3.OperationalError:
        return None
    finally:
        conn.close()


def _list_user_daily_summaries_sync(db_path: Path, user_id: str | None, limit: int) -> list[dict]:
    if limit <= 0:
        return []
    if not db_path.exists():
        return []
    conn = sqlite3.connect(db_path)
    try:
        if user_id is None:
            cur = conn.execute(
                """
                SELECT
                    id, summary_key, summary_date, user_id, group_id, group_name, nickname, group_card,
                    message_count, first_event_time, last_event_time, first_log_time_text, last_log_time_text,
                    sample_messages_json, keywords_json, summary_text, content_hash, source_message_count,
                    created_at, updated_at
                FROM chat_agent_user_daily_summaries
                ORDER BY summary_date DESC, id DESC
                LIMIT ?
                """,
                (int(limit),),
            )
        else:
            cur = conn.execute(
                """
                SELECT
                    id, summary_key, summary_date, user_id, group_id, group_name, nickname, group_card,
                    message_count, first_event_time, last_event_time, first_log_time_text, last_log_time_text,
                    sample_messages_json, keywords_json, summary_text, content_hash, source_message_count,
                    created_at, updated_at
                FROM chat_agent_user_daily_summaries
                WHERE user_id = ?
                ORDER BY summary_date DESC, id DESC
                LIMIT ?
                """,
                (str(user_id), int(limit)),
            )
        rows = cur.fetchall()
        return [
            {
                "id": row[0],
                "summary_key": row[1],
                "summary_date": row[2],
                "user_id": row[3],
                "group_id": row[4],
                "group_name": row[5],
                "nickname": row[6],
                "group_card": row[7],
                "message_count": row[8],
                "first_event_time": row[9],
                "last_event_time": row[10],
                "first_log_time_text": row[11],
                "last_log_time_text": row[12],
                "sample_messages_json": row[13],
                "keywords_json": row[14],
                "summary_text": row[15],
                "content_hash": row[16],
                "source_message_count": row[17],
                "created_at": row[18],
                "updated_at": row[19],
            }
            for row in rows
        ]
    except sqlite3.OperationalError:
        return []
    finally:
        conn.close()


async def upsert_user_daily_summary(config, row: dict) -> None:
    await asyncio.to_thread(_upsert_user_daily_summary_sync, config.chat_agent_db_path, row)


async def get_user_daily_summary(config, summary_key: str) -> dict | None:
    return await asyncio.to_thread(_get_user_daily_summary_sync, config.chat_agent_db_path, str(summary_key))


async def list_user_daily_summaries(config, user_id: str | None = None, limit: int = 20) -> list[dict]:
    return await asyncio.to_thread(_list_user_daily_summaries_sync, config.chat_agent_db_path, user_id, limit)


def _upsert_user_style_profile_sync(db_path: Path, profile: dict) -> None:
    _ensure_parent(db_path)
    conn = sqlite3.connect(db_path)
    try:
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            """
            INSERT INTO chat_agent_user_style_profiles (
                profile_key, user_id, group_id,
                message_count, peer_reply_count,
                sample_messages_json, sample_peer_replies_json,
                user_style_text, peer_response_style_text, recommended_bot_style,
                content_hash, created_at, updated_at
            ) VALUES (
                ?, ?, ?,
                ?, ?,
                ?, ?,
                ?, ?, ?,
                ?, ?, ?
            )
            ON CONFLICT(profile_key) DO UPDATE SET
                user_id=excluded.user_id,
                group_id=excluded.group_id,
                message_count=excluded.message_count,
                peer_reply_count=excluded.peer_reply_count,
                sample_messages_json=excluded.sample_messages_json,
                sample_peer_replies_json=excluded.sample_peer_replies_json,
                user_style_text=excluded.user_style_text,
                peer_response_style_text=excluded.peer_response_style_text,
                recommended_bot_style=excluded.recommended_bot_style,
                content_hash=excluded.content_hash,
                updated_at=excluded.updated_at
            """,
            (
                profile.get("profile_key", ""),
                profile.get("user_id", ""),
                profile.get("group_id", "") or "",
                int(profile.get("message_count", 0) or 0),
                int(profile.get("peer_reply_count", 0) or 0),
                profile.get("sample_messages_json", "[]"),
                profile.get("sample_peer_replies_json", "[]"),
                profile.get("user_style_text", ""),
                profile.get("peer_response_style_text", ""),
                profile.get("recommended_bot_style", ""),
                profile.get("content_hash", ""),
                profile.get("created_at", now),
                profile.get("updated_at", now),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def _get_user_style_profile_sync(db_path: Path, user_id: str, group_id: str | None = None) -> dict | None:
    if not db_path.exists():
        return None
    uid = str(user_id or "").strip()
    if not uid:
        return None
    gid = str(group_id or "").strip()

    conn = sqlite3.connect(db_path)
    try:
        if gid:
            cur = conn.execute(
                """
                SELECT
                    profile_key,
                    user_id,
                    group_id,
                    message_count,
                    peer_reply_count,
                    user_style_text,
                    peer_response_style_text,
                    recommended_bot_style,
                    updated_at
                FROM chat_agent_user_style_profiles
                WHERE user_id = ? AND group_id = ?
                ORDER BY message_count DESC
                LIMIT 1
                """,
                (uid, gid),
            )
            row = cur.fetchone()
            if row:
                return {
                    "profile_key": row[0],
                    "user_id": row[1],
                    "group_id": row[2],
                    "message_count": row[3],
                    "peer_reply_count": row[4],
                    "user_style_text": row[5],
                    "peer_response_style_text": row[6],
                    "recommended_bot_style": row[7],
                    "updated_at": row[8],
                }

        cur = conn.execute(
            """
            SELECT
                profile_key,
                user_id,
                group_id,
                message_count,
                peer_reply_count,
                user_style_text,
                peer_response_style_text,
                recommended_bot_style,
                updated_at
            FROM chat_agent_user_style_profiles
            WHERE user_id = ?
            ORDER BY message_count DESC
            LIMIT 1
            """,
            (uid,),
        )
        row = cur.fetchone()
        if not row:
            return None
        return {
            "profile_key": row[0],
            "user_id": row[1],
            "group_id": row[2],
            "message_count": row[3],
            "peer_reply_count": row[4],
            "user_style_text": row[5],
            "peer_response_style_text": row[6],
            "recommended_bot_style": row[7],
            "updated_at": row[8],
        }
    except sqlite3.OperationalError:
        return None
    finally:
        conn.close()


async def upsert_user_style_profile(config, profile: dict) -> None:
    await asyncio.to_thread(_upsert_user_style_profile_sync, config.chat_agent_db_path, profile)


async def get_user_style_profile(config, user_id: str, group_id: str | None = None) -> dict | None:
    return await asyncio.to_thread(_get_user_style_profile_sync, config.chat_agent_db_path, str(user_id), group_id)
