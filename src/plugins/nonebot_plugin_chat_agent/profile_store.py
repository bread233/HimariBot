from __future__ import annotations

import asyncio
import json
import sqlite3
from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path


def _ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def _connect(db_path: Path) -> sqlite3.Connection:
    _ensure_parent(db_path)
    return sqlite3.connect(db_path)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_aliases(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except Exception:
        return []
    if not isinstance(data, list):
        return []
    result: list[str] = []
    for item in data:
        text = str(item or "").strip()
        if text and text not in result:
            result.append(text)
    return result


def _dump_aliases(aliases: Iterable[str]) -> str:
    values: list[str] = []
    for item in aliases:
        text = str(item or "").strip()
        if text and text not in values:
            values.append(text)
    return json.dumps(values[:20], ensure_ascii=False)


def _init_profile_storage_sync(db_path: Path) -> None:
    conn = _connect(db_path)
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS chat_agent_user_profiles (
                user_id TEXT PRIMARY KEY,
                display_name TEXT DEFAULT '',
                aliases TEXT DEFAULT '[]',
                common_topics TEXT DEFAULT '',
                catchphrases TEXT DEFAULT '',
                interaction_notes TEXT DEFAULT '',
                preference_notes TEXT DEFAULT '',
                summary TEXT DEFAULT '',
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS chat_agent_user_group_aliases (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                group_id TEXT NOT NULL,
                group_name TEXT DEFAULT '',
                group_card TEXT DEFAULT '',
                nickname TEXT DEFAULT '',
                last_seen_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_chat_agent_user_group_aliases_user_group
            ON chat_agent_user_group_aliases(user_id, group_id)
            """
        )
        conn.commit()
    finally:
        conn.close()


def _upsert_user_seen_sync(db_path: Path, session_info: dict) -> None:
    user_id = str(session_info.get("user_id") or "").strip()
    if not user_id:
        return
    nickname = str(session_info.get("nickname") or "").strip()
    group_id = str(session_info.get("group_id") or "").strip()
    group_name = str(session_info.get("group_name") or "").strip()
    group_card = str(session_info.get("group_card") or "").strip()
    conn = _connect(db_path)
    try:
        row = conn.execute(
            "SELECT display_name, aliases FROM chat_agent_user_profiles WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        display_name = nickname
        merged_aliases: list[str] = []
        if row:
            existing_display_name, existing_aliases = row
            display_name = str(existing_display_name or "").strip() or nickname
            merged_aliases.extend(_load_aliases(existing_aliases))
        for value in [nickname, group_card]:
            text = str(value or "").strip()
            if text and text not in merged_aliases:
                merged_aliases.append(text)
        conn.execute(
            """
            INSERT INTO chat_agent_user_profiles
                (user_id, display_name, aliases, common_topics, catchphrases, interaction_notes, preference_notes, summary, updated_at)
            VALUES (?, ?, ?, '', '', '', '', '', ?)
            ON CONFLICT(user_id) DO UPDATE SET
                display_name = CASE
                    WHEN chat_agent_user_profiles.display_name = '' AND excluded.display_name != '' THEN excluded.display_name
                    ELSE chat_agent_user_profiles.display_name
                END,
                aliases = excluded.aliases,
                updated_at = excluded.updated_at
            """,
            (user_id, display_name, _dump_aliases(merged_aliases), _now()),
        )
        if group_id:
            conn.execute(
                """
                INSERT INTO chat_agent_user_group_aliases
                    (user_id, group_id, group_name, group_card, nickname, last_seen_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id, group_id) DO UPDATE SET
                    group_name = excluded.group_name,
                    group_card = excluded.group_card,
                    nickname = excluded.nickname,
                    last_seen_at = excluded.last_seen_at
                """,
                (user_id, group_id, group_name, group_card or nickname, nickname, _now()),
            )
        conn.commit()
    finally:
        conn.close()


def _truncate_text(text: str, limit: int) -> str:
    text = (text or "").strip()
    if limit > 0 and len(text) > limit:
        return text[:limit].rstrip()
    return text


def _append_line(lines: list[str], label: str, value: str) -> None:
    value = (value or "").strip()
    if value:
        lines.append(f"- {label}：{value}")


def _load_user_profile_context_sync(db_path: Path, session_info: dict) -> str:
    user_id = str(session_info.get("user_id") or "").strip()
    if not user_id:
        return ""
    nickname = str(session_info.get("nickname") or "").strip()
    group_id = str(session_info.get("group_id") or "").strip()
    group_card = str(session_info.get("group_card") or "").strip()
    conn = _connect(db_path)
    try:
        profile_row = conn.execute(
            """
            SELECT display_name, aliases, common_topics, catchphrases, interaction_notes, preference_notes, summary
            FROM chat_agent_user_profiles
            WHERE user_id = ?
            """,
            (user_id,),
        ).fetchone()
        alias_row = None
        if group_id:
            alias_row = conn.execute(
                """
                SELECT group_name, group_card, nickname
                FROM chat_agent_user_group_aliases
                WHERE user_id = ? AND group_id = ?
                """,
                (user_id, group_id),
            ).fetchone()
    finally:
        conn.close()

    lines: list[str] = ["说话者画像：", f"- QQ：{user_id}"]
    display_name = nickname
    aliases: list[str] = []
    common_topics = catchphrases = interaction_notes = preference_notes = summary = ""
    if profile_row:
        display_name = str(profile_row[0] or "").strip() or display_name
        aliases = _load_aliases(profile_row[1])
        common_topics = str(profile_row[2] or "").strip()
        catchphrases = str(profile_row[3] or "").strip()
        interaction_notes = str(profile_row[4] or "").strip()
        preference_notes = str(profile_row[5] or "").strip()
        summary = str(profile_row[6] or "").strip()

    _append_line(lines, "常用昵称", display_name)
    if aliases:
        _append_line(lines, "已知别名", "、".join(aliases[:5]))

    current_group_card = group_card
    current_group_name = str(session_info.get("group_name") or "").strip()
    if alias_row:
        current_group_name = str(alias_row[0] or "").strip() or current_group_name
        current_group_card = str(alias_row[1] or "").strip() or current_group_card
        if not display_name:
            display_name = str(alias_row[2] or "").strip() or display_name
    if current_group_card and current_group_card != display_name:
        _append_line(lines, "当前群昵称", current_group_card)
    if current_group_name:
        _append_line(lines, "当前群名", current_group_name)
    _append_line(lines, "常聊话题", common_topics)
    _append_line(lines, "口头禅", catchphrases)
    _append_line(lines, "偏好/备注", preference_notes or interaction_notes)
    _append_line(lines, "摘要", summary)
    return _truncate_text("\n".join(lines), 800)


async def init_profile_storage(config) -> None:
    await asyncio.to_thread(_init_profile_storage_sync, config.chat_agent_db_path)


async def upsert_user_seen(config, session_info: dict) -> None:
    await asyncio.to_thread(_upsert_user_seen_sync, config.chat_agent_db_path, session_info)


async def load_user_profile_context(config, session_info: dict) -> str:
    return await asyncio.to_thread(_load_user_profile_context_sync, config.chat_agent_db_path, session_info)
