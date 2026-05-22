from pathlib import Path
from nonebot import get_driver, logger, on_message
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, MessageEvent
from nonebot.params import EventMessage
from nonebot.typing import T_State
import asyncio

from .config import Config
from .trigger_rules import should_trigger
from .codex_provider import ask_codex
from .cooldown import UserCooldown

__plugin_meta__ = {
    "name": "codex_chat",
    "description": "群聊 @/reply 触发的 Codex 文本问答",
    "usage": "@bot 或 reply bot 触发",
}

driver = get_driver()
plugin_config = Config()
_cooldown = UserCooldown(plugin_config.codex_chat_cd_seconds)

codex_chat = on_message(priority=plugin_config.codex_chat_command_priority, block=False)

def _extract_prompt(event: GroupMessageEvent) -> str:
    text = event.get_plaintext().strip()
    at_ids = {seg.data.get("qq") for seg in event.message if getattr(seg, "type", "") == "at" and seg.data.get("qq")}
    for at_id in at_ids:
        text = text.replace(f"@{at_id}", "").strip()
    return text.strip()

@codex_chat.handle()
async def _(bot: Bot, event: MessageEvent, state: T_State, msg=EventMessage()):
    del state, msg
    if not plugin_config.codex_chat_enable or not isinstance(event, GroupMessageEvent):
        return

    user_id = int(event.user_id)
    group_id = int(event.group_id)
    prompt = _extract_prompt(event)[: plugin_config.codex_chat_max_prompt_chars]

    # CD
    remain = _cooldown.remaining(user_id)
    if remain > 0:
        await codex_chat.finish("先等一下，过会儿再叫我。")

    if not prompt:
        _cooldown.hit(user_id)
        await codex_chat.finish("我在，想问什么？")

    # 白名单 + 兴趣评分判定
    trigger, score = should_trigger(group_id, prompt, plugin_config)
    if not trigger:
        logger.info(f"codex_chat skip_trigger group_id={group_id} score={score}")
        return

    # 执行 Codex
    final_prompt = f"你是上原绯玛丽。用户消息：{prompt}\n请直接给出适合发到 QQ 群里的简短回答。"
    result = await ask_codex(plugin_config, final_prompt)
    _cooldown.hit(user_id)

    if result.ok and result.text:
        await codex_chat.finish(result.text)
    await codex_chat.finish("我这边暂时没想出来，稍后再试。")