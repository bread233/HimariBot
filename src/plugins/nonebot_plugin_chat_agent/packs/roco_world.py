from __future__ import annotations

from pathlib import Path

try:
    from ..roco_world_importer import import_roco_world_pack
except Exception:  # pragma: no cover
    from roco_world_importer import import_roco_world_pack


async def update_roco_world_pack(config, manifest: dict) -> dict:
    pack_key = str(manifest.get("pack_key") or "roco_world").strip()
    source_ref = str(manifest.get("source_ref") or "").strip()
    if not source_ref:
        return {
            "ok": False,
            "status": "missing_resources",
            "pack_key": pack_key,
            "message": "\u7f3a\u5c11\u672c\u5730\u6e90\u6570\u636e\uff0cP4o-4 \u5c06\u652f\u6301\u5728\u7ebf\u4e0b\u8f7d/\u722c\u53d6\u3002",
        }
    src = Path(source_ref).expanduser()
    if not src.exists():
        return {
            "ok": False,
            "status": "missing_resources",
            "pack_key": pack_key,
            "message": "\u7f3a\u5c11\u672c\u5730\u6e90\u6570\u636e\uff0cP4o-4 \u5c06\u652f\u6301\u5728\u7ebf\u4e0b\u8f7d/\u722c\u53d6\u3002",
        }
    out = await import_roco_world_pack(
        config,
        str(src),
        pack_key=pack_key,
        title=str(manifest.get("title") or "roco world wiki"),
        description=str(manifest.get("description") or "roco world wiki local knowledge pack"),
    )
    out["status"] = "ok" if out.get("ok") else "failed"
    return out
