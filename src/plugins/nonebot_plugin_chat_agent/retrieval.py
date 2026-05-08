from __future__ import annotations

import re

from .embedding_client import cosine_similarity, embed_texts_with_cache

_STOPWORDS = {
    "用户",
    "纠正",
    "提醒",
    "不要",
    "不是",
    "以后",
    "应该",
    "可以",
    "这个",
    "那个",
    "什么",
    "怎么",
    "没有",
    "知道",
    "如果",
    "已经",
    "当前",
    "回答",
    "问题",
    "模型",
    "旧知识",
    "乱说",
    "一个",
    "一下",
    "因为",
    "所以",
    "但是",
    "然后",
    "就是",
    "刚才",
    "刚刚",
    "之前",
}


def _extract_english_tokens(text: str) -> list[str]:
    return [token for token in re.findall(r"[a-z0-9_.-]+", (text or "").lower()) if len(token) >= 2]


def _extract_chinese_ngrams(text: str) -> list[str]:
    chunks = re.findall(r"[\u4e00-\u9fff]+", text or "")
    result: list[str] = []
    for chunk in chunks:
        if len(chunk) < 2:
            continue
        for size in range(2, min(4, len(chunk)) + 1):
            for idx in range(0, len(chunk) - size + 1):
                token = chunk[idx : idx + size]
                if token in _STOPWORDS:
                    continue
                result.append(token)
    return result


def _tokenize(text: str) -> list[str]:
    tokens = _extract_english_tokens(text)
    tokens.extend(_extract_chinese_ngrams(text))
    return [token for token in tokens if token not in _STOPWORDS]


def score_text_overlap(query: str, text: str) -> float:
    q_tokens = set(_tokenize(query))
    t_tokens = set(_tokenize(text))
    if not q_tokens or not t_tokens:
        return 0.0
    overlap = q_tokens.intersection(t_tokens)
    if not overlap:
        return 0.0
    precision = len(overlap) / len(q_tokens)
    recall = len(overlap) / len(t_tokens)
    score = (precision * 0.7) + (recall * 0.3)
    return max(0.0, min(1.0, score))


def build_retrieval_context(prompt: str, profile_context: str, group_context: str, memory_context: str, history_context: str) -> dict:
    candidates = [
        ("profile", profile_context or "", score_text_overlap(prompt, profile_context or "")),
        ("group", group_context or "", score_text_overlap(prompt, group_context or "")),
        ("memory", memory_context or "", score_text_overlap(prompt, memory_context or "")),
        ("history", history_context or "", score_text_overlap(prompt, history_context or "")),
    ]
    if prompt and ("刚才" in prompt or "刚刚" in prompt or "之前" in prompt or "测什么" in prompt or "说了什么" in prompt):
        candidates = [
            (name, text, score + (0.12 if name == "history" and text else 0.0))
            for name, text, score in candidates
        ]
    if prompt and ("我是谁" in prompt or "我叫什么" in prompt or "我在群里叫什么" in prompt):
        candidates = [
            (name, text, score + (0.15 if name in {"profile", "group"} and text else 0.0))
            for name, text, score in candidates
        ]
    if prompt and ("纠正" in prompt or "不是" in prompt or "不对" in prompt):
        candidates = [
            (name, text, score + (0.08 if name == "memory" and text else 0.0))
            for name, text, score in candidates
        ]
    best_name = "none"
    best_text = ""
    best_score = 0.0
    for name, text, score in candidates:
        if score > best_score:
            best_name = name
            best_text = text
            best_score = score
    if best_score >= 0.45 and best_text:
        return {
            "score": best_score,
            "source": "db",
            "content": best_text[:2000].strip(),
            "notes": f"best_source={best_name}",
        }
    return {"score": best_score, "source": "none", "content": "", "notes": f"best_source={best_name}"}


def build_embedding_query(prompt: str) -> str:
    return f"为这个问题检索最相关的历史纠错、用户画像或聊天记录：{prompt}"


def build_embedding_doc(source: str, content: str) -> str:
    if source in {"correction", "memory"}:
        return f"历史纠错规则：{content}"
    if source == "profile":
        return f"用户画像：{content}"
    if source == "group":
        return f"当前群信息：{content}"
    if source == "history":
        return f"聊天记录：{content}"
    if source == "web":
        return f"网页资料：{content}"
    return f"资料不足说明：{content}"


def source_bonus(source: str) -> float:
    if source in {"correction", "memory"}:
        return 0.04
    if source in {"profile", "group"}:
        return 0.02
    if source == "history":
        return 0.01
    return 0.0


async def build_embedding_retrieval_context(config, prompt: str, candidates: list[dict]) -> dict:
    usable = []
    for item in candidates:
        source = str(item.get("source", "")).strip()
        content = str(item.get("content", "")).strip()
        if source and content:
            usable.append({"source": source, "content": content})
    if not usable:
        return {"status": "empty", "score": 0.0, "weighted_score": 0.0, "margin": 0.0, "source": "", "content": "", "candidate_content": "", "notes": "embedding_empty"}

    query = build_embedding_query(prompt)
    docs = [build_embedding_doc(item["source"], item["content"]) for item in usable]
    embed_items = [{"source": "query", "content": query}] + [
        {"source": usable[idx]["source"], "content": docs[idx]} for idx in range(len(usable))
    ]
    try:
        vectors = await embed_texts_with_cache(config, embed_items)
    except Exception as e:
        return {"status": "error", "score": 0.0, "weighted_score": 0.0, "margin": 0.0, "source": "", "content": "", "candidate_content": "", "notes": f"embedding_error={type(e).__name__}"}

    if len(vectors) < 2:
        return {"status": "error", "score": 0.0, "weighted_score": 0.0, "margin": 0.0, "source": "", "content": "", "candidate_content": "", "notes": "embedding_invalid_response"}

    qv = vectors[0]
    scored = []
    for idx, item in enumerate(usable, start=1):
        score = cosine_similarity(qv, vectors[idx])
        weighted = score + source_bonus(item["source"])
        scored.append((item, score, weighted))
    scored.sort(key=lambda x: x[2], reverse=True)
    top1 = scored[0]
    top2_score = scored[1][1] if len(scored) > 1 else 0.0
    margin = top1[1] - top2_score

    reliable_score = float(getattr(config, "chat_agent_embedding_reliable_score", 0.68))
    candidate_score = float(getattr(config, "chat_agent_embedding_candidate_score", 0.60))
    min_margin = float(getattr(config, "chat_agent_embedding_min_margin", 0.05))

    notes = (
        f"embedding_top1={top1[0]['source']} "
        f"embedding_score={top1[1]:.4f} "
        f"embedding_weighted={top1[2]:.4f} "
        f"margin={margin:.4f}"
    )
    if top1[1] >= reliable_score and margin >= min_margin:
        return {
            "status": "reliable",
            "score": top1[1],
            "weighted_score": top1[2],
            "margin": margin,
            "source": top1[0]["source"],
            "content": top1[0]["content"],
            "candidate_content": "",
            "notes": notes,
        }
    if top1[1] >= candidate_score:
        return {
            "status": "candidate",
            "score": top1[1],
            "weighted_score": top1[2],
            "margin": margin,
            "source": top1[0]["source"],
            "content": "",
            "candidate_content": top1[0]["content"],
            "notes": notes,
        }
    return {
        "status": "low",
        "score": top1[1],
        "weighted_score": top1[2],
        "margin": margin,
        "source": top1[0]["source"],
        "content": "",
        "candidate_content": "",
        "notes": notes,
    }
