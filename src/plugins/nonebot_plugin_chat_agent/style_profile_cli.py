from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace


def _import_style_profile():
    if __package__ in (None, ""):
        cur_dir = Path(__file__).resolve().parent
        sys.path.insert(0, str(cur_dir))
        import style_profile  # type: ignore

        return style_profile

    from . import style_profile

    return style_profile


async def _run(args) -> dict:
    style_profile = _import_style_profile()
    config = SimpleNamespace(chat_agent_db_path=Path(args.db_path))

    dry_run = not bool(args.write)
    if args.dry_run:
        dry_run = True

    return await style_profile.build_style_profiles(
        config,
        user_id=args.user_id,
        group_id=args.group_id,
        min_messages=args.min_messages,
        limit_users=args.limit_users,
        limit_rows=args.limit_rows,
        reply_window_seconds=args.reply_window_seconds,
        dry_run=dry_run,
    )


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Manual deterministic user style profile builder (no LLM, no embedding).")
    p.add_argument("--db-path", required=True)
    p.add_argument("--user-id", default=None)
    p.add_argument("--group-id", default=None)
    p.add_argument("--min-messages", type=int, default=5)
    p.add_argument("--limit-users", type=int, default=None)
    p.add_argument("--limit-rows", type=int, default=None)
    p.add_argument("--reply-window-seconds", type=int, default=180)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--write", action="store_true")
    p.add_argument("--json", action="store_true")

    args = p.parse_args(argv)

    out = asyncio.run(_run(args))
    if args.json:
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0

    print(f"dry_run: {out.get('dry_run')}")
    print(f"rows_count: {out.get('rows_count')}")
    print(f"profile_count: {out.get('profile_count')}")
    print(f"written_count: {out.get('written_count')}")
    print(f"skipped_count: {out.get('skipped_count')}")
    print(f"error_count: {out.get('error_count')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
