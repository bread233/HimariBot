from __future__ import annotations

import json

from .query import get_recent_group_episodes, get_recent_long_memory_candidates, get_recent_user_episodes


_MAX_CHARS = 1200
_MIN_MAX_CHARS = 200
_MAX_MAX_CHARS = 3000


def _truncate(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "…"


def _as_int(value, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _as_float(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def build_memory_recall(
    group_id: str | None = None,
    user_id: str | None = None,
    limit: int = 5,
    min_importance: int = 0,
    min_confidence: float = 0.0,
    max_chars: int = _MAX_CHARS,
) -> str:
    lines: list[str] = []

    min_importance = _as_int(min_importance, default=0)
    min_confidence = _as_float(min_confidence, default=0.0)
    max_chars_raw = _as_int(max_chars, default=_MAX_CHARS)
    if max_chars_raw < _MIN_MAX_CHARS:
        max_chars = _MIN_MAX_CHARS
    elif max_chars_raw > _MAX_MAX_CHARS:
        max_chars = _MAX_MAX_CHARS
    else:
        max_chars = max_chars_raw

    if group_id:
        group_episodes = get_recent_group_episodes(group_id=group_id, limit=limit)

        for ep in group_episodes:
            if _as_int(ep.get("importance"), default=0) < min_importance:
                continue
            if _as_float(ep.get("confidence"), default=0.0) < min_confidence:
                continue

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
            if _as_int(ep.get("importance"), default=0) < min_importance:
                continue
            if _as_float(ep.get("confidence"), default=0.0) < min_confidence:
                continue

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
    return _truncate(recall_text, max_chars)


def _parse_json_list(value: object) -> list:
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                return parsed
        except Exception:
            pass
    return []


def build_long_memory_recall(
    group_id: str | None = None,
    user_id: str | None = None,
    limit: int = 10,
    min_importance: int = 0,
    min_confidence: float = 0.0,
    max_chars: int = _MAX_CHARS,
) -> str:
    if not group_id:
        return ""

    min_importance = max(0, min(_as_int(min_importance), 10))
    min_confidence = max(0.0, min(_as_float(min_confidence), 1.0))
    limit = max(1, min(_as_int(limit, default=10), 20))
    max_chars_raw = _as_int(max_chars, default=_MAX_CHARS)
    if max_chars_raw < _MIN_MAX_CHARS:
        max_chars = _MIN_MAX_CHARS
    elif max_chars_raw > _MAX_MAX_CHARS:
        max_chars = _MAX_MAX_CHARS
    else:
        max_chars = max_chars_raw

    candidates = get_recent_long_memory_candidates(
        group_id=group_id,
        status="approved",
        limit=limit,
    )

    lines: list[str] = []

    for c in candidates:
        if c.get("status") != "approved":
            continue

        imp = _as_int(c.get("importance"), default=0)
        if imp < min_importance:
            continue

        conf = _as_float(c.get("confidence"), default=0.0)
        if conf < min_confidence:
            continue

        summary = (c.get("summary") or "").strip()
        if not summary:
            continue

        c_user_id = (c.get("user_id") or "").strip()
        c_target_user_id = (c.get("target_user_id") or "").strip()

        is_group_level = not c_user_id and not c_target_user_id
        is_current_user = bool(user_id) and c_user_id == user_id
        is_current_target = bool(user_id) and c_target_user_id == user_id

        if user_id:
            if not (is_group_level or is_current_user or is_current_target):
                continue
        else:
            if not is_group_level:
                continue

        title = (c.get("title") or "").strip()
        scope_type = c.get("scope_type") or "?"
        memory_type = c.get("memory_type") or "?"
        keywords = _parse_json_list(c.get("keywords_json"))

        entry_lines = []
        if title:
            entry_lines.append(f"长期记忆：{title}")
        entry_lines.append(
            f"类型：{scope_type}/{memory_type} "
            f"重要度：{imp} 置信度：{conf}"
        )
        entry_lines.append(f"摘要：{summary}")

        if keywords:
            kw_text = "、".join(str(k) for k in keywords[:5])
            entry_lines.append(f"关键词：{kw_text}")

        lines.append("\n".join(entry_lines))

    recall_text = "\n\n".join(lines)
    return _truncate(recall_text, max_chars)
