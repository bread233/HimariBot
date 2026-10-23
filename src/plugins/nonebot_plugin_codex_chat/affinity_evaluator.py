"""Contextual affinity event classification, separate from Planner and Replyer."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from collections import defaultdict, deque
from datetime import datetime, timezone
from typing import Any

from .maibot_core.codex_llm_adapter import generate_text
from src.common.database.affinity_store import get_or_create_affinity
from src.common.database.database import get_db_session
from src.common.database.database_model import HimariBotAffinity
from .mood_state import get_affinity_mood_multiplier

log = logging.getLogger(__name__)
COOLDOWN_SECONDS = 60
MAX_DAILY_CHANGES = 20
EVENT_RANGES = {
    "ordinary": (0.0, 0.0),
    "friendly": (0.5, 2.0),
    "deep": (1.0, 3.0),
    "special_positive": (3.0, 5.0),
    "mild_negative": (-1.0, -0.5),
    "negative": (-3.0, -1.0),
    "special_negative": (-5.0, -3.0),
    "repair": (0.5, 3.0),
}
_history: dict[str, deque[str]] = defaultdict(lambda: deque(maxlen=8))
_inflight: set[str] = set()
_recent_events: dict[str, tuple[str, float]] = {}
_negative_streak: dict[str, tuple[str, int]] = {}
REPEAT_WINDOW_SECONDS = 30 * 60


def _parse_evaluation(raw: str) -> tuple[str, float] | None:
    match = re.search(r"\{[\s\S]*?\}", raw)
    if not match:
        return None
    try:
        data = json.loads(match.group())
        kind = str(data["event_type"])
        confidence = float(data["confidence"])
        delta = float(data["base_delta"])
        import math
        if kind not in EVENT_RANGES or not math.isfinite(delta) or not math.isfinite(confidence):
            return None
        low, high = EVENT_RANGES[kind]
        if confidence < 0.75 or not low <= delta <= high:
            return None
        return kind, delta
    except (KeyError, ValueError, TypeError, json.JSONDecodeError):
        return None


async def evaluate_affinity_event(
    qq_id: str, group_id: str, message: str, *, addressed: bool
) -> None:
    """Evaluate meaningful bot-directed events; failures never block chat."""
    qq_id = str(qq_id).strip()
    group_id = str(group_id).strip()
    message = str(message).strip()
    if not qq_id.isdecimal() or not message:
        return
    context = _history[group_id]
    context.append(f"{qq_id}: {message[:300]}")
    if not addressed or len(message) < 3 or qq_id in _inflight:
        return
    _inflight.add(qq_id)
    try:
        record = await asyncio.to_thread(get_or_create_affinity, qq_id)
        now = datetime.now(timezone.utc)
        if record.last_evaluated_at and (now - record.last_evaluated_at).total_seconds() < COOLDOWN_SECONDS:
            return
        if record.daily_reset_date == now.date().isoformat() and record.daily_change_count >= MAX_DAILY_CHANGES:
            return
        prompt = (
            "判断用户与机器人之间的互动事件。仅评价对机器人本人的态度，"
            "不能把群友之间的冲突算作对机器人的态度。"
            "普通聊天、重复问候、玩笑和刷好感输出ordinary。"
            "重大帮助和承诺必须有上下文证据，不采信单方面宣称。"
            "参考上下文，输出严格JSON："
            '{"event_type":"ordinary","base_delta":0,"confidence":0.9}。'
            "事件类型和分值范围："
            + json.dumps(EVENT_RANGES, ensure_ascii=False)
            + "\n最近消息：\n" + "\n".join(context)
            + "\n当前QQ：" + qq_id + "\n当前消息：" + message[:500]
        )
        result = await generate_text(
            prompt, system_prompt="你是HimariBot的独立关系事件分类器，只输出JSON，不参与聊天。",
            request_type="affinity_evaluation",
        )
        if not result.ok:
            return
        parsed = _parse_evaluation(result.text)
        if parsed is None:
            return
        kind, base_delta = parsed
        if kind != "ordinary":
            signature = f"{kind}:{message.casefold()[:200]}"
            previous = _recent_events.get(qq_id)
            if previous and previous[0] == signature and time.monotonic() - previous[1] < REPEAT_WINDOW_SECONDS:
                return
        changed = await asyncio.to_thread(_persist_evaluation, qq_id, kind, base_delta)
        if changed and kind != "ordinary":
            _recent_events[qq_id] = (signature, time.monotonic())
    except Exception:
        log.exception("affinity evaluation failed for qq_id=%s", qq_id)
    finally:
        _inflight.discard(qq_id)


def _persist_evaluation(qq_id: str, kind: str, delta: float) -> bool:
    from sqlalchemy import func, update

    now = datetime.now(timezone.utc)
    date = now.date().isoformat()
    with get_db_session() as session:
        record = session.get(HimariBotAffinity, qq_id)
        if record is None:
            return
        today_count = record.daily_change_count if record.daily_reset_date == date else 0
        if record.last_evaluated_at and (now - record.last_evaluated_at).total_seconds() < COOLDOWN_SECONDS:
            return
        if delta and today_count >= MAX_DAILY_CHANGES:
            return
        adjusted = delta * get_affinity_mood_multiplier(delta < 0)
        if delta < 0 and record.affinity_score >= 40:
            adjusted *= 0.5
        streak_day, streak = _negative_streak.get(qq_id, ("", 0))
        if streak_day != date:
            streak = 0
        if delta < 0 and streak >= 3:
            adjusted *= max(0.25, 0.75 ** (streak - 2))
        session.execute(
            update(HimariBotAffinity)
            .where(HimariBotAffinity.qq_id == qq_id)
            .values(
                affinity_score=func.min(100.0, func.max(-20.0, HimariBotAffinity.affinity_score + adjusted)),
                interaction_count=HimariBotAffinity.interaction_count + (1 if delta else 0),
                daily_change_count=today_count + (1 if delta else 0),
                daily_reset_date=date,
                last_evaluated_at=now,
                last_interaction_at=now,
                updated_at=now,
            )
        )
        if delta < 0:
            _negative_streak[qq_id] = (date, streak + 1)
        elif delta > 0:
            _negative_streak[qq_id] = (date, 0)
        return bool(delta)
