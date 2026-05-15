from __future__ import annotations

from dataclasses import dataclass, field
from typing import Awaitable, Callable

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


def build_web_evidence_messages(
    payload: WebEvidenceFinalizerInput | None = None,
    *,
    prompt: str = "",
    query: str = "",
    evidence_context: str = "",
    style_extra: str = "",
) -> list[dict[str, str]]:
    if payload is not None:
        sys_prompt = str(payload.system_prompt or "").strip()
        q = str(payload.user_prompt or payload.prompt or "").strip()
        p = str(payload.prompt or "").strip()
        ev = str(payload.evidence_context or "").strip()
    else:
        p = str(prompt or "").strip()
        q = str(query or p).strip()
        ev = str(evidence_context or "").strip()
        sys_prompt = (
            "你需要基于已提供的网页摘要回答问题。\n"
            "回答必须全中文，不要输出英文标题词。\n"
            "不要输出这些英文词：snippet, snippets, cautious, conclusion, reasons, evidence, source。\n"
            "需要表达 summary/snippet 时用“摘要”；需要表达 cautious 时用“谨慎”或“保守”。\n"
            "建议使用格式：\n"
            "结论：...\n"
            "理由：\n"
            "1. ...\n"
            "2. ...\n"
            "3. ...\n"
            "只能基于已提供资料作答，不要编造事实。\n"
            "若证据不足，直接说不确定或暂时没查到可靠资料。\n"
            "不要把“值得入手”、“两极分化”、“推荐”这类搜索标题直接当成结论。\n"
            "如果资料没有具体优缺点、评分、玩家评价、实机或评测内容，只能说资料不足。\n"
            "不要基于标题扩写评价。\n"
            "如果资料未明确给出，不要编造概率、比分、积分、排名、日期、版本号或其他数字。"
            f"{style_extra}"
        )
    user_content = f"Question: {p}\nQuery: {q}\n\nEvidence:\n{ev}"
    return [
        {"role": "system", "content": sys_prompt},
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


async def handle_unknown_like_retry(
    reply: str,
    *,
    answerable: bool,
    evidence_messages: list[dict[str, str]],
    llm_call: Callable[[list[dict[str, str]]], Awaitable[str]],
    clean_reply: Callable[[str], str],
    fallback_reply: str,
    unknown_reply: str | None = None,
    retry_system_prompt: str = "",
) -> tuple[str, bool]:
    def _looks_unknown_after_retry(text: str) -> bool:
        t = str(text or "").strip()
        if not t:
            return True
        marker = str(unknown_reply or "").strip()
        if marker and marker in t:
            return True
        return evaluate_web_evidence_reply(
            t,
            answerable=True,
            answer_style="",
            unknown_reply=unknown_reply,
        ) == "unknown_like"

    reason = evaluate_web_evidence_reply(
        reply,
        answerable=answerable,
        answer_style="",
        unknown_reply=unknown_reply,
    )
    if reason != "unknown_like":
        return str(reply or "").strip(), False
    retry_messages = list(evidence_messages)
    retry_messages.insert(
        1,
        {
            "role": "system",
            "content": str(retry_system_prompt or "").strip(),
        },
    )
    try:
        retry_reply = await llm_call(retry_messages)
        retry_reply = clean_reply(retry_reply)
        if retry_reply and not _looks_unknown_after_retry(retry_reply):
            return retry_reply, True
        return str(fallback_reply or "").strip(), True
    except Exception:
        return str(fallback_reply or "").strip(), True
