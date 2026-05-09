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
    p.add_argument("--json", action="store_true")

    args = p.parse_args(argv)

    out = asyncio.run(_run(args))
    if args.json:
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0

    results = out.get("results") or []
    for r in results:
        rank = r.get("rank")
        score = r.get("score")
        summary_key = r.get("summary_key")
        user_id = r.get("user_id")
        group_id = r.get("group_id")
        head = str(r.get("summary_text_head", "") or "").replace("\n", " ")
        print(f"{rank}\t{score:.4f}\t{summary_key}\t{user_id}\t{group_id}\t{head}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
