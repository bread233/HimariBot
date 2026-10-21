from __future__ import annotations

import time
from typing import Any, Optional

from nonebot.adapters.onebot.v11 import Message, MessageSegment


def validate_reply_route(
    routes: dict[str, dict[str, Any]],
    requested_message_id: Any,
    *,
    is_group: bool,
    target_id: str,
    bot_self_id: str,
    ttl_seconds: float,
    now: Optional[float] = None,
) -> tuple[str, str]:
    message_id = "" if requested_message_id is None else str(requested_message_id).strip()
    if not message_id:
        return "", "missing_reply_message_id"
    route = routes.get(message_id)
    if route is None:
        return "", "route_not_found"
    current = time.time() if now is None else now
    if current - float(route.get("ts", 0)) > ttl_seconds:
        return "", "route_expired"
    if bool(route.get("is_group")) != is_group:
        return "", "chat_type_mismatch"
    if str(route.get("target_id", "") or "").strip() != target_id:
        return "", "target_mismatch"
    route_bot_id = str(route.get("bot_self_id", "") or "").strip()
    if route_bot_id and route_bot_id != bot_self_id:
        return "", "bot_mismatch"
    return message_id, ""


def resolve_reply_message_id(explicit_id: Any, message: Any = None, reply_message: Any = None) -> str:
    candidates = (
        explicit_id,
        getattr(message, "reply_to", None),
        getattr(reply_message, "message_id", None),
    )
    for candidate in candidates:
        if candidate is None:
            continue
        normalized = str(candidate).strip()
        if normalized:
            return normalized
    return ""


def _component_kind(component: Any) -> str:
    format_name = getattr(component, "format_name", None)
    return format_name() if callable(format_name) else (format_name or type(component).__name__)


async def build_onebot_message(message: Any, validated_reply_message_id: str = "") -> tuple[Optional[Message], list[str]]:
    parts: list[MessageSegment] = []
    if validated_reply_message_id:
        parts.append(MessageSegment.reply(validated_reply_message_id))

    raw_message = getattr(message, "raw_message", None)
    components = getattr(raw_message, "components", None) if raw_message is not None else None
    if not components:
        plain_text = str(getattr(message, "processed_plain_text", "") or "").strip()
        if plain_text:
            parts.append(MessageSegment.text(plain_text))
        return (Message(parts), []) if parts else (None, [])

    unsupported: list[str] = []
    for component in components:
        kind = _component_kind(component)
        if kind == "reply":
            continue
        if kind == "text":
            text = str(getattr(component, "text", "") or "").strip()
            if text:
                parts.append(MessageSegment.text(text))
            continue
        if kind in {"image", "emoji"}:
            binary_data = getattr(component, "binary_data", None) or b""
            if not binary_data:
                try:
                    loader = getattr(component, "load_image_binary" if kind == "image" else "load_emoji_binary")
                    await loader()
                    binary_data = getattr(component, "binary_data", None) or b""
                except Exception:
                    continue
            if binary_data:
                parts.append(MessageSegment.image(binary_data))
            continue
        unsupported.append(str(kind))
    return (Message(parts), unsupported) if parts else (None, unsupported)


async def call_onebot_send(bot: Any, *, is_group: bool, target_id: str, message: Message) -> Any:
    if is_group:
        return await bot.call_api("send_group_msg", group_id=int(target_id), message=message)
    return await bot.call_api("send_private_msg", user_id=int(target_id), message=message)


async def send_captured_reply(
    bot: Any,
    reply: Any,
    routes: dict[str, dict[str, Any]],
    *,
    is_group: bool,
    target_id: str,
    bot_self_id: str,
    ttl_seconds: float,
) -> tuple[Any, str, str, Optional[Message]]:
    requested_id = str(getattr(reply, "reply_to_message_id", "") or "").strip()
    validated_id, reason = validate_reply_route(
        routes,
        requested_id,
        is_group=is_group,
        target_id=target_id,
        bot_self_id=bot_self_id,
        ttl_seconds=ttl_seconds,
    )
    raw = getattr(reply, "raw", None)
    if raw is None:
        raw = type("CapturedText", (), {"raw_message": None, "processed_plain_text": reply.text})()
    message, _ = await build_onebot_message(raw, validated_id)
    if message is None:
        return None, validated_id, reason, None
    response = await call_onebot_send(bot, is_group=is_group, target_id=target_id, message=message)
    return response, validated_id, reason, message
