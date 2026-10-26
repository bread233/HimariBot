"""Lightweight event inputs for the global mood engine.

Tracks one unanswered bot utterance per group; no periodic background task.
"""

from __future__ import annotations

import re
import time
from threading import RLock

from .mood_state import apply_mood_event, note_recent_emotion

WAIT_SECONDS = 20 * 60
_lock = RLock()
_pending: dict[str, tuple[float, str]] = {}
_recent_sentiment: dict[tuple[str, str], tuple[str, float]] = {}
SENTIMENT_COOLDOWN_SECONDS = 60
_BOT_NAME = re.compile(r"(?i)(?<![a-z])himari(?![a-z])|ひまり|日葵")
_POSITIVE = ("谢谢你", "感谢你", "喜欢你", "爱你", "辛苦了", "你真棒", "你真好", "对不起", "抱歉", "谢谢", "感谢", "你太厉害了", "好可爱", "做得真好")
_PRAISE = ("你真棒", "你真好", "你太厉害了", "好可爱", "做得真好")
_AFFECTION = ("喜欢你", "爱你")
_CARE = ("辛苦了", "对不起", "抱歉")
_NEGATIVE = ("讨厌你", "你真烦", "闭嘴", "滚开", "你真蠢", "你真笨", "烦死你了")


def is_bot_directed(message: str, addressed: bool) -> bool:
    """Recognize explicit bot names without treating other group chat as directed."""
    return addressed or bool(_BOT_NAME.search(message))


def _sentiment(message: str) -> int:
    negative = any(phrase in message for phrase in _NEGATIVE)
    positive = any(phrase in message for phrase in _POSITIVE)
    return 0 if positive == negative else (1 if positive else -1)


def note_targeted_mood(group_id: str, qq_id: str, message: str, *, addressed: bool) -> None:
    """A mild mood response to explicit bot-directed sentiment, never a score change."""
    if not is_bot_directed(message, addressed):
        return
    direction = _sentiment(message)
    social_touch = any(word in message for word in ("摸摸头", "摸头", "抱抱", "rua", "戳戳", "戳一戳"))
    if not direction and not (addressed and social_touch):
        return
    key = (str(group_id), str(qq_id))
    signature = str(direction) + ":" + message.strip().casefold()[:200]
    with _lock:
        previous = _recent_sentiment.get(key)
        now = time.monotonic()
        if previous and previous[0] == signature and now - previous[1] < SENTIMENT_COOLDOWN_SECONDS:
            return
        _recent_sentiment[key] = (signature, now)
    if not direction and social_touch:
        change, description = 2.0, "被轻轻互动，有点惊讶和开心😊"
    elif direction > 0:
        if any(word in message for word in _AFFECTION):
            change, description = 10.0, "被表达喜欢，有点害羞🥰"
        elif any(word in message for word in _PRAISE):
            change, description = 8.0, "被夸奖，有点高兴😊"
        elif any(word in message for word in _CARE):
            change, description = 6.0, "受到关心，有点感动🥹"
        else:
            change, description = 5.0, "受到感谢，有点高兴😊"
    else:
        change = -9.0 if any(word in message for word in ("讨厌你", "滚开", "闭嘴")) else -5.0
        description = "被责备，有点难过🥺" if change > -9 else "被攻击，有点生气😠"
    apply_mood_event(valence=change, sociability=change * 0.5)
    note_recent_emotion(qq_id, description)


def note_bot_spoke(group_id: str, bot_message_id: str = "") -> None:
    if not group_id:
        return
    with _lock:
        _pending[str(group_id)] = (time.monotonic(), str(bot_message_id))


def note_group_activity(group_id: str, addressed_to_bot: bool) -> None:
    """Apply one mild loneliness event, or clear pending when addressed.

    Unrelated group traffic does not count as a reply. Calling this only
    evaluates the pending event; it does not ask the bot to speak.
    """
    if not group_id:
        return
    with _lock:
        pending = _pending.get(str(group_id))
        if pending is None:
            return
        if addressed_to_bot:
            _pending.pop(str(group_id), None)
            apply_mood_event(valence=1.0, sociability=1.0)
        elif time.monotonic() - pending[0] >= WAIT_SECONDS:
            # Group traffic alone is not evidence that a bot-directed question
            # was ignored. Expire the marker without penalizing ordinary silence.
            _pending.pop(str(group_id), None)
