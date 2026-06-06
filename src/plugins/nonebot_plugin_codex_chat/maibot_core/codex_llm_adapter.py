from __future__ import annotations

import importlib
import sys
from typing import Any

try:
    from .common.logger import get_logger
except Exception:  # pragma: no cover - import compatibility for local smoke
    import logging

    def get_logger(name: str):
        return logging.getLogger(name)

logger = get_logger("codex_llm_adapter")


_PLUGIN_CONFIG_CANDIDATES = (
    "src.plugins.nonebot_plugin_codex_chat.config",
    "nonebot_plugin_codex_chat.config",
)


def _get_plugin_config():
    """惰性解析 Codex Chat 插件配置。

    优先级：
    1. ``sys.modules`` 中已注册的 ``src.plugins.nonebot_plugin_codex_chat.config``
    2. ``sys.modules`` 中已注册的 ``nonebot_plugin_codex_chat.config``
    3. 尝试 ``importlib.import_module`` 加载两者

    Returns:
        ConfigModel: nonebot 插件配置对象。

    Raises:
        RuntimeError: 当所有候选模块都不可用时抛出。
    """
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
        "Unable to load codex chat plugin config from candidates: "
        + " | ".join(errors)
    )


async def generate_text(
    prompt: str,
    *,
    system_prompt: str | None = None,
    request_type: str = "",
    image_base64: str | None = None,
    image_url: str | None = None,
    extra: dict | None = None,
) -> str:
    config = _get_plugin_config()
    logger.info(f"maibot_codex_llm request_type={request_type}")

    try:
        from ..codex_provider import ask_codex
    except Exception as exc:
        logger.exception(f"maibot_codex_llm failed error={exc}")
        return ""

    payload_parts: list[str] = []
    if system_prompt:
        payload_parts.append(f"[system]\n{system_prompt}")
    payload_parts.append(prompt)
    if image_url:
        payload_parts.append(f"[image_url]\n{image_url}")
    if image_base64:
        payload_parts.append("[image_base64]\n<base64 omitted>")
    if extra:
        payload_parts.append(f"[extra]\n{extra}")
    payload = "\n\n".join(payload_parts).strip()

    try:
        result = await ask_codex(config, payload)
        if not result.ok:
            logger.warning(f"maibot_codex_llm failed error={result.reason}")
            return ""
        text = (result.text or "").strip()
        logger.info(f"maibot_codex_llm success chars={len(text)}")
        return text
    except Exception as exc:
        logger.exception(f"maibot_codex_llm failed error={exc}")
        return ""
