from __future__ import annotations

from nonebot import on_message
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, MessageEvent, PrivateMessageEvent
from nonebot.rule import Rule
from nonebot.typing import T_State

from .config import get_chat_agent_config
from .llm_client import chat_completions
from .prompt import build_system_prompt
from .utils import extract_group_prompt, extract_private_prompt, get_bot_nicknames, get_original_plain_text, strip_thinking, truncate_reply


async def chat_agent_rule(bot: Bot, event: MessageEvent, state: T_State) -> bool:
    config = get_chat_agent_config()
    if not config.chat_agent_enable:
        return False

    if isinstance(event, GroupMessageEvent):
        prompt = extract_group_prompt(event, bot.self_id)
        if prompt is None:
            return False
        state["chat_agent_prompt"] = prompt
        state["chat_agent_is_group"] = True
        return True

    if isinstance(event, PrivateMessageEvent):
        prompt = extract_private_prompt(get_original_plain_text(event), get_bot_nicknames())
        if prompt is None:
            return False
        state["chat_agent_prompt"] = prompt
        state["chat_agent_is_group"] = False
        return True

    return False


chat_agent = on_message(rule=Rule(chat_agent_rule), priority=4, block=True)


@chat_agent.handle()
async def _(bot: Bot, event: MessageEvent, state: T_State):
    config = get_chat_agent_config()
    prompt = state.get("chat_agent_prompt", "")
    is_group = bool(state.get("chat_agent_is_group", isinstance(event, GroupMessageEvent)))

    prompt = prompt.strip()
    if not prompt:
        reply = "叫我有什么事？" if is_group else "你想聊什么？"
        await chat_agent.finish(reply)
        return

    messages = [
        {"role": "system", "content": build_system_prompt()},
        {"role": "user", "content": prompt},
    ]

    try:
        reply = await chat_completions(messages, config)
        reply = truncate_reply(strip_thinking(reply), config.chat_agent_max_reply_length)
    except Exception:
        await chat_agent.finish("模型接口暂时没有响应。")
        return

    await chat_agent.finish(reply or "模型接口暂时没有响应。")


get_chat_agent_config().ensure_data_dir()
