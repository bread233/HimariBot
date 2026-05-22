from __future__ import annotations

from pathlib import Path
import re
import time

try:
    from nonebot import logger
except Exception:
    import logging

    logger = logging.getLogger("codex_chat")

_SECTION_NAME_RE = re.compile(r"^##\s*([a-zA-Z_]+)(?:\s*\+?\s*(-?\d+))?\s*$")
_BULLET_RE = re.compile(r"^\s*-\s+(.*)\s*$")

_ALLOWED_SECTIONS = {
    "active",
    "technical",
    "technical_error",
    "culture",
    "news",
    "activity",
    "question",
    "sharp",
    "life",
    "low_value",
    "zero",
    "service_request",
}

_DEFAULT_WEIGHTS = {
    "active": 5,
    "technical": 6,
    "technical_error": 2,
    "culture": 6,
    "news": 3,
    "activity": 8,
    "question": 2,
    "sharp": 3,
    "life": 5,
    "low_value": 0,
    "zero": 0,
    "service_request": 0,
}

_cache: dict[str, dict] = {}
_reload_seconds = 10


def _parse_interest_markdown(markdown_text: str) -> dict:
    sections: dict[str, dict] = {}
    current_section: str | None = None
    current_weight: int | None = None

    for raw in (markdown_text or "").splitlines():
        line = raw.rstrip()
        m = _SECTION_NAME_RE.match(line.strip())
        if m:
            name = (m.group(1) or "").strip().lower()
            if name not in _ALLOWED_SECTIONS:
                current_section = None
                current_weight = None
                continue
            current_section = name
            w_raw = (m.group(2) or "").strip()
            if w_raw:
                try:
                    current_weight = int(w_raw)
                except Exception:
                    current_weight = _DEFAULT_WEIGHTS.get(name, 0)
            else:
                current_weight = _DEFAULT_WEIGHTS.get(name, 0)
            sections.setdefault(current_section, {"weight": current_weight, "items": []})
            sections[current_section]["weight"] = current_weight
            continue

        if not current_section:
            continue
        b = _BULLET_RE.match(line)
        if not b:
            continue
        item = (b.group(1) or "").strip()
        if not item:
            continue
        sections[current_section]["items"].append(item)

    return sections


def _validate_regex_piece(piece: str) -> bool:
    try:
        re.compile(f"(?:{piece})", flags=re.I)
        return True
    except re.error:
        return False


def _normalize_items(items: list[str]) -> tuple[list[str], list[str]]:
    out: list[str] = []
    raw_terms: list[str] = []
    seen: set[str] = set()
    for item in items or []:
        s = str(item or "").strip()
        if not s:
            continue
        key = s.lower()
        if key in seen:
            continue
        seen.add(key)
        raw_terms.append(s)
        if s.lower().startswith("regex:"):
            piece = s[6:].strip()
            if not piece:
                continue
            if not _validate_regex_piece(piece):
                logger.warning("codex_chat interest_skill invalid_regex=1")
                continue
            out.append(piece)
        else:
            out.append(re.escape(s))
    return out, raw_terms


def load_interest_skill(path: str, force: bool = False) -> dict:
    p = str(path or "").strip()
    if not p:
        return {"path": p, "mtime": 0.0, "patterns": {}, "weights": {}, "terms": {}}

    now = time.time()
    cached = _cache.get(p)
    if cached and not force:
        checked_at = float(cached.get("checked_at", 0.0) or 0.0)
        if _reload_seconds > 0 and (now - checked_at) < _reload_seconds:
            return dict(cached.get("value") or {})

    try:
        fp = Path(p)
        if not fp.is_file():
            value = {"path": p, "mtime": 0.0, "patterns": {}, "weights": {}, "terms": {}}
            _cache[p] = {"checked_at": now, "mtime": 0.0, "value": value}
            return dict(value)
        mtime = fp.stat().st_mtime
        if cached and not force and float(cached.get("mtime", 0.0) or 0.0) == float(mtime):
            cached["checked_at"] = now
            return dict(cached.get("value") or {})
        text = fp.read_text(encoding="utf-8")
    except Exception:
        value = {"path": p, "mtime": 0.0, "patterns": {}, "weights": {}, "terms": {}}
        _cache[p] = {"checked_at": now, "mtime": 0.0, "value": value}
        return dict(value)

    sections = _parse_interest_markdown(text)
    patterns: dict[str, str] = {}
    weights: dict[str, int] = {}
    terms: dict[str, list[str]] = {}
    for sec, payload in (sections or {}).items():
        weight = int(payload.get("weight", _DEFAULT_WEIGHTS.get(sec, 0)) or 0)
        items = payload.get("items") or []
        pieces, raw_terms = _normalize_items(items)
        if raw_terms:
            terms[sec] = raw_terms
        weights[sec] = weight
        if pieces:
            patterns[sec] = "(?:" + "|".join(pieces) + ")"

    value = {"path": p, "mtime": float(mtime), "patterns": patterns, "weights": weights, "terms": terms}
    _cache[p] = {"checked_at": now, "mtime": float(mtime), "value": value}
    return dict(value)
