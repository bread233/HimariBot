from __future__ import annotations

from dataclasses import dataclass

from .policy import DecisionPolicy
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
    selected_skill_registered: bool = False
    policy: DecisionPolicy | None = None


@dataclass
class RuntimeDecisionInput:
    prompt: str = ""
    selected_skill_name: str | None = None
    selected_skill_action: str | None = None
    selected_skill_route: str | None = None
    selected_skill_registered: bool = False
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
    policy: DecisionPolicy | None = None


def decide_runtime_route(data: RuntimeDecisionInput) -> RuntimeDecisionResult:
    policy = data.policy or DecisionPolicy()
    canonical_action = policy.canonical_action(data.selected_skill_action)
    if (
        canonical_action
        and str(data.selected_skill_route or "").strip() == "direct_message"
        and (data.selected_skill_registered or (not policy.registered_action_required))
    ):
        return RuntimeDecisionResult(
            route=DecisionRoute.DIRECT_ACTION,
            skill_name=data.selected_skill_name,
            action_name=canonical_action,
            action_route=data.selected_skill_route,
            web_allowed=False,
            reason=data.reason_hint or "internal_skill_action",
            confidence=data.confidence or 1.0,
            answerable=data.answerable,
        )
    if data.official_direct_reply:
        return RuntimeDecisionResult(
            route=DecisionRoute.OFFICIAL_RESOLVER,
            skill_name=data.selected_skill_name,
            web_allowed=data.skill_web_allowed,
            reason=data.reason_hint or "official_direct_answer",
            confidence=data.confidence or 1.0,
            answerable=data.answerable,
        )
    if data.history_direct_reply:
        return RuntimeDecisionResult(
            route=DecisionRoute.MEMORY_HISTORY,
            skill_name=data.selected_skill_name,
            web_allowed=data.skill_web_allowed,
            reason=data.reason_hint or "explicit_history_direct_reply",
            confidence=data.confidence or 0.9,
            answerable=data.answerable,
        )
    if data.skill_evidence_used:
        return RuntimeDecisionResult(
            route=DecisionRoute.SKILL_EVIDENCE,
            skill_name=data.selected_skill_name,
            web_allowed=data.skill_web_allowed,
            evidence_source=data.skill_evidence_source or "skill_bridge",
            reason=data.reason_hint or "skill_evidence_bridge",
            confidence=data.confidence or 0.85,
            answerable=data.answerable,
        )
    if data.selected_skill_name and (not data.skill_web_allowed):
        return RuntimeDecisionResult(
            route=DecisionRoute.SKILL_CONTEXT,
            skill_name=data.selected_skill_name,
            web_allowed=False,
            reason=data.reason_hint or "skill_context_web_blocked",
            confidence=data.confidence or 0.5,
            answerable=data.answerable,
        )
    if str(data.lightweight_mode or "").strip() == "web_evidence":
        return RuntimeDecisionResult(
            route=DecisionRoute.WEB_EVIDENCE,
            skill_name=data.selected_skill_name,
            web_allowed=data.skill_web_allowed,
            reason=data.reason_hint or "web_evidence",
            confidence=data.confidence or 0.75,
            answerable=data.answerable,
        )
    if data.local_knowledge_unknown:
        return RuntimeDecisionResult(
            route=DecisionRoute.LOCAL_KNOWLEDGE,
            skill_name=data.selected_skill_name,
            web_allowed=data.skill_web_allowed,
            reason=data.reason_hint or "local_no_answer",
            confidence=data.confidence or 0.3,
            answerable=data.answerable,
        )
    return RuntimeDecisionResult(
        route=data.default_route or DecisionRoute.PLAIN_CHAT,
        skill_name=data.selected_skill_name,
        web_allowed=data.skill_web_allowed,
        reason=data.reason_hint or "default_plain_chat",
        confidence=data.confidence or 0.5,
        answerable=data.answerable,
    )


def build_runtime_decision(signals: RuntimeDecisionSignals) -> RuntimeDecisionResult:
    return decide_runtime_route(
        RuntimeDecisionInput(
            selected_skill_name=signals.selected_skill_name,
            selected_skill_action=signals.internal_skill_action,
            selected_skill_route=signals.internal_skill_route,
            selected_skill_registered=signals.selected_skill_registered,
            skill_web_allowed=signals.skill_web_allowed,
            skill_evidence_used=signals.skill_evidence_used,
            skill_evidence_source=signals.skill_evidence_source,
            official_direct_reply=signals.official_direct_reply,
            history_direct_reply=signals.history_direct_reply,
            lightweight_mode=signals.lightweight_mode,
            local_knowledge_unknown=signals.local_knowledge_unknown,
            answerable=signals.answerable,
            default_route=signals.default_route,
            reason_hint=signals.reason_hint,
            confidence=signals.confidence,
            policy=signals.policy,
        )
    )
