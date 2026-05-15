from __future__ import annotations

from dataclasses import dataclass, field

from .quality_guard import (
    definition_quality_reason,
    is_unknown_like_reply,
    should_retry_short_answer,
    sports_quality_reason,
)


@dataclass
class WebEvidenceFinalizerInput:
    prompt: str
    evidence_context: str
    answerable: bool
    answer_style: str
    unknown_reply: str
    system_prompt: str
    user_prompt: str
    tool_notes: list[str] = field(default_factory=list)


@dataclass
class WebEvidenceFinalizerResult:
    reply: str
    used_fallback: bool = False
    retry_count: int = 0
    tool_notes: list[str] = field(default_factory=list)


def build_web_evidence_messages(payload: WebEvidenceFinalizerInput) -> list[dict[str, str]]:
    user_content = (
        f"Question: {payload.prompt}\n"
        f"Query: {payload.user_prompt or payload.prompt}\n\n"
        f"Evidence:\n{payload.evidence_context}"
    )
    return [
        {"role": "system", "content": str(payload.system_prompt or "").strip()},
        {"role": "user", "content": user_content},
    ]


def evaluate_web_evidence_reply(
    reply: str,
    *,
    answerable: bool,
    answer_style: str = "",
    unknown_reply: str | None = None,
    min_chars: int = 45,
) -> str:
    text = str(reply or "").strip()
    if answerable and is_unknown_like_reply(text, unknown_reply=unknown_reply):
        return "unknown_like"
    if should_retry_short_answer(
        text,
        answerable=answerable,
        answer_style=answer_style,
        min_chars=min_chars,
    ):
        return "short_answer"
    style = str(answer_style or "").strip().lower()
    if answerable and style == "definition_summary" and definition_quality_reason(text, min_chars=min_chars):
        return "definition_quality"
    if answerable and style == "sports_stats_first" and sports_quality_reason(text, min_chars=min_chars):
        return "sports_quality"
    return "ok"
