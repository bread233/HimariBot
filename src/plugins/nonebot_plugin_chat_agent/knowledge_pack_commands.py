from __future__ import annotations

from collections.abc import Awaitable, Callable
from shlex import split as shlex_split

try:
    from .knowledge_pack_manager import knowledge_pack_manager
    from .knowledge_sources.roco_world.sync import RocoWorldSyncService
except Exception:  # pragma: no cover
    from knowledge_pack_manager import knowledge_pack_manager
    from knowledge_sources.roco_world.sync import RocoWorldSyncService


def _is_group_at_bot(event) -> bool:
    try:
        fn = getattr(event, "is_tome", None)
        if callable(fn):
            return bool(fn())
    except Exception:
        pass
    return bool(getattr(event, "to_me", False))


def _parse_roco_sync_args(arg_text: str) -> dict:
    out = {
        "cmd": "roco_sync",
        "dry_run": False,
        "embed_changed": False,
        "limit": None,
        "embedding_limit": None,
        "types": None,
    }
    unknown: list[str] = []
    tokens = shlex_split(arg_text or "")
    i = 0
    while i < len(tokens):
        t = str(tokens[i] or "").strip()
        if t == "--dry-run":
            out["dry_run"] = True
            i += 1
            continue
        if t == "--embed":
            out["embed_changed"] = True
            i += 1
            continue
        if t == "--all-confirm":
            out["all_confirm"] = True
            i += 1
            continue
        if t in {"--limit", "--embedding-limit", "--types"}:
            if i + 1 >= len(tokens):
                return {"cmd": "roco_error", "error": f"missing value for {t}"}
            v = str(tokens[i + 1] or "").strip()
            if t == "--types":
                vals = [x.strip().lower() for x in v.split(",") if x.strip()]
                out["types"] = vals or None
            else:
                try:
                    n = int(v)
                except Exception:
                    return {"cmd": "roco_error", "error": f"invalid integer for {t}: {v}"}
                if n <= 0:
                    return {"cmd": "roco_error", "error": f"invalid value for {t}: {v}"}
                if t == "--limit":
                    out["limit"] = n
                else:
                    out["embedding_limit"] = n
            i += 2
            continue
        unknown.append(t)
        i += 1
    if unknown:
        return {"cmd": "roco_error", "error": "unknown argument(s): " + " ".join(unknown)}
    return out


def parse_knowledge_command(prompt: str, event=None) -> dict | None:
    text = str(prompt or "").strip()
    if not text:
        return None
    if text == "\u77e5\u8bc6\u5e93\u72b6\u6001":
        return {"cmd": "status", "pack_key": ""}
    if text.startswith("\u77e5\u8bc6\u5e93\u72b6\u6001 "):
        return {"cmd": "status", "pack_key": text.split(" ", 1)[1].strip()}
    if text.startswith("\u77e5\u8bc6\u5e93\u66f4\u65b0 "):
        return {"cmd": "update", "pack_key": text.split(" ", 1)[1].strip()}
    if text == "\u6d1b\u514b\u738b\u56fd\u4e16\u754c\u6570\u636e\u66f4\u65b0":
        return {"cmd": "update", "pack_key": "roco_world"}

    if text.startswith("/chatagent_knowledge "):
        body = text[len("/chatagent_knowledge ") :].strip()
        if body == "roco status":
            return {"cmd": "roco_status"}
        if body.startswith("roco sync"):
            args = body[len("roco sync") :].strip()
            return _parse_roco_sync_args(args)
        return None

    # Chinese alias (group requires @bot)
    if text.startswith("\u6d1b\u514b\u738b\u56fd"):
        is_group = bool(getattr(event, "group_id", None))
        if is_group and not _is_group_at_bot(event):
            return None
        body = text[len("\u6d1b\u514b\u738b\u56fd") :].strip()
        if body == "status":
            return {"cmd": "roco_status"}
        if body.startswith("\u66f4\u65b0"):
            args = body[len("\u66f4\u65b0") :].strip()
            return _parse_roco_sync_args(args)
        return {"cmd": "roco_error", "error": "usage: 洛克王国 status | 洛克王国 更新 [--dry-run] [--limit N] [--embed] [--embedding-limit N] [--types a,b]"}
    return None


def _is_admin_or_superuser(event, superusers: set[str]) -> bool:
    uid = str(getattr(event, "user_id", "") or "")
    if uid and uid in superusers:
        return True
    role = str(getattr(getattr(event, "sender", None), "role", "") or "")
    if role in {"admin", "owner"}:
        return True
    return False


async def handle_knowledge_command(
    config,
    event,
    prompt: str,
    superusers: set[str],
    notify_start: Callable[[str], Awaitable[None]] | None = None,
    notify_done: Callable[[str], Awaitable[None]] | None = None,
) -> str | None:
    cmd = parse_knowledge_command(prompt, event=event)
    if not cmd:
        return None
    if cmd["cmd"] == "roco_error":
        return str(cmd.get("error") or "invalid roco command")
    if cmd["cmd"] == "status":
        st = await knowledge_pack_manager.get_status(config, cmd.get("pack_key") or None)
        if not st.get("ok"):
            return f"pack not found: {cmd.get('pack_key','')}"
        if "item" in st:
            x = st["item"]
            return (
                f"{x.get('pack_key','')} | status={x.get('status','')} | running={x.get('running',0)} "
                f"| chunks={x.get('chunks',0)} | last_update_at={x.get('last_update_at','')}"
            )
        items = st.get("items", [])
        if not items:
            return "no knowledge packs found"
        lines = [
            f"{x.get('pack_key','')} | status={x.get('status','')} | running={x.get('running',0)} "
            f"| chunks={x.get('chunks',0)} | last_update_at={x.get('last_update_at','')}"
            for x in items[:20]
        ]
        return "\n".join(lines)
    if cmd["cmd"] == "update":
        if not _is_admin_or_superuser(event, superusers):
            return "\u4ec5\u8d85\u7ea7\u7ba1\u7406\u5458\u6216\u7fa4\u7ba1\u7406\u5458\u53ef\u6267\u884c\u77e5\u8bc6\u5e93\u66f4\u65b0\u3002"
        pack_key = str(cmd.get("pack_key") or "").strip()
        if not pack_key:
            return "pack not found"
        st = await knowledge_pack_manager.get_status(config, pack_key)
        if not st.get("ok"):
            return "pack not found"
        if knowledge_pack_manager.is_running(pack_key):
            return "\u6b63\u5728\u66f4\u65b0"
        start_tip = "\u5f00\u59cb\u66f4\u65b0\u6d1b\u514b\u738b\u56fd\u4e16\u754c\u6570\u636e\uff0c\u8bf7\u7a0d\u7b49\u2026\u2026"
        if notify_start is not None:
            await notify_start(start_tip)
        async def _notify_result(res: dict) -> None:
            if notify_done is None:
                return
            if not res.get("ok"):
                msg = str(res.get("message") or res.get("status") or "update failed")
                await notify_done(f"\u66f4\u65b0\u5931\u8d25\uff1apack={res.get('pack_key','')} status={res.get('status','failed')} {msg}")
                return
            await notify_done(
                f"\u66f4\u65b0\u5b8c\u6210\uff1aok pack={res.get('pack_key','')} docs={res.get('imported_docs',0)} "
                f"chunks={res.get('imported_chunks',0)} assets={res.get('imported_assets',0)} "
                f"update_source={res.get('update_source','')} records_count={res.get('records_count',0)} "
                f"pet={res.get('pet_count',0)} skill={res.get('skill_count',0)} item={res.get('item_count',0)} "
                f"egg={res.get('egg_count',0)} furniture={res.get('furniture_count',0)}"
            )

        started = await knowledge_pack_manager.start_background_update(
            config,
            pack_key,
            requested_by=str(getattr(event, "user_id", "")),
            notify_done=_notify_result,
        )
        if started.get("status") == "running":
            return "\u6b63\u5728\u66f4\u65b0"
        if not started.get("ok"):
            return "update failed"
        return "\u5df2\u5f00\u59cb\u540e\u53f0\u66f4\u65b0\u6d1b\u514b\u738b\u56fd\u4e16\u754c\u6570\u636e\uff0c\u8bf7\u7a0d\u540e\u67e5\u770b\u7ed3\u679c\u3002"
    if cmd["cmd"] == "roco_status":
        if not _is_admin_or_superuser(event, superusers):
            return "\u4ec5\u8d85\u7ea7\u7ba1\u7406\u5458\u6216\u7fa4\u7ba1\u7406\u5458\u53ef\u67e5\u770b roco \u540c\u6b65\u72b6\u6001\u3002"
        svc = RocoWorldSyncService()
        st = await svc.status()
        return (
            f"roco status | pack_key={st.get('pack_key','')} | data_root={st.get('data_root','')} "
            f"| records_file_exists={int(bool(st.get('records_file_exists', False)))} "
            f"| state_file_exists={int(bool(st.get('state_file_exists', False)))} | state={st.get('state', {})}"
        )
    if cmd["cmd"] == "roco_sync":
        if not _is_admin_or_superuser(event, superusers):
            return "\u4ec5\u8d85\u7ea7\u7ba1\u7406\u5458\u6216\u7fa4\u7ba1\u7406\u5458\u53ef\u6267\u884c roco \u540c\u6b65\u3002"
        dry_run = bool(cmd.get("dry_run", False))
        limit = cmd.get("limit")
        all_confirm = bool(cmd.get("all_confirm", False))
        if (not dry_run) and (limit is None) and (not all_confirm):
            return (
                "拒绝裸 sync：请使用 --dry-run 或 --limit N；"
                "全量执行需显式 --all-confirm。"
            )
        svc = RocoWorldSyncService()
        out = await svc.sync_source(
            config,
            dry_run=dry_run,
            limit=limit,
            types=cmd.get("types"),
            embed_changed=bool(cmd.get("embed_changed", False)),
            embedding_limit=cmd.get("embedding_limit"),
        )
        if str(out.get("status") or "") == "busy":
            running = dict(out.get("running") or {})
            return (
                f"roco sync | ok=0 | status=busy | message={out.get('message','roco sync is already running')} "
                f"| action={running.get('action','')} | started_at={running.get('started_at','')}"
            )
        emb = dict(out.get("embedding") or {})
        asset = dict(out.get("asset") or {})
        imp = dict(out.get("import") or {})
        failed_cnt = len(asset.get("failed") or [])
        return (
            f"roco sync | ok={int(bool(out.get('ok', False)))} | dry_run={int(bool(out.get('dry_run', False)))} "
            f"| records_count={out.get('records_count',0)} "
            f"| asset.total_assets={asset.get('total_assets',0)} | asset.existing_count={asset.get('existing_count',0)} "
            f"| asset.skipped_existing_count={asset.get('skipped_existing_count',0)} "
            f"| asset.missing_count={asset.get('missing_count',0)} | asset.would_download_count={asset.get('would_download_count',0)} "
            f"| asset.downloaded_count={asset.get('downloaded_count',0)} | asset.saved_count={asset.get('saved_count',0)} "
            f"| asset.failed_count={failed_cnt} "
            f"| import.imported_docs={imp.get('imported_docs',0)} | import.imported_chunks={imp.get('imported_chunks',0)} "
            f"| would_import_docs={out.get('would_import_docs',0)} | would_import_chunks={out.get('would_import_chunks',0)} "
            f"| embedding.enabled={int(bool(emb.get('enabled', False)))} | embedding.changed_chunk_count={emb.get('changed_chunk_count',0)} "
            f"| embedding.embedded_count={emb.get('embedded_count',0)} | embedding.would_embed_count={emb.get('would_embed_count',0)} "
            f"| embedding.failed_count={emb.get('failed_count',0)} "
            f"| records_file={out.get('records_file','')} | data_root={out.get('data_root','')}"
        )
    return None
