from __future__ import annotations

import json
import re
from typing import Any

from .query import (
    get_approved_long_memory_candidates_for_group,
    get_recent_group_episodes,
    get_recent_long_memory_candidates,
    get_recent_user_episodes,
)

_MAX_CHARS = 1200
_MIN_MAX_CHARS = 200
_MAX_MAX_CHARS = 3000
_QUERY_STOPWORDS = {
    "什么",
    "怎么",
    "如何",
    "是否",
    "这个",
    "那个",
    "群里",
    "一下",
    "请问",
}


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


def _normalize_query_text(value: object) -> str:
    text = str(value or "").strip().lower()
    if not text:
        return ""
    return re.sub(r"\s+", " ", text)


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


def _normalize_user_id_set(values: object) -> set[str]:
    if values is None:
        return set()
    if isinstance(values, str):
        values = [values]
    elif not isinstance(values, (list, tuple, set)):
        values = [values]

    out: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if not text or text.lower() == "all":
            continue
        out.add(text)
    return out


def _candidate_matches_target_user(candidate: dict[str, Any], target_user_ids: set[str]) -> bool:
    if not target_user_ids:
        return False
    user_id = str(candidate.get("user_id") or "").strip()
    target_user_id = str(candidate.get("target_user_id") or "").strip()
    return user_id in target_user_ids or target_user_id in target_user_ids


def _tokenize_memory_query(query: str) -> list[str]:
    normalized = _normalize_query_text(query)
    if not normalized:
        return []

    tokens: list[str] = []
    seen: set[str] = set()

    def add_token(token: str) -> None:
        token = token.strip().lower()
        if not token or token in _QUERY_STOPWORDS:
            return
        if token in seen:
            return
        seen.add(token)
        tokens.append(token)

    for part in re.findall(r"[a-z0-9_]+|[\u4e00-\u9fff]+", normalized):
        if re.fullmatch(r"[a-z0-9_]+", part):
            add_token(part)
            continue
        if len(part) <= 2:
            add_token(part)
            continue
        if len(part) <= 6:
            add_token(part)
        for size in range(2, min(6, len(part)) + 1):
            for i in range(0, len(part) - size + 1):
                add_token(part[i : i + size])

    return tokens[:30]


def _score_text_field(text: str, tokens: list[str]) -> float:
    if not text:
        return 0.0
    score = 0.0
    lowered = text.lower()
    for token in tokens:
        if token and token in lowered:
            score += 1.0
    return score


def _score_long_memory_for_query(candidate: dict[str, Any], query: str, tokens: list[str]) -> float:
    normalized_query = _normalize_query_text(query)
    if not normalized_query:
        return 0.0

    title = str(candidate.get("title") or "").strip()
    summary = str(candidate.get("summary") or "").strip()
    notes = str(candidate.get("notes") or "").strip()
    user_id = str(candidate.get("user_id") or "").strip().lower()
    target_user_id = str(candidate.get("target_user_id") or "").strip().lower()
    keywords = [str(item).strip().lower() for item in _parse_json_list(candidate.get("keywords_json")) if str(item).strip()]

    score = 0.0
    score += _score_text_field(title, tokens) * 4.0
    score += _score_text_field(summary, tokens) * 3.0
    score += _score_text_field(notes, tokens) * 1.0
    score += sum(5.0 for token in tokens if token and any(token in kw for kw in keywords))
    score += sum(8.0 for token in tokens if token and token == user_id)
    score += sum(8.0 for token in tokens if token and token == target_user_id)

    if normalized_query and (
        normalized_query in _normalize_query_text(title)
        or normalized_query in _normalize_query_text(summary)
        or any(normalized_query in kw for kw in keywords)
    ):
        score += 6.0

    if score <= 0.0:
        return 0.0

    score += _as_int(candidate.get("importance"), default=0) * 0.1
    score += _as_float(candidate.get("confidence"), default=0.0) * 0.5
    return score


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


def build_query_memory_recall(
    group_id: str,
    query: str,
    *,
    limit: int = 10,
    max_scan: int = 200,
    min_score: float = 1.0,
    max_chars: int = 1200,
    target_user_ids: list[str] | None = None,
    require_target_match: bool = False,
) -> str:
    group_id = str(group_id or "").strip()
    query = str(query or "").strip()
    if not group_id or not query:
        return ""

    limit = max(1, min(_as_int(limit, default=10), 20))
    max_scan = max(20, min(_as_int(max_scan, default=200), 200))
    max_chars = max(200, min(_as_int(max_chars, default=1200), 3000))
    min_score = max(0.0, _as_float(min_score, default=1.0))

    candidates = get_approved_long_memory_candidates_for_group(group_id, limit=max_scan)
    tokens = _tokenize_memory_query(query)
    if not tokens:
        return ""

    target_ids = _normalize_user_id_set(target_user_ids)
    scored: list[tuple[float, dict[str, Any]]] = []
    for candidate in candidates:
        target_matched = _candidate_matches_target_user(candidate, target_ids)
        if require_target_match and target_ids and not target_matched:
            continue

        score = _score_long_memory_for_query(candidate, query, tokens)
        if target_matched:
            score += 50.0
        if score < min_score:
            continue
        scored.append((score, candidate))

    if not scored:
        return ""

    scored.sort(
        key=lambda item: (
            -item[0],
            -_as_int(item[1].get("importance"), default=0),
            -_as_float(item[1].get("confidence"), default=0.0),
            -_as_int(item[1].get("updated_at"), default=0),
            -_as_int(item[1].get("id"), default=0),
        )
    )

    lines: list[str] = []
    for idx, (score, candidate) in enumerate(scored[:limit], 1):
        scope_type = candidate.get("scope_type") or "?"
        memory_type = candidate.get("memory_type") or "?"
        importance = candidate.get("importance", 0)
        confidence = candidate.get("confidence", 0.0)
        title = str(candidate.get("title") or "").strip()
        summary = str(candidate.get("summary") or "").strip()
        keywords = _parse_json_list(candidate.get("keywords_json"))
        user_id = str(candidate.get("user_id") or "").strip()
        target_user_id = str(candidate.get("target_user_id") or "").strip()

        lines.append(
            f"[{idx}] score={score:.2f} {scope_type}/{memory_type} "
            f"importance={importance} confidence={confidence}"
        )
        if title:
            lines.append(f"title={title}")
        if summary:
            lines.append(f"summary={summary}")
        if keywords:
            lines.append(f"keywords={'、'.join(str(k) for k in keywords[:8])}")
        if user_id:
            lines.append(f"user_id={user_id}")
        if target_user_id:
            lines.append(f"target_user_id={target_user_id}")

    return _truncate("\n".join(lines), max_chars)
