from __future__ import annotations

from collections.abc import Awaitable, Callable

try:
    from .knowledge_pack_manager import knowledge_pack_manager
except Exception:  # pragma: no cover
    from knowledge_pack_manager import knowledge_pack_manager


def parse_knowledge_command(prompt: str) -> dict | None:
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
    cmd = parse_knowledge_command(prompt)
    if not cmd:
        return None
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
    return None
