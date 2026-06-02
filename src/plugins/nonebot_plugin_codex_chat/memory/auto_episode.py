from __future__ import annotations

import asyncio
from typing import Optional

from nonebot import get_driver, logger

from ..config import ConfigModel
from .query import get_pending_memcells_for_episode
from .episodes import generate_episode_for_memcell


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

async def _episode_worker_loop(config: ConfigModel) -> None:
    interval = _clamp_int(
        config.codex_chat_memory_episode_auto_interval_seconds,
        default=300,
        min_value=30,
        max_value=86400,
    )
    limit_per_tick = _clamp_int(
        config.codex_chat_memory_episode_auto_limit_per_tick,
        default=1,
        min_value=1,
        max_value=3,
    )
    recent_limit = _clamp_int(
        config.codex_chat_memory_episode_auto_recent_limit,
        default=20,
        min_value=1,
        max_value=50,
    )
    min_age = _clamp_int(
        config.codex_chat_memory_episode_auto_min_age_seconds,
        default=180,
        min_value=0,
        max_value=86400,
    )

    allowed_groups = [str(x) for x in config.allowed_groups_list]

    logger.info(
        "codex_chat_memory episode_worker started "
        f"interval={interval} limit_per_tick={limit_per_tick}"
    )

    while True:
        try:
            candidates = get_pending_memcells_for_episode(
                allowed_group_ids=allowed_groups,
                limit=recent_limit,
                min_age_seconds=min_age,
            )

            processed = 0
            for candidate in candidates:
                if processed >= limit_per_tick:
                    break

                memcell_id = int(candidate.get("id", 0) or 0)
                if memcell_id <= 0:
                    continue

                try:
                    result = await generate_episode_for_memcell(
                        config,
                        memcell_id,
                        force=False,
                    )

                    if result.get("ok"):
                        logger.info(
                            "episode_worker generated "
                            f"memcell_id={memcell_id} "
                            f"user_episode_saved={result.get('user_episode_saved', 0)}"
                        )
                    elif result.get("skipped"):
                        logger.debug(
                            "episode_worker skipped memcell_id=%s reason=%s",
                            memcell_id,
                            result.get("reason"),
                        )
                    else:
                        logger.warning(
                            "episode_worker failed memcell_id=%s error=%s",
                            memcell_id,
                            result.get("error"),
                        )

                except Exception:
                    logger.warning(
                        "episode_worker exception memcell_id=%s",
                        memcell_id,
                        exc_info=True,
                    )

                processed += 1

        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning("episode_worker loop_error", exc_info=True)

        await asyncio.sleep(interval)


def register_memory_episode_worker() -> None:
    global _registered

    if _registered:
        return

    _registered = True

    async def _on_startup() -> None:
        config = _load_config()

        if not config.codex_chat_memory_episode_auto_enabled:
            logger.info("codex_chat_memory episode_worker disabled")
            return

        allowed_groups = [str(x) for x in config.allowed_groups_list]
        if not allowed_groups:
            logger.warning("codex_chat_memory episode_worker disabled no_allowed_groups")
            return

        global _task
        _task = asyncio.create_task(_episode_worker_loop(config))

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

    logger.info("codex_chat_memory episode_worker registered")
