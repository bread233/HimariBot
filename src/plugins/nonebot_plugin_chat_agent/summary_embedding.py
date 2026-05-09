from __future__ import annotations

import asyncio
import importlib.machinery
import importlib.util
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path


def _import_modules():
    try:
        from . import embedding_client, retrieval_store  # type: ignore

        return embedding_client, retrieval_store
    except Exception:
        base_dir = Path(__file__).resolve().parent
        pkg_name = "_chat_agent_standalone"

        if pkg_name not in sys.modules:
            pkg = importlib.util.module_from_spec(importlib.machinery.ModuleSpec(pkg_name, None))
            pkg.__path__ = [str(base_dir)]
            sys.modules[pkg_name] = pkg

        def load(mod_basename: str):
            full_name = f"{pkg_name}.{mod_basename}"
            if full_name in sys.modules:
                return sys.modules[full_name]
            file_path = base_dir / f"{mod_basename}.py"
            spec = importlib.util.spec_from_file_location(full_name, file_path)
            if spec is None or spec.loader is None:
                raise ImportError(f"cannot load module: {full_name}")
            module = importlib.util.module_from_spec(spec)
            sys.modules[full_name] = module
            spec.loader.exec_module(module)
            return module

        retrieval_store = load("retrieval_store")
        embedding_client = load("embedding_client")
        return embedding_client, retrieval_store


def build_summary_embedding_key(row: dict) -> str:
    summary_key = str(row.get("summary_key", "") or "")
    content_hash = str(row.get("content_hash", "") or "")
    return f"daily_summary:{summary_key}:{content_hash}"


def build_summary_embedding_text(row: dict) -> str:
    summary_date = str(row.get("summary_date", "") or "")
    user_id = str(row.get("user_id", "") or "")
    group_id = str(row.get("group_id", "") or "")
    group_name = str(row.get("group_name", "") or "")
    nickname = str(row.get("nickname", "") or "")
    group_card = str(row.get("group_card", "") or "")
    message_count = int(row.get("message_count", 0) or 0)
    summary_text = str(row.get("summary_text", "") or "")

    head = "\n".join(
        [
            "Chat log daily summary",
            f"Date: {summary_date}",
            f"User: {user_id}",
            f"Group: {group_id} {group_name}".rstrip(),
            f"Nickname: {nickname}".rstrip(),
            f"Group card: {group_card}".rstrip(),
            f"Message count: {message_count}",
            "",
        ]
    )
    combined = head + summary_text
    combined = combined.strip()
    if len(combined) <= 4000:
        return combined
    return combined[:4000]


def load_daily_summary_rows(
    db_path: Path,
    limit: int | None = None,
    offset: int = 0,
    only_missing: bool = True,
    embedding_model: str | None = None,
) -> list[dict]:
    if not db_path.exists():
        return []
    model = str(embedding_model or "")
    conn = sqlite3.connect(db_path)
    try:
        sql = """
        SELECT
            id,
            summary_key,
            summary_date,
            user_id,
            group_id,
            group_name,
            nickname,
            group_card,
            message_count,
            summary_text,
            content_hash
        FROM chat_agent_user_daily_summaries
        ORDER BY id ASC
        LIMIT ? OFFSET ?
        """
        lim = int(limit) if limit is not None else 1000000000
        cur = conn.execute(sql, (lim, int(offset)))
        rows = cur.fetchall()

        out: list[dict] = []
        for r in rows:
            row = {
                "id": r[0],
                "summary_key": r[1],
                "summary_date": r[2],
                "user_id": r[3],
                "group_id": r[4],
                "group_name": r[5],
                "nickname": r[6],
                "group_card": r[7],
                "message_count": r[8],
                "summary_text": r[9],
                "content_hash": r[10],
            }
            if only_missing:
                cache_key = build_summary_embedding_key(row)
                try:
                    cur2 = conn.execute(
                        "SELECT model FROM chat_agent_embedding_cache WHERE cache_key=? LIMIT 1",
                        (cache_key,),
                    )
                    hit = cur2.fetchone()
                    if hit and model and str(hit[0] or "") == model:
                        continue
                except sqlite3.OperationalError:
                    pass
            out.append(row)
        return out
    except sqlite3.OperationalError:
        return []
    finally:
        conn.close()


def _upsert_embedding_cache_sync(db_path: Path, cache_key: str, source: str, content: str, model: str, embedding: list[float]) -> None:
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
                source = excluded.source,
                content = excluded.content,
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


async def embed_daily_summaries(
    config,
    limit: int | None = None,
    offset: int = 0,
    only_missing: bool = True,
    dry_run: bool = True,
) -> dict:
    embedding_client, retrieval_store = _import_modules()
    db_path = Path(config.chat_agent_db_path)
    model = str(getattr(config, "chat_agent_embedding_model", "") or "")

    if dry_run:
        all_rows = load_daily_summary_rows(db_path, limit=limit, offset=offset, only_missing=False, embedding_model=model)
        rows = load_daily_summary_rows(db_path, limit=limit, offset=offset, only_missing=only_missing, embedding_model=model)
        skipped_existing_count = max(0, len(all_rows) - len(rows)) if only_missing else 0
        samples: list[dict] = []
        for row in rows[:5]:
            cache_key = build_summary_embedding_key(row)
            text = build_summary_embedding_text(row)
            samples.append(
                {
                    "summary_key": row.get("summary_key"),
                    "content_hash": row.get("content_hash"),
                    "cache_key": cache_key,
                    "text_len": len(text),
                    "text_head": text[:300],
                }
            )
        return {
            "total_candidate_count": len(rows),
            "embedded_count": 0,
            "skipped_existing_count": skipped_existing_count,
            "error_count": 0,
            "samples": samples,
        }

    await retrieval_store.init_retrieval_storage(config)

    conn = sqlite3.connect(db_path)
    try:
        sql = """
            SELECT
                id,
                summary_key,
                summary_date,
                user_id,
                group_id,
                group_name,
                nickname,
                group_card,
                message_count,
                summary_text,
                content_hash
            FROM chat_agent_user_daily_summaries
            ORDER BY id ASC
            LIMIT ? OFFSET ?
        """
        lim = int(limit) if limit is not None else 1000000000
        cur = conn.execute(sql, (lim, int(offset)))
        rows = cur.fetchall()
    finally:
        conn.close()

    total_candidate_count = len(rows)
    embedded_count = 0
    skipped_existing_count = 0
    error_count = 0
    samples: list[dict] = []

    to_embed: list[dict] = []
    cache_conn = sqlite3.connect(db_path)
    try:
        for r in rows:
            row = {
                "id": r[0],
                "summary_key": r[1],
                "summary_date": r[2],
                "user_id": r[3],
                "group_id": r[4],
                "group_name": r[5],
                "nickname": r[6],
                "group_card": r[7],
                "message_count": r[8],
                "summary_text": r[9],
                "content_hash": r[10],
            }
            cache_key = build_summary_embedding_key(row)
            if only_missing:
                try:
                    cur2 = cache_conn.execute(
                        "SELECT model FROM chat_agent_embedding_cache WHERE cache_key=? LIMIT 1",
                        (cache_key,),
                    )
                    hit = cur2.fetchone()
                    if hit and model and str(hit[0] or "") == model:
                        skipped_existing_count += 1
                        continue
                except sqlite3.OperationalError:
                    pass
            to_embed.append(row)
    finally:
        cache_conn.close()

    batch_size = 16
    for i in range(0, len(to_embed), batch_size):
        batch = to_embed[i : i + batch_size]
        texts = [build_summary_embedding_text(r) for r in batch]
        try:
            vecs = await embedding_client.embed_texts(config, texts)
        except Exception:
            error_count += len(batch)
            continue
        for row, vec, text in zip(batch, vecs, texts, strict=False):
            try:
                cache_key = build_summary_embedding_key(row)
                await asyncio.to_thread(
                    _upsert_embedding_cache_sync,
                    db_path,
                    cache_key,
                    "daily_summary",
                    text,
                    model,
                    vec,
                )
                embedded_count += 1
                if len(samples) < 5:
                    samples.append(
                        {
                            "summary_key": row.get("summary_key"),
                            "cache_key": cache_key,
                            "dim": len(vec),
                        }
                    )
            except Exception:
                error_count += 1

    return {
        "total_candidate_count": total_candidate_count,
        "embedded_count": embedded_count,
        "skipped_existing_count": skipped_existing_count,
        "error_count": error_count,
        "samples": samples,
    }
