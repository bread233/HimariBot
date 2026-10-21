from dataclasses import dataclass
from typing import Any, Iterable


QUESTION_CUES = ("吗", "怎么", "为什么", "为啥", "什么", "谁", "哪", "多少", "能不能", "可以吗")


@dataclass(frozen=True)
class ReplyTargetGuardResult:
    allowed: bool
    reason: str
    age_seconds: float
    direct_target: bool


def is_direct_reply_target(message: Any) -> bool:
    if bool(getattr(message, "is_at", False) or getattr(message, "is_mentioned", False)):
        return True
    text = str(getattr(message, "processed_plain_text", "") or "").strip()
    return any(cue in text for cue in QUESTION_CUES)


def message_epoch_seconds(message: Any) -> tuple[float | None, str]:
    message_info = getattr(message, "message_info", None)
    additional = getattr(message_info, "additional_config", None) or {}
    raw_epoch = additional.get("event_timestamp_epoch") if isinstance(additional, dict) else None
    try:
        if raw_epoch is not None and float(raw_epoch) > 0:
            return float(raw_epoch), str(additional.get("event_timestamp_source") or "event_epoch")
    except (TypeError, ValueError):
        pass
    timestamp = getattr(message, "timestamp", None)
    try:
        return float(timestamp.timestamp()), "legacy_datetime"
    except (AttributeError, TypeError, ValueError, OverflowError):
        return None, "missing_timestamp"


def evaluate_reply_target(
    target_message: Any,
    *,
    current_session_id: str,
    now_epoch: float,
    max_age_seconds: float,
    candidate_messages: Iterable[Any],
) -> ReplyTargetGuardResult:
    direct_target = is_direct_reply_target(target_message)
    if str(getattr(target_message, "session_id", "") or "") != str(current_session_id or ""):
        return ReplyTargetGuardResult(False, "cross_session", 0.0, direct_target)
    target_epoch, timestamp_source = message_epoch_seconds(target_message)
    if target_epoch is None:
        return ReplyTargetGuardResult(False, "missing_timestamp", 0.0, direct_target)
    age_seconds = max(0.0, float(now_epoch) - target_epoch)
    if age_seconds > max(0.0, float(max_age_seconds)):
        return ReplyTargetGuardResult(False, f"expired:{timestamp_source}", age_seconds, direct_target)
    if not direct_target:
        for candidate in candidate_messages:
            if str(getattr(candidate, "session_id", "") or "") != str(current_session_id or ""):
                continue
            candidate_epoch, _ = message_epoch_seconds(candidate)
            if candidate_epoch is not None and candidate_epoch > target_epoch:
                return ReplyTargetGuardResult(False, "superseded", age_seconds, direct_target)
    return ReplyTargetGuardResult(True, f"fresh:{timestamp_source}", age_seconds, direct_target)


def evaluate_runtime_target(runtime: Any, target_message: Any, max_age_seconds: float, now_epoch: float):
    """使用运行时当前消息缓存执行发送前最终校验。"""

    return evaluate_reply_target(
        target_message,
        current_session_id=runtime.session_id,
        now_epoch=now_epoch,
        max_age_seconds=max_age_seconds,
        candidate_messages=runtime.message_cache,
    )
