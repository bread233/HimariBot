from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from functools import partial
import inspect
from typing import Any, cast, Union

from apscheduler.triggers.base import BaseTrigger
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from nonebot.adapters import Bot, Event, Message, MessageSegment, MessageTemplate
from nonebot.exception import FinishedException
from nonebot.matcher import Matcher
from nonebot.params import Depends
from nonebot.rule import Rule as Rule
from nonebot.typing import T_State, _DependentCallable
from nonebot.utils import is_coroutine_callable, run_sync
from ..nonebot_plugin_alconna import UniMessage
from tzlocal import get_localzone

from .entity import BYPASS_ENTITY, CooldownEntity

_tz = get_localzone()
SupportMsgType = Union[str, Message, MessageSegment, MessageTemplate, UniMessage]


def _entity_id_dep_wrapper(entity: Union[CooldownEntity, _DependentCallable[str]]) -> _DependentCallable[str]:
    if isinstance(entity, CooldownEntity):
        entity_id_dep = entity.get_entity_id
    else:
        entity_id_dep = entity
    return entity_id_dep


def _limit_dep_wrapper(limit: Union[int, _DependentCallable[int]]) -> _DependentCallable[int]:
    if isinstance(limit, int):
        limit_dep = lambda: limit  # noqa: E731
    else:
        limit_dep = limit
    return limit_dep


def _reject_dep_wrapper(reject: Union[None, SupportMsgType, _DependentCallable[Any]]) -> _DependentCallable[Any]:
    if isinstance(reject, (str, Message, MessageSegment, MessageTemplate, UniMessage)):
        async def _send_msg(bot: Bot, matcher: Matcher, event: Event):
            if isinstance(reject, UniMessage):
                await reject.finish(event, bot)
            else:
                await matcher.finish(reject)
        reject_func = _send_msg
    elif reject is not None:    # callable
        if not is_coroutine_callable(reject):
            reject = run_sync(reject)
        reject_func = reject
    else:
        async def _null():
            return None
        reject_func = _null

    async def _inject_wrapper(*args, **kwargs):
        sig = inspect.signature(reject_func)
        bound = sig.bind(*args, **kwargs)
        return partial(reject_func, **bound.arguments)

    setattr(_inject_wrapper, "__signature__", inspect.signature(reject_func))
    return _inject_wrapper


def inject_increaser(state: T_State, func: Callable):
    executors = state.setdefault("plugin_limiter:increaser", [])
    assert isinstance(executors, list)
    executors.append(func)


# region: FixWindow
@dataclass
class FixWindowUsage:
    start_time: datetime
    available: int


_FixWindowCooldownDict: dict[str, dict[str, FixWindowUsage]] = {}


def Cooldown(
    entity: Union[CooldownEntity, _DependentCallable[str]],
    period: Union[int, timedelta, str],
    *,
    limit: Union[int, _DependentCallable[int]] = 5,
    reject: Union[None, SupportMsgType, _DependentCallable[Any]] = None,
    set_increaser: bool = False,
    name: Union[None, str] = None,
):
    if isinstance(period, str):
        trigger = CronTrigger.from_crontab(period)
    else:
        if isinstance(period, timedelta):
            interval_length = int(period.total_seconds())
        else:
            interval_length = period
        trigger = IntervalTrigger(seconds=interval_length)
    trigger = cast(BaseTrigger, trigger)

    if isinstance(name, str):
        if name not in _FixWindowCooldownDict:
            _FixWindowCooldownDict[name] = {}
        bucket = _FixWindowCooldownDict[name]
    else:
        bucket: dict[str, FixWindowUsage] = {}

    async def _limiter_dependency(
        state: T_State,
        entity_id: str = Depends(_entity_id_dep_wrapper(entity)),
        limit: int = Depends(_limit_dep_wrapper(limit)),
        reject_cb: Callable[..., Awaitable[Any]] = Depends(_reject_dep_wrapper(reject))
    ) -> None:
        if entity_id == BYPASS_ENTITY:
            return

        now = datetime.now(tz=_tz)

        if entity_id not in bucket:
            bucket[entity_id] = FixWindowUsage(now, limit)
        usage = bucket[entity_id]

        def _increase_action(reset: bool = True):
            if reset:
                usage.start_time = now
                usage.available = limit
            usage.available -= 1

        if usage.available > 0:
            if set_increaser:
                inject_increaser(state, partial(_increase_action, False))
            else:
                _increase_action(False)
            return

        reset_time = trigger.get_next_fire_time(usage.start_time, now)
        assert reset_time is not None, "reset_time should not be None"

        if now >= reset_time:
            if set_increaser:
                inject_increaser(state, _increase_action)
            else:
                _increase_action()
            return

        await reject_cb()
        raise FinishedException()

    return Depends(_limiter_dependency)


# region: SlidingWindow
@dataclass
class SlidingWindowUsage:
    timestamps: deque[datetime] = field(default_factory=deque)


_SlidingWindowCooldownDict: dict[str, dict[str, SlidingWindowUsage]] = {}


def SlidingWindowCooldown(
    entity: Union[CooldownEntity, _DependentCallable[str]],
    period: Union[int, timedelta],
    *,
    limit: Union[int, _DependentCallable[int]] = 5,
    reject: Union[None, SupportMsgType, _DependentCallable[Any]] = None,
    set_increaser: bool = False,
    name: Union[None, str] = None,
):
    if isinstance(period, timedelta):
        window_length = int(period.total_seconds())
    else:
        window_length = int(period)

    if isinstance(name, str):
        bucket = _SlidingWindowCooldownDict.setdefault(name, {})
    else:
        bucket: dict[str, SlidingWindowUsage] = {}

    async def _limiter_dependency(
        state: T_State,
        entity_id: str = Depends(_entity_id_dep_wrapper(entity)),
        limit: int = Depends(_limit_dep_wrapper(limit)),
        reject_cb: Callable[..., Awaitable[Any]] = Depends(_reject_dep_wrapper(reject))
    ) -> None:
        if entity_id == BYPASS_ENTITY:
            return

        now = datetime.now(tz=_tz)

        if entity_id not in bucket:
            bucket[entity_id] = SlidingWindowUsage()
        usage = bucket[entity_id]

        while usage.timestamps and (now - usage.timestamps[0]).total_seconds() >= window_length:
            usage.timestamps.popleft()

        def _increase_action():
            usage.timestamps.append(now)

        if len(usage.timestamps) < limit:
            if set_increaser:
                inject_increaser(state, _increase_action)
            else:
                _increase_action()
            return

        await reject_cb()
        raise FinishedException()

    return Depends(_limiter_dependency)


# region: LeakyBucket
@dataclass
class LeakyBucketUsage:
    last_update_time: datetime
    capacity: int
    used: int


_LeakyBucketCooldownDict: dict[str, dict[str, LeakyBucketUsage]] = {}


def LeakyBucketCooldown(
    entity: Union[CooldownEntity, _DependentCallable[str]],
    capacity: int,
    leak_speed: int,
    *,
    pour_size: Union[int, _DependentCallable[int]] = 10,
    reject: Union[None, SupportMsgType, _DependentCallable[Any]] = None,
    set_increaser: bool = False,
    name: Union[None, str] = None,
):
    if isinstance(name, str):
        if name not in _LeakyBucketCooldownDict:
            _LeakyBucketCooldownDict[name] = {}
        bucket = _LeakyBucketCooldownDict[name]
    else:
        bucket: dict[str, LeakyBucketUsage] = {}

    async def _limiter_dependency(
        state: T_State,
        entity_id: str = Depends(_entity_id_dep_wrapper(entity)),
        pour_size: int = Depends(_limit_dep_wrapper(pour_size)),
        reject_cb: Callable[..., Awaitable[Any]] = Depends(_reject_dep_wrapper(reject))
    ) -> None:
        if entity_id == BYPASS_ENTITY:
            return

        now = datetime.now(tz=_tz)

        if entity_id not in bucket:
            bucket[entity_id] = LeakyBucketUsage(now, capacity, capacity)
        usage = bucket[entity_id]

        leaked_size = int((now - usage.last_update_time).total_seconds()) * leak_speed
        usage.used = max(usage.used - leaked_size, 0)
        usage.last_update_time = now

        def _increase_action():
            usage.used += pour_size

        if usage.used + pour_size <= usage.capacity:
            if set_increaser:
                inject_increaser(state, _increase_action)
            else:
                _increase_action()
            return

        await reject_cb()
        raise FinishedException()

    return Depends(_limiter_dependency)


# region: TokenBucket
@dataclass
class TokenBucketUsage:
    last_update_time: datetime
    capacity: int
    available: int


_TokenBucketCooldownDict: dict[str, dict[str, TokenBucketUsage]] = {}


def TokenBucketCooldown(
    entity: Union[CooldownEntity, _DependentCallable[str]],
    capacity: int,
    add_speed: int,
    *,
    consume_size: Union[int, _DependentCallable[int]] = 10,
    reject: Union[None, SupportMsgType, _DependentCallable[Any]] = None,
    set_increaser: bool = False,
    name: Union[None, str] = None,
):
    if isinstance(name, str):
        if name not in _TokenBucketCooldownDict:
            _TokenBucketCooldownDict[name] = {}
        bucket = _TokenBucketCooldownDict[name]
    else:
        bucket: dict[str, TokenBucketUsage] = {}

    async def _limiter_dependency(
        state: T_State,
        entity_id: str = Depends(_entity_id_dep_wrapper(entity)),
        consume_size: int = Depends(_limit_dep_wrapper(consume_size)),
        reject_cb: Callable[..., Awaitable[Any]] = Depends(_reject_dep_wrapper(reject))
    ) -> None:
        if entity_id == BYPASS_ENTITY:
            return

        now = datetime.now(tz=_tz)

        if entity_id not in bucket:
            bucket[entity_id] = TokenBucketUsage(now, capacity, 0)
        usage = bucket[entity_id]

        resume_size = int((now - usage.last_update_time).total_seconds()) * add_speed
        usage.available = min(resume_size + usage.available, usage.capacity)
        usage.last_update_time = now

        def _increase_action():
            usage.available -= consume_size

        if usage.available >= consume_size:
            if set_increaser:
                inject_increaser(state, _increase_action)
            else:
                _increase_action()
            return

        await reject_cb()
        raise FinishedException()

    return Depends(_limiter_dependency)
