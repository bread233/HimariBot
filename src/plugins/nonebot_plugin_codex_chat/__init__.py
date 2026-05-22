from pathlib import Path
from nonebot import logger, on_message
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, MessageEvent
from nonebot.params import EventMessage
from nonebot.typing import T_State
import asyncio

from .config import get_config
from .trigger_rules import should_trigger
from .codex_provider import ask_codex
from .cooldown import UserCooldown

__plugin_meta__ = {
    "name": "codex_chat",
    "description": "群聊 @/reply 触发的 Codex 文本问答",
    "usage": "@bot 或 reply bot 触发",
}

plugin_config = get_config()
_codex_lock = asyncio.Lock()
_proactive_interval = UserCooldown(plugin_config.codex_chat_proactive_min_interval_seconds)

codex_chat = on_message(priority=plugin_config.codex_chat_command_priority, block=False)
logger.info(
    "codex_chat config_loaded=1 "
    f"enable={1 if plugin_config.codex_chat_enable else 0} "
    f"proactive={1 if plugin_config.codex_chat_proactive_enabled else 0} "
    f"allowed_groups={plugin_config.allowed_groups_list} "
    f"threshold={plugin_config.codex_chat_interest_threshold}"
)

_DEFAULT_PERSONA = "你是上原绯玛丽。请用适合发到 QQ 群里的简短中文回答。"

def _load_persona(path: str) -> str:
    p = str(path or "").strip()
    if not p:
        return _DEFAULT_PERSONA
    try:
        text = Path(p).read_text(encoding="utf-8").strip()
    except Exception:
        return _DEFAULT_PERSONA
    return text if text else _DEFAULT_PERSONA

def _build_prompt(persona: str, user_prompt: str) -> str:
    p = str(persona or "").strip()
    if not p:
        p = _DEFAULT_PERSONA
    u = str(user_prompt or "").strip()
    return f"{p}\n\n用户消息：{u}\n请直接给出适合发到 QQ 群里的简短回答。"

def _extract_prompt(event: GroupMessageEvent) -> str:
    text = event.get_plaintext().strip()
    at_ids = {seg.data.get("qq") for seg in event.message if getattr(seg, "type", "") == "at" and seg.data.get("qq")}
    for at_id in at_ids:
        text = text.replace(f"@{at_id}", "").strip()
    return text.strip()

def _is_reply_to_bot(event: GroupMessageEvent, bot: Bot) -> bool:
    reply = getattr(event, "reply", None)
    if not reply:
        return False
    sender = getattr(reply, "sender", None)
    user_id = None
    if sender is not None:
        user_id = getattr(sender, "user_id", None)
        if user_id is None and isinstance(sender, dict):
            user_id = sender.get("user_id")
    if user_id is None:
        data = getattr(reply, "data", None)
        if isinstance(data, dict):
            reply_sender = data.get("sender")
            if isinstance(reply_sender, dict):
                user_id = reply_sender.get("user_id")
    if user_id is None:
        return False
    try:
        return int(user_id) == int(getattr(bot, "self_id", 0) or 0)
    except Exception:
        return False

@codex_chat.handle()
async def _(bot: Bot, event: MessageEvent, state: T_State, msg=EventMessage()):
    del state, msg
    if not plugin_config.codex_chat_enable or not isinstance(event, GroupMessageEvent):
        return

    user_id = int(event.user_id)
    group_id = int(event.group_id)
    prompt = _extract_prompt(event)[: plugin_config.codex_chat_max_prompt_chars]
    prompt_len = len(prompt)
    mode = "proactive"
    score = 0
    is_to_me = False
    try:
        is_to_me = bool(event.is_tome())
    except Exception:
        is_to_me = False
    if is_to_me:
        mode = "at"
        trigger = True
    elif _is_reply_to_bot(event, bot):
        mode = "reply"
        trigger = True
    else:
        trigger, score = should_trigger(group_id, prompt, plugin_config)
        if not trigger:
            logger.info(f"codex_chat skip_trigger mode={mode} group_id={group_id} score={score} prompt_len={prompt_len}")
            return
        mode = "proactive"

    if mode in {"at", "reply"}:
        if _codex_lock.locked():
            logger.info(f"codex_chat busy_skip=1 mode={mode} group_id={group_id} user_id={user_id} prompt_len={prompt_len}")
            await codex_chat.finish("我还在思考上一条，稍后再 @ 我～")
    else:
        remain = _proactive_interval.remaining(group_id)
        if remain > 0:
            logger.info(
                f"codex_chat proactive_skip=1 reason=min_interval group_id={group_id} user_id={user_id} "
                f"remain={remain} score={score} prompt_len={prompt_len}"
            )
            return
        if _codex_lock.locked():
            logger.info(
                f"codex_chat proactive_skip=1 reason=busy group_id={group_id} user_id={user_id} score={score} prompt_len={prompt_len}"
            )
            return
        _proactive_interval.hit(group_id)

    if not prompt:
        logger.info(f"codex_chat empty_prompt mode={mode} group_id={group_id} prompt_len={prompt_len}")
        await codex_chat.finish("我在，想问什么？")

    logger.info(f"codex_chat trigger=1 mode={mode} group_id={group_id} score={score} prompt_len={prompt_len}")
    persona = _load_persona(plugin_config.codex_chat_persona_path)
    final_prompt = _build_prompt(persona, prompt)
    async with _codex_lock:
        result = await ask_codex(plugin_config, final_prompt)

    if result.ok and result.text:
        await codex_chat.finish(result.text)
    await codex_chat.finish("我这边暂时没想出来，稍后再试。")
