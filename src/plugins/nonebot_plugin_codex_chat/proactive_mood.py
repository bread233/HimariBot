"""Strict process-local quota for planner-labelled mood expression.

Reservation is acquired before reply generation; successful host delivery commits
it. Uncertain delivery holds the reservation until expiry (fail closed).
"""
from __future__ import annotations

import time
import uuid
from datetime import datetime
from threading import RLock

from .mood_state import get_mood_snapshot

COOLDOWN_SECONDS = 3 * 60 * 60
DAILY_LIMIT = 2
RESERVATION_SECONDS = 15 * 60
_lock = RLock()
_usage: dict[str, tuple[str, int, float]] = {}
_reservations: dict[str, tuple[str, str, float]] = {}


def _eligible_mood() -> bool:
    state = get_mood_snapshot()
    return state.sociability >= 45 and state.energy >= 35 and not 40 <= state.valence <= 65


def _quota_available(group_id: str, now: float, today: str) -> bool:
    day, count, last = _usage.get(group_id, ("", 0, 0.0))
    if day != today:
        count = 0
    if count >= DAILY_LIMIT or (last and now - last < COOLDOWN_SECONDS):
        return False
    return not any(gid == group_id for gid, _, _ in _reservations.values())


def _expire(now: float) -> None:
    for token, (_, _, created) in list(_reservations.items()):
        if now - created >= RESERVATION_SECONDS:
            del _reservations[token]


def can_express(group_id: str) -> bool:
    if not group_id or not _eligible_mood():
        return False
    now = time.monotonic()
    with _lock:
        _expire(now)
        return _quota_available(str(group_id), now, datetime.now().date().isoformat())


def reserve_expression(group_id: str) -> str | None:
    if not group_id or not _eligible_mood():
        return None
    now = time.monotonic()
    today = datetime.now().date().isoformat()
    with _lock:
        _expire(now)
        if not _quota_available(str(group_id), now, today):
            return None
        token = uuid.uuid4().hex
        _reservations[token] = (str(group_id), today, now)
        return token


def release_expression(token: str) -> bool:
    with _lock:
        return _reservations.pop(token, None) is not None


def confirm_delivered(group_id: str, token: str) -> bool:
    if not token or not group_id:
        return False
    with _lock:
        _expire(time.monotonic())
        item = _reservations.get(token)
        if item is None or item[0] != str(group_id):
            return False
        del _reservations[token]
        day, count, _ = _usage.get(str(group_id), ("", 0, 0.0))
        today = datetime.now().date().isoformat()
        _usage[str(group_id)] = (today, (count if day == today else 0) + 1, time.monotonic())
        return True


def planner_mood_guidance(group_id: str) -> str:
    if not group_id:
        return ""
    if not can_express(group_id):
        return "【主动情绪表达限制】当前不要为了表达自己的情绪而主动发言；正常回答和自然接话不受影响。"
    return (
        "【主动情绪表达】只有存在自然接话机会且主要为了表达当前情绪时，"
        "才在reply工具设置mood_expression=true；正常回答、接话、回应@一律为false。"
        "人格优先，不要索取关注、责怪沉默或重复表达；可以选择不说话。"
    )

# Compatibility with the current reply/capture bridge until token propagation is wired.
# These helpers are intentionally separate from the reservation API.
_pending_legacy: dict[str, tuple[str, float]] = {}

def stage_expression(group_id: str, text: str) -> bool:
    if not group_id or not text.strip() or not can_express(group_id):
        return False
    with _lock:
        _pending_legacy[str(group_id)] = (text.strip(), time.monotonic())
    return True

_legacy_confirm_delivered = confirm_delivered

def confirm_delivered(group_id: str, token_or_text: str) -> bool:
    with _lock:
        if token_or_text in _reservations:
            return _legacy_confirm_delivered(group_id, token_or_text)
        candidate = _pending_legacy.get(str(group_id))
        if not candidate or candidate[0] != token_or_text.strip() or time.monotonic() - candidate[1] > 120:
            return False
        _pending_legacy.pop(str(group_id), None)
        if not can_express(group_id):
            return False
        today = datetime.now().date().isoformat()
        day, count, _ = _usage.get(str(group_id), ("", 0, 0.0))
        _usage[str(group_id)] = (today, (count if day == today else 0) + 1, time.monotonic())
        return True
