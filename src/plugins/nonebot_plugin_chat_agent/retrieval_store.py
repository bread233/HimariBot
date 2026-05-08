from __future__ import annotations

import asyncio
import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


def _ensure_parent(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)


def _init_retrieval_storage_sync(db_path: Path) -> None:
    _ensure_parent(db_path)
    conn = sqlite3.connect(db_path)
    try:
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


def make_embedding_cache_key(model: str, source: str, content: str) -> str:
    raw = f"{model}\n{source}\n{content}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _get_cached_embedding_sync(db_path: Path, model: str, source: str, content: str) -> list[float] | None:
    if not db_path.exists():
        return None
    cache_key = make_embedding_cache_key(model, source, content)
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.execute(
            """
            SELECT embedding_json
            FROM chat_agent_embedding_cache
            WHERE cache_key = ?
            LIMIT 1
            """,
            (cache_key,),
        )
        row = cursor.fetchone()
    finally:
        conn.close()
    if not row:
        return None
    try:
        data = json.loads(row[0])
    except Exception:
        return None
    if not isinstance(data, list):
        return None
    return [float(x) for x in data]


def _set_cached_embedding_sync(db_path: Path, model: str, source: str, content: str, embedding: list[float]) -> None:
    _ensure_parent(db_path)
    cache_key = make_embedding_cache_key(model, source, content)
    now = datetime.now(timezone.utc).isoformat()
    payload = json.dumps([float(x) for x in embedding], ensure_ascii=False)
    dim = len(embedding)
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """
            INSERT INTO chat_agent_embedding_cache
            (cache_key, source, content, embedding_json, model, dim, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(cache_key) DO UPDATE SET
                embedding_json = excluded.embedding_json,
                model = excluded.model,
                dim = excluded.dim,
                updated_at = excluded.updated_at
            """,
            (cache_key, source, content, payload, model, dim, now, now),
        )
        conn.commit()
    finally:
        conn.close()


async def init_retrieval_storage(config) -> None:
    await asyncio.to_thread(_init_retrieval_storage_sync, Path(config.chat_agent_db_path))


async def get_cached_embedding(config, source: str, content: str) -> list[float] | None:
    model = str(getattr(config, "chat_agent_embedding_model", "") or "")
    return await asyncio.to_thread(_get_cached_embedding_sync, Path(config.chat_agent_db_path), model, source, content)


async def set_cached_embedding(config, source: str, content: str, embedding: list[float]) -> None:
    model = str(getattr(config, "chat_agent_embedding_model", "") or "")
    await asyncio.to_thread(_set_cached_embedding_sync, Path(config.chat_agent_db_path), model, source, content, embedding)
