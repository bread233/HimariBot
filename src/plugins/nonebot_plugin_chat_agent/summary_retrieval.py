from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import math
import sqlite3
import sys
from pathlib import Path


def _import_embedding_client():
    try:
        from . import embedding_client  # type: ignore

        return embedding_client
    except Exception:
        base_dir = Path(__file__).resolve().parent
        pkg_name = "_chat_agent_standalone"

        if pkg_name not in sys.modules:
            pkg = importlib.util.module_from_spec(importlib.machinery.ModuleSpec(pkg_name, None))
            pkg.__path__ = [str(base_dir)]
            sys.modules[pkg_name] = pkg

        full_name = f"{pkg_name}.embedding_client"
        if full_name in sys.modules:
            return sys.modules[full_name]

        file_path = base_dir / "embedding_client.py"
        spec = importlib.util.spec_from_file_location(full_name, file_path)
        if spec is None or spec.loader is None:
            raise ImportError(f"cannot load module: {full_name}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[full_name] = module
        spec.loader.exec_module(module)
        return module


def cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b:
        return 0.0
    if len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


def build_query_embedding_text(query: str) -> str:
    q = str(query or "").strip()
    if not q:
        return ""
    return "Search relevant chat log daily summaries for this user query:\n" + q


def load_daily_summary_embedding_candidates(db_path: Path, model: str | None = None, limit: int | None = None) -> list[dict]:
    if not db_path.exists():
        return []
    conn = sqlite3.connect(db_path)
    try:
        sql = """
        SELECT
            cache.cache_key,
            cache.source,
            cache.content,
            cache.embedding_json,
            cache.model,
            cache.dim,
            s.summary_key,
            s.summary_date,
            s.user_id,
            s.group_id,
            s.group_name,
            s.nickname,
            s.group_card,
            s.message_count,
            s.summary_text,
            s.content_hash
        FROM chat_agent_embedding_cache AS cache
        JOIN chat_agent_user_daily_summaries AS s
            ON cache.cache_key = ('daily_summary:' || s.summary_key || ':' || s.content_hash)
        WHERE cache.source = 'daily_summary'
        """
        params: list[object] = []
        if model:
            sql += " AND cache.model = ?"
            params.append(str(model))
        sql += " ORDER BY s.id ASC"
        if limit is not None and int(limit) > 0:
            sql += " LIMIT ?"
            params.append(int(limit))

        cur = conn.execute(sql, tuple(params))
        rows = cur.fetchall()

        out: list[dict] = []
        for r in rows:
            try:
                emb = json.loads(r[3])
                if not isinstance(emb, list):
                    continue
                vec = [float(x) for x in emb]
            except Exception:
                continue

            out.append(
                {
                    "cache_key": r[0],
                    "source": r[1],
                    "content": r[2],
                    "embedding": vec,
                    "model": r[4],
                    "dim": r[5],
                    "summary_key": r[6],
                    "summary_date": r[7],
                    "user_id": r[8],
                    "group_id": r[9],
                    "group_name": r[10],
                    "nickname": r[11],
                    "group_card": r[12],
                    "message_count": r[13],
                    "summary_text": r[14],
                    "content_hash": r[15],
                }
            )
        return out
    except sqlite3.OperationalError:
        return []
    finally:
        conn.close()


async def retrieve_daily_summaries(
    config,
    query: str,
    top_k: int = 5,
    candidate_limit: int | None = None,
    min_score: float = 0.60,
    min_margin: float = 0.04,
) -> dict:
    embedding_client = _import_embedding_client()
    model = str(getattr(config, "chat_agent_embedding_model", "") or "")
    db_path = Path(getattr(config, "chat_agent_db_path"))

    query_text = build_query_embedding_text(query)
    vecs = await embedding_client.embed_texts(config, [query_text])
    query_vec = vecs[0] if vecs else []

    candidates = load_daily_summary_embedding_candidates(db_path, model=model or None, limit=candidate_limit)
    scored: list[tuple[float, dict]] = []
    for c in candidates:
        score = cosine_similarity(query_vec, c.get("embedding") or [])
        scored.append((score, c))

    scored.sort(key=lambda x: x[0], reverse=True)
    picked = scored[: max(1, int(top_k))]

    top1_score = picked[0][0] if len(picked) >= 1 else 0.0
    top2_score = picked[1][0] if len(picked) >= 2 else 0.0
    margin = top1_score - top2_score
    reliable = bool(top1_score >= float(min_score) and margin >= float(min_margin))

    results: list[dict] = []
    for idx, (score, row) in enumerate(picked, start=1):
        summary_text = str(row.get("summary_text", "") or "")
        results.append(
            {
                "rank": idx,
                "score": float(score),
                "summary_key": row.get("summary_key"),
                "summary_date": row.get("summary_date"),
                "user_id": row.get("user_id"),
                "group_id": row.get("group_id"),
                "group_name": row.get("group_name"),
                "nickname": row.get("nickname"),
                "group_card": row.get("group_card"),
                "message_count": row.get("message_count"),
                "summary_text_head": summary_text[:800],
                "cache_key": row.get("cache_key"),
                "model": row.get("model"),
                "dim": row.get("dim"),
            }
        )

    return {
        "query": query,
        "candidate_count": len(candidates),
        "top_k": int(top_k),
        "top1_score": float(top1_score),
        "top2_score": float(top2_score),
        "margin": float(margin),
        "reliable": reliable,
        "min_score": float(min_score),
        "min_margin": float(min_margin),
        "results": results,
    }
