from __future__ import annotations

import time

import httpx


async def extract_with_ollama_vision(
    *,
    base_url: str,
    model: str,
    images_base64: list[str],
    timeout: float,
    max_tokens: int,
    keep_alive: str,
) -> dict:
    t0 = time.perf_counter()
    url = f"{str(base_url or '').rstrip('/')}/api/chat"
    payload = {
        "model": model,
        "stream": False,
        "keep_alive": keep_alive,
        "options": {"num_predict": max(16, int(max_tokens or 160)), "temperature": 0},
        "messages": [
            {
                "role": "user",
                "content": "请用中文简短提取图片信息。按以下格式输出，不要解释：summary: ... ocr: ... objects: ...",
                "images": images_base64,
            }
        ],
    }
    try:
        async with httpx.AsyncClient(timeout=float(timeout or 120.0), follow_redirects=True) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json() or {}
        content = str(((data.get("message") or {}).get("content") or "")).strip()
        elapsed = round(time.perf_counter() - t0, 3)
        if not content:
            return {
                "success": False,
                "content": "",
                "elapsed": elapsed,
                "model": model,
                "provider": "ollama_native",
                "error": "empty_content",
            }
        return {
            "success": True,
            "content": content,
            "elapsed": elapsed,
            "model": model,
            "provider": "ollama_native",
            "error": "",
        }
    except Exception as e:
        return {
            "success": False,
            "content": "",
            "elapsed": round(time.perf_counter() - t0, 3),
            "model": model,
            "provider": "ollama_native",
            "error": f"{type(e).__name__}:{str(e)[:120]}",
        }
