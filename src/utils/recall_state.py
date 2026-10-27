"""Shared short-lived recall markers for delayed OneBot replies."""
import time
from contextvars import ContextVar

send_origin_id: ContextVar[str | None] = ContextVar("send_origin_id", default=None)
_recalled: dict[tuple[str, str, str], float] = {}
_TTL = 600

def _key(bot_id: object, group_id: object, message_id: object) -> tuple[str, str, str]:
    return str(bot_id), str(group_id), str(message_id)

def mark_recalled(bot_id: object, group_id: object, message_id: object) -> None:
    now = time.monotonic()
    for key, expiry in list(_recalled.items()):
        if expiry <= now:
            del _recalled[key]
    _recalled[_key(bot_id, group_id, message_id)] = now + _TTL

def was_recalled(bot_id: object, group_id: object, message_id: object) -> bool:
    return _recalled.get(_key(bot_id, group_id, message_id), 0) > time.monotonic()
