from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import math
import re
import sqlite3
import sys
from pathlib import Path


_WS_RE = re.compile(r"\s+")
_ASCII_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{1,63}")
_CJK_TOKEN_RE = re.compile(r"[\u4e00-\u9fff]{2,}")
_PUNCT_ONLY_RE = re.compile(r"^[\W_]+$", flags=re.UNICODE)
_LOW_VALUE_TERMS = {
    "谁",
    "什么",
    "哪个",
    "哪些",
    "经常",
    "有没有",
    "知道",
    "记录",
    "系统",
    "维护",
}


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


def extract_query_terms(query: str) -> list[str]:
    raw = _WS_RE.sub(" ", str(query or "").strip())
    if not raw:
        return []

    candidates: list[str] = []
    if " " in raw:
        candidates.extend(raw.split(" "))
    candidates.extend(_ASCII_TOKEN_RE.findall(raw))
    candidates.extend(_CJK_TOKEN_RE.findall(raw))

    seen: set[str] = set()
    out: list[str] = []
    for term in candidates:
        t = str(term or "").strip()
        if len(t) < 2:
            continue
        if _PUNCT_ONLY_RE.fullmatch(t):
            continue
        if t in _LOW_VALUE_TERMS:
            continue
        key = t.lower() if t.isascii() else t
        if key in seen:
            continue
        seen.add(key)
        out.append(t)
        if len(out) >= 12:
            break
    return out


def compute_term_overlap(query_terms: list[str], text: str) -> dict:
    s = str(text or "")
    if not s or not query_terms:
        return {"overlap_count": 0, "matched_terms": []}

    lower = s.lower()
    matched: list[str] = []
    for t in query_terms:
        term = str(t or "")
        if len(term) < 2:
            continue
        if term.isascii():
            if term.lower() in lower:
                matched.append(term)
        else:
            if term in s:
                matched.append(term)
    return {"overlap_count": len(matched), "matched_terms": matched}


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
    overlap_min_score: float = 0.50,
    min_overlap: int = 2,
    strong_score: float = 0.68,
    weak_margin_floor: float = 0.02,
) -> dict:
    embedding_client = _import_embedding_client()
    model = str(getattr(config, "chat_agent_embedding_model", "") or "")
    db_path = Path(getattr(config, "chat_agent_db_path"))

    query_text = build_query_embedding_text(query)
    query_terms = extract_query_terms(query)
    vecs = await embedding_client.embed_texts(config, [query_text])
    query_vec = vecs[0] if vecs else []

    candidates = load_daily_summary_embedding_candidates(db_path, model=model or None, limit=candidate_limit)
    scored: list[tuple[float, dict]] = []
    for c in candidates:
        score = cosine_similarity(query_vec, c.get("embedding") or [])
        scored.append((score, c))

    scored.sort(key=lambda x: x[0], reverse=True)
    picked = scored[: max(1, int(top_k))]

    results: list[dict] = []
    for idx, (score, row) in enumerate(picked, start=1):
        summary_text = str(row.get("summary_text", "") or "")
        overlap_text = "\n".join(
            [
                summary_text,
                str(row.get("group_name", "") or ""),
                str(row.get("nickname", "") or ""),
                str(row.get("group_card", "") or ""),
            ]
        )
        overlap = compute_term_overlap(query_terms, overlap_text)
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
                "overlap_count": int(overlap.get("overlap_count") or 0),
                "matched_terms": overlap.get("matched_terms") or [],
                "cache_key": row.get("cache_key"),
                "model": row.get("model"),
                "dim": row.get("dim"),
            }
        )

    top1_score = results[0]["score"] if results else 0.0
    top2_score = results[1]["score"] if len(results) >= 2 else 0.0
    margin = float(top1_score) - float(top2_score)
    top1_overlap_count = int(results[0].get("overlap_count") or 0) if results else 0
    top1_matched_terms = results[0].get("matched_terms") if results else []

    reliable = False
    reliable_by = "low_confidence"
    gate_reason = "top1_score below thresholds or insufficient overlap/margin"

    if results:
        if margin < float(weak_margin_floor):
            if float(top1_score) >= 0.75 and top1_overlap_count >= int(min_overlap):
                reliable = True
                reliable_by = "high_score_low_margin"
                gate_reason = "margin < weak_margin_floor but top1_score >= 0.75 and overlap_count >= min_overlap"
            else:
                reliable = False
                reliable_by = "low_margin"
                gate_reason = "margin < weak_margin_floor"
        elif float(top1_score) >= float(strong_score) and margin >= float(min_margin):
            reliable = True
            reliable_by = "strong_score"
            gate_reason = "top1_score >= strong_score and margin >= min_margin"
        elif (
            float(top1_score) >= float(overlap_min_score)
            and margin >= float(min_margin)
            and top1_overlap_count >= int(min_overlap)
        ):
            reliable = True
            reliable_by = "score_margin_overlap"
            gate_reason = "top1_score >= overlap_min_score and margin >= min_margin and overlap_count >= min_overlap"
        else:
            reliable = False
            reliable_by = "low_confidence"
            gate_reason = "top1_score below thresholds or insufficient overlap/margin"

    return {
        "query": query,
        "query_terms": query_terms,
        "candidate_count": len(candidates),
        "top_k": int(top_k),
        "top1_score": float(top1_score),
        "top2_score": float(top2_score),
        "margin": float(margin),
        "reliable": reliable,
        "reliable_by": reliable_by,
        "gate_reason": gate_reason,
        "min_score": float(min_score),
        "min_margin": float(min_margin),
        "overlap_min_score": float(overlap_min_score),
        "min_overlap": int(min_overlap),
        "strong_score": float(strong_score),
        "weak_margin_floor": float(weak_margin_floor),
        "top1_overlap_count": top1_overlap_count,
        "top1_matched_terms": top1_matched_terms,
        "results": results,
    }
