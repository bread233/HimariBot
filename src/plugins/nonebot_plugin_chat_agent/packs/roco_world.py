from __future__ import annotations

import logging
from pathlib import Path
import json
import shutil
from datetime import datetime, timezone

try:
    from ..roco_world_importer import import_roco_world_pack
    from ..roco_world_crawler import RocoCrawlerConfig, crawl_roco_world_source
except Exception:  # pragma: no cover
    from roco_world_importer import import_roco_world_pack
    from roco_world_crawler import RocoCrawlerConfig, crawl_roco_world_source

logger = logging.getLogger("nonebot_plugin_chat_agent.roco_world")


async def update_roco_world_pack(config, manifest: dict, force_online_refresh: bool = False) -> dict:
    pack_key = str(manifest.get("pack_key") or "roco_world").strip()
    source_ref = str(manifest.get("source_ref") or "").strip()
    manifest_path = Path(str(manifest.get("manifest_path") or "")).resolve() if manifest.get("manifest_path") else None
    pack_dir = manifest_path.parent if manifest_path else Path("data/nonebot_chat_agent/knowledge_packs") / pack_key
    source_dir = pack_dir / "source"
    assets_dir = pack_dir / "assets"
    online_source_url = str(manifest.get("online_source_url") or "").strip()
    src = Path(source_ref).expanduser() if source_ref else source_dir

    def _has_local_source(path: Path) -> bool:
        if not path.exists():
            return False
        if path.is_file():
            return path.suffix.lower() in {".jsonl", ".json", ".db", ".sqlite", ".sqlite3"}
        for p in path.rglob("*"):
            if p.is_file() and p.suffix.lower() in {".jsonl", ".json", ".db", ".sqlite", ".sqlite3"}:
                return True
        return False

    should_try_online = bool(online_source_url) and (force_online_refresh or not _has_local_source(src))
    logger.info(
        "roco update start pack=%s should_try_online=%s force_online_refresh=%s source=%s online_source_url=%s",
        pack_key,
        should_try_online,
        force_online_refresh,
        str(src),
        bool(online_source_url),
    )

    if should_try_online:
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        tmp_dir = pack_dir / "tmp" / f"update_{ts}"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        try:
            crawl_res = crawl_roco_world_source(
                RocoCrawlerConfig(
                    base_url=online_source_url,
                    output_dir=tmp_dir,
                    assets_dir=tmp_dir / "assets",
                    request_delay=float(manifest.get("request_delay", 0.5) or 0.5),
                    timeout=float(manifest.get("timeout", 20.0) or 20.0),
                    max_pages=int(
                        manifest.get(
                            "max_pages",
                            sum(
                                int((manifest.get("crawler_limits") or {}).get(k, d) or d)
                                for k, d in (
                                    ("pet", 3000),
                                    ("skill", 3000),
                                    ("item", 3000),
                                    ("egg", 1000),
                                    ("furniture", 1000),
                                )
                            ),
                        )
                        or 0
                    ),
                    download_images=bool(manifest.get("download_images", True)),
                    crawler_limits=(manifest.get("crawler_limits") or None),
                )
            )
        except Exception as e:
            logger.warning("roco crawler failed pack=%s error=%s", pack_key, str(e)[:300])
            return {
                "ok": False,
                "status": "crawl_failed",
                "pack_key": pack_key,
                "message": f"{type(e).__name__}:{str(e)[:200]}",
                "update_source": "online_crawler",
            }
        if not crawl_res.get("ok"):
            logger.warning(
                "roco crawler result failed pack=%s errors=%s category_counts=%r",
                pack_key,
                len(crawl_res.get("errors", []) or []),
                crawl_res.get("category_counts", {}),
            )
            return {
                "ok": False,
                "status": "crawl_failed",
                "pack_key": pack_key,
                "message": str(crawl_res.get("errors", ["crawl failed"])[0])[:300],
                "update_source": "online_crawler",
                "crawl_errors_count": len(crawl_res.get("errors", []) or []),
                "pet_count": int(((crawl_res.get("category_counts") or {}).get("pet", 0) or 0)),
                "skill_count": int(((crawl_res.get("category_counts") or {}).get("skill", 0) or 0)),
                "item_count": int(((crawl_res.get("category_counts") or {}).get("item", 0) or 0)),
                "egg_count": int(((crawl_res.get("category_counts") or {}).get("egg", 0) or 0)),
                "furniture_count": int(((crawl_res.get("category_counts") or {}).get("furniture", 0) or 0)),
            }
        source_dir.mkdir(parents=True, exist_ok=True)
        assets_dir.mkdir(parents=True, exist_ok=True)
        src_records = tmp_dir / "source" / "records.jsonl"
        if not src_records.exists():
            return {
                "ok": False,
                "status": "crawl_failed",
                "pack_key": pack_key,
                "message": "records_missing",
                "update_source": "online_crawler",
            }
        shutil.copy2(src_records, source_dir / "records.jsonl")
        src_state = tmp_dir / "source" / "crawl_state.json"
        if src_state.exists():
            shutil.copy2(src_state, source_dir / "crawl_state.json")
        tmp_assets = tmp_dir / "assets"
        if tmp_assets.exists():
            if assets_dir.exists():
                shutil.rmtree(assets_dir)
            shutil.copytree(tmp_assets, assets_dir)
        src = source_dir
        update_source = "online_crawler"
        logger.info(
            "roco crawler done pack=%s records=%s assets=%s category_counts=%r",
            pack_key,
            crawl_res.get("records_count", 0),
            crawl_res.get("assets_count", 0),
            crawl_res.get("category_counts", {}),
        )
    elif not _has_local_source(src):
        if not online_source_url:
            return {
                "ok": False,
                "status": "missing_resources",
                "pack_key": pack_key,
                "message": "\u7f3a\u5c11\u672c\u5730\u6e90\u6570\u636e\uff0cP4o-4 \u5c06\u652f\u6301\u5728\u7ebf\u4e0b\u8f7d/\u722c\u53d6\u3002",
            }
    else:
        update_source = "local_source"

    out = await import_roco_world_pack(
        config,
        str(src),
        pack_key=pack_key,
        title=str(manifest.get("title") or "roco world wiki"),
        description=str(manifest.get("description") or "roco world wiki local knowledge pack"),
    )
    logger.info("roco import start pack=%s source=%s", pack_key, str(src))
    out["status"] = "ok" if out.get("ok") else "failed"
    out["records_count"] = int(out.get("imported_docs", 0) or 0)
    out["assets_count"] = int(out.get("imported_assets", 0) or 0)
    out["update_source"] = update_source
    out["source_ref"] = str(src)
    out["crawl_errors_count"] = int(len(out.get("errors", []) or []))
    cc = (crawl_res.get("category_counts") or {}) if should_try_online else {}
    out["pet_count"] = int(cc.get("pet", 0) or 0)
    out["skill_count"] = int(cc.get("skill", 0) or 0)
    out["item_count"] = int(cc.get("item", 0) or 0)
    out["egg_count"] = int(cc.get("egg", 0) or 0)
    out["furniture_count"] = int(cc.get("furniture", 0) or 0)
    logger.info(
        "roco import done pack=%s docs=%s chunks=%s assets=%s",
        pack_key,
        out.get("imported_docs", 0),
        out.get("imported_chunks", 0),
        out.get("imported_assets", 0),
    )
    logger.info(
        "roco update done pack=%s update_source=%s records_count=%s category_counts=%r",
        pack_key,
        out.get("update_source", ""),
        out.get("records_count", 0),
        {
            "pet": out.get("pet_count", 0),
            "skill": out.get("skill_count", 0),
            "item": out.get("item_count", 0),
            "egg": out.get("egg_count", 0),
            "furniture": out.get("furniture_count", 0),
        },
    )
    if manifest_path and manifest_path.exists():
        try:
            old = json.loads(manifest_path.read_text(encoding="utf-8-sig", errors="replace").lstrip("\ufeff") or "{}")
            if not isinstance(old, dict):
                old = {}
            now = datetime.now(timezone.utc).isoformat()
            old["status"] = out["status"]
            old["last_update_at"] = now
            if out.get("ok"):
                old["last_import_at"] = now
            old["last_error"] = "" if out.get("ok") else str(out.get("message", ""))[:300]
            old["records_count"] = int(out.get("records_count", 0) or 0)
            old["assets_count"] = int(out.get("assets_count", 0) or 0)
            old["source_ref"] = str(src)
            old["pet_count"] = int(out.get("pet_count", 0) or 0)
            old["skill_count"] = int(out.get("skill_count", 0) or 0)
            old["item_count"] = int(out.get("item_count", 0) or 0)
            old["egg_count"] = int(out.get("egg_count", 0) or 0)
            old["furniture_count"] = int(out.get("furniture_count", 0) or 0)
            manifest_path.write_text(json.dumps(old, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass
    return out
