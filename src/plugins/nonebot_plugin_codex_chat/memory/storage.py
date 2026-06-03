from __future__ import annotations

import json
import sqlite3
import time
from difflib import SequenceMatcher
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

    # Create new tables for episodes
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS chat_agent_group_episodes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            memcell_id INTEGER NOT NULL UNIQUE,
            group_id TEXT NOT NULL,
            summary TEXT NOT NULL DEFAULT '',
            topic TEXT NOT NULL DEFAULT '',
            keywords_json TEXT NOT NULL DEFAULT '[]',
            importance INTEGER NOT NULL DEFAULT 0,
            confidence REAL NOT NULL DEFAULT 0,
            model_name TEXT NOT NULL DEFAULT '',
            raw_json TEXT NOT NULL DEFAULT '{}',
            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL,
            FOREIGN KEY(memcell_id) REFERENCES chat_agent_memcells(id)
        )
        """
    )

    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_chat_agent_group_episodes_group_created
        ON chat_agent_group_episodes(group_id, created_at)
        """
    )

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS chat_agent_user_episodes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            memcell_id INTEGER NOT NULL,
            group_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            summary TEXT NOT NULL DEFAULT '',
            attitude TEXT NOT NULL DEFAULT '',
            preference_candidates_json TEXT NOT NULL DEFAULT '[]',
            style_observation TEXT NOT NULL DEFAULT '',
            topic_keywords_json TEXT NOT NULL DEFAULT '[]',
            importance INTEGER NOT NULL DEFAULT 0,
            confidence REAL NOT NULL DEFAULT 0,
            model_name TEXT NOT NULL DEFAULT '',
            raw_json TEXT NOT NULL DEFAULT '{}',
            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL,
            FOREIGN KEY(memcell_id) REFERENCES chat_agent_memcells(id),
            UNIQUE(memcell_id, user_id)
        )
        """
    )

    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_chat_agent_user_episodes_group_user_created
        ON chat_agent_user_episodes(group_id, user_id, created_at)
        """
    )

    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_chat_agent_user_episodes_memcell
        ON chat_agent_user_episodes(memcell_id)
        """
    )

    # Long-term memory candidates (read-only this round; writers come later)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS chat_agent_long_memory_candidates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            scope_type TEXT NOT NULL,
            group_id TEXT,
            user_id TEXT,
            target_user_id TEXT,
            memory_type TEXT NOT NULL,
            title TEXT NOT NULL DEFAULT '',
            summary TEXT NOT NULL DEFAULT '',
            keywords_json TEXT NOT NULL DEFAULT '[]',
            evidence_memcell_ids_json TEXT NOT NULL DEFAULT '[]',
            evidence_episode_ids_json TEXT NOT NULL DEFAULT '[]',
            importance INTEGER NOT NULL DEFAULT 0,
            confidence REAL NOT NULL DEFAULT 0.0,
            status TEXT NOT NULL DEFAULT 'pending',
            source TEXT NOT NULL DEFAULT 'episode_consolidation',
            source_model TEXT NOT NULL DEFAULT '',
            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL,
            notes TEXT NOT NULL DEFAULT ''
        )
        """
    )

    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_long_memory_candidates_scope
        ON chat_agent_long_memory_candidates(scope_type, group_id, user_id, status, updated_at)
        """
    )

    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_long_memory_candidates_status
        ON chat_agent_long_memory_candidates(status, updated_at)
        """
    )

    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_long_memory_candidates_group
        ON chat_agent_long_memory_candidates(group_id, updated_at)
        """
    )

    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_long_memory_candidates_user
        ON chat_agent_long_memory_candidates(group_id, user_id, updated_at)
        """
    )

    conn.commit()
    logger.info(
        "codex_chat_memory db_init tables="
        "[chat_agent_memcells chat_agent_memcell_messages chat_agent_group_episodes "
        "chat_agent_user_episodes chat_agent_long_memory_candidates]"
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


def _as_list(value: object) -> list:
    return value if isinstance(value, list) else []

def _as_dict(value: object) -> dict:
    return value if isinstance(value, dict) else {}

def _as_int(value: object) -> int:
    try:
        return int(value)
    except Exception:
        return 0


def _as_float(value: object) -> float:
    try:
        return float(value)
    except Exception:
        return 0.0


def save_episode_result(memcell_id: int, result: dict, model_name: str) -> dict:
    """Save episode results to database with idempotent writes."""
    if not isinstance(result, dict):
        raise ValueError("result must be a dict")

    now = int(time.time())
    saved_user_episodes = 0

    with get_conn() as conn:
        cur = conn.cursor()

        cur.execute(
            "SELECT group_id FROM chat_agent_memcells WHERE id = ?",
            (memcell_id,),
        )
        row = cur.fetchone()

        if not row:
            raise ValueError(f"Memcell {memcell_id} does not exist")

        group_id = str(row[0])

        group_episode = _as_dict(result.get("group_episode"))

        summary = str(group_episode.get("summary", ""))
        topic = str(group_episode.get("topic", ""))
        keywords = _as_list(group_episode.get("keywords"))
        importance = _as_int(group_episode.get("importance"))
        confidence = _as_float(group_episode.get("confidence"))

        keywords_json = json.dumps(keywords, ensure_ascii=False)
        group_raw_json = json.dumps(group_episode, ensure_ascii=False)

        cur.execute(
            """
            INSERT INTO chat_agent_group_episodes (
                memcell_id, group_id, summary, topic,
                keywords_json, importance, confidence, model_name, raw_json,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(memcell_id) DO UPDATE SET
                group_id = excluded.group_id,
                summary = excluded.summary,
                topic = excluded.topic,
                keywords_json = excluded.keywords_json,
                importance = excluded.importance,
                confidence = excluded.confidence,
                model_name = excluded.model_name,
                raw_json = excluded.raw_json,
                updated_at = excluded.updated_at
            """,
            (
                memcell_id,
                group_id,
                summary,
                topic,
                keywords_json,
                importance,
                confidence,
                str(model_name or ""),
                group_raw_json,
                now,
                now,
            ),
        )

        user_episodes = _as_list(result.get("user_episodes"))

        for episode_raw in user_episodes:
            episode = _as_dict(episode_raw)
            if not episode:
                continue

            user_id = str(episode.get("user_id", "")).strip()
            if not user_id:
                continue

            summary = str(episode.get("summary", ""))
            attitude = str(episode.get("attitude", ""))
            preference_candidates = _as_list(episode.get("preference_candidates"))
            style_observation = str(episode.get("style_observation", ""))
            topic_keywords = _as_list(episode.get("topic_keywords"))
            importance = _as_int(episode.get("importance"))
            confidence = _as_float(episode.get("confidence"))

            preference_candidates_json = json.dumps(
                preference_candidates,
                ensure_ascii=False,
            )
            topic_keywords_json = json.dumps(topic_keywords, ensure_ascii=False)
            user_raw_json = json.dumps(episode, ensure_ascii=False)

            cur.execute(
                """
                INSERT INTO chat_agent_user_episodes (
                    memcell_id, group_id, user_id, summary, attitude,
                    preference_candidates_json, style_observation, topic_keywords_json,
                    importance, confidence, model_name, raw_json,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(memcell_id, user_id) DO UPDATE SET
                    group_id = excluded.group_id,
                    summary = excluded.summary,
                    attitude = excluded.attitude,
                    preference_candidates_json = excluded.preference_candidates_json,
                    style_observation = excluded.style_observation,
                    topic_keywords_json = excluded.topic_keywords_json,
                    importance = excluded.importance,
                    confidence = excluded.confidence,
                    model_name = excluded.model_name,
                    raw_json = excluded.raw_json,
                    updated_at = excluded.updated_at
                """,
                (
                    memcell_id,
                    group_id,
                    user_id,
                    summary,
                    attitude,
                    preference_candidates_json,
                    style_observation,
                    topic_keywords_json,
                    importance,
                    confidence,
                    str(model_name or ""),
                    user_raw_json,
                    now,
                    now,
                ),
            )

            saved_user_episodes += 1

        conn.commit()

    return {
        "group_episode_saved": 1,
        "user_episode_saved": saved_user_episodes,
        "memcell_id": memcell_id,
        "group_id": group_id,
    }


_VALID_SCOPE_TYPES = frozenset({
    "group", "user", "relation", "fact", "style", "preference",
})

_VALID_MEMORY_TYPES = frozenset({
    "preference", "style", "relationship", "fact", "topic", "habit", "alias", "warning",
})


def _normalize_memory_text(value: object) -> str:
    s = str(value or "").strip().lower()[:500]
    return "".join(s.split())


def _is_similar_long_memory(
    title_a: str,
    summary_a: str,
    title_b: str,
    summary_b: str,
) -> bool:
    norm_summary_a = _normalize_memory_text(summary_a)
    norm_summary_b = _normalize_memory_text(summary_b)

    if norm_summary_a and norm_summary_a == norm_summary_b:
        return True

    if not norm_summary_a or not norm_summary_b:
        return False

    ratio = SequenceMatcher(None, norm_summary_a, norm_summary_b).ratio()

    norm_title_a = _normalize_memory_text(title_a)
    norm_title_b = _normalize_memory_text(title_b)
    if norm_title_a and norm_title_a == norm_title_b and ratio >= 0.75:
        return True

    if ratio >= 0.92:
        return True

    return False


def save_long_memory_candidates(
    candidates: list[dict],
    *,
    source_model: str = "",
    source: str = "episode_consolidation",
) -> dict:
    if not isinstance(candidates, list):
        return {"saved": 0, "skipped": 0, "duplicate_skipped": 0, "candidate_ids": []}

    now = int(time.time())
    saved_ids: list[int] = []
    skipped = 0
    duplicate_skipped = 0

    with get_conn() as conn:
        cur = conn.cursor()

        for candidate in candidates:
            if not isinstance(candidate, dict):
                skipped += 1
                continue

            scope_type = str(candidate.get("scope_type", "") or "")
            if scope_type not in _VALID_SCOPE_TYPES:
                skipped += 1
                continue

            memory_type = str(candidate.get("memory_type", "") or "")
            if memory_type not in _VALID_MEMORY_TYPES:
                skipped += 1
                continue

            summary = str(candidate.get("summary", "") or "")
            if not summary.strip():
                skipped += 1
                continue

            title = str(candidate.get("title", "") or "")
            group_id = str(candidate.get("group_id", "") or "")
            user_id = str(candidate.get("user_id", "") or "")
            target_user_id = str(candidate.get("target_user_id", "") or "")
            notes = str(candidate.get("notes", "") or "")

            keywords = _as_list(candidate.get("keywords"))
            evidence_memcell_ids = _as_list(candidate.get("evidence_memcell_ids"))
            evidence_episode_ids = _as_list(candidate.get("evidence_episode_ids"))

            keywords_json = json.dumps(keywords, ensure_ascii=False)
            evidence_memcell_ids_json = json.dumps(evidence_memcell_ids, ensure_ascii=False)
            evidence_episode_ids_json = json.dumps(evidence_episode_ids, ensure_ascii=False)

            importance = _as_int(candidate.get("importance"))
            importance = max(0, min(importance, 10))

            confidence = _as_float(candidate.get("confidence"))
            confidence = max(0.0, min(confidence, 1.0))

            existing_rows = cur.execute(
                """SELECT id, title, summary
                   FROM chat_agent_long_memory_candidates
                   WHERE status = 'approved'
                     AND scope_type = ? AND group_id = ?
                     AND user_id = ? AND target_user_id = ?
                     AND memory_type = ?
                   ORDER BY updated_at DESC, id DESC
                   LIMIT 50""",
                (scope_type, group_id, user_id, target_user_id, memory_type),
            ).fetchall()

            is_duplicate = False
            for row in existing_rows:
                if _is_similar_long_memory(
                    title, summary,
                    str(row["title"] or ""),
                    str(row["summary"] or ""),
                ):
                    is_duplicate = True
                    break

            if is_duplicate:
                duplicate_skipped += 1
                skipped += 1
                continue

            cur.execute(
                """
                INSERT INTO chat_agent_long_memory_candidates (
                    scope_type, group_id, user_id, target_user_id,
                    memory_type, title, summary, keywords_json,
                    evidence_memcell_ids_json, evidence_episode_ids_json,
                    importance, confidence, status, source, source_model,
                    created_at, updated_at, notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    scope_type,
                    group_id,
                    user_id,
                    target_user_id,
                    memory_type,
                    title,
                    summary,
                    keywords_json,
                    evidence_memcell_ids_json,
                    evidence_episode_ids_json,
                    importance,
                    confidence,
                    "approved",
                    source,
                    source_model,
                    now,
                    now,
                    notes,
                ),
            )

            saved_ids.append(int(cur.lastrowid))

        conn.commit()

    saved_count = len(saved_ids)

    logger.info(
        "codex_chat_memory long_memory_saved saved={} skipped={} duplicate_skipped={} source_model={} status=approved",
        saved_count,
        skipped,
        duplicate_skipped,
        source_model or "",
    )

    return {
        "saved": saved_count,
        "skipped": skipped,
        "duplicate_skipped": duplicate_skipped,
        "candidate_ids": saved_ids,
    }
