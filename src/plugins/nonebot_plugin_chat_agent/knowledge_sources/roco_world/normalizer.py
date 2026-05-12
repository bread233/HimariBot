from __future__ import annotations

import hashlib
import json


_SUPPORTED_CATEGORIES = {"pet", "skill", "item", "egg", "furniture", "region", "dungeon", "update_log", "other"}


def _norm_text(x: object, limit: int = 2000) -> str:
    return str(x or "").strip()[:limit]


def _norm_category(raw: object) -> str:
    x = _norm_text(raw, 64).lower()
    return x if x in _SUPPORTED_CATEGORIES else "other"


def _build_doc_key(pack_key: str, category: str, title: str, source_ref: str) -> str:
    seed = f"{pack_key}|{category}|{title}|{source_ref}".encode("utf-8", errors="ignore")
    return hashlib.sha1(seed).hexdigest()


def normalize_record_to_entry(record: dict, pack_key: str = "roco_world") -> dict:
    category = _norm_category(record.get("category"))
    title = _norm_text(record.get("title") or record.get("name"), 120)
    source_url = _norm_text(record.get("source_url"), 500)
    source_path = _norm_text(record.get("source_path"), 500)
    image_path = _norm_text(record.get("image_path"), 500)
    image_url = _norm_text(record.get("image_url"), 500)
    source_ref = source_path or source_url or title
    doc_key = _build_doc_key(pack_key, category, title, source_ref)
    metadata = dict(record.get("metadata") or {})
    for k, v in record.items():
        if k in {
            "pack_key",
            "category",
            "title",
            "name",
            "doc_key",
            "source_path",
            "source_url",
            "content",
            "metadata",
            "metadata_json",
        }:
            continue
        metadata.setdefault(str(k), v)
    metadata["entry_type"] = category
    aliases = record.get("aliases")
    if isinstance(aliases, list):
        metadata["aliases"] = [str(x).strip() for x in aliases if str(x).strip()]
    else:
        metadata["aliases"] = []
    metadata["source_name"] = "BiliGame \u6d1b\u514b\u738b\u56fd WIKI"
    metadata["source_license"] = "CC BY-NC-SA 4.0"
    assets = []
    if image_path or image_url:
        assets.append(
            {
                "kind": "image",
                "path": image_path,
                "url": image_url,
                "role": "primary",
            }
        )
    metadata["assets"] = assets
    if image_path:
        metadata["image_path"] = image_path
    if image_url:
        metadata["image_url"] = image_url
    content = _norm_text(record.get("content"), 8000)
    return {
        "pack_key": pack_key,
        "category": category,
        "title": title,
        "doc_key": doc_key,
        "source_path": source_path,
        "source_url": source_url,
        "content": content,
        "metadata_json": json.dumps(metadata, ensure_ascii=False),
    }
