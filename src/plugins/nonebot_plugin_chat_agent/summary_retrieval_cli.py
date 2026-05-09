from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace


def _import_summary_retrieval():
    if __package__ in (None, ""):
        cur_dir = Path(__file__).resolve().parent
        sys.path.insert(0, str(cur_dir))
        import summary_retrieval  # type: ignore

        return summary_retrieval

    from . import summary_retrieval

    return summary_retrieval


async def _run(args) -> dict:
    summary_retrieval = _import_summary_retrieval()

    base_url = args.embedding_base_url or os.environ.get("CHAT_AGENT_EMBEDDING_BASE_URL") or ""
    model = args.embedding_model or os.environ.get("CHAT_AGENT_EMBEDDING_MODEL") or ""
    timeout_text = str(args.embedding_timeout or os.environ.get("CHAT_AGENT_EMBEDDING_TIMEOUT") or "120")
    try:
        timeout = int(timeout_text)
    except Exception:
        timeout = 120

    config = SimpleNamespace(
        chat_agent_db_path=Path(args.db_path),
        chat_agent_embedding_base_url=base_url,
        chat_agent_embedding_model=model,
        chat_agent_embedding_timeout=timeout,
    )

    return await summary_retrieval.retrieve_daily_summaries(
        config,
        query=args.query,
        top_k=args.top_k,
        candidate_limit=args.candidate_limit,
        min_score=args.min_score,
        min_margin=args.min_margin,
        overlap_min_score=args.overlap_min_score,
        min_overlap=args.min_overlap,
        strong_score=args.strong_score,
        weak_margin_floor=args.weak_margin_floor,
    )


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Manual daily summary retrieval CLI (no LLM, no DB writes).")
    p.add_argument("--db-path", required=True)
    p.add_argument("--query", required=True)
    p.add_argument("--embedding-base-url", default=None)
    p.add_argument("--embedding-model", default=None)
    p.add_argument("--embedding-timeout", default=None)
    p.add_argument("--top-k", type=int, default=5)
    p.add_argument("--candidate-limit", type=int, default=None)
    p.add_argument("--min-score", type=float, default=0.60)
    p.add_argument("--min-margin", type=float, default=0.04)
    p.add_argument("--overlap-min-score", type=float, default=0.50)
    p.add_argument("--min-overlap", type=int, default=2)
    p.add_argument("--strong-score", type=float, default=0.68)
    p.add_argument("--weak-margin-floor", type=float, default=0.02)
    p.add_argument("--json", action="store_true")

    args = p.parse_args(argv)

    out = asyncio.run(_run(args))
    if args.json:
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0

    reliable = out.get("reliable")
    reliable_by = out.get("reliable_by")
    gate_reason = out.get("gate_reason")
    top1_score = out.get("top1_score")
    top2_score = out.get("top2_score")
    margin = out.get("margin")
    top1_overlap_count = out.get("top1_overlap_count")
    top1_matched_terms = out.get("top1_matched_terms")
    print(
        f"reliable={reliable} reliable_by={reliable_by} top1={top1_score:.4f} top2={top2_score:.4f} margin={margin:.4f} "
        f"top1_overlap={top1_overlap_count} top1_terms={top1_matched_terms} reason={gate_reason}"
    )

    results = out.get("results") or []
    for r in results:
        rank = r.get("rank")
        score = r.get("score")
        summary_key = r.get("summary_key")
        user_id = r.get("user_id")
        group_id = r.get("group_id")
        head = str(r.get("summary_text_head", "") or "").replace("\n", " ")
        overlap_count = r.get("overlap_count")
        matched_terms = r.get("matched_terms")
        print(f"{rank}\t{score:.4f}\t{overlap_count}\t{matched_terms}\t{summary_key}\t{user_id}\t{group_id}\t{head}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
