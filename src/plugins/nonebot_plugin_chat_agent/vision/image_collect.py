from __future__ import annotations

import base64
import html
import mimetypes
from pathlib import Path
from urllib.parse import urlparse

import httpx
from nonebot import logger


def _sanitize_url(url: str) -> str:
    clean = html.unescape(str(url or "").strip())
    marker = ",file_size="
    idx = clean.find(marker)
    if idx > 0:
        clean = clean[:idx]
    return clean


def _extract_image_refs(message, source: str) -> list[dict]:
    refs: list[dict] = []
    if not message:
        return refs
    for seg in message:
        seg_type = str(getattr(seg, "type", "") or "")
        if seg_type != "image":
            continue
        data = getattr(seg, "data", {}) or {}
        url = str(data.get("url", "") or "").strip()
        file_ref = str(data.get("file", "") or "").strip()
        refs.append({"source": source, "url": url, "file": file_ref})
    return refs


async def _download_image_as_base64(url: str, timeout: float = 30.0) -> tuple[str, str, int]:
    parsed = urlparse(url)
    mime = mimetypes.guess_type(parsed.path)[0] or "application/octet-stream"
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        data = resp.content
        content_type = str(resp.headers.get("content-type", "") or "").split(";")[0].strip()
        if content_type:
            mime = content_type
        return base64.b64encode(data).decode("utf-8"), mime, len(data)


def _read_local_image_as_base64(path_text: str) -> tuple[str, str, int] | None:
    p = Path(path_text)
    if not p.exists() or not p.is_file():
        return None
    data = p.read_bytes()
    mime = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
    return base64.b64encode(data).decode("utf-8"), mime, len(data)


async def collect_event_images(event, max_images: int = 3) -> dict:
    refs: list[dict] = []
    refs.extend(_extract_image_refs(getattr(event, "message", None), "current"))
    reply = getattr(event, "reply", None)
    if reply is not None:
        refs.extend(_extract_image_refs(getattr(reply, "message", None), "reply"))
    images: list[dict] = []
    warnings: list[str] = []
    for ref in refs[: max(1, int(max_images or 3))]:
        url = _sanitize_url(ref.get("url", ""))
        file_ref = str(ref.get("file", "") or "").strip()
        source = ref.get("source", "current")
        if url:
            try:
                b64, mime, size = await _download_image_as_base64(url)
                images.append({"source": source, "url": url, "mime": mime, "size": size, "base64": b64})
                logger.info(f"image_collect downloaded=1 source={source} size={size}")
                continue
            except Exception as e:
                warnings.append(f"download_failed:{type(e).__name__}")
        if file_ref:
            local = _read_local_image_as_base64(file_ref)
            if local is not None:
                b64, mime, size = local
                images.append({"source": source, "file": file_ref, "mime": mime, "size": size, "base64": b64})
                logger.info(f"image_collect downloaded=1 source={source} size={size}")
                continue
            warnings.append("local_file_unavailable")
    return {"image_count": len(images), "images": images, "warnings": warnings}
