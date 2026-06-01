from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable


@dataclass
class MessageRecord:
    group_id: str
    user_id: str
    message_id: str
    timestamp: int
    sender_nickname: str
    sender_card: str
    sender_role: str
    sender_title: str
    text: str
    text_len: int
    message_type: str = "text"
    filtered: int = 0
    filter_reason: str = ""


@dataclass
class GroupBuffer:
    group_id: str
    records: list[MessageRecord] = field(default_factory=list)
    total_text_len: int = 0
    buffer_start_time: int = 0
    last_message_time: int = 0

    @property
    def message_count(self) -> int:
        return len(self.records)

    def add(self, record: MessageRecord) -> None:
        self.records.append(record)
        self.total_text_len += record.text_len
        if self.buffer_start_time <= 0:
            self.buffer_start_time = record.timestamp
        self.last_message_time = record.timestamp

    def reset(self) -> None:
        self.records.clear()
        self.total_text_len = 0
        self.buffer_start_time = 0
        self.last_message_time = 0

    def should_flush(
        self,
        *,
        max_messages: int,
        max_chars: int,
        idle_seconds: int,
        now: int,
    ) -> bool:
        if not self.records:
            return False
        if max_messages > 0 and self.message_count >= max_messages:
            return True
        if max_chars > 0 and self.total_text_len >= max_chars:
            return True
        if idle_seconds > 0 and self.last_message_time > 0:
            return now - self.last_message_time >= idle_seconds
        return False


_CQ_RE = re.compile(r"\[CQ:[^\]]*\]")
_LONG_URL_RE = re.compile(r"https?://\S{80,}")

_SENSITIVE_PATTERNS = [
    "R18",
    "r18",
    "色图",
    "涩图",
    "黄图",
    "色情",
    "hentai",
    "porn",
    "本子",
    "里番",
    "裸体",
    "半裸",
    "全裸",
    "露点",
    "乳交",
    "足交",
    "内裤",
    "内衣",
    "丁字",
    "开腿",
    "脱衣",
    "掀裙",
    "走光",
]

_SENSITIVE_RE = re.compile(
    "|".join(re.escape(pattern) for pattern in _SENSITIVE_PATTERNS),
    re.I,
)


def clean_text(raw: str) -> str:
    text = str(raw or "")
    text = _CQ_RE.sub("", text)
    text = _LONG_URL_RE.sub("[URL]", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()


def is_sensitive(text: str) -> bool:
    return bool(_SENSITIVE_RE.search(str(text or "")))


def parse_allowed_groups(value: object) -> set[str]:
    if value is None:
        return set()

    if isinstance(value, str):
        items: Iterable[object] = value.split(",")
    elif isinstance(value, (list, tuple, set)):
        items = value
    else:
        items = [value]

    result: set[str] = set()
    for item in items:
        group_id = str(item or "").strip()
        if group_id:
            result.add(group_id)
    return result
