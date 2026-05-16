from __future__ import annotations

from dataclasses import dataclass
import importlib

from nonebot import logger


@dataclass
class InternalActionResult:
    text: str | None = None
    image_url: str | None = None
    action_name: str = ""


def _normalize_action_name(action_name: str) -> str:
    return str(action_name or "").strip().lower()


def get_registered_internal_actions() -> set[str]:
    return {"60s.today_image", "internal_60s_news"}


def is_registered_internal_action(action_name: str) -> bool:
    return _normalize_action_name(action_name) in get_registered_internal_actions()


async def _run_60s_today_image(action_name: str) -> InternalActionResult:
    try:
        mod = importlib.import_module("src.plugins.60s")
        try:
            image_url = await mod.get_calendar()
        except ValueError:
            image_url = await mod.get_calendar_url(mod.wechat_oa_cookie, mod.wechat_oa_token)
        return InternalActionResult(image_url=str(image_url or "").strip() or None, action_name=action_name)
    except Exception as e:
        logger.warning(f"internal_skill_action name={action_name} success=0 error={type(e).__name__}")
        return InternalActionResult(text="今日 60s 新闻暂时获取失败。", action_name=action_name)


async def run_internal_skill_action(action_name: str) -> InternalActionResult | None:
    action = _normalize_action_name(action_name)
    if action == "60s.today_image":
        return await _run_60s_today_image("60s.today_image")
    if action == "internal_60s_news":
        return await _run_60s_today_image("internal_60s_news")
    return None
