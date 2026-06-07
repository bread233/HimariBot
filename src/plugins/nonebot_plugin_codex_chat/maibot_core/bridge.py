from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from .bootstrap import bootstrap_src_alias
from src.outbound import OutboundCapture
from src.chat.message_receive.chat_manager import chat_manager

bootstrap_src_alias()


# fix33b: 入站同步识图，单消息最多识别 1 张图片，避免多图拖死。
MAX_INLINE_VISION_IMAGES = 1

# 复用 codex_vision_adapter.DEFAULT_VISION_PROMPT 的措辞；这里显式再写一次，
# 避免与 codex_vision_adapter 顶层 import 在本函数外产生副作用。
_BRIDGE_INLINE_VISION_PROMPT = (
    "请用中文简洁描述这张图片的主要内容。"
    "若无法判断，请明确说无法判断。不要编造看不见的信息。"
)


def _should_describe_image(comp: Any) -> bool:
    """判断一个 ImageComponent 是否仍需要被识图补全描述。

    触发条件（任一即可）：
    - ``content`` 为空（None / 空字符串 / 纯空白）；
    - ``content.strip() == "[图片]"``（onebot_media 入站默认占位符）；
    - ``content`` 含 "识别中"（占位文案，常见于上下游未完成识别时）。

    已经填了 ``[图片：<xxx>]`` 之类真实描述的 component 不会被再次识别。
    """

    content = getattr(comp, "content", None)
    if content is None:
        return True
    normalized = str(content).strip()
    if not normalized:
        return True
    if normalized == "[图片]":
        return True
    if "识别中" in normalized:
        return True
    return False


def _guess_image_mime(data: bytes) -> str | None:
    """按 magic byte 推断常见图片 mime；与 codex_vision_adapter._guess_mime_type 保持一致。"""

    if not data:
        return None
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"GIF87a") or data.startswith(b"GIF89a"):
        return "image/gif"
    if data.startswith(b"RIFF") and b"WEBP" in data[:16]:
        return "image/webp"
    return None


async def _describe_inbound_images(components: list[Any] | None) -> None:
    """对入站 components 中前 N 张未识图 ImageComponent 同步调 Codex 视觉识别。

    - 直接改 ``ImageComponent.content``（不是 frozen dataclass，普通实例属性可写）；
    - 失败时保留原 content，绝不抛异常；不阻塞整条消息；
    - 重复 component / 重复 binary_data 不再二次识别（``_should_describe_image`` 守门）；
    - 每张图最多只识别 1 张，超出的图片计入 ``skipped`` 计数。
    """

    if not components:
        return

    from .codex_vision_adapter import describe_image
    from src.common.data_models.message_component_data_model import ImageComponent
    from .common.logger import get_logger

    logger = get_logger("bridge")

    images_total = 0
    ok_count = 0
    fail_count = 0
    skip_count = 0

    for index, comp in enumerate(components):
        if not isinstance(comp, ImageComponent):
            continue
        binary_data = getattr(comp, "binary_data", None)
        if not binary_data:
            continue
        images_total += 1

        if ok_count + fail_count >= MAX_INLINE_VISION_IMAGES:
            skip_count += 1
            continue

        if not _should_describe_image(comp):
            continue

        binary_len = len(binary_data)
        mime = _guess_image_mime(binary_data) or "unknown"
        try:
            result = await describe_image(
                image_bytes=binary_data,
                mime_type=None,
                prompt=_BRIDGE_INLINE_VISION_PROMPT,
                context={"source": "bridge_inline_vision", "index": str(index)},
            )
        except Exception as exc:
            logger.warning(
                "maibot_bridge_image_vision_failed error=describe_exception:%s "
                "source=codex_cli_image mime=%s index=%s bytes=%s",
                type(exc).__name__,
                mime,
                index,
                binary_len,
            )
            fail_count += 1
            continue

        if not result.ok:
            logger.warning(
                "maibot_bridge_image_vision_failed error=%s source=%s "
                "mime=%s index=%s bytes=%s",
                result.error,
                result.source,
                mime,
                index,
                binary_len,
            )
            fail_count += 1
            continue

        text = (result.text or "").strip()
        if not text:
            logger.warning(
                "maibot_bridge_image_vision_failed error=empty_text source=%s "
                "mime=%s index=%s bytes=%s",
                result.source,
                mime,
                index,
                binary_len,
            )
            fail_count += 1
            continue

        comp.content = f"[图片：{text}]"
        ok_count += 1
        logger.info(
            "maibot_bridge_image_vision_success source=%s chars=%s "
            "mime=%s index=%s bytes=%s",
            result.source,
            len(text),
            mime,
            index,
            binary_len,
        )

    if images_total:
        logger.info(
            "maibot_bridge_image_vision_done images=%s ok=%s failed=%s skipped=%s",
            images_total,
            ok_count,
            fail_count,
            skip_count,
        )


@dataclass(slots=True)
class MaibotInboundMessage:
    platform: str
    message_id: str
    user_id: str
    user_nickname: str
    user_cardname: str | None
    group_id: str | None
    group_name: str | None
    plain_text: str
    components: list[Any] | None = None
    raw_segments: list[dict[str, Any]] | None = None
    raw_event: Any | None = None


@dataclass(slots=True)
class MaibotOutboundMessage:
    text: str
    segments: list[dict] | None = None
    reply_to_message_id: str | None = None
    raw: Any | None = None
    source: str = "maibot_capture"


@dataclass(slots=True)
class MaibotHandleResult:
    should_reply: bool
    replies: list[MaibotOutboundMessage] = field(default_factory=list)
    reason: str = ""



def build_maibot_outbound_replies(captured_messages: list[Any]) -> list[MaibotOutboundMessage]:
    replies: list[MaibotOutboundMessage] = []
    for msg in captured_messages:
        text = str(getattr(msg, "text", "") or "").strip()
        if not text:
            continue
        replies.append(
            MaibotOutboundMessage(
                text=text,
                segments=getattr(msg, "segments", None),
                reply_to_message_id=getattr(msg, "reply_to_message_id", None),
                raw=getattr(msg, "raw", None),
                source=str(getattr(msg, "source", "maibot_capture") or "maibot_capture"),
            )
        )
    return replies


async def handle_inbound_message(
    inbound: MaibotInboundMessage,
    receiver: Any | None = None,
) -> MaibotHandleResult:
    """将外部消息送入 maibot_core 入站链路。"""

    from src.chat.message_receive.message import SessionMessage
    from src.common.data_models.mai_message_data_model import GroupInfo, MessageInfo, UserInfo
    from src.common.data_models.message_component_data_model import MessageSequence, TextComponent

    if receiver is None:
        from .chat.heart_flow.heartflow_message_processor import HeartFCMessageReceiver

        receiver = HeartFCMessageReceiver()

    session_message = SessionMessage(
        message_id=inbound.message_id,
        timestamp=datetime.now(),
        platform=inbound.platform,
    )
    session_message.platform = inbound.platform
    session_message.message_id = inbound.message_id
    session_message.message_info = MessageInfo(
        user_info=UserInfo(
            user_id=inbound.user_id,
            user_nickname=inbound.user_nickname,
            user_cardname=inbound.user_cardname,
        ),
        group_info=(
            GroupInfo(group_id=inbound.group_id, group_name=inbound.group_name or "群聊")
            if inbound.group_id
            else None
        ),
        additional_config={},
    )
    if inbound.components:
        await _describe_inbound_images(inbound.components)
        raw_message = MessageSequence(inbound.components)
    else:
        raw_message = MessageSequence([TextComponent(text=inbound.plain_text)])
    session_message.raw_message = raw_message
    session_message.processed_plain_text = inbound.plain_text
    session_message.initialized = True

    session = await chat_manager.get_or_create_session(
        inbound.platform,
        inbound.user_id,
        inbound.group_id,
    )
    session_message.session_id = session.session_id

    try:
        with OutboundCapture() as capture:
            await receiver.process_message(session_message)

        captured_count = len(capture.messages)
        replies = build_maibot_outbound_replies(capture.messages)
        result = MaibotHandleResult(
            should_reply=bool(replies),
            replies=replies,
            reason="maibot_core_outbound_captured" if replies else "maibot_core_no_reply",
        )
        from .common.logger import get_logger

        get_logger("bridge").info(
            f"maibot_outbound_capture captured count={captured_count}; "
            f"maibot_bridge_result should_reply={result.should_reply} replies={len(result.replies)} reason={result.reason}"
        )
        return result
    except Exception as exc:
        from .common.logger import get_logger

        get_logger("bridge").exception(f"maibot_bridge_result should_reply=False replies=0 reason=maibot_bridge_error:{exc}")
        return MaibotHandleResult(should_reply=False, replies=[], reason=f"maibot_bridge_error:{exc}")
