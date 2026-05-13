from __future__ import annotations

import asyncio
import json
import sqlite3
import re
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
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS chat_agent_knowledge_packs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pack_key TEXT NOT NULL UNIQUE,
                title TEXT NOT NULL DEFAULT '',
                description TEXT NOT NULL DEFAULT '',
                source_type TEXT NOT NULL DEFAULT '',
                source_ref TEXT NOT NULL DEFAULT '',
                enabled INTEGER NOT NULL DEFAULT 1,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS chat_agent_knowledge_documents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pack_key TEXT NOT NULL,
                doc_key TEXT NOT NULL,
                title TEXT NOT NULL DEFAULT '',
                source_path TEXT NOT NULL DEFAULT '',
                source_url TEXT NOT NULL DEFAULT '',
                source_type TEXT NOT NULL DEFAULT '',
                content_hash TEXT NOT NULL DEFAULT '',
                metadata_json TEXT NOT NULL DEFAULT '{}',
                enabled INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(pack_key, doc_key)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS chat_agent_knowledge_chunks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pack_key TEXT NOT NULL,
                doc_key TEXT NOT NULL,
                chunk_key TEXT NOT NULL UNIQUE,
                title TEXT NOT NULL DEFAULT '',
                section TEXT NOT NULL DEFAULT '',
                content TEXT NOT NULL DEFAULT '',
                content_hash TEXT NOT NULL DEFAULT '',
                source_path TEXT NOT NULL DEFAULT '',
                source_url TEXT NOT NULL DEFAULT '',
                chunk_index INTEGER NOT NULL DEFAULT 0,
                token_count INTEGER NOT NULL DEFAULT 0,
                embedding_json TEXT NOT NULL DEFAULT '',
                metadata_json TEXT NOT NULL DEFAULT '{}',
                enabled INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS chat_agent_knowledge_assets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pack_key TEXT NOT NULL,
                asset_key TEXT NOT NULL UNIQUE,
                asset_type TEXT NOT NULL DEFAULT '',
                title TEXT NOT NULL DEFAULT '',
                local_path TEXT NOT NULL DEFAULT '',
                source_url TEXT NOT NULL DEFAULT '',
                content_hash TEXT NOT NULL DEFAULT '',
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_chat_agent_knowledge_chunks_pack_enabled ON chat_agent_knowledge_chunks(pack_key, enabled)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_chat_agent_knowledge_chunks_doc_key ON chat_agent_knowledge_chunks(doc_key)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_chat_agent_knowledge_chunks_content_hash ON chat_agent_knowledge_chunks(content_hash)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_chat_agent_knowledge_chunks_pack_doc_chunk ON chat_agent_knowledge_chunks(pack_key, doc_key, chunk_index)")

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS chat_agent_embedding_cache (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                cache_key TEXT NOT NULL UNIQUE,
                source TEXT NOT NULL,
                content TEXT NOT NULL,
                embedding_json TEXT NOT NULL,
                model TEXT NOT NULL,
                dim INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_chat_agent_embedding_cache_source
            ON chat_agent_embedding_cache(source)
            """
        )
        conn.commit()
    finally:
        conn.close()


def _is_valid_pack_key(pack_key: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z0-9_.-]+", str(pack_key or "").strip()))


def _clamp_limit(limit: int, lo: int = 1, hi: int = 100) -> int:
    try:
        v = int(limit)
    except Exception:
        v = lo
    return max(lo, min(hi, v))


def _upsert_knowledge_pack_sync(db_path: Path, row: dict) -> None:
    _init_storage_sync(db_path)
    pack_key = str(row.get("pack_key", "")).strip()
    if not _is_valid_pack_key(pack_key):
        raise ValueError("invalid pack_key")
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """
            INSERT INTO chat_agent_knowledge_packs (
                pack_key, title, description, source_type, source_ref, enabled, metadata_json, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(pack_key) DO UPDATE SET
                title=excluded.title,
                description=excluded.description,
                source_type=excluded.source_type,
                source_ref=excluded.source_ref,
                enabled=excluded.enabled,
                metadata_json=excluded.metadata_json,
                updated_at=CURRENT_TIMESTAMP
            """,
            (
                pack_key,
                str(row.get("title", "") or "")[:120],
                str(row.get("description", "") or "")[:300],
                str(row.get("source_type", "") or "")[:64],
                str(row.get("source_ref", "") or "")[:300],
                int(row.get("enabled", 1) or 1),
                str(row.get("metadata_json", "{}") or "{}"),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def _upsert_knowledge_documents_sync(db_path: Path, rows: list[dict]) -> int:
    _init_storage_sync(db_path)
    conn = sqlite3.connect(db_path)
    count = 0
    try:
        for row in rows or []:
            pack_key = str(row.get("pack_key", "")).strip()
            doc_key = str(row.get("doc_key", "")).strip()
            if not (_is_valid_pack_key(pack_key) and doc_key):
                continue
            conn.execute(
                """
                INSERT INTO chat_agent_knowledge_documents (
                    pack_key, doc_key, title, source_path, source_url, source_type, content_hash, metadata_json, enabled, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(pack_key, doc_key) DO UPDATE SET
                    title=excluded.title,
                    source_path=excluded.source_path,
                    source_url=excluded.source_url,
                    source_type=excluded.source_type,
                    content_hash=excluded.content_hash,
                    metadata_json=excluded.metadata_json,
                    enabled=excluded.enabled,
                    updated_at=CURRENT_TIMESTAMP
                """,
                (
                    pack_key, doc_key,
                    str(row.get("title", "") or "")[:200],
                    str(row.get("source_path", "") or ""),
                    str(row.get("source_url", "") or ""),
                    str(row.get("source_type", "") or "")[:64],
                    str(row.get("content_hash", "") or "")[:64],
                    str(row.get("metadata_json", "{}") or "{}"),
                    int(row.get("enabled", 1) or 1),
                ),
            )
            count += 1
        conn.commit()
        return count
    finally:
        conn.close()


def _upsert_knowledge_chunks_sync(db_path: Path, rows: list[dict]) -> int:
    _init_storage_sync(db_path)
    conn = sqlite3.connect(db_path)
    count = 0
    try:
        for row in rows or []:
            pack_key = str(row.get("pack_key", "")).strip()
            doc_key = str(row.get("doc_key", "")).strip()
            chunk_key = str(row.get("chunk_key", "")).strip()
            if not (_is_valid_pack_key(pack_key) and doc_key and chunk_key):
                continue
            conn.execute(
                """
                INSERT INTO chat_agent_knowledge_chunks (
                    pack_key, doc_key, chunk_key, title, section, content, content_hash, source_path, source_url,
                    chunk_index, token_count, embedding_json, metadata_json, enabled, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(chunk_key) DO UPDATE SET
                    pack_key=excluded.pack_key,
                    doc_key=excluded.doc_key,
                    title=excluded.title,
                    section=excluded.section,
                    content=excluded.content,
                    content_hash=excluded.content_hash,
                    source_path=excluded.source_path,
                    source_url=excluded.source_url,
                    chunk_index=excluded.chunk_index,
                    token_count=excluded.token_count,
                    embedding_json=excluded.embedding_json,
                    metadata_json=excluded.metadata_json,
                    enabled=excluded.enabled,
                    updated_at=CURRENT_TIMESTAMP
                """,
                (
                    pack_key, doc_key, chunk_key,
                    str(row.get("title", "") or "")[:200],
                    str(row.get("section", "") or "")[:200],
                    str(row.get("content", "") or ""),
                    str(row.get("content_hash", "") or "")[:64],
                    str(row.get("source_path", "") or ""),
                    str(row.get("source_url", "") or ""),
                    int(row.get("chunk_index", 0) or 0),
                    int(row.get("token_count", 0) or 0),
                    str(row.get("embedding_json", "") or ""),
                    str(row.get("metadata_json", "{}") or "{}"),
                    int(row.get("enabled", 1) or 1),
                ),
            )
            count += 1
        conn.commit()
        return count
    finally:
        conn.close()


def _list_knowledge_packs_sync(db_path: Path, include_disabled: bool = False) -> list[dict]:
    if not db_path.exists():
        return []
    conn = sqlite3.connect(db_path)
    try:
        q = "SELECT pack_key,title,description,source_type,source_ref,enabled,metadata_json,created_at,updated_at FROM chat_agent_knowledge_packs"
        if not include_disabled:
            q += " WHERE enabled=1"
        q += " ORDER BY pack_key ASC"
        rows = conn.execute(q).fetchall()
        return [
            {
                "pack_key": r[0], "title": r[1], "description": r[2], "source_type": r[3], "source_ref": r[4],
                "enabled": r[5], "metadata_json": r[6], "created_at": r[7], "updated_at": r[8],
            }
            for r in rows
        ]
    except sqlite3.OperationalError:
        return []
    finally:
        conn.close()


def _list_knowledge_chunks_sync(db_path: Path, pack_key: str | None = None, limit: int = 100) -> list[dict]:
    if not db_path.exists():
        return []
    limit = _clamp_limit(limit, 1, 500)
    conn = sqlite3.connect(db_path)
    try:
        params: list = []
        q = """
            SELECT c.pack_key,c.doc_key,c.chunk_key,c.title,c.section,c.content,c.content_hash,c.source_path,c.source_url,c.chunk_index,c.token_count,c.embedding_json,c.metadata_json,c.enabled,
                   d.enabled as doc_enabled,p.enabled as pack_enabled
            FROM chat_agent_knowledge_chunks c
            LEFT JOIN chat_agent_knowledge_documents d ON c.pack_key=d.pack_key AND c.doc_key=d.doc_key
            LEFT JOIN chat_agent_knowledge_packs p ON c.pack_key=p.pack_key
        """
        if pack_key:
            q += " WHERE c.pack_key=?"
            params.append(pack_key)
        q += " ORDER BY c.pack_key, c.doc_key, c.chunk_index LIMIT ?"
        params.append(limit)
        rows = conn.execute(q, tuple(params)).fetchall()
        return [
            {
                "pack_key": r[0], "doc_key": r[1], "chunk_key": r[2], "title": r[3], "section": r[4], "content": r[5],
                "content_hash": r[6], "source_path": r[7], "source_url": r[8], "chunk_index": r[9], "token_count": r[10],
                "embedding_json": r[11], "metadata_json": r[12], "enabled": r[13], "doc_enabled": r[14], "pack_enabled": r[15],
            }
            for r in rows
        ]
    except sqlite3.OperationalError:
        return []
    finally:
        conn.close()


def _search_knowledge_chunks_lexical_sync(db_path: Path, query: str, pack_key: str | None = None, limit: int = 5, min_score: float = 0.25) -> list[dict]:
    rows = _list_knowledge_chunks_sync(db_path, pack_key=pack_key, limit=1000)
    q_raw = str(query or "").lower().strip()
    if not q_raw:
        return []
    q_no_stop = re.sub(r"(是什么|怎么|如何|一下|吗|呢|么|嘛)", "", q_raw)
    q = re.sub(r"[^\w\u4e00-\u9fff]+", "", q_no_stop)
    zh_groups = [x for x in re.findall(r"[\u4e00-\u9fff]{2,}", q) if len(x) >= 2]
    zh_ngrams = set()
    for g in zh_groups:
        for n in range(2, 7):
            if len(g) < n:
                continue
            for i in range(0, len(g) - n + 1):
                zh_ngrams.add(g[i : i + n])
    en_tokens = [x for x in re.findall(r"[a-z0-9]{2,}", q_no_stop) if len(x) >= 2]
    all_tokens = list(dict.fromkeys([*sorted(zh_ngrams, key=len, reverse=True), *en_tokens]))
    if not all_tokens:
        return []
    out = []
    for r in rows:
        if int(r.get("enabled", 0) or 0) != 1:
            continue
        if int(r.get("doc_enabled", 0) or 0) != 1:
            continue
        if int(r.get("pack_enabled", 0) or 0) != 1:
            continue
        title = str(r.get("title", "") or "").lower().lstrip("\ufeff")
        section = str(r.get("section", "") or "").lower().lstrip("\ufeff")
        content = str(r.get("content", "") or "").lower().lstrip("\ufeff")
        title_norm = re.sub(r"[^\w\u4e00-\u9fff]+", "", title)
        section_norm = re.sub(r"[^\w\u4e00-\u9fff]+", "", section)
        content_norm = re.sub(r"[^\w\u4e00-\u9fff]+", "", content)
        blob = " ".join([title, section, content])
        blob_norm = "".join([title_norm, section_norm, content_norm])
        score = 0.0
        for t in all_tokens[:30]:
            is_zh = bool(re.search(r"[\u4e00-\u9fff]", t))
            if t in title_norm or t in section_norm:
                score += 0.16 if is_zh else 0.10
            elif t in content_norm:
                score += 0.10 if is_zh else 0.10
        if q in blob or q in blob_norm:
            score += 0.15
        if score >= float(min_score):
            x = dict(r)
            x["score"] = round(score, 4)
            out.append(x)
    out.sort(key=lambda x: (float(x.get("score", 0.0)), -int(x.get("token_count", 0) or 0)), reverse=True)
    return out[: _clamp_limit(limit, 1, 20)]


def _delete_knowledge_pack_sync(db_path: Path, pack_key: str) -> int:
    _init_storage_sync(db_path)
    if not _is_valid_pack_key(pack_key):
        raise ValueError("invalid pack_key")
    conn = sqlite3.connect(db_path)
    try:
        cur1 = conn.execute("DELETE FROM chat_agent_knowledge_chunks WHERE pack_key=?", (pack_key,))
        cur2 = conn.execute("DELETE FROM chat_agent_knowledge_documents WHERE pack_key=?", (pack_key,))
        cur3 = conn.execute("DELETE FROM chat_agent_knowledge_assets WHERE pack_key=?", (pack_key,))
        cur4 = conn.execute("DELETE FROM chat_agent_knowledge_packs WHERE pack_key=?", (pack_key,))
        conn.commit()
        return int(cur1.rowcount or 0) + int(cur2.rowcount or 0) + int(cur3.rowcount or 0) + int(cur4.rowcount or 0)
    finally:
        conn.close()


async def upsert_knowledge_pack(config, row: dict) -> None:
    await asyncio.to_thread(_upsert_knowledge_pack_sync, config.chat_agent_db_path, row)


async def upsert_knowledge_documents(config, rows: list[dict]) -> int:
    return await asyncio.to_thread(_upsert_knowledge_documents_sync, config.chat_agent_db_path, rows)


async def upsert_knowledge_chunks(config, rows: list[dict]) -> int:
    return await asyncio.to_thread(_upsert_knowledge_chunks_sync, config.chat_agent_db_path, rows)


async def list_knowledge_packs(config, include_disabled: bool = False) -> list[dict]:
    return await asyncio.to_thread(_list_knowledge_packs_sync, config.chat_agent_db_path, include_disabled)


async def list_knowledge_chunks(config, pack_key: str | None = None, limit: int = 100) -> list[dict]:
    return await asyncio.to_thread(_list_knowledge_chunks_sync, config.chat_agent_db_path, pack_key, limit)


async def search_knowledge_chunks_lexical(config, query: str, pack_key: str | None = None, limit: int = 5, min_score: float = 0.25) -> list[dict]:
    return await asyncio.to_thread(_search_knowledge_chunks_lexical_sync, config.chat_agent_db_path, query, pack_key, limit, min_score)


def _tokenize_text_for_knowledge(text: str) -> tuple[str, list[str], list[str], list[str]]:
    q_raw = str(text or "").lower().strip()
    q_no_stop = re.sub(r"(是什么|怎么|如何|一下|吗|呢|？|\?)", "", q_raw)
    q_norm = re.sub(r"[^\w\u4e00-\u9fff]+", "", q_no_stop)
    zh_groups = [x for x in re.findall(r"[\u4e00-\u9fff]{2,}", q_norm) if len(x) >= 2]
    zh_ngrams = set()
    for g in zh_groups:
        for n in range(2, 7):
            if len(g) < n:
                continue
            for i in range(0, len(g) - n + 1):
                zh_ngrams.add(g[i : i + n])
    en_tokens = [x for x in re.findall(r"[a-z0-9]{2,}", q_no_stop) if len(x) >= 2]
    digit_tokens = [x for x in re.findall(r"\d+", q_no_stop) if x]
    return q_norm, sorted(zh_ngrams, key=len, reverse=True), en_tokens, digit_tokens


def _pseudo_vector_score(query_norm: str, zh_tokens: list[str], en_tokens: list[str], row: dict) -> float:
    title = str(row.get("title", "") or "").lower()
    section = str(row.get("section", "") or "").lower()
    content = str(row.get("content", "") or "").lower()
    blob = f"{title} {section} {content}"
    title_norm = re.sub(r"[^\w\u4e00-\u9fff]+", "", title)
    section_norm = re.sub(r"[^\w\u4e00-\u9fff]+", "", section)
    content_norm = re.sub(r"[^\w\u4e00-\u9fff]+", "", content)
    blob_norm = title_norm + section_norm + content_norm
    score = 0.0
    for t in zh_tokens[:40]:
        if t in title_norm:
            score += 0.14
        elif t in section_norm:
            score += 0.10
        elif t in content_norm:
            score += 0.08
    for t in en_tokens[:20]:
        if t in title_norm:
            score += 0.12
        elif t in section_norm:
            score += 0.08
        elif t in content_norm:
            score += 0.06
    if query_norm and query_norm in blob_norm:
        score += 0.12
    if any(x in section for x in ("pet", "skill", "item", "egg", "furniture")):
        score += 0.03
    return min(1.0, max(0.0, score))


def _normalize_cosine_to_unit(v: float) -> float:
    # cosine in [-1, 1] -> [0, 1]
    x = (float(v) + 1.0) / 2.0
    if x < 0.0:
        return 0.0
    if x > 1.0:
        return 1.0
    return x


def _parse_embedding_json_safe(payload: str) -> list[float] | None:
    s = str(payload or "").strip()
    if not s:
        return None
    try:
        arr = json.loads(s)
    except Exception:
        return None
    if not isinstance(arr, list) or not arr:
        return None
    out: list[float] = []
    try:
        for x in arr:
            out.append(float(x))
    except Exception:
        return None
    return out


def _load_knowledge_vector_rows_sync(db_path: Path, pack_key: str | None, scan_limit: int) -> list[dict]:
    if scan_limit <= 0:
        return []
    if not db_path.exists():
        return []
    conn = sqlite3.connect(db_path)
    try:
        sql = """
            SELECT
                c.pack_key,c.doc_key,c.chunk_key,c.title,c.section,c.content,c.content_hash,c.source_path,c.source_url,
                c.chunk_index,c.token_count,c.embedding_json,c.metadata_json,c.enabled,d.enabled,p.enabled,c.updated_at,c.id
            FROM chat_agent_knowledge_chunks c
            LEFT JOIN chat_agent_knowledge_documents d ON d.pack_key=c.pack_key AND d.doc_key=c.doc_key
            LEFT JOIN chat_agent_knowledge_packs p ON p.pack_key=c.pack_key
            WHERE c.embedding_json IS NOT NULL
              AND TRIM(c.embedding_json) <> ''
        """
        args: list = []
        if pack_key:
            sql += " AND c.pack_key = ?"
            args.append(str(pack_key))
        sql += " ORDER BY c.updated_at DESC, c.id DESC, c.chunk_key ASC LIMIT ?"
        args.append(int(scan_limit))
        rows = conn.execute(sql, tuple(args)).fetchall()
    finally:
        conn.close()
    out: list[dict] = []
    for r in rows:
        out.append(
            {
                "pack_key": r[0], "doc_key": r[1], "chunk_key": r[2], "title": r[3], "section": r[4], "content": r[5],
                "content_hash": r[6], "source_path": r[7], "source_url": r[8], "chunk_index": r[9], "token_count": r[10],
                "embedding_json": r[11], "metadata_json": r[12], "enabled": r[13], "doc_enabled": r[14], "pack_enabled": r[15],
                "updated_at": r[16], "id": r[17],
            }
        )
    return out


def _search_knowledge_chunks_hybrid_sync(
    db_path: Path,
    query: str,
    pack_key: str | None = None,
    limit: int = 5,
    min_score: float = 0.25,
    query_embedding: list[float] | None = None,
    max_vector_scan: int = 1000,
) -> list[dict]:
    scan_cap = max(100, int(max_vector_scan or 1000))
    all_rows = _list_knowledge_chunks_sync(db_path, pack_key=pack_key, limit=scan_cap)
    q_norm, zh_tokens, en_tokens, digit_tokens = _tokenize_text_for_knowledge(query)
    if not q_norm and not zh_tokens and not en_tokens and not digit_tokens:
        return []
    qvec = list(query_embedding or [])
    has_query_vec = bool(qvec)
    vector_error = ""
    lexical_candidates: dict[str, dict] = {}
    vector_candidates: list[dict] = []
    try:
        from . import embedding_client  # type: ignore
    except Exception:
        embedding_client = None  # type: ignore

    vector_topn = max(_clamp_limit(limit, 1, 20) * 5, 20)

    for r in all_rows:
        if int(r.get("enabled", 0) or 0) != 1 or int(r.get("doc_enabled", 0) or 0) != 1 or int(r.get("pack_enabled", 0) or 0) != 1:
            continue
        key = str(r.get("chunk_key", "") or f"{r.get('doc_key','')}#{r.get('chunk_index',0)}")
        x = dict(r)
        # Lightweight lexical score computed from normalized tokens
        title_norm = re.sub(r"[^\w\u4e00-\u9fff]+", "", str(x.get("title", "")).lower())
        section_norm = re.sub(r"[^\w\u4e00-\u9fff]+", "", str(x.get("section", "")).lower())
        content_norm = re.sub(r"[^\w\u4e00-\u9fff]+", "", str(x.get("content", "")).lower())
        lexical_score = 0.0
        for t in zh_tokens[:30]:
            if t in title_norm or t in section_norm:
                lexical_score += 0.16
            elif t in content_norm:
                lexical_score += 0.10
        for t in en_tokens[:20]:
            if t in title_norm or t in section_norm:
                lexical_score += 0.10
            elif t in content_norm:
                lexical_score += 0.08
        if q_norm and (q_norm in title_norm or q_norm in section_norm or q_norm in content_norm):
            lexical_score += 0.15
        x["lexical_score"] = lexical_score
        if lexical_score > 0.0:
            lexical_candidates[key] = x

    if has_query_vec and embedding_client is not None:
        vector_rows = _load_knowledge_vector_rows_sync(db_path, pack_key=pack_key, scan_limit=scan_cap)
        for r in vector_rows:
            if int(r.get("enabled", 0) or 0) != 1 or int(r.get("doc_enabled", 0) or 0) != 1 or int(r.get("pack_enabled", 0) or 0) != 1:
                continue
            cvec = _parse_embedding_json_safe(str(r.get("embedding_json", "") or ""))
            if not cvec:
                continue
            try:
                raw_cos = float(embedding_client.cosine_similarity(qvec, cvec))
                vs = _normalize_cosine_to_unit(raw_cos)
                vx = dict(r)
                vx["vector_score"] = vs
                vx["vector_source"] = "embedding_json"
                vector_candidates.append(vx)
            except Exception as e:
                vector_error = str(e)[:160]

    if vector_candidates:
        vector_candidates.sort(key=lambda a: float(a.get("vector_score", 0.0) or 0.0), reverse=True)
        vector_candidates = vector_candidates[: min(vector_topn, scan_cap)]

    merged: dict[str, dict] = {}
    for key, row in lexical_candidates.items():
        z = dict(row)
        z["vector_score"] = _pseudo_vector_score(q_norm, zh_tokens, en_tokens, z)
        z["vector_source"] = "pseudo"
        z["candidate_source"] = "lexical"
        merged[key] = z

    for x in vector_candidates:
        key = str(x.get("chunk_key", "") or f"{x.get('doc_key','')}#{x.get('chunk_index',0)}")
        old = merged.get(key)
        if not old:
            z = dict(x)
            z.setdefault("lexical_score", 0.0)
            z["candidate_source"] = "vector"
            z["vector_rank"] = len(merged) + 1
            merged[key] = z
            continue
        old_vs = float(old.get("vector_score", 0.0) or 0.0)
        new_vs = float(x.get("vector_score", 0.0) or 0.0)
        if new_vs >= old_vs:
            old["vector_score"] = new_vs
            old["vector_source"] = "embedding_json"
        old["candidate_source"] = "both"

    out: list[dict] = []
    for x in merged.values():
        title = str(x.get("title", "") or "")
        title_norm = re.sub(r"[^\w\u4e00-\u9fff]+", "", title.lower())
        title_bonus = 0.0
        if q_norm and title_norm == q_norm:
            title_bonus = 0.8
        elif q_norm and q_norm in title_norm:
            title_bonus = 0.35
        category_bonus = 0.08 if any(s in str(x.get("section", "")).lower() for s in ("pet", "skill", "item", "egg", "furniture")) else 0.0
        if digit_tokens:
            content_norm = re.sub(r"[^\w\u4e00-\u9fff]+", "", str(x.get("content", "")).lower())
            blob = f"{title_norm}{content_norm}"
            if not all(d in blob for d in digit_tokens):
                x["vector_score"] = min(float(x.get("vector_score", 0.0) or 0.0), 0.25)
        final = float(x.get("lexical_score", 0.0) or 0.0) * 0.55 + float(x.get("vector_score", 0.0) or 0.0) * 0.35 + title_bonus + category_bonus
        x["score"] = round(final, 4)
        x["hybrid_score"] = x["score"]
        if vector_error:
            x["vector_error"] = vector_error
        if final >= float(min_score):
            out.append(x)
    out.sort(key=lambda a: (float(a.get("score", 0.0)), float(a.get("lexical_score", 0.0)), float(a.get("vector_score", 0.0))), reverse=True)
    return out[: _clamp_limit(limit, 1, 20)]


async def search_knowledge_chunks_hybrid(config, query: str, pack_key: str | None = None, limit: int = 5, min_score: float = 0.25) -> list[dict]:
    query_vec: list[float] | None = None
    try:
        from . import embedding_client  # type: ignore
        q_items = [{"source": "knowledge_query", "content": str(query or "")}]
        q_res = await embedding_client.embed_texts_with_cache(config, q_items)
        if q_res and isinstance(q_res[0], list) and q_res[0]:
            query_vec = [float(x) for x in q_res[0]]
    except Exception:
        query_vec = None
    max_vector_scan = int(getattr(config, "chat_agent_knowledge_max_vector_scan", 1000) or 1000)
    if max_vector_scan <= 0:
        max_vector_scan = 1000
    return await asyncio.to_thread(
        _search_knowledge_chunks_hybrid_sync,
        config.chat_agent_db_path,
        query,
        pack_key,
        limit,
        min_score,
        query_vec,
        max_vector_scan,
    )


async def delete_knowledge_pack(config, pack_key: str) -> int:
    return await asyncio.to_thread(_delete_knowledge_pack_sync, config.chat_agent_db_path, pack_key)


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


def _materialize_chat_agent_skill_proposal_sync(
    db_path: Path,
    proposal_key: str,
    enabled: bool = False,
    reviewed_by: str = "",
    review_note: str = "",
) -> bool:
    _init_storage_sync(db_path)
    pkey = str(proposal_key or "").strip()
    if not _validate_skill_key(pkey):
        return False
    if pkey in _RESERVED_BUILTIN_SKILL_KEYS:
        return False
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.execute(
            """
            SELECT
                proposal_key, title, description, intent_kinds, trigger_terms, negative_terms,
                group_ids, priority, content, status
            FROM chat_agent_skill_proposals
            WHERE proposal_key = ?
            LIMIT 1
            """,
            (pkey,),
        )
        row = cur.fetchone()
        if not row:
            return False
        status = str(row[9] or "").strip().lower()
        if status != "approved":
            return False
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
                row[0],
                row[1],
                row[2],
                row[3],
                row[4],
                row[5],
                row[6],
                float(row[7] or 1.0),
                row[8],
                1 if enabled else 0,
            ),
        )
        rb = str(reviewed_by or "").strip()[:80]
        rn = str(review_note or "").strip()[:300]
        if rb or rn:
            conn.execute(
                """
                UPDATE chat_agent_skill_proposals
                SET updated_at=CURRENT_TIMESTAMP, reviewed_by=?, review_note=?
                WHERE proposal_key=?
                """,
                (rb, rn, pkey),
            )
        conn.commit()
        return True
    finally:
        conn.close()


async def materialize_chat_agent_skill_proposal(
    config,
    proposal_key: str,
    enabled: bool = False,
    reviewed_by: str = "",
    review_note: str = "",
) -> bool:
    return await asyncio.to_thread(
        _materialize_chat_agent_skill_proposal_sync,
        config.chat_agent_db_path,
        proposal_key,
        enabled,
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
