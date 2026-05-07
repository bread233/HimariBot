from __future__ import annotations

from .fact_guard import detect_fact_sensitive_question
from .memory import build_memory_reminder_for_user, format_memories_for_prompt
from .group_tools import get_group_info_context, get_group_member_seen_context
from .profile_store import load_user_profile_context
from .storage import load_memories, load_recent_messages
from .tool_router import should_use_web_tool
from .web_tools import build_web_context


def _is_context_question(prompt: str) -> bool:
    text = (prompt or "").strip()
    return any(
        token in text
        for token in [
            "刚才说了什么",
            "刚刚说了什么",
            "之前说了什么",
            "刚才在测什么",
            "刚刷了啥",
            "在测什么",
        ]
    )


def _is_self_identity_question(prompt: str) -> bool:
    text = (prompt or "").strip()
    patterns = [
        "我是谁",
        "我是谁啊",
        "你知道我是谁吗",
        "你知道我叫什么吗",
        "我叫什么",
        "我在群里叫什么",
    ]
    return any(pattern in text for pattern in patterns)


def _extract_last_user_message(history: list[dict], current_prompt: str) -> str | None:
    current = (current_prompt or "").strip()
    for item in reversed(history):
        if item.get("role") != "user":
            continue
        content = str(item.get("content", "")).strip()
        if not content or content == current:
            continue
        plain = content.split("：", 1)[-1].strip() if "：" in content else content
        if plain:
            return plain
    return None


def _should_web_mode(config, prompt: str) -> tuple[bool, str, bool]:
    web_mode = str(getattr(config, "chat_agent_web_mode", "auto")).lower()
    tool_router_enabled = bool(getattr(config, "chat_agent_enable_tool_router", True))
    web_enabled = bool(getattr(config, "chat_agent_enable_web", False))
    route = should_use_web_tool(prompt) if tool_router_enabled and web_mode == "auto" else None
    guard = detect_fact_sensitive_question(prompt) if getattr(config, "chat_agent_enable_fact_guard", True) else None
    if web_mode == "off":
        return False, prompt, False
    if web_mode == "always":
        if _is_context_question(prompt):
            return False, prompt, False
        return web_enabled, prompt, False
    if route or guard:
        return web_enabled, (route or {}).get("query") or (guard.get("search_query") if guard else None) or prompt, True
    return False, prompt, False


async def build_context_pack(config, session_info: dict, prompt: str, bot=None, event=None) -> dict:
    session_id = session_info["session_id"]
    history_limit = int(getattr(config, "chat_agent_history_max_messages", 10))
    memory_limit = int(getattr(config, "chat_agent_memory_max_results", 5))
    web_enabled = bool(getattr(config, "chat_agent_enable_web", False))
    is_identity_question = _is_self_identity_question(prompt)

    try:
        profile_context = await load_user_profile_context(config, session_info)
    except Exception:
        profile_context = ""

    if is_identity_question and profile_context:
        identity_hint_lines = [
            "",
            "身份回答要求：",
            "- 用户正在问自己的身份/昵称。",
            "- 请只基于本轮提供的“说话者画像”和“当前发言人在群内”资料回答。",
            "- 如果问题是“我在群里叫什么”，请优先回答当前群昵称/群名片；如果群名片为空，请回答当前显示的是 QQ 昵称。",
            "- 不要推测群里有没有其他人。",
            "- 不要编造没有提供的信息。",
            "- 不要回答“我不知道”，除非上下文里完全没有 QQ、昵称、群昵称信息。",
            "- 回答要简短。",
        ]
        profile_context = profile_context.rstrip() + "\n" + "\n".join(identity_hint_lines)

    group_context = ""
    if bot is not None and event is not None and session_info.get("session_type") == "group":
        parts = []
        try:
            info_context = await get_group_info_context(bot, event, session_info)
        except Exception:
            info_context = ""
        if info_context:
            parts.append(info_context)
        try:
            member_context = await get_group_member_seen_context(bot, event, session_info)
        except Exception:
            member_context = ""
        if member_context:
            parts.append(member_context)
        group_context = "\n\n".join(parts).strip()

    try:
        history = await load_recent_messages(config, session_id, history_limit)
    except Exception:
        history = []

    if _is_context_question(prompt):
        last_user = _extract_last_user_message(history, prompt)
        if last_user:
            return {
                "direct_reply": f"你刚才说：{last_user}",
                "should_call_llm": False,
                "web_used": False,
                "profile_context": profile_context,
                "group_context": group_context,
                "history_context": "",
                "memory_context": "",
                "web_context": "",
                "tool_notes": "",
            }

    try:
        memories = await load_memories(config, session_id, memory_limit)
    except Exception:
        memories = []

    memory_context = format_memories_for_prompt(memories)
    memory_reminder = build_memory_reminder_for_user(memories, prompt)
    if memory_reminder:
        memory_context = f"{memory_context}\n\n{memory_reminder}".strip() if memory_context else memory_reminder

    history_lines = []
    for item in history:
        role = item.get("role")
        content = str(item.get("content", "")).strip()
        if not content:
            continue
        if role == "user":
            if session_info["session_type"] == "group":
                nick = item.get("nickname") or "用户"
                content = f"{nick}：{content}"
            else:
                content = f"用户：{content}"
        elif role == "assistant":
            content = f"助手：{content}"
        history_lines.append(content)
    history_context = "\n".join(history_lines[-history_limit:]).strip()

    should_web = False
    web_query = prompt
    route_like = False
    web_context = ""
    tool_notes = []
    web_used = False

    if not is_identity_question:
        should_web, web_query, route_like = _should_web_mode(config, prompt)
        if should_web and web_enabled:
            try:
                web_context = await build_web_context(config, web_query)
            except Exception:
                web_context = ""
            if web_context:
                web_used = True
            else:
                tool_notes.append("web_search_failed")
                if str(getattr(config, "chat_agent_web_mode", "auto")).lower() == "auto" and route_like:
                    tool_notes.append("fact_sensitive_no_web")
        elif should_web and not web_enabled:
            tool_notes.append("web_disabled")
    else:
        tool_notes.append("identity_question_no_web")

    if memory_reminder:
        tool_notes.append("memory_reminder_ready")

    return {
        "direct_reply": None,
        "should_call_llm": True,
        "web_used": web_used,
        "profile_context": profile_context,
        "group_context": group_context,
        "history_context": history_context,
        "memory_context": memory_context,
        "web_context": web_context,
        "tool_notes": "\n".join(tool_notes).strip(),
    }
