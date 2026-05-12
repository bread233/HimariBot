from __future__ import annotations

import asyncio
import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .normalizer import normalize_record_to_entry
from .paths import RocoWorldPaths, get_roco_world_paths
from .assets import RocoWorldAssetManager
from .downloader import sync_roco_source_to_records

try:
    from ...storage import upsert_knowledge_pack, upsert_knowledge_documents, upsert_knowledge_chunks
except Exception:  # pragma: no cover
    from storage import upsert_knowledge_pack, upsert_knowledge_documents, upsert_knowledge_chunks


class RocoWorldSyncService:
    _sync_lock: asyncio.Lock = asyncio.Lock()
    _running_meta: dict = {}

    def __init__(self, data_root: Path | None = None, pack_key: str = "roco_world") -> None:
        self.paths: RocoWorldPaths = get_roco_world_paths(data_root)
        self.pack_key = str(pack_key or "roco_world").strip()

    def resolved_data_root(self) -> str:
        return str(self.paths.root.resolve())

    async def status(self) -> dict:
        state = {}
        if self.paths.state_file.exists():
            try:
                state = json.loads(self.paths.state_file.read_text(encoding="utf-8-sig", errors="replace").lstrip("\ufeff") or "{}")
            except Exception:
                state = {}
        return {
            "ok": True,
            "pack_key": self.pack_key,
            "data_root": self.resolved_data_root(),
            "records_file_exists": self.paths.records_file.exists(),
            "state_file_exists": self.paths.state_file.exists(),
            "state": state,
            "running": bool(self.__class__._running_meta),
            "running_meta": dict(self.__class__._running_meta or {}),
        }

    @classmethod
    def get_running_meta(cls) -> dict:
        return dict(cls._running_meta or {})

    async def _acquire_sync_lock(self, *, action: str, dry_run: bool, limit: int | None, types: list[str] | None, embed_changed: bool, embedding_limit: int | None) -> dict | None:
        cls = self.__class__
        if cls._sync_lock.locked():
            return {
                "ok": False,
                "status": "busy",
                "message": "roco sync is already running",
                "running": cls.get_running_meta(),
                "pack_key": self.pack_key,
                "data_root": self.resolved_data_root(),
            }
        await cls._sync_lock.acquire()
        cls._running_meta = {
            "action": action,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "dry_run": bool(dry_run),
            "limit": int(limit) if isinstance(limit, int) else None,
            "types": list(types or []),
            "embed_changed": bool(embed_changed),
            "embedding_limit": int(embedding_limit) if isinstance(embedding_limit, int) else None,
        }
        return None

    @classmethod
    def _release_sync_lock(cls) -> None:
        cls._running_meta = {}
        if cls._sync_lock.locked():
            cls._sync_lock.release()

    async def sync_from_records_jsonl(
        self,
        config,
        dry_run: bool = False,
        *,
        embed_changed: bool = False,
        embedding_limit: int | None = None,
    ) -> dict:
        self.paths.source_dir.mkdir(parents=True, exist_ok=True)
        self.paths.assets_dir.mkdir(parents=True, exist_ok=True)
        if not self.paths.records_file.exists():
            return {
                "ok": False,
                "dry_run": bool(dry_run),
                "status": "missing_records",
                "records_file": str(self.paths.records_file),
                "data_root": self.resolved_data_root(),
            }

        doc_rows: list[dict] = []
        chunk_rows: list[dict] = []
        count = 0
        with self.paths.records_file.open("r", encoding="utf-8-sig", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    raw = json.loads(line)
                except Exception:
                    continue
                entry = normalize_record_to_entry(raw, pack_key=self.pack_key)
                if not entry["title"] or not entry["content"]:
                    continue
                count += 1
                doc_rows.append(
                    {
                        "pack_key": self.pack_key,
                        "doc_key": entry["doc_key"],
                        "title": entry["title"],
                        "source_path": entry["source_path"],
                        "source_url": entry["source_url"],
                        "source_type": "knowledge_source_roco_world",
                        "content_hash": hashlib.sha256(entry["content"].encode("utf-8", errors="ignore")).hexdigest(),
                        "metadata_json": entry["metadata_json"],
                        "enabled": 1,
                    }
                )
                chunk_rows.append(
                    {
                        "pack_key": self.pack_key,
                        "doc_key": entry["doc_key"],
                        "chunk_key": f"{entry['doc_key']}:0",
                        "title": entry["title"],
                        "section": entry["category"],
                        "content": entry["content"],
                        "content_hash": hashlib.sha256(entry["content"].encode("utf-8", errors="ignore")).hexdigest(),
                        "source_path": entry["source_path"],
                        "source_url": entry["source_url"],
                        "chunk_index": 0,
                        "token_count": 0,
                        "embedding_json": "",
                        "metadata_json": entry["metadata_json"],
                        "enabled": 1,
                    }
                )

        existing_map = self._load_existing_chunk_state(config, [str(x.get("chunk_key", "") or "") for x in chunk_rows])
        for row in chunk_rows:
            ck = str(row.get("chunk_key", "") or "")
            old = existing_map.get(ck) or {}
            if not old:
                continue
            if str(old.get("content_hash", "") or "") == str(row.get("content_hash", "") or ""):
                old_emb = str(old.get("embedding_json", "") or "")
                if old_emb:
                    row["embedding_json"] = old_emb
        embedding_plan = self._build_embedding_plan(chunk_rows, existing_map, embedding_limit=embedding_limit)

        if dry_run:
            return {
                "ok": True,
                "dry_run": True,
                "pack_key": self.pack_key,
                "records_count": count,
                "would_import_docs": len(doc_rows),
                "would_import_chunks": len(chunk_rows),
                "embedding": (
                    await self.embed_changed_knowledge_chunks(
                        config,
                        chunk_rows,
                        dry_run=True,
                        embedding_limit=embedding_limit,
                    )
                    if embed_changed
                    else {
                        "enabled": False,
                        "dry_run": True,
                        "changed_chunk_count": int(embedding_plan.get("changed_chunk_count", 0) or 0),
                        "would_embed_count": 0,
                        "embedded_count": 0,
                        "skipped_unchanged_count": int(embedding_plan.get("skipped_unchanged_count", 0) or 0),
                        "failed_count": 0,
                        "failed": [],
                    }
                ),
                "data_root": self.resolved_data_root(),
            }

        await upsert_knowledge_pack(
            config,
            {
                "pack_key": self.pack_key,
                "title": "roco world wiki",
                "description": "roco world local source sync skeleton",
                "source_type": "knowledge_source_roco_world",
                "source_ref": str(self.paths.records_file),
                "enabled": 1,
                "metadata_json": "{}",
            },
        )
        imported_docs = await upsert_knowledge_documents(config, doc_rows)
        imported_chunks = await upsert_knowledge_chunks(config, chunk_rows)
        now = datetime.now(timezone.utc).isoformat()
        self.paths.state_file.write_text(
            json.dumps(
                {
                    "status": "ok",
                    "last_sync_at": now,
                    "records_file": str(self.paths.records_file),
                    "records_count": count,
                    "imported_docs": imported_docs,
                    "imported_chunks": imported_chunks,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        embedding_res = (
            await self.embed_changed_knowledge_chunks(
                config,
                chunk_rows,
                dry_run=False,
                embedding_limit=embedding_limit,
            )
            if embed_changed
            else {
                "enabled": False,
                "dry_run": False,
                "changed_chunk_count": int(embedding_plan.get("changed_chunk_count", 0) or 0),
                "would_embed_count": 0,
                "embedded_count": 0,
                "skipped_unchanged_count": int(embedding_plan.get("skipped_unchanged_count", 0) or 0),
                "failed_count": 0,
                "failed": [],
            }
        )
        return {
            "ok": True,
            "pack_key": self.pack_key,
            "records_count": count,
            "imported_docs": imported_docs,
            "imported_chunks": imported_chunks,
            "embedding": embedding_res,
            "data_root": self.resolved_data_root(),
        }

    def _load_existing_chunk_state(self, config, chunk_keys: list[str]) -> dict[str, dict]:
        db_path = Path(getattr(config, "chat_agent_db_path", "") or "")
        if not db_path.exists():
            return {}
        keys = [str(x or "").strip() for x in chunk_keys if str(x or "").strip()]
        if not keys:
            return {}
        conn = sqlite3.connect(db_path)
        try:
            out: dict[str, dict] = {}
            batch = 200
            for i in range(0, len(keys), batch):
                part = keys[i : i + batch]
                holders = ",".join(["?"] * len(part))
                rows = conn.execute(
                    f"SELECT chunk_key, content_hash, embedding_json FROM chat_agent_knowledge_chunks WHERE chunk_key IN ({holders})",
                    part,
                ).fetchall()
                for r in rows:
                    out[str(r[0])] = {
                        "content_hash": str(r[1] or ""),
                        "embedding_json": str(r[2] or ""),
                    }
            return out
        finally:
            conn.close()

    def _build_embedding_plan(self, chunk_rows: list[dict], existing_map: dict[str, dict], embedding_limit: int | None) -> dict:
        changed: list[dict] = []
        for row in chunk_rows:
            ck = str(row.get("chunk_key", "") or "")
            if not ck:
                continue
            old = existing_map.get(ck)
            new_hash = str(row.get("content_hash", "") or "")
            if old is None:
                changed.append(row)
                continue
            old_hash = str(old.get("content_hash", "") or "")
            old_emb = str(old.get("embedding_json", "") or "").strip()
            if (not old_hash) or old_hash != new_hash or (not old_emb):
                changed.append(row)
        if isinstance(embedding_limit, int) and embedding_limit > 0:
            changed = changed[: int(embedding_limit)]
        return {
            "changed_rows": changed,
            "changed_chunk_count": len(changed),
            "skipped_unchanged_count": max(0, len(chunk_rows) - len(changed)),
        }

    async def embed_changed_knowledge_chunks(
        self,
        config,
        chunk_rows: list[dict],
        *,
        dry_run: bool = False,
        embedding_limit: int | None = None,
    ) -> dict:
        existing_map = self._load_existing_chunk_state(config, [str(x.get("chunk_key", "") or "") for x in chunk_rows])
        plan = self._build_embedding_plan(chunk_rows, existing_map, embedding_limit)
        changed_rows = list(plan.get("changed_rows") or [])
        if dry_run:
            return {
                "enabled": True,
                "dry_run": True,
                "changed_chunk_count": int(plan.get("changed_chunk_count", 0) or 0),
                "would_embed_count": int(plan.get("changed_chunk_count", 0) or 0),
                "embedded_count": 0,
                "skipped_unchanged_count": int(plan.get("skipped_unchanged_count", 0) or 0),
                "failed_count": 0,
                "failed": [],
            }
        if not changed_rows:
            return {
                "enabled": True,
                "dry_run": False,
                "changed_chunk_count": 0,
                "would_embed_count": 0,
                "embedded_count": 0,
                "skipped_unchanged_count": int(plan.get("skipped_unchanged_count", 0) or 0),
                "failed_count": 0,
                "failed": [],
            }
        failed: list[dict] = []
        embedded = 0
        try:
            try:
                from ... import embedding_client  # type: ignore
            except Exception:
                import embedding_client  # type: ignore
            items = [{"source": "knowledge_pack", "content": str(x.get("content", "") or "")} for x in changed_rows]
            vecs = await embedding_client.embed_texts_with_cache(config, items)
            patch_rows = []
            for i, row in enumerate(changed_rows):
                vec = vecs[i] if i < len(vecs) else []
                if not vec:
                    failed.append({"chunk_key": str(row.get("chunk_key", "") or ""), "error": "empty_embedding"})
                    continue
                patch = dict(row)
                patch["embedding_json"] = json.dumps([float(x) for x in vec], ensure_ascii=False)
                patch_rows.append(patch)
            if patch_rows:
                await upsert_knowledge_chunks(config, patch_rows)
                embedded = len(patch_rows)
        except Exception as e:
            failed.append({"chunk_key": "*batch*", "error": f"{type(e).__name__}:{str(e)[:200]}"})
        return {
            "enabled": True,
            "dry_run": False,
            "changed_chunk_count": int(plan.get("changed_chunk_count", 0) or 0),
            "would_embed_count": 0,
            "embedded_count": int(embedded),
            "skipped_unchanged_count": int(plan.get("skipped_unchanged_count", 0) or 0),
            "failed_count": len(failed),
            "failed": failed,
        }

    async def fix_missing_assets_from_records(self, dry_run: bool = True) -> dict:
        self.paths.source_dir.mkdir(parents=True, exist_ok=True)
        self.paths.assets_dir.mkdir(parents=True, exist_ok=True)
        if not self.paths.records_file.exists():
            return {
                "ok": False,
                "dry_run": bool(dry_run),
                "status": "missing_records",
                "records_file": str(self.paths.records_file),
                "data_root": self.resolved_data_root(),
            }
        rows: list[dict] = []
        with self.paths.records_file.open("r", encoding="utf-8-sig", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except Exception:
                    continue
        mgr = RocoWorldAssetManager(self.paths)
        out = mgr.fix_missing_assets(rows, dry_run=dry_run)
        out["pack_key"] = self.pack_key
        out["data_root"] = self.resolved_data_root()
        return out

    async def sync_source(
        self,
        config,
        *,
        dry_run: bool = True,
        embed_changed: bool = False,
        embedding_limit: int | None = None,
        limit: int | None = None,
        types: list[str] | None = None,
        base_url: str = "https://wiki.biligame.com/rocom",
    ) -> dict:
        busy = await self._acquire_sync_lock(
            action="sync_source",
            dry_run=dry_run,
            limit=limit,
            types=types,
            embed_changed=embed_changed,
            embedding_limit=embedding_limit,
        )
        if busy:
            return busy
        try:
            source_res = await sync_roco_source_to_records(
                paths=self.paths,
                base_url=base_url,
                timeout=20.0,
                limit=limit,
                types=types,
                download_images=False,
            )
            if not source_res.get("ok"):
                return {
                    "ok": False,
                    "status": source_res.get("status", "source_failed"),
                    "source": source_res,
                    "pack_key": self.pack_key,
                    "data_root": self.resolved_data_root(),
                }
            asset_res = await self.fix_missing_assets_from_records(dry_run=dry_run)
            if dry_run:
                embedding_res = {"enabled": False, "dry_run": True, "changed_chunk_count": 0, "would_embed_count": 0, "embedded_count": 0, "skipped_unchanged_count": 0, "failed_count": 0, "failed": []}
                if embed_changed:
                    embedding_res = await self.sync_from_records_jsonl(config, dry_run=True, embed_changed=True, embedding_limit=embedding_limit)
                    embedding_res = embedding_res.get("embedding", embedding_res)
                return {
                    "ok": True,
                    "dry_run": True,
                    "pack_key": self.pack_key,
                    "records_count": int(source_res.get("records_count", 0) or 0),
                    "valid_entity_assets": int(source_res.get("valid_entity_assets", 0) or 0),
                    "rejected_generic_assets": int(source_res.get("rejected_generic_assets", 0) or 0),
                    "unresolved_image_refs": int(source_res.get("unresolved_image_refs", 0) or 0),
                    "entity_img_candidates_checked": int(source_res.get("entity_img_candidates_checked", 0) or 0),
                    "entity_img_candidates_accepted": int(source_res.get("entity_img_candidates_accepted", 0) or 0),
                    "entity_img_candidates_rejected": int(source_res.get("entity_img_candidates_rejected", 0) or 0),
                    "records_file": str(self.paths.records_file),
                    "asset": asset_res,
                    "embedding": embedding_res,
                    "data_root": self.resolved_data_root(),
                }
            import_res = await self.sync_from_records_jsonl(config, dry_run=False, embed_changed=embed_changed, embedding_limit=embedding_limit)
            return {
                "ok": bool(import_res.get("ok", False)),
                "dry_run": False,
                "pack_key": self.pack_key,
                "records_count": int(source_res.get("records_count", 0) or 0),
                "records_file": str(self.paths.records_file),
                "asset": asset_res,
                "import": import_res,
                "embedding": import_res.get("embedding", {}),
                "data_root": self.resolved_data_root(),
            }
        finally:
            self.__class__._release_sync_lock()
