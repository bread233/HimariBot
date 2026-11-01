"""人物事实的默认拒绝访问策略；身份键与事实可见性分别判定。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class TrustedProfileScope:
    platform: str
    user_id: str
    group_id: str
    session_id: str

    @classmethod
    def from_runtime(cls, runtime: Any) -> "TrustedProfileScope | None":
        stream = getattr(runtime, "chat_stream", None)
        if stream is None:
            return None
        group = str(getattr(stream, "group_id", "") or "").strip()
        platform = str(getattr(stream, "platform", "") or "").strip()
        if not group or not platform:
            return None
        return cls(platform, str(getattr(stream, "user_id", "") or "").strip(),
                   group, str(getattr(runtime, "session_id", "") or "").strip())

    @classmethod
    def from_message(cls, message: Any) -> "TrustedProfileScope | None":
        """从内部 SessionMessage 的消息元数据提取群作用域。"""
        info = getattr(message, "message_info", None)
        group_info = getattr(info, "group_info", None)
        group = str(getattr(group_info, "group_id", "") or "").strip()
        platform = str(getattr(message, "platform", "") or "").strip()
        if not group or not platform:
            return None
        user_info = getattr(info, "user_info", None)
        return cls(platform, str(getattr(user_info, "user_id", "") or "").strip(),
                   group, str(getattr(message, "session_id", "") or "").strip())

GROUP_PRIVATE = "group_private"
PUBLIC = "public"


def normalize_fact_scope(fact: Mapping[str, Any]) -> tuple[str, str]:
    """仅接受明确公开标记；缺失/未知标记均视为群内私有。"""
    visibility = str(fact.get("visibility") or "").strip().lower()
    group_id = str(fact.get("source_group_id") or "").strip()
    return (PUBLIC if visibility == PUBLIC else GROUP_PRIVATE), group_id


def can_read_fact(fact: Mapping[str, Any], *, reader_group_id: str) -> bool:
    """普通群聊访问：公开事实可跨群；群私有事实须有匹配来源群。"""
    group = str(reader_group_id or "").strip()
    if not group:
        return False
    visibility, source_group = normalize_fact_scope(fact)
    if visibility == PUBLIC:
        return True
    return bool(source_group and source_group == group)


def filter_visible_facts(
    facts: list[dict[str, Any]], *, reader_group_id: str
) -> list[dict[str, Any]]:
    return [fact for fact in facts if can_read_fact(fact, reader_group_id=reader_group_id)]
