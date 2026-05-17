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
    classifier_observe_casual_skip_include: list[str] = field(
        default_factory=lambda: [
            "你好",
            "您好",
            "哈喽",
            "hello",
            "hi",
            "谢谢",
            "感谢",
            "辛苦",
            "早安",
            "晚安",
            "再见",
            "拜拜",
        ]
    )
    classifier_observe_casual_skip_exclude: list[str] = field(
        default_factory=lambda: [
            "帮我",
            "查",
            "做",
            "怎么",
            "如何",
            "推荐",
            "吃啥",
            "吃什么",
            "天气",
            "新闻",
            "ppt",
            "pdf",
        ]
    )

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


def _normalize_text_list(value) -> list[str]:
    out: list[str] = []
    if isinstance(value, list):
        for item in value:
            s = str(item or "").strip().lower()
            if s:
                out.append(s)
    return out


def should_skip_classifier_observe_as_casual(prompt: str, policy: DecisionPolicy) -> bool:
    text = str(prompt or "").strip().lower()
    if not text:
        return False
    excludes = _normalize_text_list(policy.classifier_observe_casual_skip_exclude)
    includes = _normalize_text_list(policy.classifier_observe_casual_skip_include)
    if any(token in text for token in excludes):
        return False
    if any(token in text for token in includes):
        return True
    return False


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
    include_tokens = _normalize_text_list(raw.get("classifier_observe_casual_skip_include"))
    if include_tokens:
        policy.classifier_observe_casual_skip_include = include_tokens
    exclude_tokens = _normalize_text_list(raw.get("classifier_observe_casual_skip_exclude"))
    if exclude_tokens:
        policy.classifier_observe_casual_skip_exclude = exclude_tokens
    return policy
