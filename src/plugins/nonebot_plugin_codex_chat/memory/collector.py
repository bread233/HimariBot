from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Optional

from nonebot import get_driver, logger, on_message
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, MessageEvent

from .policy import (
    GroupBuffer,
    MessageRecord,
    clean_text,
    is_sensitive,
    parse_allowed_groups,
)
from .storage import init_db, insert_memcell

_DEFAULT_ALLOWED_GROUPS = "861300681,1139272387,610726923,279182779,415399529"


@dataclass
class MemoryRuntimeConfig:
    enable: bool = True
    observe_only: bool = True
    allowed_groups: set[str] | None = None
    max_messages: int = 20
    max_chars: int = 2000
    idle_seconds: int = 180
    raw_preview_max_chars: int = 1200
    store_messages: bool = True


def _parse_bool(value: object, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y", "on"}:
        return True
    if text in {"0", "false", "no", "n", "off"}:
        return False
    return default


def _parse_int(value: object, default: int) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _load_config() -> MemoryRuntimeConfig:
    driver_config = get_driver().config

    allowed_groups = parse_allowed_groups(
        getattr(
            driver_config,
            "codex_chat_memory_allowed_groups",
            _DEFAULT_ALLOWED_GROUPS,
        )
    )

    return MemoryRuntimeConfig(
        enable=_parse_bool(
            getattr(driver_config, "codex_chat_memory_enable", True),
            True,
        ),
        observe_only=_parse_bool(
            getattr(driver_config, "codex_chat_memory_observe_only", True),
            True,
        ),
        allowed_groups=allowed_groups,
        max_messages=_parse_int(
            getattr(driver_config, "codex_chat_memory_cell_max_messages", 20),
            20,
        ),
        max_chars=_parse_int(
            getattr(driver_config, "codex_chat_memory_cell_max_chars", 2000),
            2000,
        ),
        idle_seconds=_parse_int(
            getattr(driver_config, "codex_chat_memory_cell_idle_seconds", 180),
            180,
        ),
        raw_preview_max_chars=_parse_int(
            getattr(driver_config, "codex_chat_memory_raw_preview_max_chars", 1200),
            1200,
        ),
        store_messages=_parse_bool(
            getattr(driver_config, "codex_chat_memory_store_messages", True),
            True,
        ),
    )


class MemoryCollector:
    def __init__(self) -> None:
        self._buffers: dict[str, GroupBuffer] = {}
        self._lock = asyncio.Lock()
        self._config = MemoryRuntimeConfig()
        self._idle_task: Optional[asyncio.Task] = None
        self._started = False

    async def start(self) -> None:
        if self._started:
            return

        self._config = _load_config()

        if not self._config.enable:
            logger.info("codex_chat_memory disabled")
            self._started = True
            return

        try:
            init_db()
        except Exception:
            logger.warning("codex_chat_memory db_init_failed", exc_info=True)

        self._idle_task = asyncio.create_task(self._idle_flush_loop())
        self._started = True

        logger.info(
            "codex_chat_memory started "
            f"observe_only={self._config.observe_only} "
            f"allowed_groups={sorted(self._config.allowed_groups or set())} "
            f"max_messages={self._config.max_messages} "
            f"max_chars={self._config.max_chars} "
            f"idle_seconds={self._config.idle_seconds}"
        )

    async def stop(self) -> None:
        if not self._started:
            return

        if self._idle_task:
            self._idle_task.cancel()
            try:
                await self._idle_task
            except asyncio.CancelledError:
                pass
            self._idle_task = None

        await self.flush_all(reason="shutdown")
        self._started = False
        logger.info("codex_chat_memory stopped")

    async def handle(self, bot: Bot, event: MessageEvent) -> None:
        if not self._started:
            await self.start()

        if not self._config.enable:
            return

        if not isinstance(event, GroupMessageEvent):
            return

        group_id = str(event.group_id)
        user_id = str(event.user_id)

        if str(getattr(bot, "self_id", "")) == user_id:
            return

        allowed_groups = self._config.allowed_groups or set()
        if allowed_groups and group_id not in allowed_groups:
            return

        raw_text = event.get_plaintext()
        cleaned_text = clean_text(raw_text)

        if not cleaned_text:
            return

        lower_text = cleaned_text.lower()
        if (
            lower_text.startswith("/codex_memory")
            or lower_text.startswith("codex_memory")
            or cleaned_text.startswith("/codex记忆")
            or cleaned_text.startswith("codex记忆")
        ):
            return

        timestamp = int(getattr(event, "time", 0) or time.time())
        message_id = str(getattr(event, "message_id", "") or "")

        sender = getattr(event, "sender", None)
        sender_nickname = str(getattr(sender, "nickname", "") or "")
        sender_card = str(getattr(sender, "card", "") or "")
        sender_role = str(getattr(sender, "role", "") or "")
        sender_title = str(getattr(sender, "title", "") or "")

        filtered = 0
        filter_reason = ""
        text_to_store = cleaned_text

        if is_sensitive(cleaned_text):
            filtered = 1
            filter_reason = "sensitive"
            text_to_store = "[filtered_sensitive_content]"
            logger.info(
                "codex_chat_memory message_filtered "
                f"group_id={group_id} user_id={user_id} reason=sensitive"
            )

        record = MessageRecord(
            group_id=group_id,
            user_id=user_id,
            message_id=message_id,
            timestamp=timestamp,
            sender_nickname=sender_nickname,
            sender_card=sender_card,
            sender_role=sender_role,
            sender_title=sender_title,
            text=text_to_store,
            text_len=len(text_to_store),
            message_type="text",
            filtered=filtered,
            filter_reason=filter_reason,
        )

        async with self._lock:
            buffer = self._buffers.get(group_id)

            if (
                buffer is not None
                and buffer.records
                and self._config.idle_seconds > 0
                and timestamp - buffer.last_message_time >= self._config.idle_seconds
            ):
                self._flush_group_locked(group_id, reason="idle_boundary")

            buffer = self._buffers.setdefault(group_id, GroupBuffer(group_id=group_id))
            buffer.add(record)

            logger.info(
                "codex_chat_memory buffer_append "
                f"group_id={group_id} user_id={user_id} message_id={message_id} "
                f"text_len={record.text_len} buffer_count={buffer.message_count}"
            )

            if buffer.should_flush(
                max_messages=self._config.max_messages,
                max_chars=self._config.max_chars,
                idle_seconds=0,
                now=timestamp,
            ):
                self._flush_group_locked(group_id, reason="threshold")

    async def flush_all(self, reason: str = "manual") -> None:
        async with self._lock:
            for group_id in list(self._buffers.keys()):
                self._flush_group_locked(group_id, reason=reason)

    def _flush_group_locked(self, group_id: str, reason: str) -> None:
        buffer = self._buffers.get(group_id)
        if buffer is None or not buffer.records:
            return

        records = list(buffer.records)

        try:
            memcell_id = insert_memcell(
                records,
                preview_max_chars=self._config.raw_preview_max_chars,
            )
        except Exception:
            logger.warning(
                f"codex_chat_memory flush_failed group_id={group_id} reason={reason}",
                exc_info=True,
            )
            return

        participants_count = len({record.user_id for record in records})
        preview_len = sum(record.text_len for record in records)

        logger.info(
            "codex_chat_memory memcell_created "
            f"group_id={group_id} memcell_id={memcell_id} "
            f"message_count={len(records)} participants={participants_count} "
            f"preview_len={preview_len} reason={reason}"
        )

        self._buffers.pop(group_id, None)

    async def _idle_flush_loop(self) -> None:
        while True:
            await asyncio.sleep(30)
            if not self._config.enable:
                continue

            now = int(time.time())

            async with self._lock:
                for group_id, buffer in list(self._buffers.items()):
                    if buffer.should_flush(
                        max_messages=0,
                        max_chars=0,
                        idle_seconds=self._config.idle_seconds,
                        now=now,
                    ):
                        self._flush_group_locked(group_id, reason="idle_loop")


_collector = MemoryCollector()
_memory_matcher = on_message(priority=0, block=False)
_lifecycle_registered = False


@_memory_matcher.handle()
async def _handle_memory_collect(bot: Bot, event: MessageEvent) -> None:
    try:
        await _collector.handle(bot, event)
    except Exception:
        logger.warning("codex_chat_memory handle_failed", exc_info=True)


def register_memory_collector() -> None:
    global _lifecycle_registered

    if _lifecycle_registered:
        return

    driver = get_driver()
    driver.on_startup(_collector.start)
    driver.on_shutdown(_collector.stop)

    _lifecycle_registered = True
    logger.info("codex_chat_memory registered")
