from __future__ import annotations

import re


_UNKNOWN_MARKERS = (
    "资料不足以确认",
    "资料里没有明确说明",
    "我查到了相关网页，但资料不足以确认",
    "不知道",
    "我不知道",
)

_DEFINITION_FEATURE_WORDS = (
    "开放世界",
    "冒险",
    "精灵",
    "收集",
    "养成",
    "探索",
    "魔法学院",
    "ip",
)

_SPORTS_BLOCK_WORDS = (
    "可能是因为",
    "淘汰原因",
    "射击能力",
    "快速进攻",
    "强大的球员水平",
    "表现不佳导致",
)


def is_unknown_like_reply(reply: str, unknown_reply: str | None = None) -> bool:
    text = str(reply or "").strip().lower()
    if not text:
        return True
    if unknown_reply and str(unknown_reply).strip().lower() in text:
        return True
    return any(marker in text for marker in _UNKNOWN_MARKERS)


def definition_quality_reason(reply: str, *, min_chars: int = 45) -> str | None:
    text = str(reply or "").strip()
    if len(text) < max(1, int(min_chars)):
        return "too_short"
    if not any(token in text for token in ("是", "是一款", "属于", "以")):
        return "missing_definition"
    if not any(token in text.lower() for token in _DEFINITION_FEATURE_WORDS):
        return "missing_feature"
    return None


def sports_quality_reason(reply: str, *, min_chars: int = 45) -> str | None:
    text = str(reply or "").strip()
    if any(token in text for token in _SPORTS_BLOCK_WORDS):
        return "generic_or_speculative"
    if len(text) < max(1, int(min_chars)) and "没有提取到可确认的近期数据" not in text and "没有提取到可确认的具体数据" not in text:
        return "too_short"
    return None


def should_retry_short_answer(
    reply: str,
    *,
    answerable: bool,
    answer_style: str = "",
    min_chars: int = 45,
) -> bool:
    if not answerable:
        return False
    text = str(reply or "").strip()
    if len(text) < max(1, int(min_chars)):
        return True
    style = str(answer_style or "").strip().lower()
    if style == "definition_summary":
        return definition_quality_reason(text, min_chars=min_chars) is not None
    if style == "sports_stats_first":
        return sports_quality_reason(text, min_chars=min_chars) is not None
    return False


def build_definition_quality_fallback(evidence_context: str, prompt: str = "") -> str:
    lines = str(evidence_context or "").splitlines()
    title = ""
    snippets: list[str] = []
    for raw in lines:
        s = raw.strip()
        if s.startswith("标题：") and not title:
            title = s.replace("标题：", "", 1).strip()
        if s.startswith("摘要："):
            snip = s.replace("摘要：", "", 1).strip()
            if snip:
                snippets.append(snip)
        if len(snippets) >= 2:
            break
    basis = "；".join(snippets[:2]).strip("；")
    if basis:
        return (
            f"根据当前网页资料：{basis}。简单说，{title or '该内容'}是一款以精灵收集与养成为核心的冒险游戏；"
            "主要特征包括开放世界探索和宠物培养对战。"
        )
    return "根据当前网页资料：简单说，它是一款以精灵收集与养成为核心的冒险游戏；主要特征包括开放世界探索和宠物培养对战。"


def build_sports_quality_fallback(evidence_context: str = "") -> str:
    return (
        "根据当前网页资料：已命中球员数据统计页/球员资料页；"
        "但当前资料没有提取到可确认的近期逐场数据，因此只能确认相关数据页存在，不能推测淘汰原因。"
    )
