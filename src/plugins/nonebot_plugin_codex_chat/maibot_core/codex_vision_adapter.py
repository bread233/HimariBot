"""Codex vision adapter.

当前实现只做安全收口：接收图片 bytes / path，做大小与 mime 校验，
然后明确返回是否支持多模态视觉。当前 codex provider 不支持真实图片输入，
因此不会伪造视觉识别结果。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
import base64
import logging

logger = logging.getLogger(__name__)

MAX_IMAGE_BYTES = 10 * 1024 * 1024
ALLOWED_IMAGE_MIME_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp"}


@dataclass(slots=True)
class CodexVisionResult:
    text: str = ""
    ok: bool = False
    error: str | None = "vision_not_implemented"
    source: str = "codex_vision_stub"


def _guess_mime_type(data: bytes, fallback: str | None = None) -> str | None:
    if not data:
        return fallback
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"GIF87a") or data.startswith(b"GIF89a"):
        return "image/gif"
    if data.startswith(b"RIFF") and b"WEBP" in data[:16]:
        return "image/webp"
    return fallback


async def describe_image(
    *,
    image_path: str | None = None,
    image_bytes: bytes | None = None,
    mime_type: str | None = None,
    prompt: str | None = None,
    context: dict[str, Any] | None = None,
) -> CodexVisionResult:
    """安全的视觉入口：解析图片输入，但当前 provider 不支持真实多模态。"""
    raw_bytes = b""
    source_path = ""
    if image_bytes:
        raw_bytes = bytes(image_bytes)
    elif image_path:
        path = Path(image_path)
        source_path = path.name
        if not path.exists():
            logger.warning("codex_vision_adapter failed error=image_file_not_found mime=%s bytes=0", mime_type)
            return CodexVisionResult(ok=False, error="image_file_not_found", source="codex_vision_stub")
        if path.stat().st_size > MAX_IMAGE_BYTES:
            logger.warning("codex_vision_adapter failed error=image_too_large mime=%s bytes=%s", mime_type, path.stat().st_size)
            return CodexVisionResult(ok=False, error="image_too_large", source="codex_vision_stub")
        raw_bytes = path.read_bytes()
    else:
        logger.warning("codex_vision_adapter failed error=missing_image_data mime=%s bytes=0", mime_type)
        return CodexVisionResult(ok=False, error="missing_image_data", source="codex_vision_stub")

    if len(raw_bytes) > MAX_IMAGE_BYTES:
        logger.warning("codex_vision_adapter failed error=image_too_large mime=%s bytes=%s", mime_type, len(raw_bytes))
        return CodexVisionResult(ok=False, error="image_too_large", source="codex_vision_stub")

    final_mime = _guess_mime_type(raw_bytes, fallback=mime_type)
    if final_mime not in ALLOWED_IMAGE_MIME_TYPES:
        logger.warning("codex_vision_adapter failed error=unsupported_mime_type:%s mime=%s bytes=%s", final_mime, final_mime, len(raw_bytes))
        return CodexVisionResult(ok=False, error=f"unsupported_mime_type:{final_mime}", source="codex_vision_stub")

    # 当前 provider 没有真正的多模态入参通道，image_base64 只是文本 payload 占位，不能伪装成视觉成功。
    logger.warning("codex_vision_adapter multimodal unsupported")
    logger.info(
        "codex_vision_adapter failed error=vision_multimodal_not_supported mime=%s bytes=%s",
        final_mime,
        len(raw_bytes),
    )
    return CodexVisionResult(ok=False, error="vision_multimodal_not_supported", source="codex_vision_stub")
