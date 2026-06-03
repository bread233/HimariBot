from pathlib import Path
from nonebot import get_driver, logger, on_command, on_message
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, MessageEvent, Message, MessageSegment
from nonebot.params import CommandArg, EventMessage
from nonebot.typing import T_State
import asyncio
import secrets
import time
from .config import ConfigModel, get_config
from .trigger_rules import should_trigger, score_interest_text
from .codex_provider import ask_codex
from .cooldown import UserCooldown
from .interest_skill import load_interest_skill
from .context_extractors import extract_message_context
from .memory import (
    register_memory_collector,
    register_memory_commands,
    register_memory_episode_worker,
    build_memory_recall,
)
from .log_sanitize import sanitize_for_log

__plugin_meta__ = {
    "name": "codex_chat",
    "description": "群聊 @/reply 触发的 Codex 文本问答",
    "usage": "@bot 或 reply bot 触发",
}

plugin_config = get_config()
_codex_lock = asyncio.Lock()
_proactive_interval = UserCooldown(plugin_config.codex_chat_proactive_min_interval_seconds)

register_memory_collector()
register_memory_commands()
register_memory_episode_worker()

codex_chat = on_message(priority=plugin_config.codex_chat_command_priority, block=False)
driver = get_driver()
_superusers = {str(x) for x in (getattr(driver.config, "superusers", set()) or set())}
logger.info(
    "codex_chat config_loaded=1 %s",
    sanitize_for_log({
        "enable": 1 if plugin_config.codex_chat_enable else 0,
        "proactive": 1 if plugin_config.codex_chat_proactive_enabled else 0,
        "allowed_groups": plugin_config.allowed_groups_list,
        "threshold": plugin_config.codex_chat_interest_threshold,
    })
)

_INTEREST_ALLOWED_SECTIONS = {
    "active",
    "technical",
    "technical_error",
    "culture",
    "news",
    "activity",
    "question",
    "sharp",
    "life",
    "low_value",
    "zero",
    "service_request",
}

_INTEREST_SECTION_DEFAULT_WEIGHT = {
    "active": 5,
    "technical": 6,
    "technical_error": 2,
    "culture": 6,
    "news": 3,
    "activity": 8,
    "question": 2,
    "sharp": 3,
    "life": 5,
    "low_value": 0,
    "zero": 0,
    "service_request": 0,
}

_interest_pending: dict[str, dict] = {}

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

def _build_prompt(persona: str, user_prompt: str, context_prompt: str = "") -> str:
    p = str(persona or "").strip()
    u = str(user_prompt or "").strip()
    c = str(context_prompt or "").strip()

    if not p:
        p = _DEFAULT_PERSONA

    parts = [p]

    if u:
        parts.append(f"用户消息：\n{u}")
    else:
        parts.append("用户消息：\n（用户没有附加文字，主要内容见群聊附加上下文）")

    if c:
        parts.append(
            "群聊附加上下文：\n"
            f"{c}\n\n"
            "请只根据上面的上下文自然接话或吐槽，不要编造没有提供的信息。"
        )

    parts.append(
        "回复要求：\n"
        "- 直接给出适合发到 QQ 群里的简短中文回答。\n"
        "- 如果是合并消息、搬运内容或卡片分享，可以根据内容自然吐槽。\n"
        "- 不要解释你为什么触发。\n"
        "- 不要编造没有提供的信息。"
    )

    return "\n\n".join(x for x in parts if x)

def _get_event_group_id(event: MessageEvent) -> str | None:
    group_id = getattr(event, "group_id", None)
    return str(group_id) if group_id is not None else None

def _build_memory_recall_context(event: MessageEvent, plugin_config: ConfigModel) -> str:
    if not plugin_config.codex_chat_memory_recall_enabled:
        return ""

    group_id = _get_event_group_id(event)
    if not group_id:
        return ""

    user_id = str(event.get_user_id() or "")
    if not plugin_config.codex_chat_memory_recall_include_user:
        user_id = ""

    limit = plugin_config.codex_chat_memory_recall_limit
    try:
        limit = int(limit)
    except Exception:
        limit = 5
    limit = max(1, min(limit, 10))

    try:
        recall_text = build_memory_recall(
            group_id=group_id,
            user_id=user_id or None,
            limit=limit,
        ).strip()
    except Exception:
        logger.warning("codex_chat_memory recall_context_failed", exc_info=True)
        return ""

    if not recall_text:
        return ""

    logger.info(
        "codex_chat_memory recall_context injected group_id={} user_id={} len={}",
        group_id,
        user_id or "",
        len(recall_text),
    )

    return (
        "【可参考的历史记忆】\n"
        "以下内容来自近期群聊摘要，可能不完整；只作为辅助参考，不确定时不要编造。\n"
        f"{recall_text}"
    )

def _as_reply(event: GroupMessageEvent, text: str) -> Message:
    return Message([
        MessageSegment.reply(event.message_id),
        MessageSegment.text(str(text or "")),
    ])

def _reply_if_direct(event: GroupMessageEvent, mode: str, text: str):
    if mode in {"at", "reply"}:
        return _as_reply(event, text)
    return text

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

def _is_superuser(event: MessageEvent) -> bool:
    try:
        uid = str(getattr(event, "user_id", "") or "")
    except Exception:
        uid = ""
    return bool(uid) and uid in _superusers

def _interest_skill_path() -> str:
    return str(getattr(plugin_config, "codex_chat_interest_skill_path", "") or "").strip()

def _load_interest_terms() -> dict:
    path = _interest_skill_path()
    data = load_interest_skill(path, force=False)
    return dict((data or {}).get("terms") or {})

def _update_interest_rules_file(path: str, section: str, terms: list[str]) -> tuple[bool, str]:
    p = str(path or "").strip()
    if not p or p != _interest_skill_path():
        return False, "path_not_allowed"
    sec = str(section or "").strip().lower()
    if sec not in _INTEREST_ALLOWED_SECTIONS:
        return False, "invalid_section"
    cleaned_terms = []
    seen = set()
    for t in terms or []:
        s = str(t or "").strip()
        if not s:
            continue
        k = s.lower()
        if k in seen:
            continue
        seen.add(k)
        cleaned_terms.append(s)
    if not cleaned_terms:
        return False, "empty_terms"

    fp = Path(p)
    fp.parent.mkdir(parents=True, exist_ok=True)
    if fp.exists():
        try:
            lines = fp.read_text(encoding="utf-8").splitlines()
        except Exception:
            lines = []
    else:
        lines = ["# Codex Chat Interest Rules", ""]

    header = f"## {sec} +{int(_INTEREST_SECTION_DEFAULT_WEIGHT.get(sec, 0) or 0)}"
    start = None
    for i, line in enumerate(lines):
        if line.strip().lower().startswith("## "):
            if line.strip().lower().startswith(f"## {sec}"):
                start = i
                break
    if start is None:
        if lines and lines[-1].strip():
            lines.append("")
        lines.append(header)
        for term in cleaned_terms:
            lines.append(f"- {term}")
        lines.append("")
        try:
            fp.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
        except Exception:
            return False, "write_failed"
        return True, "ok"

    end = len(lines)
    for j in range(start + 1, len(lines)):
        if lines[j].strip().startswith("## "):
            end = j
            break

    existing = set()
    for k in range(start + 1, end):
        raw = lines[k].strip()
        if raw.startswith("- "):
            existing.add(raw[2:].strip().lower())
    insert_terms = [t for t in cleaned_terms if t.lower() not in existing]
    if not insert_terms:
        return True, "no_change"

    insert_at = end
    while insert_at > start + 1 and lines[insert_at - 1].strip() == "":
        insert_at -= 1
    for offset, term in enumerate(insert_terms):
        lines.insert(insert_at + offset, f"- {term}")
    if insert_at + len(insert_terms) < len(lines) and lines[insert_at + len(insert_terms)].strip() != "":
        lines.insert(insert_at + len(insert_terms), "")
    try:
        fp.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    except Exception:
        return False, "write_failed"
    return True, "ok"


codex_interest = on_command("codex_interest", priority=1, block=True)


@codex_interest.handle()
async def _(bot: Bot, event: MessageEvent, arg=CommandArg()):
    text = str(arg.extract_plain_text() or "").strip()
    if not text:
        await codex_interest.finish("用法：/codex_interest add|confirm|reload|test|show ...")
    parts = [p for p in text.split() if p.strip()]
    action = parts[0].lower()
    if action in {"add", "confirm", "reload"} and not _is_superuser(event):
        await codex_interest.finish("权限不足：仅 SUPERUSERS 可用。")

    if action == "add":
        if len(parts) < 3:
            await codex_interest.finish("用法：/codex_interest add <section> <词1> <词2> ...")
        section = parts[1].lower()
        if section not in _INTEREST_ALLOWED_SECTIONS:
            await codex_interest.finish("section 无效。")
        terms = parts[2:]
        token = secrets.token_hex(4)
        _interest_pending[token] = {
            "section": section,
            "terms": terms,
            "user_id": str(getattr(event, "user_id", "") or ""),
            "group_id": str(getattr(event, "group_id", "") or ""),
            "created_at": int(time.time()),
        }
        await codex_interest.finish(f"已生成确认 token={token}，请执行：/codex_interest confirm {token}")

    if action == "confirm":
        if len(parts) != 2:
            await codex_interest.finish("用法：/codex_interest confirm <token>")
        token = parts[1].strip()
        payload = _interest_pending.get(token)
        if not payload:
            await codex_interest.finish("token 不存在或已过期。")
        ok, reason = _update_interest_rules_file(
            _interest_skill_path(),
            payload.get("section", ""),
            payload.get("terms", []),
        )
        _interest_pending.pop(token, None)
        if not ok:
            await codex_interest.finish(f"写入失败：{reason}")
        load_interest_skill(_interest_skill_path(), force=True)
        await codex_interest.finish("已写入并 reload。")

    if action == "reload":
        load_interest_skill(_interest_skill_path(), force=True)
        await codex_interest.finish("已 reload。")

    if action == "test":
        if len(parts) < 2:
            await codex_interest.finish("用法：/codex_interest test <文本>")
        sample = " ".join(parts[1:]).strip()
        score = score_interest_text(sample, config=plugin_config)
        thr = int(getattr(plugin_config, "codex_chat_interest_threshold", 8) or 8)
        trigger = score >= thr
        await codex_interest.finish(f"文本：{sample}\nscore={score} threshold={thr} trigger={str(bool(trigger)).lower()}")

    if action == "show":
        if len(parts) != 2:
            await codex_interest.finish("用法：/codex_interest show <section>")
        section = parts[1].lower()
        if section not in _INTEREST_ALLOWED_SECTIONS:
            await codex_interest.finish("section 无效。")
        terms = _load_interest_terms().get(section, [])
        await codex_interest.finish(f"{section}：{', '.join(terms) if terms else '(empty)'}")

    await codex_interest.finish("未知子命令。")

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
    context = await extract_message_context(bot, event, plugin_config)
    context_text = str(context.get("text") or "").strip()
    context_prompt = str(context.get("prompt") or "").strip()
    context_sources = context.get("sources") or []
    context_len = len(context_text)

    score_text = "\n".join(x for x in [prompt, context_text] if x).strip()
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
        trigger, score = should_trigger(group_id, score_text, plugin_config)
        if not trigger:
            logger.info(
                f"codex_chat skip_trigger mode={mode} group_id={group_id} "
                f"score={score} prompt_len={prompt_len} "
                f"context_sources={context_sources} context_len={context_len}"
            )
            return
        mode = "proactive"

    if mode in {"at", "reply"}:
        if _codex_lock.locked():
            logger.info(f"codex_chat busy_skip=1 mode={mode} group_id={group_id} user_id={user_id} prompt_len={prompt_len}")
            await codex_chat.finish(_reply_if_direct(event, mode, "我还在思考上一条，稍后再 @ 我～"))
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

    if not prompt and not context_text:
        logger.info(
            f"codex_chat empty_prompt mode={mode} group_id={group_id} "
            f"prompt_len={prompt_len} context_sources={context_sources} context_len={context_len}"
        )
        await codex_chat.finish(_reply_if_direct(event, mode, "我在，想问什么？"))

    logger.info(
        f"codex_chat trigger=1 mode={mode} group_id={group_id} "
        f"score={score} prompt_len={prompt_len} "
        f"context_sources={context_sources} context_len={context_len}"
    )
    persona = _load_persona(plugin_config.codex_chat_persona_path)
    memory_recall_context = _build_memory_recall_context(event, plugin_config)
    if memory_recall_context:
        if context_prompt:
            context_prompt = f"{context_prompt}\n\n{memory_recall_context}"
        else:
            context_prompt = memory_recall_context
    final_prompt = _build_prompt(persona, prompt, context_prompt)
    async with _codex_lock:
        result = await ask_codex(plugin_config, final_prompt)

    if result.ok and result.text:
        await codex_chat.finish(_reply_if_direct(event, mode, result.text))
    await codex_chat.finish(_reply_if_direct(event, mode, "我这边暂时没想出来，稍后再试。"))
