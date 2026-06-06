"""Codex vision adapter stub.

当前仅提供统一的视觉入口占位，后续再接真正的 codex vision 实现。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
import logging

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class CodexVisionResult:
    text: str = ""
    ok: bool = False
    error: str | None = "vision_not_implemented"
    source: str = "codex_vision_stub"


async def describe_image(
    *,
    image_path: str | None = None,
    image_bytes: bytes | None = None,
    mime_type: str | None = None,
    prompt: str | None = None,
    context: dict[str, Any] | None = None,
) -> CodexVisionResult:
    """视觉描述占位实现。

    当前不调用任何外部模型，不读取大文件，不抛异常。
    """
    del image_path, image_bytes, mime_type, prompt, context
    logger.warning("codex vision adapter is not implemented; returning empty result")
    return CodexVisionResult()
