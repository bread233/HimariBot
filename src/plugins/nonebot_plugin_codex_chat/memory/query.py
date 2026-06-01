from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from .storage import DB_PATH, get_conn

_MAX_LIMIT = 20


def _clamp_limit(limit: int | str | None, default: int = 5) -> int:
    try:
        value = int(limit) if limit is not None else default
    except Exception:
        value = default
    return max(1, min(value, _MAX_LIMIT))


def _db_exists() -> bool:
    return Path(DB_PATH).exists()


def _open_readonly_conn() -> sqlite3.Connection:
    conn = get_conn()
    conn.row_factory = sqlite3.Row
    return conn


def _row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return dict(row)


def get_memory_status() -> dict[str, Any]:
    db_path = str(DB_PATH)

    if not _db_exists():
        return {
            "db_exists": False,
            "db_path": db_path,
            "memcell_count": 0,
            "message_count": 0,
            "latest_memcell_id": None,
            "latest_created_at": None,
        }

    with _open_readonly_conn() as conn:
        memcell_count = int(
            conn.execute("SELECT COUNT(*) FROM chat_agent_memcells").fetchone()[0]
        )
        message_count = int(
            conn.execute("SELECT COUNT(*) FROM chat_agent_memcell_messages").fetchone()[0]
        )
        latest = conn.execute(
            """
            SELECT id, created_at
            FROM chat_agent_memcells
            ORDER BY id DESC
            LIMIT 1
            """
        ).fetchone()

    return {
        "db_exists": True,
        "db_path": db_path,
        "memcell_count": memcell_count,
        "message_count": message_count,
        "latest_memcell_id": latest["id"] if latest else None,
        "latest_created_at": latest["created_at"] if latest else None,
    }


def get_recent_memcells(group_id: str | None = None, limit: int = 5) -> list[dict[str, Any]]:
    if not _db_exists():
        return []

    limit = _clamp_limit(limit, default=5)

    with _open_readonly_conn() as conn:
        if group_id:
            rows = conn.execute(
                """
                SELECT id, group_id, start_message_id, end_message_id,
                       start_time, end_time, message_count,
                       raw_text_preview, created_at
                FROM chat_agent_memcells
                WHERE group_id = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (str(group_id), limit),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT id, group_id, start_message_id, end_message_id,
                       start_time, end_time, message_count,
                       raw_text_preview, created_at
                FROM chat_agent_memcells
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()

    return [dict(row) for row in rows]


def get_user_messages(group_id: str, user_id: str, limit: int = 10) -> list[dict[str, Any]]:
    if not _db_exists():
        return []

    limit = _clamp_limit(limit, default=10)

    with _open_readonly_conn() as conn:
        rows = conn.execute(
            """
            SELECT memcell_id, group_id, user_id, message_id, timestamp,
                   sender_nickname, sender_card, sender_role, sender_title,
                   text, text_len, filtered
            FROM chat_agent_memcell_messages
            WHERE group_id = ? AND user_id = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (str(group_id), str(user_id), limit),
        ).fetchall()

    return [dict(row) for row in rows]


def get_memcell_detail(memcell_id: int) -> dict[str, Any] | None:
    if not _db_exists():
        return None

    with _open_readonly_conn() as conn:
        memcell = conn.execute(
            """
            SELECT id, group_id, start_message_id, end_message_id,
                   start_time, end_time, participants_json,
                   message_count, raw_text_preview, keywords_json,
                   status, created_at, updated_at
            FROM chat_agent_memcells
            WHERE id = ?
            """,
            (int(memcell_id),),
        ).fetchone()

        if memcell is None:
            return None

        messages = conn.execute(
            """
            SELECT id, memcell_id, group_id, user_id, message_id, timestamp,
                   sender_nickname, sender_card, sender_role, sender_title,
                   text, text_len, message_type, filtered, filter_reason, created_at
            FROM chat_agent_memcell_messages
            WHERE memcell_id = ?
            ORDER BY id ASC
            """,
            (int(memcell_id),),
        ).fetchall()

    return {
        "memcell": dict(memcell),
        "messages": [dict(row) for row in messages],
    }
