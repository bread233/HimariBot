from __future__ import annotations

from contextlib import AbstractContextManager
from contextvars import ContextVar, Token
from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class CapturedOutboundMessage:
    text: str
    segments: list[dict] | None = None
    reply_to_message_id: str | None = None
    raw: Any | None = None
    source: str = "maibot_capture"


_current_outbound_buffer: ContextVar[list[CapturedOutboundMessage] | None] = ContextVar(
    "maibot_outbound_buffer",
    default=None,
)


class OutboundCapture(AbstractContextManager["OutboundCapture"]):
    def __init__(self) -> None:
        self._messages: list[CapturedOutboundMessage] = []
        self._token: Token[list[CapturedOutboundMessage] | None] | None = None

    def __enter__(self) -> "OutboundCapture":
        self._token = _current_outbound_buffer.set(self._messages)
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._token is not None:
            _current_outbound_buffer.reset(self._token)
            self._token = None

    @property
    def messages(self) -> list[CapturedOutboundMessage]:
        return list(self._messages)



def capture_outbound_message(
    text: str,
    reply_to_message_id: str | None = None,
    raw: Any | None = None,
    segments: list[dict] | None = None,
    source: str = "maibot_capture",
) -> bool:
    text = str(text or "").strip()
    if not text:
        return False

    buffer = _current_outbound_buffer.get()
    if buffer is None:
        return False
    buffer.append(
        CapturedOutboundMessage(
            text=text,
            segments=segments,
            reply_to_message_id=reply_to_message_id,
            raw=raw,
            source=source,
        )
    )
    return True



def has_outbound_capture() -> bool:
    return _current_outbound_buffer.get() is not None
