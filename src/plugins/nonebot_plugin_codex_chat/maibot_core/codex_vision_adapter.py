"""Codex vision adapter.

通过 Codex CLI 的 ``--image`` 参数注入图片, 实现真实视觉识别。
前置验证已确认 codexcli 容器可访问 ``/app/data/...`` 路径。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
import hashlib
import importlib
import logging
import sys

logger = logging.getLogger(__name__)

MAX_IMAGE_BYTES = 10 * 1024 * 1024
ALLOWED_IMAGE_MIME_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp"}
MIME_TO_EXT = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/gif": ".gif",
    "image/webp": ".webp",
}
DEFAULT_VISION_PROMPT = (
    "请用中文简洁描述这张图片的主要内容。"
    "若无法判断，请明确说无法判断。不要编造看不见的信息。"
)
VISION_TMP_DIR = "/app/data/nonebot_chat_agent/maibot_media/vision_tmp"
SOURCE_CODEX_CLI_IMAGE = "codex_cli_image"
_PLUGIN_CONFIG_CANDIDATES = (
    "src.plugins.nonebot_plugin_codex_chat",
    "nonebot_plugin_codex_chat",
)
_CODEX_PROVIDER_CANDIDATES = (
    "src.plugins.nonebot_plugin_codex_chat.codex_provider",
    "nonebot_plugin_codex_chat.codex_provider",
)


@dataclass(slots=True)
class CodexVisionResult:
    text: str = ""
    ok: bool = False
    error: str | None = "vision_not_implemented"
    source: str = SOURCE_CODEX_CLI_IMAGE


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


def _load_plugin_config():
    """惰性解析 codex_chat 插件 config, 与 codex_llm_adapter 同样的回退链。"""

    errors: list[str] = []
    for module_name in _PLUGIN_CONFIG_CANDIDATES:
        module = sys.modules.get(module_name)
        if module is not None and hasattr(module, "get_config"):
            return module.get_config()
    for module_name in _PLUGIN_CONFIG_CANDIDATES:
        try:
            module = importlib.import_module(module_name)
            get_config = getattr(module, "get_config")
            return get_config()
        except Exception as exc:
            errors.append(f"{module_name}: {type(exc).__name__}: {exc}")
    raise RuntimeError(
        "Unable to load codex_chat plugin config for vision adapter: "
        + " | ".join(errors)
    )


def _get_codex_provider_module():
    """惰性解析 codex_provider 模块, 复用 codex_llm_adapter 的候选策略。"""
    errors: list[str] = []

    for module_name in _CODEX_PROVIDER_CANDIDATES:
        module = sys.modules.get(module_name)
        if module is not None and hasattr(module, "ask_codex"):
            return module

    for module_name in _CODEX_PROVIDER_CANDIDATES:
        try:
            module = importlib.import_module(module_name)
            if hasattr(module, "ask_codex"):
                return module
        except Exception as exc:
            errors.append(f"{module_name}: {type(exc).__name__}: {exc}")

    raise RuntimeError(
        "Unable to load codex_provider from candidates: "
        + " | ".join(errors)
    )


async def describe_image(
    *,
    image_path: str | None = None,
    image_bytes: bytes | None = None,
    mime_type: str | None = None,
    prompt: str | None = None,
    context: dict[str, Any] | None = None,
) -> CodexVisionResult:
    """通过 Codex CLI --image 注入图片, 真实调用多模态视觉。"""

    raw_bytes = b""
    source_path_name = ""
    if image_bytes:
        raw_bytes = bytes(image_bytes)
    elif image_path:
        path = Path(image_path)
        source_path_name = path.name
        if not path.exists():
            logger.warning(
                "codex_vision_adapter failed error=image_file_not_found mime=%s bytes=0 image_basename=%s",
                mime_type, source_path_name,
            )
            return CodexVisionResult(ok=False, error="image_file_not_found", source=SOURCE_CODEX_CLI_IMAGE)
        if path.stat().st_size > MAX_IMAGE_BYTES:
            logger.warning(
                "codex_vision_adapter failed error=image_too_large mime=%s bytes=%s image_basename=%s",
                mime_type, path.stat().st_size, source_path_name,
            )
            return CodexVisionResult(ok=False, error="image_too_large", source=SOURCE_CODEX_CLI_IMAGE)
        raw_bytes = path.read_bytes()
    else:
        logger.warning(
            "codex_vision_adapter failed error=missing_image_data mime=%s bytes=0",
            mime_type,
        )
        return CodexVisionResult(ok=False, error="missing_image_data", source=SOURCE_CODEX_CLI_IMAGE)

    if len(raw_bytes) > MAX_IMAGE_BYTES:
        logger.warning(
            "codex_vision_adapter failed error=image_too_large mime=%s bytes=%s",
            mime_type, len(raw_bytes),
        )
        return CodexVisionResult(ok=False, error="image_too_large", source=SOURCE_CODEX_CLI_IMAGE)

    final_mime = _guess_mime_type(raw_bytes, fallback=mime_type)
    if final_mime not in ALLOWED_IMAGE_MIME_TYPES:
        logger.warning(
            "codex_vision_adapter failed error=unsupported_mime_type:%s mime=%s bytes=%s",
            final_mime, final_mime, len(raw_bytes),
        )
        return CodexVisionResult(
            ok=False, error=f"unsupported_mime_type:{final_mime}", source=SOURCE_CODEX_CLI_IMAGE
        )

    codex_image_path: str
    if image_path:
        path = Path(image_path)
        if path.exists():
            codex_image_path = str(path)
            image_basename = path.name
        else:
            logger.warning(
                "codex_vision_adapter failed error=image_file_not_found mime=%s bytes=0 image_basename=%s",
                final_mime, path.name,
            )
            return CodexVisionResult(
                ok=False, error="image_file_not_found", source=SOURCE_CODEX_CLI_IMAGE
            )
    else:
        ext = MIME_TO_EXT.get(final_mime, ".bin")
        sha = hashlib.sha256(raw_bytes).hexdigest()[:16]
        filename = f"codex_vision_{sha}{ext}"
        try:
            tmp_dir = Path(VISION_TMP_DIR)
            tmp_dir.mkdir(parents=True, exist_ok=True)
            tmp_path = tmp_dir / filename
            tmp_path.write_bytes(raw_bytes)
            codex_image_path = str(tmp_path)
            image_basename = filename
        except Exception as exc:
            logger.warning(
                "codex_vision_adapter failed error=image_write_error:%s mime=%s bytes=%s",
                type(exc).__name__, final_mime, len(raw_bytes),
            )
            return CodexVisionResult(
                ok=False,
                error=f"image_write_error:{type(exc).__name__}",
                source=SOURCE_CODEX_CLI_IMAGE,
            )

    if not Path(codex_image_path).exists():
        logger.warning(
            "codex_vision_adapter failed error=image_path_not_accessible "
            "mime=%s bytes=%s image_basename=%s",
            final_mime, len(raw_bytes), image_basename,
        )
        return CodexVisionResult(
            ok=False,
            error="image_path_not_accessible",
            source=SOURCE_CODEX_CLI_IMAGE,
        )

    try:
        config = _load_plugin_config()
    except Exception as exc:
        logger.warning(
            "codex_vision_adapter failed error=config_load_error:%s mime=%s bytes=%s",
            type(exc).__name__, final_mime, len(raw_bytes),
        )
        return CodexVisionResult(
            ok=False,
            error=f"config_load_error:{type(exc).__name__}",
            source=SOURCE_CODEX_CLI_IMAGE,
        )

    try:
        provider = _get_codex_provider_module()
        ask_codex = provider.ask_codex
    except Exception as exc:
        logger.warning(
            "codex_vision_adapter failed error=codex_provider_import_error:%s mime=%s bytes=%s",
            type(exc).__name__, final_mime, len(raw_bytes),
        )
        return CodexVisionResult(
            ok=False,
            error=f"codex_provider_import_error:{type(exc).__name__}",
            source=SOURCE_CODEX_CLI_IMAGE,
        )

    vision_prompt = prompt or DEFAULT_VISION_PROMPT

    try:
        result = await ask_codex(config, vision_prompt, image_paths=[codex_image_path])
    except Exception as exc:
        logger.warning(
            "codex_vision_adapter failed error=codex_cli_image_error:%s:%s "
            "mime=%s bytes=%s image_basename=%s",
            type(exc).__name__, exc, final_mime, len(raw_bytes), image_basename,
        )
        return CodexVisionResult(
            ok=False,
            error=f"codex_cli_image_error:{type(exc).__name__}:{exc}",
            source=SOURCE_CODEX_CLI_IMAGE,
        )

    if not result.ok:
        reason = result.reason or "codex_cli_failed"
        logger.warning(
            "codex_vision_adapter failed error=codex_cli_image_error:%s "
            "mime=%s bytes=%s image_basename=%s",
            reason, final_mime, len(raw_bytes), image_basename,
        )
        return CodexVisionResult(
            ok=False,
            error=f"codex_cli_image_error:{reason}",
            source=SOURCE_CODEX_CLI_IMAGE,
        )

    text = (result.text or "").strip()
    if not text:
        logger.warning(
            "codex_vision_adapter failed error=empty_vision_response "
            "mime=%s bytes=%s image_basename=%s",
            final_mime, len(raw_bytes), image_basename,
        )
        return CodexVisionResult(
            ok=False, error="empty_vision_response", source=SOURCE_CODEX_CLI_IMAGE
        )

    logger.info(
        "codex_vision_adapter success source=codex_cli_image mime=%s bytes=%s "
        "image_basename=%s chars=%s",
        final_mime, len(raw_bytes), image_basename, len(text),
    )
    return CodexVisionResult(ok=True, text=text, error=None, source=SOURCE_CODEX_CLI_IMAGE)
