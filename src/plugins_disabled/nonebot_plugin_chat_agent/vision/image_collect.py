from __future__ import annotations

import base64
import html
import io
import mimetypes
from pathlib import Path
from urllib.parse import urlparse

import httpx
from nonebot import logger
from PIL import Image, ImageOps


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


def _maybe_resize_image_bytes(
    data: bytes,
    *,
    source: str,
    resize_enable: bool,
    max_side: int,
    quality: int,
) -> tuple[bytes, str, int]:
    if not resize_enable:
        return data, "application/octet-stream", len(data)
    try:
        with Image.open(io.BytesIO(data)) as img:
            img = ImageOps.exif_transpose(img)
            w, h = img.size
            longest = max(w, h)
            if longest <= max(1, int(max_side or 512)):
                return data, "application/octet-stream", len(data)
            scale = float(max_side) / float(longest)
            new_w = max(1, int(w * scale))
            new_h = max(1, int(h * scale))
            img = img.convert("RGB").resize((new_w, new_h), Image.Resampling.LANCZOS)
            out = io.BytesIO()
            q = min(95, max(40, int(quality or 80)))
            img.save(out, format="JPEG", quality=q, optimize=True)
            resized = out.getvalue()
            logger.info(
                f"image_collect resized=1 source={source} "
                f"original_size={len(data)} resized_size={len(resized)} max_side={int(max_side)} quality={q}"
            )
            return resized, "image/jpeg", len(resized)
    except Exception as e:
        logger.warning(f"image_collect resized=0 source={source} error={type(e).__name__}")
        return data, "application/octet-stream", len(data)


async def _download_image_as_base64(
    url: str,
    *,
    source: str,
    timeout: float = 30.0,
    resize_enable: bool = True,
    resize_max_side: int = 512,
    resize_quality: int = 80,
) -> tuple[str, str, int]:
    parsed = urlparse(url)
    mime = mimetypes.guess_type(parsed.path)[0] or "application/octet-stream"
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        data = resp.content
        content_type = str(resp.headers.get("content-type", "") or "").split(";")[0].strip()
        if content_type:
            mime = content_type
        resized_bytes, resized_mime, resized_size = _maybe_resize_image_bytes(
            data,
            source=source,
            resize_enable=resize_enable,
            max_side=resize_max_side,
            quality=resize_quality,
        )
        if resized_mime != "application/octet-stream":
            mime = resized_mime
        return base64.b64encode(resized_bytes).decode("utf-8"), mime, resized_size


def _read_local_image_as_base64(
    path_text: str,
    *,
    source: str,
    resize_enable: bool = True,
    resize_max_side: int = 512,
    resize_quality: int = 80,
) -> tuple[str, str, int] | None:
    p = Path(path_text)
    if not p.exists() or not p.is_file():
        return None
    data = p.read_bytes()
    mime = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
    resized_bytes, resized_mime, resized_size = _maybe_resize_image_bytes(
        data,
        source=source,
        resize_enable=resize_enable,
        max_side=resize_max_side,
        quality=resize_quality,
    )
    if resized_mime != "application/octet-stream":
        mime = resized_mime
    return base64.b64encode(resized_bytes).decode("utf-8"), mime, resized_size


async def collect_event_images(
    event,
    max_images: int = 3,
    *,
    resize_enable: bool = True,
    resize_max_side: int = 512,
    resize_quality: int = 80,
) -> dict:
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
                b64, mime, size = await _download_image_as_base64(
                    url,
                    source=source,
                    resize_enable=resize_enable,
                    resize_max_side=resize_max_side,
                    resize_quality=resize_quality,
                )
                images.append({"source": source, "url": url, "mime": mime, "size": size, "base64": b64})
                logger.info(f"image_collect downloaded=1 source={source} size={size}")
                continue
            except Exception as e:
                warnings.append(f"download_failed:{type(e).__name__}")
        if file_ref:
            local = _read_local_image_as_base64(
                file_ref,
                source=source,
                resize_enable=resize_enable,
                resize_max_side=resize_max_side,
                resize_quality=resize_quality,
            )
            if local is not None:
                b64, mime, size = local
                images.append({"source": source, "file": file_ref, "mime": mime, "size": size, "base64": b64})
                logger.info(f"image_collect downloaded=1 source={source} size={size}")
                continue
            warnings.append("local_file_unavailable")
    return {"image_count": len(images), "images": images, "warnings": warnings}
