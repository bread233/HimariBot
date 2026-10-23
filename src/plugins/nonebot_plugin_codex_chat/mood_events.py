"""Lightweight event inputs for the global mood engine.

Tracks one unanswered bot utterance per group; no periodic background task.
"""

from __future__ import annotations

import time
from threading import RLock

from .mood_state import apply_mood_event

WAIT_SECONDS = 20 * 60
_lock = RLock()
_pending: dict[str, tuple[float, str]] = {}


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
