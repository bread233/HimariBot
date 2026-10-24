"""Process-local, three-dimensional mood with monotonic time decay.

All values are in [0, 100]. Restart resets the state. No database writes.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass
from threading import RLock

BASELINE = (55.0, 50.0, 55.0)
DECAY_HALF_LIFE_SECONDS = 3 * 60 * 60
_LOCK = RLock()


@dataclass(frozen=True)
class MoodSnapshot:
    valence: float
    energy: float
    sociability: float


_state = list(BASELINE)
_updated_at = time.monotonic()
_recent_emotions: dict[str, tuple[str, float]] = {}
EMOTION_SECONDS = 15 * 60


def _clamp(value: float) -> float:
    return max(0.0, min(100.0, value))


def _settle(now: float) -> None:
    global _updated_at
    elapsed = max(0.0, now - _updated_at)
    factor = 0.5 ** (elapsed / DECAY_HALF_LIFE_SECONDS)
    for index, baseline in enumerate(BASELINE):
        _state[index] = baseline + (_state[index] - baseline) * factor
    _updated_at = now


def get_mood_snapshot() -> MoodSnapshot:
    with _LOCK:
        _settle(time.monotonic())
        return MoodSnapshot(*_state)


def apply_mood_event(
    valence: float = 0.0, energy: float = 0.0, sociability: float = 0.0
) -> MoodSnapshot:
    changes = (valence, energy, sociability)
    if not all(math.isfinite(value) for value in changes):
        raise ValueError("mood changes must be finite")
    with _LOCK:
        _settle(time.monotonic())
        for index, change in enumerate(changes):
            _state[index] = _clamp(_state[index] + max(-20.0, min(20.0, change)))
        return MoodSnapshot(*_state)


def get_mood_label() -> str:
    state = get_mood_snapshot()
    if state.valence < 35:
        return "低落" if state.energy < 45 else "烦躁"
    if state.valence >= 70:
        return "兴奋" if state.energy >= 70 else "开心"
    if state.valence >= 59:
        return "小开心"
    if state.energy < 30:
        return "疲惫"
    if state.sociability < 30:
        return "不太想说话"
    return "平静"


def note_recent_emotion(qq_id: str, description: str) -> None:
    with _LOCK:
        _recent_emotions[str(qq_id)] = (description, time.monotonic())


def get_recent_emotion(qq_id: str) -> str:
    with _LOCK:
        item = _recent_emotions.get(str(qq_id))
        if not item:
            return "无明显变化😌"
        if time.monotonic() - item[1] >= EMOTION_SECONDS:
            _recent_emotions.pop(str(qq_id), None)
            return "无明显变化😌"
        return item[0]


def get_mood_prompt() -> str:
    state = get_mood_snapshot()
    return (
        f"当前整体心情：{get_mood_label()}。"
        f"精力：{'充沛' if state.energy >= 65 else '疲惫' if state.energy < 35 else '普通'}；"
        f"社交意愿：{'积极' if state.sociability >= 65 else '低' if state.sociability < 35 else '普通'}。"
        "请遵循原本人格自然表达，不必明确说出心情；不要暴露内部数值。"
    )


def get_affinity_mood_multiplier(negative_event: bool) -> float:
    """Good mood softens minor negatives; bad mood amplifies them modestly."""
    valence = get_mood_snapshot().valence
    if negative_event:
        return max(0.5, min(1.5, 1.0 + (50.0 - valence) / 100.0))
    return max(0.75, min(1.25, 1.0 + (valence - 50.0) / 200.0))


def reset_mood() -> None:
    global _updated_at
    with _LOCK:
        _state[:] = BASELINE
        _recent_emotions.clear()
        _updated_at = time.monotonic()
