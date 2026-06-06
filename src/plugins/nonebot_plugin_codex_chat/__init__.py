from __future__ import annotations

import time
import traceback
from typing import Any, Awaitable, Callable, Optional

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


_HOST_TARGET_TTL_SECONDS = 600
_host_target_registry: dict[str, tuple[Bot, dict[str, Any]]] = {}


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
    now = time.time()
    expired_keys = [k for k, (_, v) in _host_target_registry.items() if now - float(v.get("ts", 0)) > _HOST_TARGET_TTL_SECONDS]
    for k in expired_keys:
        _host_target_registry.pop(k, None)


def _resolve_target_for_message(message: Any) -> Optional[tuple[Bot, dict[str, Any]]]:
    """根据 SessionMessage 推断应使用的 NoneBot Bot 与目标。"""

    if message is None:
        return None
    platform = str(getattr(message, "platform", "") or "").strip()
    if platform and platform != "onebot.v11":
        return None

    group_info = None
    user_info = None
    message_info = getattr(message, "message_info", None)
    if message_info is not None:
        group_info = getattr(message_info, "group_info", None)
        user_info = getattr(message_info, "user_info", None)

    if group_info is not None:
        group_id = str(getattr(group_info, "group_id", "") or "").strip()
        if group_id:
            key = f"onebot.v11:group:{group_id}"
            record = _host_target_registry.get(key)
            if record is not None:
                return record

    if user_info is not None:
        user_id = str(getattr(user_info, "user_id", "") or "").strip()
        if user_id:
            key = f"onebot.v11:private:{user_id}"
            record = _host_target_registry.get(key)
            if record is not None:
                return record

    for key, record in _host_target_registry.items():
        if key.startswith("onebot.v11:"):
            return record
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


async def _codex_chat_host_send_interceptor(message: Any) -> Optional[Any]:
    """宿主层接管 Maibot 出站消息并通过 NoneBot Bot 真实发送。"""

    target = _resolve_target_for_message(message)
    if target is None:
        return None
    bot, info = target

    text, non_text_kinds = _build_onebot_message_text(message)
    if not text:
        if non_text_kinds:
            logger.info(
                f"codex_chat_host_send_skip message_id={getattr(message, 'message_id', '')} "
                f"reason=non_text_only kinds={','.join(non_text_kinds)}"
            )
        return None

    is_group = bool(info.get("is_group"))
    target_id = str(info.get("target_id", "") or "").strip()
    if not target_id:
        return None

    message_id = str(getattr(message, "message_id", "") or "").strip()
    logger.info(
        f"codex_chat_host_send_intercept platform=onebot.v11 "
        f"is_group={is_group} target_id={target_id} "
        f"text_chars={len(text)} maibot_message_id={message_id} "
        f"non_text_kinds={','.join(non_text_kinds) if non_text_kinds else '-'}"
    )

    try:
        from nonebot.adapters.onebot.v11 import Message
    except Exception as exc:
        logger.error(
            f"codex_chat_host_send_failed stage=import_message error={type(exc).__name__}: {exc}"
        )
        return None

    try:
        if is_group:
            api_response = await bot.call_api(
                "send_group_msg",
                group_id=int(target_id),
                message=Message(text),
            )
        else:
            api_response = await bot.call_api(
                "send_private_msg",
                user_id=int(target_id),
                message=Message(text),
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
        f"target_id={target_id} is_group={is_group} text_chars={len(text)}"
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
