from __future__ import annotations

from .fact_guard import detect_fact_sensitive_question
from .memory import build_memory_reminder_for_user, format_memories_for_prompt
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


async def build_context_pack(config, session_info: dict, prompt: str) -> dict:
    session_id = session_info["session_id"]
    history_limit = int(getattr(config, "chat_agent_history_max_messages", 10))
    memory_limit = int(getattr(config, "chat_agent_memory_max_results", 5))
    web_enabled = bool(getattr(config, "chat_agent_enable_web", False))

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

    should_web, web_query, route_like = _should_web_mode(config, prompt)
    web_context = ""
    tool_notes = []
    web_used = False

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

    if memory_reminder:
        tool_notes.append("memory_reminder_ready")

    return {
        "direct_reply": None,
        "should_call_llm": True,
        "web_used": web_used,
        "history_context": history_context,
        "memory_context": memory_context,
        "web_context": web_context,
        "tool_notes": "\n".join(tool_notes).strip(),
    }
