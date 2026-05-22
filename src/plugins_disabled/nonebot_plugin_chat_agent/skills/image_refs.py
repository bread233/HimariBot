from __future__ import annotations

import base64
import re
from typing import Any
from urllib.parse import urlparse

import httpx


_URL_RE = re.compile(r"(https?://[^\s'\"<>]+|base64://[^\s'\"<>]+)", re.IGNORECASE)
_IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp", ".gif")


def _extract_first_image_ref(text: str) -> str | None:
    raw = str(text or "").strip()
    if not raw:
        return None
    lower = raw.lower()
    if lower.startswith("base64://") or lower.startswith("http://") or lower.startswith("https://"):
        return raw
    match = _URL_RE.search(raw)
    return match.group(1).strip() if match else None


def _pick_candidate(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return _extract_first_image_ref(value)
    data = getattr(value, "data", None)
    if isinstance(data, dict):
        for key in ("url", "file"):
            hit = _extract_first_image_ref(data.get(key))
            if hit:
                return hit
    if isinstance(value, dict):
        for key in ("url", "image_url", "file"):
            hit = _extract_first_image_ref(value.get(key))
            if hit:
                return hit
    return _extract_first_image_ref(str(value))


def _looks_like_image_url(url: str, content_type: str | None) -> bool:
    ct = (content_type or "").lower()
    if ct.startswith("image/"):
        return True
    if ct:
        return False
    path = urlparse(url).path.lower()
    return any(path.endswith(ext) for ext in _IMAGE_EXTS)


async def normalize_image_ref_to_base64(
    value: object,
    *,
    timeout: float = 8.0,
    max_bytes: int = 8 * 1024 * 1024,
) -> str | None:
    candidate = _pick_candidate(value)
    if not candidate:
        return None
    low = candidate.lower()
    if low.startswith("base64://"):
        return candidate
    if not (low.startswith("http://") or low.startswith("https://")):
        return None

    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=timeout) as client:
            response = await client.get(candidate)
    except Exception:
        return None

    if response.status_code != 200:
        return None
    if not _looks_like_image_url(candidate, response.headers.get("content-type")):
        return None

    content = response.content or b""
    if not content or len(content) > max_bytes:
        return None

    encoded = base64.b64encode(content).decode("ascii")
    return f"base64://{encoded}"
