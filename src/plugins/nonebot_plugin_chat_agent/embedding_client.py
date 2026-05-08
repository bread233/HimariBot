from __future__ import annotations

import math

import httpx

from .retrieval_store import get_cached_embedding, set_cached_embedding

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
    return [[float(x) for x in row] for row in embeddings]


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


async def embed_texts_with_cache(config, items: list[dict]) -> list[list[float]]:
    ordered: list[list[float] | None] = [None] * len(items)
    missing_positions: list[int] = []
    missing_texts: list[str] = []
    missing_meta: list[tuple[str, str]] = []

    for idx, item in enumerate(items):
        source = str(item.get("source", "")).strip()
        content = str(item.get("content", "")).strip()
        if not content:
            ordered[idx] = []
            continue
        cached = await get_cached_embedding(config, source, content)
        if cached is not None:
            ordered[idx] = cached
            continue
        missing_positions.append(idx)
        missing_texts.append(content)
        missing_meta.append((source, content))

    if missing_texts:
        computed = await embed_texts(config, missing_texts)
        for i, vec in enumerate(computed):
            pos = missing_positions[i]
            source, content = missing_meta[i]
            ordered[pos] = vec
            try:
                await set_cached_embedding(config, source, content, vec)
            except Exception:
                pass

    return [vec or [] for vec in ordered]
