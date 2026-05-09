from __future__ import annotations

from nonebot import get_driver, on_message
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, MessageEvent, MessageSegment, PrivateMessageEvent
from nonebot.rule import Rule
from nonebot.typing import T_State

from .config import get_chat_agent_config
from .context_pack import build_context_pack
from .llm_client import chat_completions
from .memory import detect_feedback
from .profile_store import init_profile_storage, upsert_user_seen
from .prompt import build_system_prompt
from .retrieval_store import init_retrieval_storage
from .runtime_state import get_chat_agent_lock
from .storage import build_session_info, init_storage, save_memory, save_message
from .utils import extract_group_prompt, extract_private_prompt, get_bot_nicknames, get_original_plain_text, sanitize_task_reply, strip_thinking, truncate_reply


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

driver = get_driver()


def _with_group_at(event: MessageEvent, is_group: bool, text: str):
    if not is_group:
        return text
    return MessageSegment.at(event.user_id) + MessageSegment.text(" " + text)


def _should_sanitize_task_reply(prompt: str, context_pack: dict) -> bool:
    text = (prompt or "").strip()
    if any(token in text for token in ["你是谁", "自我介绍", "可爱语气", "安慰", "陪聊", "角色扮演"]):
        return False
    if context_pack.get("retrieval_context") or context_pack.get("web_context"):
        return True
    notes = str(context_pack.get("tool_notes", "") or "")
    return any(
        token in notes
        for token in [
            "embedding_retrieval=reliable",
            "web_score=",
            "reliable_context_not_found",
            "memory_reminder_ready",
        ]
    )


@driver.on_startup
async def _init_chat_agent_storage() -> None:
    config = get_chat_agent_config()
    config.ensure_data_dir()
    if config.chat_agent_enable_history or config.chat_agent_enable_feedback_memory:
        await init_storage(config)
    await init_profile_storage(config)
    await init_retrieval_storage(config)


@chat_agent.handle()
async def _(bot: Bot, event: MessageEvent, state: T_State):
    config = get_chat_agent_config()
    prompt = state.get("chat_agent_prompt", "").strip()
    is_group = bool(state.get("chat_agent_is_group", isinstance(event, GroupMessageEvent)))
    session_info = build_session_info(event)

    try:
        await upsert_user_seen(config, session_info)
    except Exception:
        pass

    if not prompt:
        await chat_agent.finish("叫我有什么事？" if is_group else "你想聊什么呀？")
        return

    lock = get_chat_agent_lock()
    if lock.locked():
        await chat_agent.finish(_with_group_at(event, is_group, config.chat_agent_locked_reply))
        return

    await lock.acquire()
    try:
        await chat_agent.send(_with_group_at(event, is_group, config.chat_agent_busy_reply))

        feedback = detect_feedback(prompt) if config.chat_agent_enable_feedback_memory else None
        if feedback is not None:
            try:
                await save_memory(config, session_info, feedback)
            except Exception:
                pass

        context_pack = await build_context_pack(config, session_info, prompt, bot=bot, event=event)
        if context_pack.get("direct_reply"):
            reply = context_pack["direct_reply"]
            if _should_sanitize_task_reply(prompt, context_pack):
                reply = sanitize_task_reply(reply) or reply
            if config.chat_agent_enable_history:
                try:
                    await save_message(config, session_info, "user", prompt)
                    await save_message(config, session_info, "assistant", reply)
                except Exception:
                    pass
            await chat_agent.finish(_with_group_at(event, is_group, reply))
            return

        messages = [{"role": "system", "content": build_system_prompt()}]
        if context_pack.get("time_context"):
            messages.append({"role": "system", "content": context_pack["time_context"]})
        if context_pack.get("profile_context"):
            messages.append({"role": "system", "content": context_pack["profile_context"]})
        if context_pack.get("group_context"):
            messages.append({"role": "system", "content": context_pack["group_context"]})
        if context_pack.get("retrieval_context"):
            messages.append({"role": "system", "content": "本地检索到的相关资料：\n" + context_pack["retrieval_context"]})
        if context_pack.get("summary_retrieval_context"):
            messages.append({"role": "system", "content": "历史聊天摘要检索结果：\n" + context_pack["summary_retrieval_context"]})
        if context_pack.get("memory_context"):
            messages.append({"role": "system", "content": context_pack["memory_context"]})
        if context_pack.get("history_context"):
            messages.append({"role": "system", "content": "最近对话：\n" + context_pack["history_context"]})
        if context_pack.get("web_context"):
            messages.append({"role": "system", "content": "联网查询结果：\n" + context_pack["web_context"]})
        if context_pack.get("tool_notes"):
            messages.append({"role": "system", "content": "工具状态：\n" + context_pack["tool_notes"]})
        messages.append({"role": "user", "content": prompt})

        if config.chat_agent_enable_history:
            try:
                await save_message(config, session_info, "user", prompt)
            except Exception:
                pass

        reply = ""
        should_save_assistant = False
        try:
            reply = await chat_completions(messages, config)
            reply = truncate_reply(strip_thinking(reply), config.chat_agent_max_reply_length)
            should_save_assistant = bool(reply)
        except Exception:
            if context_pack.get("web_context"):
                reply = "我查到了一些相关资料，但模型接口暂时没有响应，稍后可以再试。"
            else:
                reply = config.chat_agent_llm_timeout_reply

        if reply and _should_sanitize_task_reply(prompt, context_pack):
            reply = sanitize_task_reply(reply) or reply

        if config.chat_agent_enable_history and reply and should_save_assistant:
            try:
                await save_message(config, session_info, "assistant", reply)
            except Exception:
                pass

        await chat_agent.finish(_with_group_at(event, is_group, reply or config.chat_agent_llm_timeout_reply))
        return
    finally:
        if lock.locked():
            lock.release()
