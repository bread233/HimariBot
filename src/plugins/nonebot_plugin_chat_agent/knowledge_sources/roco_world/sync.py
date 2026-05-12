from __future__ import annotations

import json
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
        }

    async def sync_from_records_jsonl(self, config, dry_run: bool = False) -> dict:
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
                        "content_hash": "",
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
                        "content_hash": "",
                        "source_path": entry["source_path"],
                        "source_url": entry["source_url"],
                        "chunk_index": 0,
                        "token_count": 0,
                        "embedding_json": "",
                        "metadata_json": entry["metadata_json"],
                        "enabled": 1,
                    }
                )

        if dry_run:
            return {
                "ok": True,
                "dry_run": True,
                "pack_key": self.pack_key,
                "records_count": count,
                "would_import_docs": len(doc_rows),
                "would_import_chunks": len(chunk_rows),
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
        return {
            "ok": True,
            "pack_key": self.pack_key,
            "records_count": count,
            "imported_docs": imported_docs,
            "imported_chunks": imported_chunks,
            "data_root": self.resolved_data_root(),
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
        limit: int | None = None,
        types: list[str] | None = None,
        base_url: str = "https://wiki.biligame.com/rocom",
    ) -> dict:
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
                "data_root": self.resolved_data_root(),
            }
        import_res = await self.sync_from_records_jsonl(config, dry_run=False)
        return {
            "ok": bool(import_res.get("ok", False)),
            "dry_run": False,
            "pack_key": self.pack_key,
            "records_count": int(source_res.get("records_count", 0) or 0),
            "records_file": str(self.paths.records_file),
            "asset": asset_res,
            "import": import_res,
            "data_root": self.resolved_data_root(),
        }
