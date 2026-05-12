from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from pathlib import Path
from typing import Any

try:
    from .knowledge_pack import normalize_pack_key, split_text_to_chunks, build_doc_key, build_chunk_key
    from .storage import upsert_knowledge_pack, upsert_knowledge_documents, upsert_knowledge_chunks
except ImportError:
    from knowledge_pack import normalize_pack_key, split_text_to_chunks, build_doc_key, build_chunk_key
    from storage import upsert_knowledge_pack, upsert_knowledge_documents, upsert_knowledge_chunks


def _norm_text(v: Any, limit: int = 2000) -> str:
    s = str(v or "").strip().lstrip("\ufeff")
    return s[:limit]


def normalize_roco_record(row: dict) -> dict:
    category = _norm_text(row.get("category") or row.get("type") or row.get("table") or "other", 64).lower()
    name = _norm_text(row.get("name") or row.get("title") or row.get("name_cn"), 120)
    title = _norm_text(row.get("title") or name, 120)
    content = _norm_text(row.get("content") or row.get("description") or row.get("desc") or row.get("effect"), 4000)
    source_url = _norm_text(row.get("source_url") or row.get("url"), 500)
    image_path = _norm_text(row.get("image_path") or row.get("icon_path") or row.get("image") or row.get("icon") or row.get("pic"), 500)
    image_url = _norm_text(row.get("image_url"), 500)
    source_path = _norm_text(row.get("source_path"), 500)
    metadata = row.get("metadata", {})
    if not isinstance(metadata, dict):
        metadata = {}
    return {
        "category": category or "other",
        "name": name,
        "title": title,
        "content": content,
        "source_url": source_url,
        "source_path": source_path,
        "image_path": image_path,
        "image_url": image_url,
        "metadata": metadata,
    }


def render_roco_record_to_text(record: dict) -> str:
    lines: list[str] = []
    category = _norm_text(record.get("category"), 64)
    title = _norm_text(record.get("title") or record.get("name"), 120)
    if category or title:
        lines.append(f"【{category}】{title}".strip())

    def _append(label: str, value: Any) -> None:
        text = _norm_text(value, 800)
        if text:
            lines.append(f"{label}：{text}")

    for key, label in [
        ("element", "属性"),
        ("attribute", "属性"),
        ("position", "定位"),
        ("obtain_method", "获取方式"),
        ("effect", "效果"),
        ("description", "说明"),
        ("content", "说明"),
    ]:
        if key in record:
            _append(label, record.get(key))
    if _norm_text(record.get("image_path")):
        _append("图片", record.get("image_path"))
    elif _norm_text(record.get("image_url")):
        _append("图片", record.get("image_url"))
    source = _norm_text(record.get("source_path") or record.get("source_url"))
    if source:
        _append("来源", source)
    return "\n".join(x for x in lines if x).strip()


def read_roco_records_from_jsonl(path: Path) -> list[dict]:
    out: list[dict] = []
    text = path.read_text(encoding="utf-8-sig", errors="replace").lstrip("\ufeff")
    if path.suffix.lower() == ".json":
        try:
            data = json.loads(text)
        except Exception:
            return out
        objs = data if isinstance(data, list) else [data]
        for obj in objs:
            if isinstance(obj, dict):
                out.append(normalize_roco_record(dict(obj)))
        return out
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except Exception:
            continue
        if isinstance(obj, dict):
            out.append(normalize_roco_record(dict(obj)))
    return out


def read_roco_records_from_sqlite(path: Path) -> tuple[list[dict], list[str]]:
    records: list[dict] = []
    skipped_tables: list[str] = []
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        for table in tables:
            try:
                cols = [str(c["name"]).lower() for c in conn.execute(f"PRAGMA table_info('{table}')")]
            except Exception:
                skipped_tables.append(table)
                continue
            name_col = next((c for c in cols if c in {"name", "title", "name_cn"}), "")
            content_col = next((c for c in cols if c in {"description", "desc", "effect", "content"}), "")
            if not name_col and not content_col:
                skipped_tables.append(table)
                continue
            query = f"SELECT * FROM '{table}' LIMIT 5000"
            try:
                rows = conn.execute(query).fetchall()
            except Exception:
                skipped_tables.append(table)
                continue
            for row in rows:
                d = {k.lower(): row[k] for k in row.keys()}
                d["table"] = table
                d["category"] = d.get("category") or d.get("type") or table
                d["source_path"] = str(path)
                records.append(normalize_roco_record(d))
    finally:
        conn.close()
    return records, skipped_tables


async def import_roco_world_pack(
    config,
    source_path: str,
    pack_key: str = "roco_world",
    title: str = "roco world wiki",
    description: str = "roco world wiki local knowledge pack",
) -> dict:
    key = normalize_pack_key(pack_key)
    source = Path(source_path)
    if not source.exists():
        raise FileNotFoundError(str(source))

    all_records: list[dict] = []
    skipped_tables: list[str] = []
    source_type = "unknown"
    targets: list[Path] = [source]
    if source.is_dir():
        source_type = "directory"
        targets = [p for p in source.rglob("*") if p.is_file() and p.suffix.lower() in {".db", ".sqlite", ".sqlite3", ".jsonl", ".json"}]
    for p in targets:
        suffix = p.suffix.lower()
        if suffix in {".jsonl", ".json"}:
            all_records.extend(read_roco_records_from_jsonl(p))
            source_type = "jsonl" if suffix == ".jsonl" else "json"
        elif suffix in {".db", ".sqlite", ".sqlite3"}:
            recs, skips = read_roco_records_from_sqlite(p)
            all_records.extend(recs)
            skipped_tables.extend(skips)
            source_type = "sqlite"

    await upsert_knowledge_pack(
        config,
        {
            "pack_key": key,
            "title": _norm_text(title or key, 120),
            "description": _norm_text(description, 300),
            "source_type": f"roco_world_{source_type}",
            "source_ref": str(source),
            "enabled": 1,
            "metadata_json": "{}",
        },
    )

    doc_rows: list[dict] = []
    chunk_rows: list[dict] = []
    imported_assets = 0
    for rec in all_records:
        title_text = _norm_text(rec.get("title") or rec.get("name"), 120)
        if not title_text:
            continue
        rendered = render_roco_record_to_text(rec)
        if not rendered:
            continue
        src_path = _norm_text(rec.get("source_path"), 500)
        src_url = _norm_text(rec.get("source_url"), 500)
        doc_key = build_doc_key(key, src_path or src_url or title_text, title_text)
        content_hash = hashlib.sha256(rendered.encode("utf-8", errors="ignore")).hexdigest()
        meta = dict(rec.get("metadata") or {})
        if _norm_text(rec.get("image_path")):
            meta["image_path"] = _norm_text(rec.get("image_path"), 500)
            imported_assets += 1
        if _norm_text(rec.get("image_url")):
            meta["image_url"] = _norm_text(rec.get("image_url"), 500)
            imported_assets += 1
        doc_rows.append(
            {
                "pack_key": key,
                "doc_key": doc_key,
                "title": title_text,
                "source_path": src_path,
                "source_url": src_url,
                "source_type": f"roco_world_{source_type}",
                "content_hash": content_hash,
                "metadata_json": json.dumps(meta, ensure_ascii=False),
                "enabled": 1,
            }
        )
        chunks = split_text_to_chunks(rendered)
        for i, chunk in enumerate(chunks):
            chunk_rows.append(
                {
                    "pack_key": key,
                    "doc_key": doc_key,
                    "chunk_key": build_chunk_key(key, doc_key, i),
                    "title": title_text,
                    "section": _norm_text(rec.get("category"), 64),
                    "content": chunk,
                    "content_hash": hashlib.sha256(chunk.encode("utf-8", errors="ignore")).hexdigest(),
                    "source_path": src_path,
                    "source_url": src_url,
                    "chunk_index": i,
                    "token_count": max(1, len(chunk) // 2),
                    "embedding_json": "",
                    "metadata_json": json.dumps(meta, ensure_ascii=False),
                    "enabled": 1,
                }
            )

    imported_docs = await upsert_knowledge_documents(config, doc_rows)
    imported_chunks = await upsert_knowledge_chunks(config, chunk_rows)
    return {
        "ok": True,
        "pack_key": key,
        "source_type": source_type,
        "imported_docs": imported_docs,
        "imported_chunks": imported_chunks,
        "imported_assets": int(imported_assets),
        "skipped_tables": sorted(set(skipped_tables)),
    }
