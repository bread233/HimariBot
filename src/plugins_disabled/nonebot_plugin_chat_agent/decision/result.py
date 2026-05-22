from __future__ import annotations

from dataclasses import dataclass


class DecisionRoute:
    DIRECT_ACTION = "direct_action"
    PLUGIN_HELP = "plugin_help"
    SKILL_CONTEXT = "skill_context"
    SKILL_EVIDENCE = "skill_evidence"
    WEB_EVIDENCE = "web_evidence"
    OFFICIAL_RESOLVER = "official_resolver"
    LOCAL_KNOWLEDGE = "local_knowledge"
    MEMORY_HISTORY = "memory_history"
    PLAIN_CHAT = "plain_chat"
    UNKNOWN = "unknown"


@dataclass
class DecisionResult:
    route: str
    skill_name: str | None = None
    action_name: str | None = None
    action_route: str | None = None
    web_allowed: bool = True
    evidence_source: str | None = None
    confidence: float = 0.0
    reason: str = ""
    answerable: bool | None = None

    def to_context_fields(self) -> dict[str, object]:
        return {
            "decision_route": self.route,
            "decision_skill_name": self.skill_name or "",
            "decision_action_name": self.action_name or "",
            "decision_action_route": self.action_route or "",
            "decision_web_allowed": bool(self.web_allowed),
            "decision_evidence_source": self.evidence_source or "",
            "decision_confidence": float(self.confidence),
            "decision_reason": self.reason or "",
        }

    def to_tool_note(self) -> str:
        return (
            f"decision route={self.route} "
            f"skill={self.skill_name or ''} "
            f"action={self.action_name or ''} "
            f"reason={self.reason or ''}"
        ).strip()
