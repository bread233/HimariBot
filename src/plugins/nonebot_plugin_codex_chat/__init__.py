from nonebot import get_driver, logger, on_message
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, MessageEvent
from nonebot.params import EventMessage

from .config import get_config
from .maibot_core.bridge import MaibotInboundMessage, handle_inbound_message

__plugin_meta__ = {
    "name": "codex_chat",
    "description": "最小化 Codex CLI 接入插件",
    "usage": "群聊中按触发条件调用 Codex CLI",
}

plugin_config = get_config()
_codex_chat = on_message(priority=plugin_config.codex_chat_command_priority, block=False)
driver = get_driver()
_superusers = {str(x) for x in (getattr(driver.config, "superusers", set()) or set())}
logger.info("codex_chat minimal bootstrap loaded")


@_codex_chat.handle()
async def _handle(event: MessageEvent, bot: Bot, message=EventMessage()):
    if not plugin_config.codex_chat_enable:
        return
    if isinstance(event, GroupMessageEvent):
        group_id = getattr(event, "group_id", None)
        if plugin_config.allowed_groups_list and int(group_id or 0) not in plugin_config.allowed_groups_list:
            return

    fallback_plain_text = str(message).strip()
    converted = None
    try:
        from .onebot_media import convert_onebot_segments_to_maibot_components

        raw_message = getattr(message, "message", None) or message
        converted = await convert_onebot_segments_to_maibot_components(
            raw_message,
            group_id=str(getattr(event, "group_id", "") or "").strip() or None,
            user_id=str(getattr(event, "user_id", "") or "").strip() or None,
            message_id=str(getattr(event, "message_id", "") or "").strip() or f"codex_chat_{getattr(event, 'message_id', '')}",
            download_media=True,
        )
    except Exception as exc:
        logger.exception(f"codex_chat_convert_segments_failed error={exc}")

    plain_text = fallback_plain_text
    components = None
    raw_segments = None
    if converted is not None:
        plain_text = str(converted.plain_text or "").strip() or fallback_plain_text
        components = converted.components
        raw_segments = converted.raw_segments

    if not plain_text and not components:
        return

    sender = getattr(event, "sender", None)
    inbound = MaibotInboundMessage(
        platform="onebot.v11",
        message_id=str(getattr(event, "message_id", "") or "").strip() or f"codex_chat_{getattr(event, 'message_id', '')}",
        user_id=str(getattr(event, "user_id", "") or "").strip(),
        user_nickname=str(getattr(sender, "nickname", "") or "").strip() or str(getattr(sender, "card", "") or "").strip() or "用户",
        user_cardname=str(getattr(sender, "card", "") or "").strip() or None,
        group_id=str(getattr(event, "group_id", "") or "").strip() or None,
        group_name=str(getattr(event, "group_name", "") or "").strip() or None,
        plain_text=plain_text,
        components=components,
        raw_segments=raw_segments,
        raw_event=event,
    )
    result = await handle_inbound_message(inbound)
    if not result.should_reply or not result.replies:
        return

    sent_count = 0
    for index, reply in enumerate(result.replies):
        if not reply.text or not str(reply.text).strip():
            logger.debug(f"codex_chat_send_from_maibot skip_empty index={index}")
            continue
        try:
            await bot.send(event, reply.text)
            sent_count += 1
            logger.info(f"codex_chat_send_from_maibot sent index={index}")
        except Exception as exc:
            logger.exception(f"codex_chat_send_from_maibot failed index={index} error={exc}")
    logger.info(
        f"codex_chat_send_from_maibot done sent_count={sent_count} replies={len(result.replies)}"
    )
