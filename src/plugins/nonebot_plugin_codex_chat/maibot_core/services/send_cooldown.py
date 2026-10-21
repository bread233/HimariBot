import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import Optional, TypeVar


T = TypeVar("T")


class SessionSendCooldown:
    def __init__(self) -> None:
        self._locks: dict[str, asyncio.Lock] = {}
        self._last_successful_send_at: dict[str, float] = {}

    def clear(self) -> None:
        self._locks.clear()
        self._last_successful_send_at.clear()

    def remaining(self, session_id: str, cooldown_seconds: float, now: Optional[float] = None) -> float:
        last_sent_at = self._last_successful_send_at.get(session_id)
        if cooldown_seconds <= 0 or last_sent_at is None:
            return 0.0
        current = time.monotonic() if now is None else now
        return max(0.0, cooldown_seconds - (current - last_sent_at))

    async def send(
        self,
        session_id: str,
        cooldown_seconds: float,
        sender: Callable[[], Awaitable[Optional[T]]],
    ) -> tuple[Optional[T], float]:
        send_lock = self._locks.setdefault(session_id, asyncio.Lock())
        async with send_lock:
            remaining = self.remaining(session_id, cooldown_seconds)
            if remaining > 0:
                return None, remaining
            result = await sender()
            if result is not None:
                self._last_successful_send_at[session_id] = time.monotonic()
            return result, 0.0
