"""Direct QQ affinity query, independent of Planner and LLM."""

from __future__ import annotations

import re
from typing import Callable

from src.common.database.affinity_store import get_or_create_affinity

_QUERY = re.compile(r"^查看好感度[！!。\s]*$")


def is_affinity_query(text: str) -> bool:
    return bool(_QUERY.fullmatch(str(text).strip()))


def affinity_level(score: float) -> str:
    """Presentation bands; internal score is never sent to QQ."""
    if score < 0:
        return "厌恶"
    if score < 20:
        return "正常"
    if score < 40:
        return "熟悉"
    if score < 60:
        return "亲近"
    if score < 80:
        return "亲密"
    return "喜欢"


def build_affinity_query_reply(
    qq_id: str, nickname: str, mood_label: Callable[[], str]
) -> str:
    from .mood_state import get_recent_emotion

    record = get_or_create_affinity(qq_id)
    mood = str(mood_label() or "平静").strip()
    name = str(nickname or "你").strip().replace("\n", " ")[:40]
    mood_emoji = {"小开心": "😊", "开心": "😄", "兴奋": "🤩", "低落": "🥺", "烦躁": "😠", "疲惫": "😴", "平静": "😌", "不太想说话": "😶"}.get(mood, "😌")
    score = f"{record.affinity_score:.4f}".rstrip("0").rstrip(".")
    return (f"对{name}的好感：{score} / 100\n"
            f"关系等级：{affinity_level(record.affinity_score)}\n"
            f"当前心情：{mood}{mood_emoji}\n"
            f"最近情绪：{get_recent_emotion(qq_id)}")
