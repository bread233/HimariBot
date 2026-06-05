from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from typing import Any

from .storage import DB_PATH, get_conn

_MAX_LIMIT = 20


def _clamp_limit(
    limit: int | str | None,
    default: int = 5,
    max_limit: int = _MAX_LIMIT,
) -> int:
    try:
        value = int(limit) if limit is not None else default
    except Exception:
        value = default
    return max(1, min(value, max_limit))


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

def get_recent_group_episodes(
    group_id: str | None = None,
    limit: int = 5,
) -> list[dict[str, Any]]:
    if not _db_exists():
        return []

    limit = _clamp_limit(limit, default=5)

    with _open_readonly_conn() as conn:
        if group_id:
            rows = conn.execute(
                """
                SELECT id, memcell_id, group_id, summary, topic,
                       keywords_json, importance, confidence, model_name,
                       created_at, updated_at
                FROM chat_agent_group_episodes
                WHERE group_id = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (str(group_id), limit),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT id, memcell_id, group_id, summary, topic,
                       keywords_json, importance, confidence, model_name,
                       created_at, updated_at
                FROM chat_agent_group_episodes
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()

    return [dict(row) for row in rows]


def get_recent_user_episodes(
    group_id: str,
    user_id: str | None = None,
    limit: int = 10,
) -> list[dict[str, Any]]:
    if not _db_exists():
        return []

    limit = _clamp_limit(limit, default=10)

    with _open_readonly_conn() as conn:
        if user_id:
            rows = conn.execute(
                """
                SELECT id, memcell_id, group_id, user_id, summary, attitude,
                       preference_candidates_json, style_observation,
                       topic_keywords_json, importance, confidence,
                       model_name, created_at, updated_at
                FROM chat_agent_user_episodes
                WHERE group_id = ? AND user_id = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (str(group_id), str(user_id), limit),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT id, memcell_id, group_id, user_id, summary, attitude,
                       preference_candidates_json, style_observation,
                       topic_keywords_json, importance, confidence,
                       model_name, created_at, updated_at
                FROM chat_agent_user_episodes
                WHERE group_id = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (str(group_id), limit),
            ).fetchall()

    return [dict(row) for row in rows]


def get_episode_by_memcell(memcell_id: int) -> dict[str, Any] | None:
    if not _db_exists():
        return None

    with _open_readonly_conn() as conn:
        group_episode = conn.execute(
            """
            SELECT id, memcell_id, group_id, summary, topic,
                   keywords_json, importance, confidence, model_name,
                   created_at, updated_at
            FROM chat_agent_group_episodes
            WHERE memcell_id = ?
            """,
            (int(memcell_id),),
        ).fetchone()

        user_episodes = conn.execute(
            """
            SELECT id, memcell_id, group_id, user_id, summary, attitude,
                   preference_candidates_json, style_observation,
                   topic_keywords_json, importance, confidence,
                   model_name, created_at, updated_at
            FROM chat_agent_user_episodes
            WHERE memcell_id = ?
            ORDER BY id ASC
            """,
            (int(memcell_id),),
        ).fetchall()

    group_episode_dict = dict(group_episode) if group_episode else None
    user_episode_list = [dict(row) for row in user_episodes]

    if group_episode_dict is None and not user_episode_list:
        return None

    return {
        "group_episode": group_episode_dict,
        "user_episodes": user_episode_list,
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


def get_pending_memcells_for_episode(
    allowed_group_ids: list[str] | None = None,
    limit: int = 20,
    min_age_seconds: int = 180,
) -> list[dict[str, Any]]:
    if not _db_exists():
        return []

    limit = _clamp_limit(limit, default=20, max_limit=50)

    with _open_readonly_conn() as conn:
        where_parts = ["ge.memcell_id IS NULL", "m.message_count > 0"]
        params: list[Any] = []

        if allowed_group_ids:
            placeholders = ", ".join(["?" for _ in range(len(allowed_group_ids))])
            where_parts.append(f"m.group_id IN ({placeholders})")
            params.extend([str(g) for g in allowed_group_ids])

        age_threshold = int(time.time()) - min_age_seconds
        where_parts.append(f"m.created_at <= ?")
        params.append(age_threshold)

        where_clause = " AND ".join(where_parts)

        rows = conn.execute(
            f"""
            SELECT m.id, m.group_id, m.message_count, m.raw_text_preview, m.created_at
            FROM chat_agent_memcells m
            LEFT JOIN chat_agent_group_episodes ge ON ge.memcell_id = m.id
            WHERE {where_clause}
            ORDER BY m.id DESC
            LIMIT ?
            """,
            params + [limit],
        ).fetchall()

    return [dict(row) for row in rows]


def get_recent_long_memory_candidates(
    scope_type: str | None = None,
    group_id: str | None = None,
    user_id: str | None = None,
    status: str | None = "pending",
    limit: int = 20,
) -> list[dict[str, Any]]:
    if not _db_exists():
        return []

    limit = _clamp_limit(limit, default=20)

    where_parts: list[str] = []
    params: list[Any] = []

    if scope_type:
        where_parts.append("scope_type = ?")
        params.append(str(scope_type))
    if group_id:
        where_parts.append("group_id = ?")
        params.append(str(group_id))
    if user_id:
        where_parts.append("user_id = ?")
        params.append(str(user_id))
    if status is not None and str(status) != "":
        where_parts.append("status = ?")
        params.append(str(status))

    where_clause = " AND ".join(where_parts) if where_parts else "1=1"

    with _open_readonly_conn() as conn:
        rows = conn.execute(
            f"""
            SELECT id, scope_type, group_id, user_id, target_user_id,
                   memory_type, title, summary, keywords_json,
                   evidence_memcell_ids_json, evidence_episode_ids_json,
                   importance, confidence, status, source, source_model,
                   created_at, updated_at, notes
            FROM chat_agent_long_memory_candidates
            WHERE {where_clause}
            ORDER BY updated_at DESC, id DESC
            LIMIT ?
            """,
            params + [limit],
        ).fetchall()

    return [dict(row) for row in rows]


def get_approved_long_memory_candidates_for_group(
    group_id: str,
    limit: int = 200,
) -> list[dict[str, Any]]:
    if not _db_exists():
        return []

    group_id = str(group_id or "").strip()
    if not group_id:
        return []

    limit = _clamp_limit(limit, default=200, max_limit=200)

    with _open_readonly_conn() as conn:
        rows = conn.execute(
            """
            SELECT id, scope_type, group_id, user_id, target_user_id,
                   memory_type, title, summary, keywords_json,
                   evidence_memcell_ids_json, evidence_episode_ids_json,
                   importance, confidence, status, source, source_model,
                   created_at, updated_at, notes
            FROM chat_agent_long_memory_candidates
            WHERE group_id = ?
              AND status = 'approved'
            ORDER BY updated_at DESC, id DESC
            LIMIT ?
            """,
            (group_id, limit),
        ).fetchall()

    return [dict(row) for row in rows]


def get_long_memory_candidate(candidate_id: int) -> dict[str, Any] | None:
    if not _db_exists():
        return None

    try:
        cid = int(candidate_id)
    except Exception:
        return None

    with _open_readonly_conn() as conn:
        row = conn.execute(
            """
            SELECT id, scope_type, group_id, user_id, target_user_id,
                   memory_type, title, summary, keywords_json,
                   evidence_memcell_ids_json, evidence_episode_ids_json,
                   importance, confidence, status, source, source_model,
                   created_at, updated_at, notes
            FROM chat_agent_long_memory_candidates
            WHERE id = ?
            """,
            (cid,),
        ).fetchone()

    return _row_to_dict(row)
