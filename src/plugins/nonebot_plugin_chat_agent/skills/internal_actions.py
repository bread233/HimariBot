from __future__ import annotations

from dataclasses import dataclass
import importlib

from nonebot import logger


@dataclass
class InternalActionResult:
    text: str | None = None
    image_url: str | None = None
    action_name: str = ""


async def _run_internal_60s_news() -> InternalActionResult:
    try:
        mod = importlib.import_module("src.plugins.60s")
        try:
            image_url = await mod.get_calendar()
        except ValueError:
            image_url = await mod.get_calendar_url(mod.wechat_oa_cookie, mod.wechat_oa_token)
        return InternalActionResult(image_url=str(image_url or "").strip() or None, action_name="internal_60s_news")
    except Exception as e:
        logger.warning(f"internal_skill_action name=internal_60s_news success=0 error={type(e).__name__}")
        return InternalActionResult(text="今日 60s 新闻暂时获取失败。", action_name="internal_60s_news")


async def run_internal_skill_action(action_name: str) -> InternalActionResult | None:
    action = str(action_name or "").strip().lower()
    if action == "internal_60s_news":
        return await _run_internal_60s_news()
    return None
