from __future__ import annotations

import json
from urllib.parse import urlparse

import httpx
from nonebot import logger


def _get_config_or_env(config, attr_name: str, env_name: str, default=None):
    value = getattr(config, attr_name, None)
    if value is not None and str(value).strip() != "":
        return value
    import os
    env_value = os.getenv(env_name)
    if env_value is not None and str(env_value).strip() != "":
        return env_value
    return default


def _parse_extra_body(value) -> dict:
    if value is None:
        return {}
    text = str(value).strip()
    if not text:
        return {}
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except Exception as exc:
        logger.warning(f"chat_agent_llm extra_body parse failed: {type(exc).__name__}")
    return {}


def _build_openai_chat_url(base_url: str) -> str:
    base = str(base_url or "").strip().rstrip("/")
    if not base:
        return "/chat/completions"
    if base.endswith("/chat/completions"):
        return base
    if base.endswith("/v1"):
        return f"{base}/chat/completions"
    return f"{base}/v1/chat/completions"


def _is_finalizer_model_name(model_name: str) -> bool:
    text = str(model_name or "").strip().lower()
    return "finalizer" in text or "lightweight" in text


def _resolve_llm_profile(config, purpose: str = "default") -> dict:
    use_finalizer = purpose == "finalizer"
    if use_finalizer:
        base_url = _get_config_or_env(config, "chat_agent_finalizer_llm_base_url", "CHAT_AGENT_FINALIZER_LLM_BASE_URL", "") or _get_config_or_env(config, "chat_agent_llm_base_url", "CHAT_AGENT_LLM_BASE_URL", "") or getattr(config, "chat_agent_base_url", "")
        api_key = _get_config_or_env(config, "chat_agent_finalizer_llm_api_key", "CHAT_AGENT_FINALIZER_LLM_API_KEY", "") or _get_config_or_env(config, "chat_agent_llm_api_key", "CHAT_AGENT_LLM_API_KEY", "") or getattr(config, "chat_agent_api_key", "")
        model = _get_config_or_env(config, "chat_agent_finalizer_llm_model", "CHAT_AGENT_FINALIZER_LLM_MODEL", "") or _get_config_or_env(config, "chat_agent_llm_model", "CHAT_AGENT_LLM_MODEL", "") or getattr(config, "chat_agent_lightweight_definition_model", "") or getattr(config, "chat_agent_model", "")
        timeout = _get_config_or_env(config, "chat_agent_finalizer_llm_timeout", "CHAT_AGENT_FINALIZER_LLM_TIMEOUT", 0) or _get_config_or_env(config, "chat_agent_llm_timeout", "CHAT_AGENT_LLM_TIMEOUT", 0) or getattr(config, "chat_agent_lightweight_definition_timeout", 0) or getattr(config, "chat_agent_timeout", 120)
        max_tokens = _get_config_or_env(config, "chat_agent_finalizer_llm_max_tokens", "CHAT_AGENT_FINALIZER_LLM_MAX_TOKENS", 0) or _get_config_or_env(config, "chat_agent_llm_max_tokens", "CHAT_AGENT_LLM_MAX_TOKENS", 0) or getattr(config, "chat_agent_web_strategy_max_tokens", 0) or getattr(config, "chat_agent_max_tokens", 512)
        extra_body = _parse_extra_body(_get_config_or_env(config, "chat_agent_finalizer_llm_extra_body", "CHAT_AGENT_FINALIZER_LLM_EXTRA_BODY", "") or _get_config_or_env(config, "chat_agent_llm_extra_body", "CHAT_AGENT_LLM_EXTRA_BODY", ""))
    else:
        base_url = _get_config_or_env(config, "chat_agent_llm_base_url", "CHAT_AGENT_LLM_BASE_URL", "") or getattr(config, "chat_agent_base_url", "")
        api_key = _get_config_or_env(config, "chat_agent_llm_api_key", "CHAT_AGENT_LLM_API_KEY", "") or getattr(config, "chat_agent_api_key", "")
        model = _get_config_or_env(config, "chat_agent_llm_model", "CHAT_AGENT_LLM_MODEL", "") or getattr(config, "chat_agent_model", "")
        timeout = _get_config_or_env(config, "chat_agent_llm_timeout", "CHAT_AGENT_LLM_TIMEOUT", 0) or getattr(config, "chat_agent_timeout", 120)
        max_tokens = _get_config_or_env(config, "chat_agent_llm_max_tokens", "CHAT_AGENT_LLM_MAX_TOKENS", 0) or getattr(config, "chat_agent_max_tokens", 512)
        extra_body = _parse_extra_body(_get_config_or_env(config, "chat_agent_llm_extra_body", "CHAT_AGENT_LLM_EXTRA_BODY", ""))
    if "think" not in extra_body and hasattr(config, "chat_agent_think"):
        extra_body["think"] = bool(getattr(config, "chat_agent_think"))
    return {
        "base_url": str(base_url or "").strip(),
        "api_key": str(api_key or "").strip(),
        "model": str(model or "").strip(),
        "timeout": float(timeout),
        "max_tokens": int(max_tokens),
        "extra_body": extra_body,
    }


async def chat_completions(
    messages,
    config,
    timeout=None,
    model=None,
    temperature=None,
    top_p=None,
    max_tokens=None,
):
    purpose = "finalizer" if _is_finalizer_model_name(str(model or "")) else "default"
    profile = _resolve_llm_profile(config, purpose=purpose)
    url = _build_openai_chat_url(profile["base_url"])
    headers = {"Content-Type": "application/json"}
    api_key = str(profile["api_key"] or "")
    if api_key and api_key.strip().lower() not in {"none", "null"}:
        headers["Authorization"] = f"Bearer {api_key}"
    model_name = str(model or profile["model"] or getattr(config, "chat_agent_model", ""))
    payload = {
        "model": model_name,
        "messages": messages,
        "temperature": 0.8 if temperature is None else temperature,
        "top_p": 0.9 if top_p is None else top_p,
        "max_tokens": profile["max_tokens"] if max_tokens is None else max_tokens,
    }
    payload.update(profile["extra_body"] or {})
    parsed = urlparse(url)
    logger.info(
        f"chat_agent_llm request purpose={purpose} model={model_name} host={parsed.netloc} path={parsed.path}"
    )
    try:
        client_timeout = profile["timeout"] if timeout is None else timeout
        async with httpx.AsyncClient(timeout=client_timeout) as client:
            resp = await client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPError as exc:
        raise RuntimeError("模型接口暂时没有响应。") from exc

    try:
        return data["choices"][0]["message"]["content"]
    except Exception as exc:
        raise RuntimeError("模型接口返回格式异常。") from exc
