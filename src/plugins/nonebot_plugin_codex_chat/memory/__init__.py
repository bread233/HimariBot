from __future__ import annotations

from .collector import register_memory_collector
from .commands import register_memory_commands

__all__ = ["register_memory_collector", "register_memory_commands"]
