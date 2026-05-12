from __future__ import annotations

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


async def handle_knowledge_command(config, event, prompt: str, superusers: set[str]) -> str | None:
    cmd = parse_knowledge_command(prompt)
    if not cmd:
        return None
    if cmd["cmd"] == "status":
        st = await knowledge_pack_manager.get_status(config, cmd.get("pack_key") or None)
        if not st.get("ok"):
            return f"pack not found: {cmd.get('pack_key','')}"
        if "item" in st:
            x = st["item"]
            return f"{x.get('pack_key','')} | status={x.get('status','')} | chunks={x.get('chunks',0)} | last_update_at={x.get('last_update_at','')}"
        items = st.get("items", [])
        if not items:
            return "no knowledge packs found"
        lines = [
            f"{x.get('pack_key','')} | status={x.get('status','')} | chunks={x.get('chunks',0)} | last_update_at={x.get('last_update_at','')}"
            for x in items[:20]
        ]
        return "\n".join(lines)
    if cmd["cmd"] == "update":
        if not _is_admin_or_superuser(event, superusers):
            return "\u4ec5\u8d85\u7ea7\u7ba1\u7406\u5458\u6216\u7fa4\u7ba1\u7406\u5458\u53ef\u6267\u884c\u77e5\u8bc6\u5e93\u66f4\u65b0\u3002"
        pack_key = str(cmd.get("pack_key") or "").strip()
        if not pack_key:
            return "pack not found"
        res = await knowledge_pack_manager.update_pack(config, pack_key, requested_by=str(getattr(event, "user_id", "")))
        if res.get("status") == "running":
            return "\u6b63\u5728\u66f4\u65b0"
        if not res.get("ok"):
            if res.get("status") == "missing_resources":
                return str(res.get("message") or "\u7f3a\u5c11\u672c\u5730\u6e90\u6570\u636e\uff0cP4o-4 \u5c06\u652f\u6301\u5728\u7ebf\u4e0b\u8f7d/\u722c\u53d6\u3002")
            if res.get("status") == "not_found":
                return "pack not found"
            if res.get("status") == "updater_not_implemented":
                return "updater not implemented"
            return "update failed"
        return (
            f"ok pack={res.get('pack_key','')} docs={res.get('imported_docs',0)} "
            f"chunks={res.get('imported_chunks',0)} assets={res.get('imported_assets',0)}"
        )
    return None
