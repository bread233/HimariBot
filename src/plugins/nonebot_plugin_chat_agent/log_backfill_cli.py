from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

from .log_ingestor import backfill_logs, iter_info_log_files, should_import_log_file
from .storage import init_storage


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Chat agent log backfill CLI")
    parser.add_argument("--log-dir", default="/app/log", help="Log directory to scan")
    parser.add_argument("--db-path", required=True, help="SQLite DB path")
    parser.add_argument("--all", action="store_true", help="Import all files (changed_only=False)")
    parser.add_argument("--limit-files", type=int, default=None, help="Limit files to process")
    parser.add_argument("--dry-run", action="store_true", help="Only show candidates, no DB writes")
    parser.add_argument("--json", action="store_true", help="Print JSON output")
    return parser


async def _run(args) -> dict:
    cfg = SimpleNamespace(
        chat_agent_db_path=Path(args.db_path),
        chat_agent_log_dir=str(args.log_dir),
    )
    changed_only = not bool(args.all)

    if args.dry_run:
        files = iter_info_log_files(cfg.chat_agent_log_dir)
        candidates: list[str] = []
        skipped: list[str] = []
        for path in files:
            try:
                should_import = await should_import_log_file(cfg, path, changed_only=changed_only)
            except Exception:
                should_import = True
            if should_import:
                candidates.append(str(path))
            else:
                skipped.append(str(path))
        if args.limit_files is not None and int(args.limit_files) >= 0:
            candidates = candidates[: int(args.limit_files)]
        return {
            "dry_run": True,
            "changed_only": changed_only,
            "files_count": len(files),
            "candidate_files_count": len(candidates),
            "skipped_files_count": len(skipped),
            "imported_files_count": 0,
            "scanned_count": 0,
            "inserted_count": 0,
            "duplicate_count": 0,
            "skipped_count": 0,
            "error_count": 0,
            "files": [],
            "candidate_files": candidates,
            "skipped_files": skipped,
        }

    await init_storage(cfg)
    result = await backfill_logs(
        cfg,
        changed_only=changed_only,
        limit_files=args.limit_files,
    )
    result["dry_run"] = False
    result["changed_only"] = changed_only
    return result


def _print_result(result: dict, as_json: bool) -> None:
    if as_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    lines = [
        f"dry_run={result.get('dry_run')}",
        f"changed_only={result.get('changed_only')}",
        f"files_count={result.get('files_count')}",
        f"candidate_files_count={result.get('candidate_files_count')}",
        f"imported_files_count={result.get('imported_files_count')}",
        f"skipped_files_count={result.get('skipped_files_count')}",
        f"scanned_count={result.get('scanned_count')}",
        f"inserted_count={result.get('inserted_count')}",
        f"duplicate_count={result.get('duplicate_count')}",
        f"skipped_count={result.get('skipped_count')}",
        f"error_count={result.get('error_count')}",
    ]
    print("\n".join(lines))


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    result = asyncio.run(_run(args))
    _print_result(result, as_json=bool(args.json))


if __name__ == "__main__":
    main()
