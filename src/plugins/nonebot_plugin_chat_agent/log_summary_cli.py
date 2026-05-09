from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace


def _import_modules():
    if __package__ in (None, ""):
        cur_dir = Path(__file__).resolve().parent
        sys.path.insert(0, str(cur_dir))
        import log_summary  # type: ignore
        import storage  # type: ignore

        return log_summary, storage

    from . import log_summary, storage

    return log_summary, storage


async def _run(args) -> dict:
    log_summary, storage = _import_modules()
    config = SimpleNamespace(chat_agent_db_path=Path(args.db_path))

    dry_run = not bool(args.write)

    if args.write:
        await storage.init_storage(config)

    return await log_summary.build_daily_summaries(
        config,
        date_from=args.date_from,
        date_to=args.date_to,
        limit_rows=args.limit_rows,
        limit_groups=args.limit_groups,
        dry_run=dry_run,
    )


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Deterministic daily summaries for chat_agent_log_messages (no LLM, no embeddings)."
    )
    p.add_argument("--db-path", required=True)
    p.add_argument("--date-from", default=None)
    p.add_argument("--date-to", default=None)
    p.add_argument("--limit-rows", type=int, default=None)
    p.add_argument("--limit-groups", type=int, default=None)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--write", action="store_true")
    p.add_argument("--json", action="store_true")

    args = p.parse_args(argv)
    if args.dry_run:
        args.write = False

    out = asyncio.run(_run(args))
    if args.json:
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0

    print(f"raw_messages_count: {out.get('raw_messages_count')}")
    print(f"grouped_count: {out.get('grouped_count')}")
    print(f"summary_count: {out.get('summary_count')}")
    print(f"written_count: {out.get('written_count')}")
    print(f"skipped_count: {out.get('skipped_count')}")
    print(f"error_count: {out.get('error_count')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
