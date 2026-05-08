from __future__ import annotations

import math

import httpx


async def embed_texts(config, texts: list[str]) -> list[list[float]]:
    base_url = str(getattr(config, "chat_agent_embedding_base_url", "http://192.168.0.112:11434")).rstrip("/")
    model = str(getattr(config, "chat_agent_embedding_model", "hf.co/Qwen/Qwen3-Embedding-0.6B-GGUF:Q8_0"))
    timeout = int(getattr(config, "chat_agent_embedding_timeout", 30))
    payload = {"model": model, "input": texts}
    async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
        resp = await client.post(f"{base_url}/api/embed", json=payload)
        resp.raise_for_status()
    data = resp.json()
    embeddings = data.get("embeddings") or []
    if not isinstance(embeddings, list) or not embeddings:
        raise RuntimeError(f"empty embeddings response: {data}")
    return embeddings


def cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b:
        return 0.0
    size = min(len(a), len(b))
    dot = sum(a[i] * b[i] for i in range(size))
    na = math.sqrt(sum(a[i] * a[i] for i in range(size)))
    nb = math.sqrt(sum(b[i] * b[i] for i in range(size)))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)
