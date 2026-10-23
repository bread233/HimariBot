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
    record = get_or_create_affinity(qq_id)
    mood = str(mood_label() or "平静").strip()
    name = str(nickname or "你").strip().replace("\n", " ")[:40]
    return f"心情：{mood}\n对{name}的好感：{affinity_level(record.affinity_score)}"
