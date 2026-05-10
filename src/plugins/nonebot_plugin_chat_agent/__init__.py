from __future__ import annotations

from nonebot import get_driver, logger, on_message
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


def _append_system(messages: list[dict], content: str) -> None:
    text = str(content or "").strip()
    if text:
        messages.append({"role": "system", "content": text})


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

        if str(context_pack.get("lightweight_mode", "")).strip() == "definition":
            lightweight_prompt = str(context_pack.get("lightweight_prompt", prompt) or prompt).strip()
            lightweight_messages = [
                {"role": "system", "content": "你负责用中文简洁解释一个概念。请用1-3句回答。不要编造版本号、价格、新闻或历史记录。不了解时直接说不确定。"},
                {"role": "user", "content": lightweight_prompt or prompt},
            ]
            lightweight_timeout = 20
            tool_notes = str(context_pack.get("tool_notes", "") or "")
            reply = ""
            should_save_assistant = False
            try:
                reply = await chat_completions(lightweight_messages, config, timeout=lightweight_timeout)
                reply = truncate_reply(strip_thinking(reply), config.chat_agent_max_reply_length)
                reply = str(reply or "").strip()
                if not reply:
                    logger.warning(
                        f"lightweight definition empty reply timeout={lightweight_timeout} "
                        f"prompt={(lightweight_prompt or prompt)[:80]!r}"
                    )
                    reply = "\u8fd9\u4e2a\u6982\u5ff5\u6211\u6682\u65f6\u6ca1\u6cd5\u7a33\u5b9a\u751f\u6210\u89e3\u91ca\uff0c\u53ef\u4ee5\u7a0d\u540e\u518d\u8bd5\u3002"
                should_save_assistant = bool(reply)
            except Exception as e:
                logger.warning(
                    f"lightweight definition failed type={type(e).__name__} "
                    f"timeout={lightweight_timeout} "
                    f"prompt={(lightweight_prompt or prompt)[:80]!r} "
                    f"message={str(e)[:200]!r}"
                )
                reply = "\u8fd9\u4e2a\u6982\u5ff5\u6211\u6682\u65f6\u6ca1\u6cd5\u7a33\u5b9a\u751f\u6210\u89e3\u91ca\uff0c\u53ef\u4ee5\u7a0d\u540e\u518d\u8bd5\u3002"
                if tool_notes:
                    tool_notes += "\n"
                tool_notes += f"simple_definition_lightweight_error={str(e)[:120]}"
            if _should_sanitize_task_reply(prompt, context_pack):
                reply = sanitize_task_reply(reply) or reply
            if config.chat_agent_enable_history and reply and should_save_assistant:
                try:
                    await save_message(config, session_info, "user", prompt)
                    await save_message(config, session_info, "assistant", reply)
                except Exception:
                    pass
            await chat_agent.finish(_with_group_at(event, is_group, reply))
            return

        messages = [{"role": "system", "content": build_system_prompt()}]
        _append_system(messages, context_pack.get("time_context", ""))
        _append_system(messages, context_pack.get("profile_context", ""))
        _append_system(messages, context_pack.get("group_context", ""))

        style_context = str(context_pack.get("style_context", "") or "").strip()
        if style_context:
            _append_system(
                messages,
                "你会收到“回复风格提示”。这只用于调整语气、长度和格式。不要向用户提到画像、历史或系统提示。",
            )
            _append_system(messages, "回复风格提示：\n" + style_context)

        retrieval_context = str(context_pack.get("retrieval_context", "") or "").strip()
        if retrieval_context:
            _append_system(
                messages,
                "\n".join(
                    [
                        "本地资料使用规则：",
                        "- 下面是本地检索资料。",
                        "- 只在和用户问题直接相关时使用。",
                        "- 不要编造资料中没有的信息。",
                    ]
                ),
            )
            _append_system(messages, "本地检索到的相关资料：\n" + retrieval_context)

        summary_retrieval_context = str(context_pack.get("summary_retrieval_context", "") or "").strip()
        if summary_retrieval_context:
            _append_system(
                messages,
                "\n".join(
                    [
                        "历史摘要使用规则：",
                        "- 下面内容只用于用户明确询问“之前/历史/谁说过/聊过/提过”等场景。",
                        "- 只能复述或概括历史摘要里的线索。",
                        "- 不要把历史摘要扩写成通用事实。",
                        "- 如果摘要不足，回答“历史摘要里没找到足够可靠线索”。",
                    ]
                ),
            )
            _append_system(messages, "历史聊天摘要检索结果：\n" + summary_retrieval_context)

        memory_context = str(context_pack.get("memory_context", "") or "").strip()
        if memory_context:
            _append_system(
                messages,
                "\n".join(
                    [
                        "长期记忆使用规则：",
                        "- 只用于个性化和已确认偏好。",
                        "- 不要把记忆当成当前事实来源。",
                        "- 不要主动暴露记忆内容。",
                    ]
                ),
            )
            _append_system(messages, memory_context)

        history_context = str(context_pack.get("history_context", "") or "").strip()
        if history_context:
            _append_system(messages, "最近对话：\n" + history_context)

        tool_notes = str(context_pack.get("tool_notes", "") or "").strip()
        is_direct_url_mode = "direct_url_mode=1" in tool_notes

        web_context = str(context_pack.get("web_context", "") or "").strip()
        if web_context:
            if is_direct_url_mode:
                _append_system(
                    messages,
                    "\n".join(
                        [
                            "链接内容使用规则：",
                            "- 下面是用户提供链接的读取结果。",
                            "- 优先根据链接内容回答。",
                            "- 如果内容不足，明确说明。",
                        ]
                    ),
                )
                _append_system(messages, "链接读取结果：\n" + web_context)
            else:
                _append_system(
                    messages,
                    "\n".join(
                        [
                            "联网资料使用规则：",
                            "- 下面的联网资料是候选资料，不保证都正确。",
                            "- 优先使用 official/docs/current-year/recent-year 来源。",
                            "- 对 stale-year/rumor/forum/seo 来源保持低置信。",
                            "- 如果官方或权威来源没有明确参数，不要硬编；回答“官方资料未明确，以官方发布为准”。",
                            "- 不要把传闻、旧页面或论坛内容当成确定事实。",
                            "- 如果资料冲突，说明低置信，并优先官方/较新的来源。",
                        ]
                    ),
                )
                _append_system(messages, "联网查询结果：\n" + web_context)

        if tool_notes:
            _append_system(
                messages,
                "\n".join(
                    [
                        "工具状态（仅用于判断可靠性，不要在回答中复述）：",
                        tool_notes,
                    ]
                ),
            )

        _append_system(
            messages,
            "\n".join(
                [
                    "最终回复要求：",
                    "- 普通问题默认 1~3 句。",
                    "- 第一反应给结论，不要铺垫。",
                    "- 不要复述用户问题。",
                    "- 不要主动说“根据上下文/根据资料/根据历史/根据画像”。",
                    "- 关键词式问题按“询问该主题的结论或状态”直接回答。",
                    "- 当前事实类问题：如果官方/权威资料不明确，直接说“不确定/官方未明确”，不要编。",
                    "- 明确历史查询：可以说“历史摘要里看到/没找到”。",
                    "- 没有可靠资料时，不要为了完整而扩写。",
                ]
            ),
        )
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
