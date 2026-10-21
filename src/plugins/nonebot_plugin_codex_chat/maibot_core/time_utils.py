import math
import time
from datetime import datetime, timezone
from typing import Any, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def normalize_unix_timestamp(raw_value: Any, received_at: Optional[float] = None) -> tuple[float, str, str]:
    """将秒/毫秒时间戳归一化为 Unix epoch 秒，无效值回退接收时间。"""

    fallback = time.time() if received_at is None else float(received_at)
    try:
        value = float(raw_value)
        source = "onebot_event_seconds"
        if value >= 100_000_000_000:
            value /= 1000.0
            source = "onebot_event_milliseconds"
        if not math.isfinite(value) or value <= 0 or value > fallback + 300:
            raise ValueError("timestamp_out_of_range")
        return value, source, ""
    except (TypeError, ValueError, OverflowError) as exc:
        return fallback, "received_at_fallback", type(exc).__name__


def wall_clock_minutes(timezone_name: str, now_epoch: Optional[float] = None) -> tuple[int, str]:
    """返回指定时区当前分钟；时区不可用时回退进程本地时间。"""

    current = time.time() if now_epoch is None else float(now_epoch)
    try:
        local_datetime = datetime.fromtimestamp(current, tz=timezone.utc).astimezone(ZoneInfo(timezone_name))
        return local_datetime.hour * 60 + local_datetime.minute, timezone_name
    except (ZoneInfoNotFoundError, ValueError):
        local_time = time.localtime(current)
        return local_time.tm_hour * 60 + local_time.tm_min, "process_local_fallback"
