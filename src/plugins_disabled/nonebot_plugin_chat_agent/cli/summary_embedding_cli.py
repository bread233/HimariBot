from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace


def _import_summary_embedding():
    if __package__ in (None, ""):
        cur_dir = Path(__file__).resolve().parent
        sys.path.insert(0, str(cur_dir))
        import summary_embedding  # type: ignore

        return summary_embedding

    from . import summary_embedding

    return summary_embedding


async def _run(args) -> dict:
    summary_embedding = _import_summary_embedding()

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

    only_missing = not bool(args.all)
    dry_run = not bool(args.write)
    if args.dry_run:
        dry_run = True

    return await summary_embedding.embed_daily_summaries(
        config,
        limit=args.limit,
        offset=args.offset,
        only_missing=only_missing,
        dry_run=dry_run,
    )


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Manual daily summary embedding cache builder (no LLM).")
    p.add_argument("--db-path", required=True)
    p.add_argument("--embedding-base-url", default=None)
    p.add_argument("--embedding-model", default=None)
    p.add_argument("--embedding-timeout", default=None)
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--offset", type=int, default=0)
    p.add_argument("--all", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--write", action="store_true")
    p.add_argument("--json", action="store_true")

    args = p.parse_args(argv)

    out = asyncio.run(_run(args))
    if args.json:
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0

    print(f"total_candidate_count: {out.get('total_candidate_count')}")
    print(f"embedded_count: {out.get('embedded_count')}")
    print(f"skipped_existing_count: {out.get('skipped_existing_count')}")
    print(f"error_count: {out.get('error_count')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
