"""QQ drawing authorization shared by task creation, tool submission and failure notices.

An active message is *not* evidence that a group member asked this bot to draw.
"""
from __future__ import annotations

from typing import Any


def validate_image_request_authorization(runtime: Any, target: Any, *, thread: Any = None) -> bool:
    """Allow direct requests to this bot, or a verified reply to its own image Thread.

    Fail closed for group messages with missing addressing metadata. In particular,
    a quote of another bot's request never grants drawing authorization.
    """
    if target is None:
        return False
    if str(getattr(target, "session_id", "") or "") != str(getattr(runtime, "session_id", "") or ""):
        return False
    if getattr(getattr(runtime, "chat_stream", None), "platform", "") != "onebot.v11":
        return False

    info = getattr(target, "message_info", None)
    config = getattr(info, "additional_config", None) or {}
    self_id = str(config.get("bot_self_id") or getattr(target, "bot_self_id", "") or "").strip()
    targets = {str(value).strip() for value in (config.get("at_targets") or ()) if str(value).strip()}
    # A real @ to this bot is sufficient; @ to someone else is never sufficient.
    if self_id and self_id in targets:
        return True
    if targets:
        return False

    # Some historical/rehydrated messages retain only explicit at_bot.
    if config.get("at_bot") is True and (getattr(target, "is_at", False) or getattr(target, "is_mentioned", False)):
        return True

    # Continuations are allowed only for an existing, owned Thread whose root
    # request was itself addressed to this bot.
    if not thread or str(thread.get("owner") or "") != str(
        getattr(getattr(info, "user_info", None), "user_id", "") or ""
    ):
        return False
    root_id = str(thread.get("root") or "").strip()
    current_id = str(getattr(target, "message_id", "") or "").strip()
    if not root_id or root_id == current_id or thread.get("job_id"):
        return False
    root = runtime.find_source_message_by_id(root_id)
    if root is None or str(getattr(root, "session_id", "") or "") != str(runtime.session_id):
        return False
    root_info = getattr(root, "message_info", None)
    root_config = getattr(root_info, "additional_config", None) or {}
    root_self = str(root_config.get("bot_self_id") or getattr(root, "bot_self_id", "") or "").strip()
    root_targets = {str(v).strip() for v in (root_config.get("at_targets") or ()) if str(v).strip()}
    return bool(root_self and root_self in root_targets or (
        not root_targets and root_config.get("at_bot") is True
        and getattr(root, "is_at", False)
    ))
