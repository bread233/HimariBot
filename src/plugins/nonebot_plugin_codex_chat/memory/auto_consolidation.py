from __future__ import annotations

import asyncio
import time
from typing import Optional

from nonebot import get_driver, logger

from ..config import ConfigModel
from .consolidation import generate_and_save_long_memory_candidates
from .query import get_recent_long_memory_candidates


_registered = False
_task: Optional[asyncio.Task] = None


def _load_config() -> ConfigModel:
    return ConfigModel.parse_obj(get_driver().config.dict())


def _clamp_int(value: object, default: int, min_value: int, max_value: int) -> int:
    try:
        parsed = int(value)
    except Exception:
        parsed = default
    return max(min_value, min(parsed, max_value))


async def _long_consolidation_worker_loop(config: ConfigModel) -> None:
    interval = _clamp_int(
        getattr(config, "codex_chat_memory_long_consolidation_auto_interval_seconds", 3600),
        default=3600,
        min_value=300,
        max_value=86400,
    )
    limit_per_tick = _clamp_int(
        getattr(config, "codex_chat_memory_long_consolidation_auto_limit_per_tick", 1),
        default=1,
        min_value=1,
        max_value=3,
    )
    episode_limit = _clamp_int(
        getattr(config, "codex_chat_memory_long_consolidation_auto_episode_limit", 10),
        default=10,
        min_value=1,
        max_value=50,
    )
    min_interval = _clamp_int(
        getattr(config, "codex_chat_memory_long_consolidation_auto_min_interval_seconds", 21600),
        default=21600,
        min_value=0,
        max_value=604800,
    )

    allowed_groups = [str(x) for x in getattr(config, "allowed_groups_list", []) or []]
    if not allowed_groups:
        logger.warning("codex_chat_memory long_consolidation_worker disabled no_allowed_groups")
        return

    provider = str(
        getattr(config, "codex_chat_memory_long_consolidation_provider", "codex") or "codex"
    )

    logger.info(
        "codex_chat_memory long_consolidation_worker started interval={} limit_per_tick={} episode_limit={} min_interval={} provider={}",
        interval,
        limit_per_tick,
        episode_limit,
        min_interval,
        provider,
    )

    while True:
        await asyncio.sleep(interval)

        now = int(time.time())
        processed = 0

        for group_id in allowed_groups:
            if processed >= limit_per_tick:
                break

            try:
                recent = get_recent_long_memory_candidates(
                    group_id=group_id,
                    status="approved",
                    limit=1,
                )

                if recent:
                    latest_updated_at = int(recent[0].get("updated_at") or 0)
                    age = now - latest_updated_at
                    if min_interval > 0 and age < min_interval:
                        logger.debug(
                            "codex_chat_memory long_consolidation_worker skipped reason=min_interval group_id={} age={}",
                            group_id,
                            age,
                        )
                        continue

                result = await generate_and_save_long_memory_candidates(
                    plugin_config=config,
                    group_id=group_id,
                    user_id=None,
                    limit=episode_limit,
                )

                if result.get("ok"):
                    if result.get("skipped"):
                        logger.info(
                            "codex_chat_memory long_consolidation_worker skipped group_id={} reason={}",
                            group_id,
                            result.get("reason", ""),
                        )
                    else:
                        logger.info(
                            "codex_chat_memory long_consolidation_worker saved group_id={} saved={} skipped_save={} candidates={} provider={} model={}",
                            group_id,
                            result.get("saved", 0),
                            result.get("skipped_save", 0),
                            len(result.get("candidates", []) or []),
                            result.get("provider", ""),
                            result.get("model", ""),
                        )
                else:
                    logger.warning(
                        "codex_chat_memory long_consolidation_worker failed group_id={} reason={} error={} provider={} model={}",
                        group_id,
                        result.get("reason", ""),
                        result.get("error", ""),
                        result.get("provider", ""),
                        result.get("model", ""),
                    )

                processed += 1

            except asyncio.CancelledError:
                raise
            except Exception:
                logger.warning(
                    "codex_chat_memory long_consolidation_worker group_error group_id={}",
                    group_id,
                    exc_info=True,
                )


def register_memory_long_consolidation_worker() -> None:
    global _registered
    if _registered:
        return
    _registered = True

    async def _on_startup() -> None:
        config = _load_config()
        if not getattr(config, "codex_chat_memory_long_consolidation_auto_enabled", False):
            logger.info("codex_chat_memory long_consolidation_worker disabled")
            return

        global _task
        _task = asyncio.create_task(_long_consolidation_worker_loop(config))

    async def _on_shutdown() -> None:
        global _task
        if _task:
            _task.cancel()
            try:
                await _task
            except asyncio.CancelledError:
                pass
            _task = None

    driver = get_driver()
    driver.on_startup(_on_startup)
    driver.on_shutdown(_on_shutdown)

    logger.info("codex_chat_memory long_consolidation_worker registered")
