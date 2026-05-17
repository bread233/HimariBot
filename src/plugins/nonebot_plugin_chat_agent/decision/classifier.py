from __future__ import annotations

from dataclasses import dataclass, field
import json
from typing import Any, Iterable

from .policy import DecisionPolicy
from .result import DecisionResult as RuntimeDecisionResult, DecisionRoute


@dataclass
class SkillCatalogEntry:
    name: str
    description: str = ""
    triggers: list[str] = field(default_factory=list)
    priority: int = 0
    chat_agent_action: str | None = None
    chat_agent_route: str | None = None


@dataclass
class ParsedDecisionCandidate:
    route: str
    skill_name: str | None
    action_name: str | None
    action_route: str | None
    confidence: float
    reason: str


def _clamp_confidence(value: Any) -> float:
    try:
        v = float(value)
    except Exception:
        v = 0.0
    if v < 0:
        return 0.0
    if v > 1:
        return 1.0
    return v


def build_skill_catalog_entries(skills: Iterable[Any], *, max_items: int = 30) -> list[SkillCatalogEntry]:
    out: list[SkillCatalogEntry] = []
    for item in skills:
        if len(out) >= max_items:
            break
        name = str(getattr(item, "name", "") or "").strip()
        if not name:
            continue
        desc = str(getattr(item, "description", "") or "").strip()
        raw_triggers = getattr(item, "triggers", []) or []
        triggers: list[str] = []
        if isinstance(raw_triggers, list):
            for t in raw_triggers:
                s = str(t or "").strip()
                if s:
                    triggers.append(s)
        out.append(
            SkillCatalogEntry(
                name=name,
                description=desc,
                triggers=triggers,
                priority=int(getattr(item, "priority", 0) or 0),
                chat_agent_action=str(getattr(item, "chat_agent_action", "") or "").strip() or None,
                chat_agent_route=str(getattr(item, "chat_agent_route", "") or "").strip() or None,
            )
        )
    return out


def render_decision_catalog(entries: list[SkillCatalogEntry], policy: DecisionPolicy, *, max_chars: int = 6000) -> str:
    lines: list[str] = []
    lines.append("Decision Catalog")
    lines.append(f"policy.registered_action_required={1 if policy.registered_action_required else 0}")
    lines.append("skills:")
    for i, entry in enumerate(entries, start=1):
        tri = ",".join(entry.triggers[:10])
        lines.append(
            f"{i}. name={entry.name} priority={entry.priority} action={entry.chat_agent_action or ''} "
            f"route={entry.chat_agent_route or ''} triggers={tri} desc={entry.description}"
        )
        if sum(len(x) + 1 for x in lines) >= max_chars:
            break
    text = "\n".join(lines)
    return text[:max_chars]


def build_decision_classifier_messages(prompt: str, catalog_text: str) -> list[dict[str, str]]:
    system = (
        "You are a route classifier. Output JSON object only. "
        "Do not answer user question. Do not execute tools or actions. "
        "Allowed route values: direct_action, plugin_help, skill_context, skill_evidence, web_evidence, "
        "official_resolver, local_knowledge, memory_history, plain_chat, unknown."
    )
    user = (
        f"User prompt:\n{prompt}\n\n"
        f"Catalog:\n{catalog_text}\n\n"
        "Return JSON with keys: route, skill_name, action_name, action_route, confidence, reason."
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def parse_decision_classifier_reply(text: str) -> ParsedDecisionCandidate | None:
    try:
        obj = json.loads(str(text or "").strip())
    except Exception:
        return None
    if not isinstance(obj, dict):
        return None
    route = str(obj.get("route", "") or "").strip()
    if not route:
        return None
    return ParsedDecisionCandidate(
        route=route,
        skill_name=str(obj.get("skill_name", "") or "").strip() or None,
        action_name=str(obj.get("action_name", "") or "").strip() or None,
        action_route=str(obj.get("action_route", "") or "").strip() or None,
        confidence=_clamp_confidence(obj.get("confidence", 0.0)),
        reason=str(obj.get("reason", "") or "").strip(),
    )


def validate_decision_candidate(
    candidate: ParsedDecisionCandidate,
    catalog_entries: list[SkillCatalogEntry],
    policy: DecisionPolicy,
    registered_actions: set[str],
    *,
    min_confidence: float = 0.55,
) -> RuntimeDecisionResult | None:
    if candidate.confidence < min_confidence:
        return None
    allowed_routes = {
        DecisionRoute.DIRECT_ACTION,
        "plugin_help",
        DecisionRoute.SKILL_CONTEXT,
        DecisionRoute.SKILL_EVIDENCE,
        DecisionRoute.WEB_EVIDENCE,
        DecisionRoute.OFFICIAL_RESOLVER,
        DecisionRoute.LOCAL_KNOWLEDGE,
        DecisionRoute.MEMORY_HISTORY,
        DecisionRoute.PLAIN_CHAT,
        "unknown",
    }
    if candidate.route not in allowed_routes:
        return None
    known_skill_names = {e.name for e in catalog_entries}
    if candidate.skill_name and candidate.skill_name not in known_skill_names:
        return None
    action_name = policy.canonical_action(candidate.action_name)
    if candidate.route == DecisionRoute.DIRECT_ACTION:
        if not action_name:
            return None
        if action_name not in {str(x).strip().lower() for x in registered_actions}:
            return None
    return RuntimeDecisionResult(
        route=candidate.route,
        skill_name=candidate.skill_name,
        action_name=action_name,
        action_route=candidate.action_route,
        web_allowed=(candidate.route != DecisionRoute.SKILL_CONTEXT),
        confidence=candidate.confidence,
        reason=candidate.reason,
    )
