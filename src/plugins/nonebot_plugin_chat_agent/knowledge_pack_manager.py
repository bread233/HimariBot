from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

try:
    from nonebot import logger
except Exception:  # pragma: no cover
    class _FallbackLogger:
        def info(self, *args, **kwargs):
            return None

        def warning(self, *args, **kwargs):
            return None

    logger = _FallbackLogger()

try:
    from .packs.roco_world import update_roco_world_pack
    from .storage import list_knowledge_chunks
except Exception:  # pragma: no cover
    from packs.roco_world import update_roco_world_pack
    from storage import list_knowledge_chunks


class KnowledgePackManager:
    def __init__(self) -> None:
        self._locks: dict[str, asyncio.Lock] = {}
        self._manifests: dict[str, dict] = {}
        self._background_tasks: set[asyncio.Task] = set()
        self._running: set[str] = set()

    def _manifest_root(self) -> Path:
        return Path("data/nonebot_chat_agent/knowledge_packs")

    def _get_lock(self, pack_key: str) -> asyncio.Lock:
        if pack_key not in self._locks:
            self._locks[pack_key] = asyncio.Lock()
        return self._locks[pack_key]

    def is_running(self, pack_key: str) -> bool:
        return pack_key in self._running or self._get_lock(pack_key).locked()

    def _load_manifest(self, manifest_path: Path) -> dict:
        text = manifest_path.read_text(encoding="utf-8-sig", errors="replace").lstrip("\ufeff")
        data = json.loads(text) if text.strip() else {}
        if not isinstance(data, dict):
            data = {}
        pack_key = str(data.get("pack_key") or manifest_path.parent.name).strip()
        return {
            "pack_key": pack_key,
            "title": str(data.get("title") or pack_key),
            "enabled": bool(data.get("enabled", True)),
            "auto_update_on_startup": bool(data.get("auto_update_on_startup", False)),
            "blocking_startup": bool(data.get("blocking_startup", False)),
            "source_type": str(data.get("source_type", "") or ""),
            "source_ref": str(data.get("source_ref", "") or ""),
            "online_source_url": str(data.get("online_source_url", "") or ""),
            "last_update_at": str(data.get("last_update_at", "") or ""),
            "last_import_at": str(data.get("last_import_at", "") or ""),
            "status": str(data.get("status", "unknown") or "unknown"),
            "manifest_path": str(manifest_path),
        }

    async def scan_manifests(self) -> dict[str, dict]:
        root = self._manifest_root()
        root.mkdir(parents=True, exist_ok=True)
        found: dict[str, dict] = {}
        for p in root.glob("*/manifest.json"):
            try:
                item = self._load_manifest(p)
            except Exception as e:
                logger.warning(f"knowledge_pack manifest read failed path={str(p)!r} error={str(e)[:200]!r}")
                continue
            pack_key = item["pack_key"]
            src = Path(item["source_ref"]).expanduser() if item.get("source_ref") else Path("")
            if pack_key == "roco_world":
                has_source = bool(src and src.exists())
                if not has_source and not item.get("online_source_url"):
                    item["status"] = "missing_resources"
                elif not has_source and item.get("online_source_url"):
                    item["status"] = "missing_local_source"
            found[pack_key] = item
        self._manifests = found
        return dict(found)

    async def startup_refresh(self, config) -> None:
        manifests = await self.scan_manifests()
        for pack_key, item in manifests.items():
            if not item.get("enabled", True):
                continue
            if not item.get("auto_update_on_startup", False):
                continue
            if pack_key != "roco_world":
                logger.info(f"knowledge_pack updater not implemented pack={pack_key}")
                continue
            if item.get("blocking_startup", False):
                await self.update_pack(config, pack_key, requested_by="startup", manifest_override=item)
            else:
                asyncio.create_task(self.update_pack(config, pack_key, requested_by="startup", manifest_override=item))

    async def get_status(self, config, pack_key: str | None = None) -> dict:
        manifests = await self.scan_manifests()
        if pack_key:
            x = manifests.get(pack_key)
            if not x:
                return {"ok": False, "error": "pack_not_found"}
            chunks = await list_knowledge_chunks(config, pack_key=pack_key, limit=500)
            x = dict(x)
            if self.is_running(pack_key):
                x["status"] = "running"
                x["running"] = 1
            else:
                x["running"] = 0
            x["chunks"] = len(chunks)
            return {"ok": True, "item": x}
        items = []
        for key, x in sorted(manifests.items(), key=lambda kv: kv[0]):
            chunks = await list_knowledge_chunks(config, pack_key=key, limit=500)
            y = dict(x)
            if self.is_running(key):
                y["status"] = "running"
                y["running"] = 1
            else:
                y["running"] = 0
            y["chunks"] = len(chunks)
            items.append(y)
        return {"ok": True, "items": items}

    async def update_pack(self, config, pack_key: str, requested_by: str = "", manifest_override: dict | None = None) -> dict:
        lock = self._get_lock(pack_key)
        if lock.locked():
            return {"ok": False, "status": "running", "pack_key": pack_key}
        async with lock:
            item = dict(manifest_override or {})
            if not item:
                manifests = await self.scan_manifests()
                item = manifests.get(pack_key) or {}
            if not item:
                return {"ok": False, "status": "not_found", "pack_key": pack_key}
            if pack_key != "roco_world":
                return {"ok": False, "status": "updater_not_implemented", "pack_key": pack_key}
            force_online_refresh = str(requested_by or "").strip().lower() != "startup"
            res = await update_roco_world_pack(config, item, force_online_refresh=force_online_refresh)
            now = datetime.now(timezone.utc).isoformat()
            res["last_update_at"] = now
            if res.get("ok"):
                res["last_import_at"] = now
            return res

    async def start_background_update(
        self,
        config,
        pack_key: str,
        requested_by: str = "",
        manifest_override: dict | None = None,
        notify_done=None,
    ) -> dict:
        lock = self._get_lock(pack_key)
        if self.is_running(pack_key):
            return {"ok": False, "status": "running", "pack_key": pack_key}
        self._running.add(pack_key)

        async def _runner() -> None:
            try:
                res = await self.update_pack(
                    config,
                    pack_key,
                    requested_by=requested_by,
                    manifest_override=manifest_override,
                )
                if notify_done is not None:
                    await notify_done(res)
            except Exception as e:
                if notify_done is not None:
                    await notify_done(
                        {
                            "ok": False,
                            "status": "failed",
                            "pack_key": pack_key,
                            "message": f"{type(e).__name__}:{str(e)[:200]}",
                        }
                    )
            finally:
                self._running.discard(pack_key)

        task = asyncio.create_task(_runner())
        self._background_tasks.add(task)
        task.add_done_callback(lambda t: self._background_tasks.discard(t))
        return {"ok": True, "status": "started", "pack_key": pack_key}


knowledge_pack_manager = KnowledgePackManager()
