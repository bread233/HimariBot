from __future__ import annotations

import httpx


async def chat_completions(messages, config):
    url = f"{config.chat_agent_base_url.rstrip('/')}/chat/completions"
    headers = {
        "Authorization": f"Bearer {config.chat_agent_api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": config.chat_agent_model,
        "messages": messages,
        "temperature": 0.8,
        "top_p": 0.9,
        "max_tokens": config.chat_agent_max_tokens,
        "think": config.chat_agent_think,
    }
    try:
        async with httpx.AsyncClient(timeout=config.chat_agent_timeout) as client:
            resp = await client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPError as exc:
        raise RuntimeError("模型接口暂时没有响应。") from exc

    try:
        return data["choices"][0]["message"]["content"]
    except Exception as exc:
        raise RuntimeError("模型接口返回格式异常。") from exc
