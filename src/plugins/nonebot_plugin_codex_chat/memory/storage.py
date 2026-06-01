from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Sequence

from nonebot import logger

from .policy import MessageRecord

DB_PATH = Path("data/nonebot_chat_agent/chat_agent_memory.db")


def _ensure_db_dir() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)


def get_conn() -> sqlite3.Connection:
    _ensure_db_dir()
    conn = sqlite3.connect(str(DB_PATH), timeout=10.0)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def init_db() -> None:
    with get_conn() as conn:
        init_tables(conn)


def init_tables(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS chat_agent_memcells (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            group_id TEXT NOT NULL,
            start_message_id TEXT,
            end_message_id TEXT,
            start_time INTEGER,
            end_time INTEGER,
            participants_json TEXT NOT NULL DEFAULT '[]',
            message_count INTEGER NOT NULL DEFAULT 0,
            raw_text_preview TEXT NOT NULL DEFAULT '',
            keywords_json TEXT NOT NULL DEFAULT '[]',
            status TEXT NOT NULL DEFAULT 'closed',
            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL
        )
        """
    )

    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_chat_agent_memcells_group_time
        ON chat_agent_memcells(group_id, end_time)
        """
    )

    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_chat_agent_memcells_created_at
        ON chat_agent_memcells(created_at)
        """
    )

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS chat_agent_memcell_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            memcell_id INTEGER NOT NULL,
            group_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            message_id TEXT NOT NULL,
            timestamp INTEGER,
            sender_nickname TEXT NOT NULL DEFAULT '',
            sender_card TEXT NOT NULL DEFAULT '',
            sender_role TEXT NOT NULL DEFAULT '',
            sender_title TEXT NOT NULL DEFAULT '',
            text TEXT NOT NULL DEFAULT '',
            text_len INTEGER NOT NULL DEFAULT 0,
            message_type TEXT NOT NULL DEFAULT 'text',
            filtered INTEGER NOT NULL DEFAULT 0,
            filter_reason TEXT NOT NULL DEFAULT '',
            created_at INTEGER NOT NULL,
            FOREIGN KEY(memcell_id) REFERENCES chat_agent_memcells(id)
        )
        """
    )

    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_chat_agent_memcell_messages_memcell
        ON chat_agent_memcell_messages(memcell_id)
        """
    )

    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_chat_agent_memcell_messages_group_user_time
        ON chat_agent_memcell_messages(group_id, user_id, timestamp)
        """
    )

    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_chat_agent_memcell_messages_message_id
        ON chat_agent_memcell_messages(message_id)
        """
    )

    conn.commit()
    logger.info(
        "codex_chat_memory db_init tables="
        "[chat_agent_memcells chat_agent_memcell_messages]"
    )


def _build_participants_json(records: Sequence[MessageRecord]) -> str:
    participants: dict[str, dict[str, object]] = {}

    for record in records:
        item = participants.setdefault(
            record.user_id,
            {
                "user_id": record.user_id,
                "nickname": record.sender_nickname,
                "card": record.sender_card,
                "role": record.sender_role,
                "title": record.sender_title,
                "message_count": 0,
            },
        )

        item["message_count"] = int(item.get("message_count", 0)) + 1

        if record.sender_nickname:
            item["nickname"] = record.sender_nickname
        if record.sender_card:
            item["card"] = record.sender_card
        if record.sender_role:
            item["role"] = record.sender_role
        if record.sender_title:
            item["title"] = record.sender_title

    return json.dumps(list(participants.values()), ensure_ascii=False)


def _build_raw_text_preview(records: Sequence[MessageRecord], max_chars: int) -> str:
    lines: list[str] = []

    for record in records:
        display = record.sender_card or record.sender_nickname or record.user_id
        role = record.sender_role or "member"
        text = record.text.strip()
        if not text:
            continue
        lines.append(f"[{record.user_id}/{display}/{role}] {text}")

    preview = "\n".join(lines)
    if max_chars <= 0:
        return ""
    return preview[:max_chars]


def insert_memcell(records: Sequence[MessageRecord], preview_max_chars: int = 1200) -> int:
    if not records:
        raise ValueError("records must not be empty")

    now = int(time.time())
    first = records[0]
    last = records[-1]

    participants_json = _build_participants_json(records)
    raw_text_preview = _build_raw_text_preview(records, preview_max_chars)

    with get_conn() as conn:
        cur = conn.cursor()

        cur.execute(
            """
            INSERT INTO chat_agent_memcells (
                group_id,
                start_message_id,
                end_message_id,
                start_time,
                end_time,
                participants_json,
                message_count,
                raw_text_preview,
                keywords_json,
                status,
                created_at,
                updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                first.group_id,
                first.message_id,
                last.message_id,
                first.timestamp,
                last.timestamp,
                participants_json,
                len(records),
                raw_text_preview,
                "[]",
                "closed",
                now,
                now,
            ),
        )

        memcell_id = int(cur.lastrowid)

        cur.executemany(
            """
            INSERT INTO chat_agent_memcell_messages (
                memcell_id,
                group_id,
                user_id,
                message_id,
                timestamp,
                sender_nickname,
                sender_card,
                sender_role,
                sender_title,
                text,
                text_len,
                message_type,
                filtered,
                filter_reason,
                created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    memcell_id,
                    record.group_id,
                    record.user_id,
                    record.message_id,
                    record.timestamp,
                    record.sender_nickname,
                    record.sender_card,
                    record.sender_role,
                    record.sender_title,
                    record.text,
                    record.text_len,
                    record.message_type,
                    record.filtered,
                    record.filter_reason,
                    now,
                )
                for record in records
            ],
        )

        conn.commit()

    return memcell_id
