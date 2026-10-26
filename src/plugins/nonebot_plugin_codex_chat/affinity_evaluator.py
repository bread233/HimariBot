"""Contextual affinity event classification, separate from Planner and Replyer."""

from __future__ import annotations

import asyncio
import json
import math
import logging
import re
import time
from pathlib import Path
from collections import defaultdict, deque
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from typing import Any

from .maibot_core.codex_llm_adapter import generate_text
from src.common.database.affinity_store import get_or_create_affinity
from src.common.database.database import get_db_session
from src.common.database.database_model import HimariBotAffinity
from .mood_state import get_affinity_mood_multiplier, apply_mood_event, note_recent_emotion
from .mood_events import is_bot_directed

log = logging.getLogger(__name__)
COOLDOWN_SECONDS = 60
MAX_DAILY_CHANGES = 20
JST = ZoneInfo("Asia/Tokyo")


def _as_utc(value: datetime) -> datetime:
    """SQLite stores historical UTC timestamps without timezone information."""
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
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
_recent_mood: dict[str, tuple[str, float]] = {}
_negative_streak: dict[str, tuple[str, int]] = {}
REPEAT_WINDOW_SECONDS = 30 * 60
_SOCIAL_CONFIG = Path.cwd() / "data/nonebot_chat_agent/codex_chat_config/social_events.json"
_DEFAULT_RULES = {
    "instruction": "结合当前对话、互动对象及关系判断真实态度；亲密动作和戳一戳不必然正向，骚扰可以负向。",
    "mood_max_delta": 10.0,
}


def _social_rules() -> dict:
    """Reload editable rules on each evaluation; invalid config never blocks chat."""
    try:
        _SOCIAL_CONFIG.parent.mkdir(parents=True, exist_ok=True)
        if not _SOCIAL_CONFIG.exists():
            _SOCIAL_CONFIG.write_text(json.dumps(_DEFAULT_RULES, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        data = json.loads(_SOCIAL_CONFIG.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or not isinstance(data.get("instruction"), str):
            raise ValueError("invalid social event rules")
        cap = float(data.get("mood_max_delta", 10))
        if not math.isfinite(cap) or not 0 <= cap <= 10:
            raise ValueError("invalid mood limit")
        return {"instruction": data["instruction"][:2000], "mood_max_delta": cap}
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        log.warning("social event config unavailable: %s", exc)
        return _DEFAULT_RULES.copy()



def _affinity_adjustment(score: float, delta: float, mood_multiplier: float) -> float:
    """Continuous curves; negative scores have independent repair/decline rules."""
    if not delta:
        return 0.0
    if score < 0:
        multiplier = 5.0 if delta > 0 else 1.5
        cap = 25.0 if delta > 0 else 10.0
    elif delta > 0:
        multiplier = 0.6 + 4.4 * math.exp(-score / 30.0)
        cap = 2.0 + 23.0 * math.exp(-score / 25.0)
    else:
        multiplier = 0.35 + 0.65 * math.exp(-score / 40.0)
        cap = 10.0
    amount = min(abs(delta * mood_multiplier * multiplier), cap)
    return amount if delta > 0 else -amount


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
        if confidence < 0.65 or not low <= delta <= high:
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
    if not is_bot_directed(message, addressed) or len(message) < 3 or qq_id in _inflight:
        return
    _inflight.add(qq_id)
    try:
        record = await asyncio.to_thread(get_or_create_affinity, qq_id)
        now = datetime.now(timezone.utc)
        affinity_allowed = not (
            (record.last_evaluated_at and (now - _as_utc(record.last_evaluated_at)).total_seconds() < COOLDOWN_SECONDS)
            or (record.daily_reset_date == now.astimezone(JST).date().isoformat() and record.daily_change_count >= MAX_DAILY_CHANGES)
        )
        rules = _social_rules()
        prompt = (
            "判断用户与机器人之间的互动事件。仅评价对机器人本人的态度，"
            "不能把群友之间的冲突算作对机器人的态度。"
            "无明确态度的普通聊天、重复问候、无针对性的玩笑和刷好感输出ordinary。"
            "明确针对机器人的感谢、关心、善意、道歉、不满或攻击，应结合上下文认真判断，"
            "对摸头、拥抱、QQ戳一戳等互动根据语境判断，可正向、负向或中性。"
            + rules["instruction"]
            + "不要仅因语气日常就归为ordinary；也不要把礼貌套话自动判为重大事件。"
            "重大帮助和承诺必须有上下文证据，不采信单方面宣称。"
            "参考上下文，输出严格JSON："
            '{"event_type":"ordinary","base_delta":0,"confidence":0.9,"mood_delta":0,"emotion":""}。'
            "mood_delta 为 -10 到 10 的情绪愉悦度变化，emotion 是简短情绪描述；"
            "情绪变化可与好感度变化不同，无法确定时都为0。"
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
        try:
            payload = json.loads(re.search(r"\{[\s\S]*?\}", result.text).group())
            mood_delta = float(payload.get("mood_delta", 0))
            if not math.isfinite(mood_delta) or abs(mood_delta) > rules["mood_max_delta"]:
                mood_delta = 0.0
            emotion = str(payload.get("emotion", ""))[:80]
        except (ValueError, TypeError, AttributeError, json.JSONDecodeError):
            mood_delta, emotion = 0.0, ""
        signature = f"{kind}:{message.casefold()[:200]}"
        previous = _recent_events.get(qq_id)
        repeated = bool(previous and previous[0] == signature and time.monotonic() - previous[1] < REPEAT_WINDOW_SECONDS)
        changed = False
        if affinity_allowed and not repeated:
            changed = await asyncio.to_thread(_persist_evaluation, qq_id, kind, base_delta)
        mood_previous = _recent_mood.get(qq_id)
        mood_allowed = not mood_previous or (
            mood_previous[0] != signature and time.monotonic() - mood_previous[1] >= COOLDOWN_SECONDS
        )
        if mood_delta and mood_allowed and not repeated:
            apply_mood_event(valence=mood_delta, sociability=mood_delta * 0.5)
            if emotion:
                note_recent_emotion(qq_id, emotion)
            _recent_mood[qq_id] = (signature, time.monotonic())
        if (changed or (mood_delta and mood_allowed and not repeated)) and not repeated:
            _recent_events[qq_id] = (signature, time.monotonic())
    except Exception:
        log.exception("affinity evaluation failed for qq_id=%s", qq_id)
    finally:
        _inflight.discard(qq_id)


def _persist_evaluation(qq_id: str, kind: str, delta: float) -> bool:
    from sqlalchemy import func, update

    now = datetime.now(timezone.utc)
    date = now.astimezone(JST).date().isoformat()
    with get_db_session() as session:
        record = session.get(HimariBotAffinity, qq_id)
        if record is None:
            return
        today_count = record.daily_change_count if record.daily_reset_date == date else 0
        if record.last_evaluated_at and (now - _as_utc(record.last_evaluated_at)).total_seconds() < COOLDOWN_SECONDS:
            return
        if delta and today_count >= MAX_DAILY_CHANGES:
            return
        adjusted = _affinity_adjustment(record.affinity_score, delta, get_affinity_mood_multiplier(delta < 0))
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
