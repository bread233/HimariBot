from dataclasses import dataclass
import importlib

from nonebot import logger

from .image_refs import normalize_image_ref_to_base64


@dataclass
class InternalActionResult:
    text: str | None = None
    image_url: str | None = None
    action_name: str = ""


def _normalize_action_name(action_name: str) -> str:
    return str(action_name or "").strip().lower()


def get_registered_internal_actions() -> set[str]:
    return {
        "60s.today_image",
        "internal_60s_news",
        "what2eat.get2eat",
        "what2eat.get2drink",
    }


def is_registered_internal_action(action_name: str) -> bool:
    return _normalize_action_name(action_name) in get_registered_internal_actions()


def _is_image_ref(value: str) -> bool:
    text = str(value or "").strip().lower()
    return text.startswith("http://") or text.startswith("https://") or text.startswith("base64://")


def _as_non_url_text(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return "\u4eca\u65e5 60s \u65b0\u95fb\u6682\u65f6\u83b7\u53d6\u5931\u8d25\u3002"
    if "没更新" in text or "最后更新日期" in text:
        return text
    return "\u4eca\u65e5 60s \u65b0\u95fb\u6682\u65f6\u83b7\u53d6\u5931\u8d25\u3002"


def _normalize_action_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, tuple) and value:
        return _normalize_action_text(value[-1])
    return str(value).strip()


async def _run_60s_today_image(action_name: str) -> InternalActionResult:
    try:
        mod = importlib.import_module("src.plugins.60s")
        try:
            image_or_text = await mod.get_calendar()
        except ValueError:
            image_or_text = await mod.get_calendar_url(mod.wechat_oa_cookie, mod.wechat_oa_token)
        payload = str(image_or_text or "").strip()
        normalized = await normalize_image_ref_to_base64(payload)
        if normalized:
            source = "base64" if payload.lower().startswith("base64://") else "url_to_base64"
            logger.info(f"internal_skill_action name={action_name} success=1 type=image source={source}")
            return InternalActionResult(image_url=normalized, action_name=action_name)
        if _is_image_ref(payload):
            logger.warning(
                f"internal_skill_action name={action_name} success=0 error=invalid_image_ref value_type={type(image_or_text).__name__}"
            )
            return InternalActionResult(text=_as_non_url_text(payload), action_name=action_name)
        logger.warning(
            f"internal_skill_action name={action_name} success=0 error=invalid_image_ref value_type={type(image_or_text).__name__}"
        )
        return InternalActionResult(text=_as_non_url_text(payload), action_name=action_name)
    except Exception as e:
        logger.warning(f"internal_skill_action name={action_name} success=0 error={type(e).__name__}")
        return InternalActionResult(
            text="\u4eca\u65e5 60s \u65b0\u95fb\u6682\u65f6\u83b7\u53d6\u5931\u8d25\u3002",
            action_name=action_name,
        )


def _what2eat_fallback(action_name: str) -> str:
    if str(action_name or "").endswith("get2drink"):
        return "\u73b0\u5728\u6682\u65f6\u6ca1\u6cd5\u51b3\u5b9a\u559d\u4ec0\u4e48\uff0c\u63d2\u4ef6\u8c03\u7528\u5931\u8d25\u4e86\u3002"
    return "\u73b0\u5728\u6682\u65f6\u6ca1\u6cd5\u51b3\u5b9a\u5403\u4ec0\u4e48\uff0c\u63d2\u4ef6\u8c03\u7528\u5931\u8d25\u4e86\u3002"


def _load_what2eat_manager():
    candidates = [
        "src.plugins.what2eat.data_source",
        "src.plugins.nonebot_plugin_what2eat.data_source",
        "src.plugins.nonebot_plugin_what2eat2.data_source",
    ]
    errors: list[str] = []
    for mod_path in candidates:
        try:
            mod = importlib.import_module(mod_path)
            manager = getattr(mod, "eating_manager", None)
            if manager is not None:
                return manager, mod_path
            errors.append(f"{mod_path}:no_manager")
        except Exception as e:
            errors.append(f"{mod_path}:{type(e).__name__}")
    logger.warning("internal_skill_action name=what2eat import_error=" + ";".join(errors[:3]))
    return None, ""


async def _run_what2eat(action_name: str, event) -> InternalActionResult:
    try:
        manager, used_mod = _load_what2eat_manager()
        if manager is None:
            logger.warning(f"internal_skill_action name={action_name} success=0 error=no_manager")
            return InternalActionResult(text=_what2eat_fallback(action_name), action_name=action_name)
        if action_name.endswith("get2drink"):
            value = manager.get2drink(event)
        else:
            value = manager.get2eat(event)
        text = _normalize_action_text(value)
        if text:
            logger.info(f"internal_skill_action name={action_name} import={used_mod}")
            logger.info(f"internal_skill_action name={action_name} success=1 type=text")
            return InternalActionResult(text=text, action_name=action_name)
        logger.warning(f"internal_skill_action name={action_name} success=0 error=empty_text")
        return InternalActionResult(text=_what2eat_fallback(action_name), action_name=action_name)
    except Exception as e:
        logger.warning(f"internal_skill_action name={action_name} success=0 error={type(e).__name__}")
        return InternalActionResult(text=_what2eat_fallback(action_name), action_name=action_name)


async def run_internal_skill_action(action_name: str, event=None) -> InternalActionResult | None:
    action = _normalize_action_name(action_name)
    if action == "60s.today_image":
        return await _run_60s_today_image("60s.today_image")
    if action == "internal_60s_news":
        return await _run_60s_today_image("internal_60s_news")
    if action == "what2eat.get2eat":
        return await _run_what2eat("what2eat.get2eat", event)
    if action == "what2eat.get2drink":
        return await _run_what2eat("what2eat.get2drink", event)
    return None
