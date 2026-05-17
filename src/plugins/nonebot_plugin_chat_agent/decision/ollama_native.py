from __future__ import annotations

from typing import Any

import httpx


async def coarse_chat_ollama_native(
    *,
    base_url: str,
    model: str,
    messages: list[dict[str, str]],
    timeout: float,
    max_tokens: int,
    api_key: str = "",
) -> str:
    base = str(base_url or "").strip().rstrip("/")
    if not base:
        raise ValueError("missing_base_url")
    if not model:
        raise ValueError("missing_model")
    url = f"{base}/api/chat"
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "think": False,
        "stream": False,
        "options": {"temperature": 0, "num_predict": int(max_tokens)},
    }
    headers: dict[str, str] = {}
    key = str(api_key or "").strip()
    if key and key.lower() not in {"empty", "none", "null"}:
        headers["Authorization"] = f"Bearer {key}"
    async with httpx.AsyncClient(timeout=float(timeout), follow_redirects=True, trust_env=False) as client:
        resp = await client.post(url, json=payload, headers=headers)
    resp.raise_for_status()
    data = resp.json() if resp.content else {}
    content = ""
    if isinstance(data, dict):
        msg = data.get("message")
        if isinstance(msg, dict):
            content = str(msg.get("content", "") or "").strip()
    return content

