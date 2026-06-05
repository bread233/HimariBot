from __future__ import annotations

from typing import Any

try:
    from ..config import get_config
except Exception:  # pragma: no cover - import compatibility for local smoke
    from config import get_config

try:
    from .common.logger import get_logger
except Exception:  # pragma: no cover - import compatibility for local smoke
    import logging

    def get_logger(name: str):
        return logging.getLogger(name)

logger = get_logger("codex_llm_adapter")


async def generate_text(
    prompt: str,
    *,
    system_prompt: str | None = None,
    request_type: str = "",
    image_base64: str | None = None,
    image_url: str | None = None,
    extra: dict | None = None,
) -> str:
    config = get_config()
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
