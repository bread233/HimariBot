from __future__ import annotations

import json
from .query import get_recent_group_episodes, get_recent_user_episodes


_MAX_CHARS = 1200


def _truncate(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "…"


def build_memory_recall(
    group_id: str | None = None,
    user_id: str | None = None,
    limit: int = 5,
) -> str:
    lines: list[str] = []

    if group_id:
        group_episodes = get_recent_group_episodes(group_id=group_id, limit=limit)

        for ep in group_episodes:
            summary = str(ep.get("summary", ""))
            topic = str(ep.get("topic", ""))
            keywords_raw = ep.get("keywords_json") or "[]"
            try:
                keywords = json.loads(str(keywords_raw))
            except Exception:
                keywords = []

            kw_text = ", ".join(str(k) for k in keywords[:5]) if keywords else ""

            line_parts = [summary]
            if topic:
                line_parts.append(f"话题：{topic}")
            if kw_text:
                line_parts.append(f"关键词：{kw_text}")

            lines.append(" ".join(line_parts))

    if user_id and group_id:
        user_episodes = get_recent_user_episodes(
            group_id=group_id, user_id=user_id, limit=limit
        )

        for ep in user_episodes:
            summary = str(ep.get("summary", ""))
            attitude = str(ep.get("attitude", ""))
            pref_raw = ep.get("preference_candidates_json") or "[]"
            try:
                prefs = json.loads(str(pref_raw))
            except Exception:
                prefs = []

            pref_text = ", ".join(str(p) for p in prefs[:3]) if prefs else ""

            line_parts = [summary]
            if attitude:
                line_parts.append(f"态度：{attitude}")
            if pref_text:
                line_parts.append(f"偏好候选：{pref_text}")

            lines.append(" ".join(line_parts))

    recall_text = "\n".join(lines)
    return _truncate(recall_text, _MAX_CHARS)
