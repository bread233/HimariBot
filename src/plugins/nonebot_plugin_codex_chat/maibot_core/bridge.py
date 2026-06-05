from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .bootstrap import bootstrap_src_alias
from .outbound import OutboundCapture

bootstrap_src_alias()


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

    from .chat.message_receive.message import SessionMessage
    from .common.data_models.mai_message_data_model import GroupInfo, MessageInfo, UserInfo
    from .common.data_models.message_component_data_model import MessageSequence, TextComponent

    if receiver is None:
        from .chat.heart_flow.heartflow_message_processor import HeartFCMessageReceiver

        receiver = HeartFCMessageReceiver()

    session_message = SessionMessage()
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
    session_message.raw_message = MessageSequence([TextComponent(text=inbound.plain_text)])
    session_message.processed_plain_text = inbound.plain_text
    session_message.initialized = True

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
