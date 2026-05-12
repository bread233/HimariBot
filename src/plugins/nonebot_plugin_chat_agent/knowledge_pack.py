import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

try:
    from .storage import (
        upsert_knowledge_pack,
        upsert_knowledge_documents,
        upsert_knowledge_chunks,
        search_knowledge_chunks_lexical,
        search_knowledge_chunks_hybrid,
    )
except ImportError:
    from storage import (
        upsert_knowledge_pack,
        upsert_knowledge_documents,
        upsert_knowledge_chunks,
        search_knowledge_chunks_lexical,
        search_knowledge_chunks_hybrid,
    )


@dataclass
class KnowledgeChunk:
    pack_key: str
    doc_key: str
    chunk_key: str
    title: str
    section: str
    content: str
    source_path: str
    source_url: str
    chunk_index: int


def normalize_pack_key(pack_key: str) -> str:
    key = str(pack_key or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", key):
        raise ValueError("invalid pack_key")
    return key


def _read_text(path: Path) -> str:
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    return text.lstrip("\ufeff")


def read_knowledge_source(path: Path) -> list[dict]:
    files: list[Path] = []
    p = Path(path)
    if p.is_file():
        files = [p]
    elif p.is_dir():
        files = [x for x in p.rglob("*") if x.is_file() and not x.name.startswith(".")]
    out: list[dict] = []
    for f in files:
        suffix = f.suffix.lower()
        if suffix not in {".md", ".txt", ".jsonl", ".json"}:
            continue
        if f.stat().st_size > 1024 * 1024:
            continue
        if suffix in {".md", ".txt"}:
            out.append({"title": f.stem, "content": _read_text(f), "section": "", "source_path": str(f)})
        elif suffix == ".jsonl":
            for line in _read_text(f).splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except Exception:
                    continue
                out.append(
                    {
                        "title": str(obj.get("title", f.stem) or f.stem),
                        "content": str(obj.get("content", "") or ""),
                        "section": str(obj.get("section", "") or ""),
                        "source_url": str(obj.get("source_url", "") or ""),
                        "source_path": str(f),
                        "metadata": obj.get("metadata", {}),
                    }
                )
        elif suffix == ".json":
            try:
                data = json.loads(_read_text(f))
            except Exception:
                continue
            objs = data if isinstance(data, list) else [data]
            for obj in objs:
                if not isinstance(obj, dict):
                    continue
                out.append(
                    {
                        "title": str(obj.get("title", f.stem) or f.stem),
                        "content": str(obj.get("content", "") or ""),
                        "section": str(obj.get("section", "") or ""),
                        "source_url": str(obj.get("source_url", "") or ""),
                        "source_path": str(f),
                        "metadata": obj.get("metadata", {}),
                    }
                )
    return out


def split_text_to_chunks(text: str, max_chars: int = 900, overlap: int = 120) -> list[str]:
    s = str(text or "").strip()
    if not s:
        return []
    parts = re.split(r"\n\s*\n+", s)
    chunks: list[str] = []
    buf = ""
    for part in parts:
        p = part.strip()
        if not p:
            continue
        if len(buf) + len(p) + 2 <= max_chars:
            buf = (buf + "\n\n" + p).strip()
        else:
            if buf:
                chunks.append(buf)
            if len(p) <= max_chars:
                buf = p
            else:
                i = 0
                step = max(100, max_chars - max(0, overlap))
                while i < len(p):
                    chunks.append(p[i : i + max_chars].strip())
                    i += step
                buf = ""
    if buf:
        chunks.append(buf)
    merged: list[str] = []
    for c in chunks:
        if merged and len(c) < 120 and len(merged[-1]) + len(c) + 2 <= max_chars:
            merged[-1] = (merged[-1] + "\n\n" + c).strip()
        else:
            merged.append(c)
    return merged


def build_doc_key(pack_key: str, source_path: str, title: str) -> str:
    raw = f"{pack_key}|{source_path}|{title}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:24]


def build_chunk_key(pack_key: str, doc_key: str, chunk_index: int) -> str:
    raw = f"{pack_key}|{doc_key}|{chunk_index}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:32]


async def import_knowledge_path(config, pack_key: str, path: str, title: str = "", description: str = "", source_type: str = "manual") -> dict:
    pack_key = normalize_pack_key(pack_key)
    rows = read_knowledge_source(Path(path))
    await upsert_knowledge_pack(
        config,
        {
            "pack_key": pack_key,
            "title": str(title or pack_key),
            "description": str(description or ""),
            "source_type": str(source_type or "manual"),
            "source_ref": str(path),
            "enabled": 1,
            "metadata_json": "{}",
        },
    )
    doc_rows = []
    chunk_rows = []
    for item in rows:
        t = str(item.get("title", "") or "")
        c = str(item.get("content", "") or "")
        if not c.strip():
            continue
        sp = str(item.get("source_path", "") or "")
        su = str(item.get("source_url", "") or "")
        section = str(item.get("section", "") or "")
        doc_key = build_doc_key(pack_key, sp, t)
        content_hash = hashlib.sha256(c.encode("utf-8", errors="ignore")).hexdigest()
        doc_rows.append(
            {
                "pack_key": pack_key,
                "doc_key": doc_key,
                "title": t,
                "source_path": sp,
                "source_url": su,
                "source_type": str(source_type or "manual"),
                "content_hash": content_hash,
                "metadata_json": json.dumps(item.get("metadata", {}), ensure_ascii=False),
                "enabled": 1,
            }
        )
        chunks = split_text_to_chunks(c)
        for i, chunk in enumerate(chunks):
            chunk_key = build_chunk_key(pack_key, doc_key, i)
            chash = hashlib.sha256(chunk.encode("utf-8", errors="ignore")).hexdigest()
            chunk_rows.append(
                {
                    "pack_key": pack_key,
                    "doc_key": doc_key,
                    "chunk_key": chunk_key,
                    "title": t,
                    "section": section,
                    "content": chunk,
                    "content_hash": chash,
                    "source_path": sp,
                    "source_url": su,
                    "chunk_index": i,
                    "token_count": max(1, len(chunk) // 2),
                    "embedding_json": "",
                    "metadata_json": json.dumps(item.get("metadata", {}), ensure_ascii=False),
                    "enabled": 1,
                }
            )
    imported_docs = await upsert_knowledge_documents(config, doc_rows)
    imported_chunks = await upsert_knowledge_chunks(config, chunk_rows)
    return {"ok": True, "pack_key": pack_key, "imported_docs": imported_docs, "imported_chunks": imported_chunks}


async def search_knowledge_pack(
    config,
    query: str,
    pack_key: str | None = None,
    limit: int = 5,
    min_score: float = 0.25,
    mode: str = "hybrid",
) -> list[dict]:
    mode_v = str(mode or "hybrid").strip().lower()
    if mode_v == "lexical":
        rows = await search_knowledge_chunks_lexical(config, query, pack_key=pack_key, limit=limit, min_score=min_score)
    elif mode_v == "vector":
        rows = await search_knowledge_chunks_hybrid(config, query, pack_key=pack_key, limit=limit, min_score=min_score)
    else:
        rows = await search_knowledge_chunks_hybrid(config, query, pack_key=pack_key, limit=limit, min_score=min_score)
    out = []
    for r in rows:
        out.append(
            {
                "pack_key": r.get("pack_key", ""),
                "doc_key": r.get("doc_key", ""),
                "title": r.get("title", ""),
                "section": r.get("section", ""),
                "content": r.get("content", ""),
                "source_path": r.get("source_path", ""),
                "source_url": r.get("source_url", ""),
                "score": float(r.get("score", 0.0) or 0.0),
            }
        )
    return out
