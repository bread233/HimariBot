import argparse
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

if __package__ in (None, ""):
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from storage import init_storage, list_knowledge_packs, list_knowledge_chunks, delete_knowledge_pack
    from knowledge_pack import import_knowledge_path, search_knowledge_pack
else:
    from .storage import init_storage, list_knowledge_packs, list_knowledge_chunks, delete_knowledge_pack
    from .knowledge_pack import import_knowledge_path, search_knowledge_pack


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Knowledge pack CLI")
    p.add_argument("--db-path", required=True)
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("import")
    s.add_argument("--pack", required=True)
    s.add_argument("--path", required=True)
    s.add_argument("--title", default="")
    s.add_argument("--description", default="")
    s.add_argument("--source-type", default="manual")
    s = sub.add_parser("list")
    s.add_argument("--all", action="store_true")
    s = sub.add_parser("chunks")
    s.add_argument("--pack", default="")
    s.add_argument("--limit", type=int, default=20)
    s = sub.add_parser("search")
    s.add_argument("--query", required=True)
    s.add_argument("--pack", default="")
    s.add_argument("--limit", type=int, default=5)
    s = sub.add_parser("delete")
    s.add_argument("--pack", required=True)
    return p


async def _run(args: argparse.Namespace) -> dict:
    cfg = SimpleNamespace(chat_agent_db_path=Path(args.db_path))
    await init_storage(cfg)
    if args.cmd == "import":
        return await import_knowledge_path(cfg, args.pack, args.path, title=args.title, description=args.description, source_type=args.source_type)
    if args.cmd == "list":
        rows = await list_knowledge_packs(cfg, include_disabled=bool(args.all))
        return {"ok": True, "count": len(rows), "items": rows}
    if args.cmd == "chunks":
        rows = await list_knowledge_chunks(cfg, pack_key=(args.pack or None), limit=int(args.limit))
        return {"ok": True, "count": len(rows), "items": rows}
    if args.cmd == "search":
        rows = await search_knowledge_pack(cfg, args.query, pack_key=(args.pack or None), limit=int(args.limit), min_score=0.25)
        return {"ok": True, "count": len(rows), "items": rows}
    if args.cmd == "delete":
        n = await delete_knowledge_pack(cfg, args.pack)
        return {"ok": True, "deleted": int(n)}
    return {"ok": False, "error": "unknown command"}


def main() -> int:
    args = _build_parser().parse_args()
    try:
        out = asyncio.run(_run(args))
        print(json.dumps(out, ensure_ascii=True))
        return 0 if out.get("ok") else 1
    except Exception as e:
        print(json.dumps({"ok": False, "error": str(e)}, ensure_ascii=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
