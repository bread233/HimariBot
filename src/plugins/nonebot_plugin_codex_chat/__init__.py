from nonebot import get_driver, logger, on_message
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, MessageEvent
from nonebot.params import EventMessage

from .codex_provider import ask_codex
from .config import get_config

__plugin_meta__ = {
    "name": "codex_chat",
    "description": "最小化 Codex CLI 接入插件",
    "usage": "群聊中按触发条件调用 Codex CLI",
}

plugin_config = get_config()
_codex_chat = on_message(priority=plugin_config.codex_chat_command_priority, block=False)
driver = get_driver()
_superusers = {str(x) for x in (getattr(driver.config, "superusers", set()) or set())}
logger.info("codex_chat minimal bootstrap loaded")


@_codex_chat.handle()
async def _handle(event: MessageEvent, bot: Bot, message=EventMessage()):
    del bot
    if not plugin_config.codex_chat_enable:
        return
    if isinstance(event, GroupMessageEvent):
        group_id = getattr(event, "group_id", None)
        if plugin_config.allowed_groups_list and int(group_id or 0) not in plugin_config.allowed_groups_list:
            return
    prompt = str(message).strip()
    if not prompt:
        return
    codex_result = await ask_codex(plugin_config, prompt)
    if not codex_result.ok:
        logger.warning("codex_chat failed reason=%s", codex_result.reason)
        return
    await _codex_chat.finish(codex_result.text)
