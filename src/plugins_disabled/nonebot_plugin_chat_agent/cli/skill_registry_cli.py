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
        get_chat_agent_skill,
        init_storage,
        list_chat_agent_skills,
        set_chat_agent_skill_enabled,
        upsert_chat_agent_skill,
    )
else:
    from ..stores.storage import (
        get_chat_agent_skill,
        init_storage,
        list_chat_agent_skills,
        set_chat_agent_skill_enabled,
        upsert_chat_agent_skill,
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Chat agent manual skill registry CLI")
    parser.add_argument("--db-path", required=True, help="SQLite DB path")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_list = sub.add_parser("list", help="List skills")
    p_list.add_argument("--all", action="store_true", help="Include disabled rows")

    p_show = sub.add_parser("show", help="Show one skill by key")
    p_show.add_argument("key")

    p_add = sub.add_parser("add", help="Add or update a manual DB skill")
    p_add.add_argument("--key", required=True)
    p_add.add_argument("--title", default="")
    p_add.add_argument("--description", default="")
    p_add.add_argument("--intent-kinds", default="")
    p_add.add_argument("--trigger-terms", default="")
    p_add.add_argument("--negative-terms", default="")
    p_add.add_argument("--group-ids", default="")
    p_add.add_argument("--priority", required=True)
    p_add.add_argument("--content", default="")
    p_add.add_argument("--disabled", action="store_true")

    p_disable = sub.add_parser("disable", help="Disable one skill by key")
    p_disable.add_argument("key")

    p_enable = sub.add_parser("enable", help="Enable one skill by key")
    p_enable.add_argument("key")
    return parser


def _build_config(args) -> SimpleNamespace:
    return SimpleNamespace(chat_agent_db_path=Path(args.db_path))


async def _run(args) -> dict:
    cfg = _build_config(args)
    await init_storage(cfg)

    if args.cmd == "list":
        rows = await list_chat_agent_skills(cfg, include_disabled=bool(args.all))
        return {"ok": True, "count": len(rows), "items": rows}

    if args.cmd == "show":
        row = await get_chat_agent_skill(cfg, str(args.key))
        return {"ok": bool(row), "item": row}

    if args.cmd == "disable":
        changed = await set_chat_agent_skill_enabled(cfg, str(args.key), False)
        return {"ok": changed, "key": str(args.key), "enabled": 0}

    if args.cmd == "enable":
        changed = await set_chat_agent_skill_enabled(cfg, str(args.key), True)
        return {"ok": changed, "key": str(args.key), "enabled": 1}

    if args.cmd == "add":
        key = str(args.key or "").strip()
        if not _valid_key(key):
            raise ValueError("invalid key: only [a-zA-Z0-9_.-] allowed")
        if key in RESERVED_KEYS:
            raise ValueError(f"Cannot use reserved builtin skill key: {key}")
        title = str(args.title or "").strip()
        description = str(args.description or "").strip()
        intent_kinds = str(args.intent_kinds or "").strip()
        trigger_terms = str(args.trigger_terms or "").strip()
        negative_terms = str(args.negative_terms or "").strip()
        group_ids = str(args.group_ids or "").strip()
        content = str(args.content or "").strip()
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

        row = {
            "key": key,
            "title": title,
            "description": description,
            "intent_kinds": intent_kinds,
            "trigger_terms": trigger_terms,
            "negative_terms": negative_terms,
            "group_ids": group_ids,
            "priority": priority,
            "content": content,
            "enabled": 0 if bool(args.disabled) else 1,
        }
        await upsert_chat_agent_skill(cfg, row)
        item = await get_chat_agent_skill(cfg, key)
        return {"ok": bool(item), "item": item}

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
