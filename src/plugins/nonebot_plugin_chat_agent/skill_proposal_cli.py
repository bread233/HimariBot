from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace

RESERVED_KEYS = {
    "official_current_fact_resolver",
    "lightweight_definition_answer",
    "evidence_route_question",
}


def _valid_key(key: str) -> bool:
    if not key:
        return False
    return all(ch.isalnum() or ch in {"_", "-", "."} for ch in key)


if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from storage import (  # type: ignore
        get_chat_agent_skill_proposal,
        list_chat_agent_skill_proposals,
        set_chat_agent_skill_proposal_status,
        upsert_chat_agent_skill_proposal,
    )
else:
    from .storage import (
        get_chat_agent_skill_proposal,
        list_chat_agent_skill_proposals,
        set_chat_agent_skill_proposal_status,
        upsert_chat_agent_skill_proposal,
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Chat agent skill proposal CLI")
    parser.add_argument("--db-path", required=True, help="SQLite DB path")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_list = sub.add_parser("list", help="List proposals")
    p_list.add_argument("--all", action="store_true", help="List all statuses")
    p_list.add_argument("--status", default="pending", help="Filter by status")
    p_list.add_argument("--limit", type=int, default=100, help="Row limit")

    p_show = sub.add_parser("show", help="Show one proposal")
    p_show.add_argument("proposal_key")

    p_propose = sub.add_parser("propose", help="Create or update a pending proposal")
    p_propose.add_argument("--proposal-key", required=True)
    p_propose.add_argument("--title", default="")
    p_propose.add_argument("--description", default="")
    p_propose.add_argument("--intent-kinds", default="")
    p_propose.add_argument("--trigger-terms", default="")
    p_propose.add_argument("--negative-terms", default="")
    p_propose.add_argument("--group-ids", default="")
    p_propose.add_argument("--priority", required=True)
    p_propose.add_argument("--content", default="")
    p_propose.add_argument("--source-type", default="manual")
    p_propose.add_argument("--source-ref", default="")
    p_propose.add_argument("--confidence", default="0")
    p_propose.add_argument("--sample", action="append", default=[])

    p_approve = sub.add_parser("approve", help="Set proposal status approved")
    p_approve.add_argument("proposal_key")
    p_approve.add_argument("--reviewed-by", default="")
    p_approve.add_argument("--note", default="")

    p_reject = sub.add_parser("reject", help="Set proposal status rejected")
    p_reject.add_argument("proposal_key")
    p_reject.add_argument("--reviewed-by", default="")
    p_reject.add_argument("--note", default="")

    p_archive = sub.add_parser("archive", help="Set proposal status archived")
    p_archive.add_argument("proposal_key")
    p_archive.add_argument("--reviewed-by", default="")
    p_archive.add_argument("--note", default="")

    return parser


def _cfg(args) -> SimpleNamespace:
    return SimpleNamespace(chat_agent_db_path=Path(args.db_path))


async def _run(args) -> dict:
    cfg = _cfg(args)
    status_by_cmd = {
        "approve": "approved",
        "reject": "rejected",
        "archive": "archived",
    }
    if args.cmd == "list":
        if args.all:
            rows = await list_chat_agent_skill_proposals(cfg, status=None, limit=args.limit)
        else:
            rows = await list_chat_agent_skill_proposals(cfg, status=args.status, limit=args.limit)
        return {"ok": True, "count": len(rows), "items": rows}

    if args.cmd == "show":
        row = await get_chat_agent_skill_proposal(cfg, str(args.proposal_key))
        return {"ok": bool(row), "item": row}

    if args.cmd == "propose":
        key = str(args.proposal_key or "").strip()
        if not _valid_key(key):
            raise ValueError("invalid proposal key: only [a-zA-Z0-9_.-] allowed")
        if key in RESERVED_KEYS:
            raise ValueError(f"Cannot use reserved builtin skill key: {key}")
        title = str(args.title or "").strip()
        description = str(args.description or "").strip()
        content = str(args.content or "").strip()
        intent_kinds = str(args.intent_kinds or "").strip()
        trigger_terms = str(args.trigger_terms or "").strip()
        if not content and not description:
            raise ValueError("content or description is required")
        if not intent_kinds and not trigger_terms:
            raise ValueError("intent-kinds or trigger-terms is required")
        if len(title) > 120:
            raise ValueError("title too long (>120)")
        if len(description) > 300:
            raise ValueError("description too long (>300)")
        if len(content) > 600:
            raise ValueError("content too long (>600)")
        try:
            priority = float(args.priority)
        except Exception as e:
            raise ValueError("invalid priority") from e
        try:
            confidence = float(args.confidence)
        except Exception as e:
            raise ValueError("invalid confidence") from e

        row = {
            "proposal_key": key,
            "title": title,
            "description": description,
            "intent_kinds": intent_kinds,
            "trigger_terms": trigger_terms,
            "negative_terms": str(args.negative_terms or "").strip(),
            "group_ids": str(args.group_ids or "").strip(),
            "priority": priority,
            "content": content,
            "source_type": str(args.source_type or "").strip(),
            "source_ref": str(args.source_ref or "").strip(),
            "confidence": confidence,
            "evidence_samples_json": list(args.sample or []),
            "status": "pending",
        }
        await upsert_chat_agent_skill_proposal(cfg, row)
        item = await get_chat_agent_skill_proposal(cfg, key)
        return {"ok": bool(item), "item": item}

    if args.cmd in status_by_cmd:
        status = status_by_cmd[args.cmd]
        changed = await set_chat_agent_skill_proposal_status(
            cfg,
            str(args.proposal_key),
            status,
            reviewed_by=str(args.reviewed_by or ""),
            review_note=str(args.note or ""),
        )
        item = await get_chat_agent_skill_proposal(cfg, str(args.proposal_key))
        return {"ok": changed, "item": item}

    return {"ok": False, "error": "unknown command"}


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    try:
        result = asyncio.run(_run(args))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except Exception as e:
        print(json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False, indent=2))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
