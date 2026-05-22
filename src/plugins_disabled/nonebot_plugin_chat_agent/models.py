from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class EvidenceItem:
    source: str = ""
    title: str = ""
    url: str = ""
    snippet: str = ""
    score: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class EvidencePack:
    route: str = ""
    query: str = ""
    items: list[EvidenceItem] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class DecisionResult:
    should_call_llm: bool = True
    direct_reply: str | None = None
    route: str = ""
    reason: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class AnswerResult:
    text: str = ""
    from_llm: bool = False
    finish: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)
