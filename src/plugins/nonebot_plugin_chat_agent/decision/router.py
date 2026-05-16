from __future__ import annotations

from dataclasses import dataclass

from .result import DecisionResult as RuntimeDecisionResult, DecisionRoute


@dataclass
class RuntimeDecisionSignals:
    internal_skill_action: str | None = None
    internal_skill_route: str | None = None
    selected_skill_name: str | None = None
    skill_web_allowed: bool = True
    skill_evidence_used: bool = False
    skill_evidence_source: str | None = None
    official_direct_reply: bool = False
    history_direct_reply: bool = False
    lightweight_mode: str | None = None
    local_knowledge_unknown: bool = False
    answerable: bool | None = None
    default_route: str = DecisionRoute.PLAIN_CHAT
    reason_hint: str = ""
    confidence: float = 0.0


def build_runtime_decision(signals: RuntimeDecisionSignals) -> RuntimeDecisionResult:
    if signals.internal_skill_action and str(signals.internal_skill_route or "").strip() == "direct_message":
        return RuntimeDecisionResult(
            route=DecisionRoute.DIRECT_ACTION,
            skill_name=signals.selected_skill_name,
            action_name=signals.internal_skill_action,
            action_route=signals.internal_skill_route,
            web_allowed=False,
            reason=signals.reason_hint or "internal_skill_action",
            confidence=signals.confidence or 1.0,
            answerable=signals.answerable,
        )
    if signals.official_direct_reply:
        return RuntimeDecisionResult(
            route=DecisionRoute.OFFICIAL_RESOLVER,
            skill_name=signals.selected_skill_name,
            web_allowed=signals.skill_web_allowed,
            reason=signals.reason_hint or "official_direct_answer",
            confidence=signals.confidence or 1.0,
            answerable=signals.answerable,
        )
    if signals.history_direct_reply:
        return RuntimeDecisionResult(
            route=DecisionRoute.MEMORY_HISTORY,
            skill_name=signals.selected_skill_name,
            web_allowed=signals.skill_web_allowed,
            reason=signals.reason_hint or "explicit_history_direct_reply",
            confidence=signals.confidence or 0.9,
            answerable=signals.answerable,
        )
    if signals.skill_evidence_used:
        return RuntimeDecisionResult(
            route=DecisionRoute.SKILL_EVIDENCE,
            skill_name=signals.selected_skill_name,
            web_allowed=signals.skill_web_allowed,
            evidence_source=signals.skill_evidence_source or "skill_bridge",
            reason=signals.reason_hint or "skill_evidence_bridge",
            confidence=signals.confidence or 0.85,
            answerable=signals.answerable,
        )
    if signals.selected_skill_name and not signals.skill_web_allowed:
        return RuntimeDecisionResult(
            route=DecisionRoute.SKILL_CONTEXT,
            skill_name=signals.selected_skill_name,
            web_allowed=False,
            reason=signals.reason_hint or "skill_context_web_blocked",
            confidence=signals.confidence or 0.5,
            answerable=signals.answerable,
        )
    if str(signals.lightweight_mode or "").strip() == "web_evidence":
        return RuntimeDecisionResult(
            route=DecisionRoute.WEB_EVIDENCE,
            skill_name=signals.selected_skill_name,
            web_allowed=signals.skill_web_allowed,
            reason=signals.reason_hint or "web_evidence",
            confidence=signals.confidence or 0.75,
            answerable=signals.answerable,
        )
    if signals.local_knowledge_unknown:
        return RuntimeDecisionResult(
            route=DecisionRoute.LOCAL_KNOWLEDGE,
            skill_name=signals.selected_skill_name,
            web_allowed=signals.skill_web_allowed,
            reason=signals.reason_hint or "local_no_answer",
            confidence=signals.confidence or 0.3,
            answerable=signals.answerable,
        )
    return RuntimeDecisionResult(
        route=signals.default_route or DecisionRoute.PLAIN_CHAT,
        skill_name=signals.selected_skill_name,
        web_allowed=signals.skill_web_allowed,
        reason=signals.reason_hint or "default_plain_chat",
        confidence=signals.confidence or 0.5,
        answerable=signals.answerable,
    )
