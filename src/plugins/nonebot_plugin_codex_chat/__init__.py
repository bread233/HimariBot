from __future__ import annotations

import time
import traceback
from typing import Any, Awaitable, Callable, Optional

from nonebot import get_driver, logger, on_message
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, MessageEvent
from nonebot.params import EventMessage

from .config import get_config
from .maibot_core.bridge import MaibotInboundMessage, handle_inbound_message
from .maibot_core.bootstrap import bootstrap_src_alias

bootstrap_src_alias()

from src.emoji_system.emoji_manager import emoji_manager
from src.prompt.prompt_manager import prompt_manager

__plugin_meta__ = {
    "name": "codex_chat",
    "description": "最小化 Codex CLI 接入插件",
    "usage": "群聊中按触发条件调用 Codex CLI",
}

plugin_config = get_config()
_codex_chat = on_message(priority=plugin_config.codex_chat_command_priority, block=False)
driver = get_driver()
_superusers = {str(x) for x in (getattr(driver.config, "superusers", set()) or set())}


def _ensure_maibot_prompts_loaded() -> None:
    if "emoji_selection" in prompt_manager.prompts:
        return
    prompt_manager.load_prompts()
    logger.info(
        f"codex_chat_prompt_manager_loaded count={len(prompt_manager.prompts)} "
        f"has_emoji_selection={'emoji_selection' in prompt_manager.prompts}"
    )


def _ensure_maibot_emojis_loaded() -> None:
    if emoji_manager.emojis:
        return
    emoji_manager.load_emojis_from_db()
    logger.info(
        f"codex_chat_emoji_manager_bootstrap_state id={id(emoji_manager)} "
        f"class={emoji_manager.__class__} "
        f"module={emoji_manager.__class__.__module__} "
        f"emoji_count={len(emoji_manager.emojis)}"
    )


_ensure_maibot_prompts_loaded()
_ensure_maibot_emojis_loaded()
logger.info("codex_chat minimal bootstrap loaded")


_HOST_TARGET_TTL_SECONDS = 600
_host_target_registry: dict[str, tuple[Bot, dict[str, Any]]] = {}
_onebot_bots_by_self_id: dict[str, Bot] = {}
_inbound_route_by_message_id: dict[str, dict[str, Any]] = {}


def _remember_target(event: MessageEvent, bot: Bot) -> None:
    """记录最近一次入站事件对应的 NoneBot Bot 与目标。"""

    if isinstance(event, GroupMessageEvent):
        group_id = str(getattr(event, "group_id", "") or "").strip()
        if not group_id:
            return
        key = f"onebot.v11:group:{group_id}"
        info: dict[str, Any] = {
            "is_group": True,
            "target_id": group_id,
            "ts": time.time(),
        }
    else:
        user_id = str(getattr(event, "user_id", "") or "").strip()
        if not user_id:
            return
        key = f"onebot.v11:private:{user_id}"
        info = {
            "is_group": False,
            "target_id": user_id,
            "ts": time.time(),
        }
    _host_target_registry[key] = (bot, info)
    bot_self_id = str(getattr(bot, "self_id", "") or "").strip()
    if bot_self_id:
        _onebot_bots_by_self_id[bot_self_id] = bot
    now = time.time()
    expired_keys = [k for k, (_, v) in _host_target_registry.items() if now - float(v.get("ts", 0)) > _HOST_TARGET_TTL_SECONDS]
    for k in expired_keys:
        _host_target_registry.pop(k, None)


def _record_inbound_route(event: MessageEvent, bot: Bot) -> None:
    """记录入站 event.message_id -> (is_group, target_id, bot_self_id)。

    fix30: 这是 outbound host_send_interceptor 解析发送目标的主索引,
    通过 reply_message_id / message.reply_to / reply_message.message_id 查回。
    """

    event_message_id = str(getattr(event, "message_id", "") or "").strip()
    if not event_message_id:
        return
    bot_self_id = str(getattr(bot, "self_id", "") or "").strip()
    if isinstance(event, GroupMessageEvent):
        group_id = str(getattr(event, "group_id", "") or "").strip()
        if not group_id:
            return
        is_group = True
        target_id = group_id
    else:
        user_id = str(getattr(event, "user_id", "") or "").strip()
        if not user_id:
            return
        is_group = False
        target_id = user_id
    _inbound_route_by_message_id[event_message_id] = {
        "is_group": is_group,
        "target_id": target_id,
        "bot_self_id": bot_self_id,
        "ts": time.time(),
    }
    now = time.time()
    expired = [
        k for k, v in _inbound_route_by_message_id.items()
        if now - float(v.get("ts", 0)) > _HOST_TARGET_TTL_SECONDS
    ]
    for k in expired:
        _inbound_route_by_message_id.pop(k, None)


def _lookup_inbound_route(
    message: Any,
    reply_message_id: str = "",
    reply_message: Any = None,
) -> Optional[dict[str, Any]]:
    """按优先级查 _inbound_route_by_message_id:
    1. reply_message_id (显式参数)
    2. message.reply_to (outbound SessionMessage 上的 reply_to 字段)
    3. reply_message.message_id (被引用消息对象的 message_id)
    """

    candidates: list[str] = []
    if reply_message_id:
        candidates.append(str(reply_message_id).strip())
    if message is not None:
        reply_to = str(getattr(message, "reply_to", "") or "").strip()
        if reply_to:
            candidates.append(reply_to)
    if reply_message is not None:
        rm_msg_id = str(getattr(reply_message, "message_id", "") or "").strip()
        if rm_msg_id:
            candidates.append(rm_msg_id)
    now = time.time()
    for mid in candidates:
        if not mid:
            continue
        record = _inbound_route_by_message_id.get(mid)
        if record is None:
            continue
        if now - float(record.get("ts", 0)) > _HOST_TARGET_TTL_SECONDS:
            _inbound_route_by_message_id.pop(mid, None)
            continue
        return record
    return None


def _extract_outbound_target(message: Any) -> Optional[tuple[bool, str, str, str]]:
    """从 outbound SessionMessage 自身 message_info 提取 (is_group, target_id, message_group_id, message_user_id)。

    严格禁止从 registry 取 target_id (fix29 修复串台 bug)。
    """

    if message is None:
        return None
    platform = str(getattr(message, "platform", "") or "").strip()
    if platform and platform != "onebot.v11":
        return None

    group_id = ""
    user_id = ""
    message_info = getattr(message, "message_info", None)
    if message_info is not None:
        group_info = getattr(message_info, "group_info", None)
        user_info = getattr(message_info, "user_info", None)
        if group_info is not None:
            group_id = str(getattr(group_info, "group_id", "") or "").strip()
        if user_info is not None:
            user_id = str(getattr(user_info, "user_id", "") or "").strip()

    if group_id:
        return True, group_id, group_id, user_id
    if user_id:
        return False, user_id, group_id, user_id
    return None


def _pick_onebot_bot(message: Any) -> Optional[Bot]:
    """为出站消息挑选 NoneBot Bot。

    严格只使用 _onebot_bots_by_self_id (按 self_id 索引), 不从 registry 群号里取 bot。
    多 bot 时按 message 自带 self_id (或 additional_config.bot_self_id) 匹配;
    无法消解时返回 None (不拦截, 不 fallback 到任意 bot)。
    """

    if not _onebot_bots_by_self_id:
        return None
    if len(_onebot_bots_by_self_id) == 1:
        return next(iter(_onebot_bots_by_self_id.values()))

    target_self_id = ""
    if message is not None:
        target_self_id = str(getattr(message, "self_id", "") or "").strip()
        if not target_self_id:
            message_info = getattr(message, "message_info", None)
            if message_info is not None:
                add_cfg = getattr(message_info, "additional_config", None) or {}
                target_self_id = str(
                    add_cfg.get("platform_io_target_self_id")
                    or add_cfg.get("bot_self_id")
                    or ""
                ).strip()
    if target_self_id and target_self_id in _onebot_bots_by_self_id:
        return _onebot_bots_by_self_id[target_self_id]
    return None


def _build_onebot_message_text(message: Any) -> tuple[Optional[str], list[str]]:
    """从 SessionMessage 提取纯文本及非文本组件类型列表。"""

    plain_text = str(getattr(message, "processed_plain_text", "") or "").strip()
    non_text_kinds: list[str] = []
    raw_message = getattr(message, "raw_message", None)
    components = getattr(raw_message, "components", None) if raw_message is not None else None
    if components:
        for component in components:
            format_name = getattr(component, "format_name", None)
            kind = format_name() if callable(format_name) else (format_name or type(component).__name__)
            if kind != "text":
                non_text_kinds.append(str(kind))
    if plain_text:
        return plain_text, non_text_kinds
    if non_text_kinds:
        return None, non_text_kinds
    return None, []


def _get_component_kind(component: Any) -> str:
    """获取组件的格式名称。"""

    format_name = getattr(component, "format_name", None)
    return format_name() if callable(format_name) else (format_name or type(component).__name__)


async def _build_onebot_message(message: Any) -> tuple[Optional[Any], list[str]]:
    """从 SessionMessage 构建 NoneBot Message，支持文本 + 图片 + 表情组件。

    返回 (Message | None, unsupported_kinds)。
    - 有可发送片段时返回 (Message, unsupported_kinds)
    - 全部不支持时返回 ([], unsupported_kinds)
    - 失败时返回 (None, unsupported_kinds)
    """

    from nonebot.adapters.onebot.v11 import Message, MessageSegment

    raw_message = getattr(message, "raw_message", None)
    components = getattr(raw_message, "components", None) if raw_message is not None else None
    if not components:
        plain_text = str(getattr(message, "processed_plain_text", "") or "").strip()
        if plain_text:
            return Message(plain_text), []
        return None, []

    message_parts: list = []
    unsupported_kinds: list[str] = []

    for component in components:
        kind = _get_component_kind(component)

        if kind == "text":
            text_val = str(getattr(component, "text", "") or "").strip()
            if text_val:
                message_parts.append(MessageSegment.text(text_val))
            continue

        if kind in ("image", "emoji"):
            binary_data: Optional[bytes] = getattr(component, "binary_data", None) or b""
            if not binary_data:
                try:
                    if kind == "image":
                        await component.load_image_binary()
                    else:
                        await component.load_emoji_binary()
                    binary_data = getattr(component, "binary_data", None) or b""
                except Exception as exc:
                    logger.warning(
                        f"codex_chat_host_send_media_load_failed kind={kind} "
                        f"error={type(exc).__name__}: {exc}"
                    )
                    continue
            if binary_data:
                message_parts.append(MessageSegment.image(binary_data))
            continue

        unsupported_kinds.append(kind)
        logger.warning(
            f"codex_chat_host_send_unsupported_component kind={kind}"
        )

    if not message_parts:
        return None, unsupported_kinds

    return Message(message_parts), unsupported_kinds


async def _codex_chat_host_send_interceptor(
    message: Any,
    reply_message_id: str = "",
    reply_message: Any = None,
) -> Optional[Any]:
    """宿主层接管 Maibot 出站消息并通过 NoneBot Bot 真实发送。

    fix30: 目标完全由 inbound route (event.message_id) 决定 (查 reply_message_id
    / message.reply_to / reply_message.message_id), 禁止:
    1. 用 outbound message_info.user_info.user_id 判定私聊目标 (那通常是 bot 自身 ID)
    2. fallback 到 bot self_id
    3. registry 中其他 group 的 stale 记录污染当前 message
    """

    # 解析 outbound 自带的 group_id (仅用于无 route 时的兜底, 不允许用 user_id 兜底)
    message_group_id = ""
    message_user_id_outbound = ""
    message_info = getattr(message, "message_info", None)
    if message_info is not None:
        group_info = getattr(message_info, "group_info", None)
        user_info = getattr(message_info, "user_info", None)
        if group_info is not None:
            message_group_id = str(getattr(group_info, "group_id", "") or "").strip()
        if user_info is not None:
            message_user_id_outbound = str(getattr(user_info, "user_id", "") or "").strip()

    # 1. 查 inbound route
    route = _lookup_inbound_route(message, reply_message_id, reply_message)
    if route is not None:
        is_group = bool(route.get("is_group"))
        target_id = str(route.get("target_id", "") or "").strip()
        route_bot_self_id = str(route.get("bot_self_id", "") or "").strip()
        resolved_via = "route"
    else:
        # 2. 无 route: 兜底只允许 outbound 自带 group_id
        if not message_group_id:
            logger.warning(
                f"codex_chat_host_send_no_route platform={getattr(message, 'platform', '')} "
                f"reply_message_id={reply_message_id} "
                f"message_group_id={message_group_id} "
                f"message_user_id={message_user_id_outbound} "
                f"message_id={getattr(message, 'message_id', '')}"
            )
            return False
        is_group = True
        target_id = message_group_id
        route_bot_self_id = ""
        resolved_via = "outbound_group_fallback"

    if not target_id:
        logger.warning(
            f"codex_chat_host_send_no_target_id is_group={is_group} "
            f"reply_message_id={reply_message_id} resolved_via={resolved_via} "
            f"message_id={getattr(message, 'message_id', '')}"
        )
        return False

    # 3. 选 bot: 优先 route 自带的 bot_self_id
    if route_bot_self_id and route_bot_self_id in _onebot_bots_by_self_id:
        bot = _onebot_bots_by_self_id[route_bot_self_id]
    else:
        bot = _pick_onebot_bot(message)
    bot_self_id = str(getattr(bot, "self_id", "") or "").strip() if bot is not None else ""
    if bot is None:
        logger.warning(
            f"codex_chat_host_send_no_bot is_group={is_group} target_id={target_id} "
            f"message_group_id={message_group_id} "
            f"route_bot_self_id={route_bot_self_id} "
            f"reply_message_id={reply_message_id} "
            f"message_id={getattr(message, 'message_id', '')}"
        )
        return None

    # 4. 私聊: target_id == bot.self_id 拒绝
    if (not is_group) and target_id == bot_self_id:
        logger.warning(
            f"codex_chat_host_send_self_target_rejected is_group={is_group} "
            f"target_id={target_id} bot_self_id={bot_self_id} "
            f"reply_message_id={reply_message_id} resolved_via={resolved_via} "
            f"message_id={getattr(message, 'message_id', '')}"
        )
        return False

    # 5. 构建 OneBot Message（支持文本 + 图片 + 表情组件）
    onebot_msg, unsupported_kinds = await _build_onebot_message(message)
    if onebot_msg is None:
        if unsupported_kinds:
            logger.info(
                f"codex_chat_host_send_skip message_id={getattr(message, 'message_id', '')} "
                f"reason=unsupported_only kinds={','.join(unsupported_kinds)}"
            )
        return None

    message_id = str(getattr(message, "message_id", "") or "").strip()
    logger.info(
        f"codex_chat_host_send_intercept platform=onebot.v11 "
        f"is_group={is_group} target_id={target_id} "
        f"resolved_via={resolved_via} "
        f"message_group_id={message_group_id} "
        f"reply_message_id={reply_message_id} "
        f"bot_self_id={bot_self_id} "
        f"parts={len(onebot_msg)} "
        f"non_text_kinds={','.join(unsupported_kinds) if unsupported_kinds else '-'}"
    )

    try:
        if is_group:
            api_response = await bot.call_api(
                "send_group_msg",
                group_id=int(target_id),
                message=onebot_msg,
            )
        else:
            api_response = await bot.call_api(
                "send_private_msg",
                user_id=int(target_id),
                message=onebot_msg,
            )
    except Exception as exc:
        logger.error(
            f"codex_chat_host_send_failed message_id={message_id} "
            f"target_id={target_id} is_group={is_group} "
            f"error={type(exc).__name__}: {exc}\n{traceback.format_exc()}"
        )
        return None

    onebot_message_id = ""
    if isinstance(api_response, dict):
        onebot_message_id = str(api_response.get("message_id", "") or "").strip()
    if not onebot_message_id:
        logger.warning(
            f"codex_chat_host_send_no_message_id message_id={message_id} "
            f"target_id={target_id} is_group={is_group} response={api_response!r}"
        )
        return None

    synthetic_message: Any
    try:
        from copy import deepcopy
        synthetic_message = deepcopy(message)
    except Exception:
        synthetic_message = message
    try:
        synthetic_message.message_id = onebot_message_id
    except Exception:
        pass

    logger.info(
        f"codex_chat_host_send_success message_id={onebot_message_id} "
        f"target_id={target_id} is_group={is_group} parts={len(onebot_msg)}"
    )
    return synthetic_message


def _register_host_send_interceptor() -> None:
    """向 maibot_core 注册宿主层出站拦截器。

    由于 ``bootstrap_src_alias`` 会把 ``maibot_core`` 树作为虚拟 ``src`` 包
    重新挂载，运行时存在两个不同的 ``send_service`` 模块对象：

    * ``nonebot_plugin_codex_chat.maibot_core.services.send_service``（宿主侧导入路径）
    * ``src.services.send_service``（Maibot 内部 ``from src...`` 路径）

    ``_host_send_interceptor`` 是模块级全局变量，两个模块对象各自持有
    一份，互不可见。本函数在两个模块对象上分别注册拦截器，并在日志中
    标注 ``module=``，以便在生产环境确认哪条路径生效。
    """

    try:
        from .maibot_core.services import send_service as _pkg_send_service
    except Exception as exc:
        logger.warning(
            f"codex_chat_host_send_interceptor_pkg_import_failed error={type(exc).__name__}: {exc}"
        )
        return

    try:
        from .maibot_core.bootstrap import bootstrap_src_alias
        bootstrap_src_alias()
    except Exception as exc:
        logger.warning(
            f"codex_chat_host_send_interceptor_bootstrap_failed error={type(exc).__name__}: {exc}"
        )

    _src_send_service = None
    try:
        import src.services.send_service as _src_send_service
    except Exception:
        _src_send_service = None

    modules_to_register = [
        (
            "nonebot_plugin_codex_chat.maibot_core.services.send_service",
            _pkg_send_service,
        )
    ]
    if _src_send_service is not None and _src_send_service is not _pkg_send_service:
        modules_to_register.append(("src.services.send_service", _src_send_service))
    elif _src_send_service is not None and _src_send_service is _pkg_send_service:
        logger.debug(
            "codex_chat_host_send_interceptor_pkg_src_same_module skip_dual"
        )

    for module_name, module in modules_to_register:
        try:
            previous = module.set_host_send_interceptor(_codex_chat_host_send_interceptor)
            logger.info(
                f"codex_chat_host_send_interceptor_registered module={module_name} "
                f"previous={previous is not None}"
            )
        except Exception as exc:
            logger.warning(
                f"codex_chat_host_send_interceptor_register_failed "
                f"module={module_name} error={type(exc).__name__}: {exc}"
            )


_register_host_send_interceptor()


@_codex_chat.handle()
async def _handle(event: MessageEvent, bot: Bot, message=EventMessage()):
    if not plugin_config.codex_chat_enable:
        return
    if isinstance(event, GroupMessageEvent):
        group_id = getattr(event, "group_id", None)
        if plugin_config.allowed_groups_list and int(group_id or 0) not in plugin_config.allowed_groups_list:
            return

    _remember_target(event, bot)
    _record_inbound_route(event, bot)

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
            self_id=str(getattr(bot, "self_id", "") or "").strip() or None,
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
