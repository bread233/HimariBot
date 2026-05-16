from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path

from nonebot import logger


@dataclass
class DecisionPolicy:
    registered_action_required: bool = True
    web_block_skill_names: set[str] = field(default_factory=lambda: {"pptx", "docx", "pdf", "xlsx"})
    skill_evidence_names: set[str] = field(default_factory=lambda: {"news", "weather"})
    action_aliases: dict[str, str] = field(default_factory=lambda: {"internal_60s_news": "60s.today_image"})

    def canonical_action(self, action_name: str | None) -> str | None:
        action = str(action_name or "").strip().lower()
        if not action:
            return None
        return self.action_aliases.get(action, action)


def _normalize_name_set(value) -> set[str]:
    out: set[str] = set()
    if isinstance(value, list):
        for item in value:
            name = str(item or "").strip().lower()
            if name:
                out.add(name)
    return out


def _normalize_aliases(value) -> dict[str, str]:
    out: dict[str, str] = {}
    if isinstance(value, dict):
        for k, v in value.items():
            key = str(k or "").strip().lower()
            val = str(v or "").strip().lower()
            if key and val:
                out[key] = val
    return out


def load_decision_policy(path: str | Path | None) -> DecisionPolicy:
    policy = DecisionPolicy()
    if not path:
        return policy
    p = Path(path)
    if not p.exists():
        return policy
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning(f"decision_policy invalid_json path={p} message={type(e).__name__}")
        return policy
    if not isinstance(raw, dict):
        return policy
    routes = raw.get("routes") if isinstance(raw.get("routes"), dict) else {}
    direct_action = routes.get("direct_action") if isinstance(routes.get("direct_action"), dict) else {}
    skill_context = routes.get("skill_context") if isinstance(routes.get("skill_context"), dict) else {}
    skill_evidence = routes.get("skill_evidence") if isinstance(routes.get("skill_evidence"), dict) else {}

    if isinstance(direct_action.get("registered_action_required"), bool):
        policy.registered_action_required = bool(direct_action.get("registered_action_required"))

    block_set = _normalize_name_set(skill_context.get("web_block_skill_names"))
    if block_set:
        policy.web_block_skill_names = block_set

    evidence_set = _normalize_name_set(skill_evidence.get("skill_names"))
    if evidence_set:
        policy.skill_evidence_names = evidence_set

    aliases = _normalize_aliases(raw.get("action_aliases"))
    if aliases:
        merged = dict(policy.action_aliases)
        merged.update(aliases)
        policy.action_aliases = merged
    return policy
