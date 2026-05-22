from __future__ import annotations

import asyncio

_chat_agent_lock = asyncio.Lock()


def get_chat_agent_lock() -> asyncio.Lock:
    return _chat_agent_lock
