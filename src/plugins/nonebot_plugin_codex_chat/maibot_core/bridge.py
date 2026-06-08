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

# prompt 文件加载失败时的兜底模板（与 prompts/zh-CN/bridge_inline_vision.prompt 内容一致）。
_DEFAULT_BRIDGE_INLINE_VISION_PROMPT = (
    "请用中文简洁描述这张图片的主要内容。"
    "若无法判断，请明确说无法判断。不要编造看不见的信息。"
)


def _load_bridge_inline_vision_prompt() -> str:
    """从 prompt 加载器获取桥接视觉识别 prompt；失败时返回默认 prompt。"""
    from .common.prompt_i18n import load_prompt
    from .common.logger import get_logger

    try:
        text = load_prompt("bridge_inline_vision")
        text = text.strip()
        if not text:
            get_logger("bridge").debug(
                "maibot_bridge_inline_vision_prompt_fallback reason=empty"
            )
            return _DEFAULT_BRIDGE_INLINE_VISION_PROMPT
        return text
    except Exception as exc:
        get_logger("bridge").warning(
            "maibot_bridge_inline_vision_prompt_fallback reason=load_error error=%s",
            type(exc).__name__,
        )
        return _DEFAULT_BRIDGE_INLINE_VISION_PROMPT


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


async def _save_inline_image_description_to_db(
    binary_hash: str,
    description: str,
    *,
    full_path: str = "",
) -> bool:
    """fix34a-1: 用复合条件 (image_hash + image_type=IMAGE) 回写图片描述到 Images 表。

    - 命中 IMAGE 行 → 更新 description / vlm_processed / no_file_flag / last_used_time
    - 未命中 → 新建 IMAGE 行；同 hash 的 EMOJI 行不会被改
    - 失败只 logger.warning，绝不抛异常
    """
    from sqlmodel import select
    from src.common.database.database import get_db_session
    from src.common.database.database_model import Images, ImageType
    from .common.logger import get_logger

    logger = get_logger("bridge")
    now = datetime.now()
    try:
        with get_db_session() as session:
            record = session.exec(
                select(Images).where(
                    Images.image_hash == binary_hash,
                    Images.image_type == ImageType.IMAGE,
                )
            ).first()
            if record is not None:
                record.description = description
                record.vlm_processed = True
                record.no_file_flag = False
                record.last_used_time = now
            else:
                session.add(Images(
                    image_hash=binary_hash, description=description, full_path=full_path,
                    image_type=ImageType.IMAGE, vlm_processed=True, no_file_flag=False,
                    query_count=0, last_used_time=now,
                ))
            session.flush()
        return True
    except Exception as exc:
        logger.warning(
            "maibot_bridge_image_db_write_failed hash=%s error=%s",
            binary_hash[:12], type(exc).__name__,
        )
        return False


async def _process_inbound_emojis(components: list[Any] | None) -> None:
    """Save inbound EmojiComponent binary data to the emoji DB via ensure_emoji_saved.

    - Only processes ``EmojiComponent`` instances; skips everything else.
    - Fail-soft: a single emoji failure logs a warning and continues.
    - Must be called before ``_describe_inbound_images`` (which only handles
      ``ImageComponent``).
    """

    if not components:
        return

    from src.common.data_models.message_component_data_model import EmojiComponent
    from src.emoji_system.emoji_manager import emoji_manager
    from .common.logger import get_logger

    logger = get_logger("bridge")

    saved = 0
    skipped = 0
    failed = 0

    for comp in components:
        if not isinstance(comp, EmojiComponent):
            continue
        binary_data = getattr(comp, "binary_data", None)
        if not binary_data:
            skipped += 1
            continue
        emoji_hash = getattr(comp, "binary_hash", None)
        saved_emoji = None
        try:
            saved_emoji = await emoji_manager.ensure_emoji_saved(
                emoji_bytes=binary_data,
                emoji_hash=emoji_hash,
            )
            saved += 1
        except Exception as exc:
            failed += 1
            logger.warning(
                "maibot_bridge_emoji_save_failed hash=%s error=%s",
                emoji_hash[:12] if emoji_hash else "?",
                exc,
            )
            continue
        if saved_emoji:
            reg_status = "failed"
            try:
                reg_status = await emoji_manager.register_emoji_by_filename(saved_emoji.full_path)
                if reg_status == "registered":
                    logger.info(
                        "maibot_bridge_emoji_registered hash=%s path=%s",
                        emoji_hash[:12] if emoji_hash else "?",
                        saved_emoji.full_path,
                    )
            except Exception as exc:
                logger.warning(
                    "maibot_bridge_emoji_register_failed hash=%s error=%s",
                    emoji_hash[:12] if emoji_hash else "?",
                    exc,
                )
            if reg_status == "failed":
                try:
                    saved_emoji.description = saved_emoji.description or "群聊中收集的表情"
                    saved_emoji.emotion = saved_emoji.emotion or ["表情"]
                    db_status = emoji_manager.register_emoji_to_db(saved_emoji)
                    if db_status == "registered":
                        if not emoji_manager.get_emoji_by_hash(saved_emoji.file_hash):
                            emoji_manager.emojis.append(saved_emoji)
                        emoji_manager._emoji_num = len(emoji_manager.emojis)
                        logger.info(
                            "maibot_bridge_emoji_fallback_registered hash=%s path=%s",
                            emoji_hash[:12] if emoji_hash else "?",
                            saved_emoji.full_path,
                        )
                    elif db_status == "skipped":
                        logger.debug(
                            "maibot_bridge_emoji_fallback_skipped hash=%s",
                            emoji_hash[:12] if emoji_hash else "?",
                        )
                except Exception as exc:
                    logger.warning(
                        "maibot_bridge_emoji_fallback_register_failed hash=%s error=%s",
                        emoji_hash[:12] if emoji_hash else "?",
                        exc,
                    )

    if saved or failed:
        logger.debug(
            "maibot_bridge_emoji_save_done emojis=%d saved=%d skipped=%d failed=%d",
            saved + skipped + failed, saved, skipped, failed,
        )


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
                prompt=_load_bridge_inline_vision_prompt(),
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
        await _save_inline_image_description_to_db(comp.binary_hash, text)
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
        await _process_inbound_emojis(inbound.components)
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
