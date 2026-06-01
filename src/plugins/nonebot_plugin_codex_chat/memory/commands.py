from __future__ import annotations

import json
import time
from typing import Any

from nonebot import get_driver, logger, on_command
from nonebot.adapters.onebot.v11 import Message, MessageEvent
from nonebot.params import CommandArg

from .query import (
    get_memcell_detail,
    get_memory_status,
    get_recent_memcells,
    get_user_messages,
)

_MAX_REPLY_CHARS = 1800
_PREVIEW_TRUNC = 300
_TEXT_TRUNC = 120

_memory_command_registered = False
_memory_cmd = on_command(
    "codex_memory",
    aliases={"codex记忆"},
    priority=5,
    block=True,
)


def _truncate(text: object, max_chars: int) -> str:
    value = str(text or "")
    if len(value) <= max_chars:
        return value
    return value[:max_chars] + "..."


def _limit_reply(text: str) -> str:
    if len(text) <= _MAX_REPLY_CHARS:
        return text
    return text[:_MAX_REPLY_CHARS] + "\n...已截断"


def _format_time(ts: Any) -> str:
    try:
        value = int(ts)
    except Exception:
        return "-"
    if value <= 0:
        return "-"
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(value))


def _is_superuser(event: MessageEvent) -> bool:
    superusers = {
        str(item)
        for item in (getattr(get_driver().config, "superusers", set()) or set())
    }
    return str(event.get_user_id()) in superusers


def _normalize_subcommand(command: str) -> str:
    mapping = {
        "status": "status",
        "状态": "status",
        "recent": "recent",
        "最近": "recent",
        "user": "user",
        "用户": "user",
        "memcell": "memcell",
        "detail": "memcell",
        "详情": "memcell",
    }
    return mapping.get(command.strip().lower(), "")


def _format_status() -> str:
    status = get_memory_status()
    lines = [
        "Codex Memory 状态",
        f"DB: {status['db_path']}",
        f"db_exists: {status['db_exists']}",
        f"memcells: {status['memcell_count']}",
        f"messages: {status['message_count']}",
        f"latest_memcell_id: {status['latest_memcell_id']}",
        f"latest_created_at: {_format_time(status['latest_created_at'])}",
    ]
    return "\n".join(lines)


def _format_recent(args: list[str]) -> str:
    group_id: str | None = None
    limit = 5

    if len(args) >= 1:
        group_id = args[0]
    if len(args) >= 2:
        try:
            limit = int(args[1])
        except ValueError:
            limit = 5

    memcells = get_recent_memcells(group_id=group_id, limit=limit)
    if not memcells:
        target = f" group={group_id}" if group_id else ""
        return f"最近 MemCell{target}\n无数据"

    lines = ["最近 MemCell"]
    for memcell in memcells:
        lines.append(
            f"#{memcell['id']} group={memcell['group_id']} "
            f"messages={memcell['message_count']} "
            f"created_at={_format_time(memcell['created_at'])}"
        )
        preview = _truncate(memcell.get("raw_text_preview", ""), _PREVIEW_TRUNC)
        if preview:
            lines.append(preview)

    return "\n\n".join(lines)


def _format_user(args: list[str]) -> str:
    if len(args) < 2:
        return "用法：/codex_memory user <group_id> <user_id> [limit]"

    group_id = args[0]
    user_id = args[1]
    limit = 10

    if len(args) >= 3:
        try:
            limit = int(args[2])
        except ValueError:
            limit = 10

    messages = get_user_messages(group_id=group_id, user_id=user_id, limit=limit)
    if not messages:
        return f"用户消息\ngroup={group_id} user={user_id}\n无数据"

    lines = [f"用户消息\ngroup={group_id} user={user_id}"]
    for message in messages:
        text = _truncate(message.get("text", ""), _TEXT_TRUNC)
        filtered = " filtered=1" if message.get("filtered") else ""
        lines.append(
            f"#{message['memcell_id']} msg={message['message_id']} "
            f"time={_format_time(message['timestamp'])}{filtered}"
        )
        if text:
            lines.append(f"  {text}")

    return "\n".join(lines)


def _format_memcell(args: list[str]) -> str:
    if not args:
        return "用法：/codex_memory memcell <memcell_id>"

    try:
        memcell_id = int(args[0])
    except ValueError:
        return "用法：/codex_memory memcell <memcell_id>"

    detail = get_memcell_detail(memcell_id)
    if detail is None:
        return f"MemCell #{memcell_id} 不存在"

    memcell = detail["memcell"]
    messages = detail["messages"]

    lines = [
        f"MemCell #{memcell['id']}",
        f"group={memcell['group_id']}",
        f"messages={memcell['message_count']}",
        f"time={_format_time(memcell['start_time'])} ~ {_format_time(memcell['end_time'])}",
    ]

    try:
        participants = json.loads(memcell.get("participants_json") or "[]")
        if participants:
            names = []
            for participant in participants:
                name = (
                    participant.get("card")
                    or participant.get("nickname")
                    or participant.get("user_id")
                    or "?"
                )
                role = participant.get("role") or "member"
                names.append(f"{name}/{role}")
            lines.append(f"participants={', '.join(names)}")
    except Exception:
        pass

    preview = _truncate(memcell.get("raw_text_preview", ""), _PREVIEW_TRUNC)
    if preview:
        lines.append(f"preview:\n{preview}")

    lines.append("消息：")
    for message in messages:
        display = (
            message.get("sender_card")
            or message.get("sender_nickname")
            or message.get("user_id")
        )
        role = message.get("sender_role") or "member"
        text = _truncate(message.get("text", ""), _TEXT_TRUNC)
        filtered = " filtered=1" if message.get("filtered") else ""
        lines.append(f"- [{message['user_id']}/{display}/{role}]{filtered} {text}")

    return "\n".join(lines)


@_memory_cmd.handle()
async def _handle_memory_command(
    event: MessageEvent,
    args: Message = CommandArg(),
) -> None:
    if not _is_superuser(event):
        await _memory_cmd.finish("无权限查看 Codex memory。")

    plain = args.extract_plain_text().strip()
    parts = plain.split()

    if not parts:
        subcommand = "status"
        rest: list[str] = []
    else:
        subcommand = _normalize_subcommand(parts[0])
        rest = parts[1:]

    try:
        if subcommand == "status":
            reply = _format_status()
        elif subcommand == "recent":
            reply = _format_recent(rest)
        elif subcommand == "user":
            reply = _format_user(rest)
        elif subcommand == "memcell":
            reply = _format_memcell(rest)
        else:
            reply = (
                "用法：\n"
                "/codex_memory status\n"
                "/codex_memory recent [group_id] [limit]\n"
                "/codex_memory user <group_id> <user_id> [limit]\n"
                "/codex_memory memcell <memcell_id>"
            )
    except Exception:
        logger.warning("codex_chat_memory command_failed", exc_info=True)
        reply = "Codex Memory 查询失败，详见日志。"

    await _memory_cmd.finish(_limit_reply(reply))


def register_memory_commands() -> None:
    global _memory_command_registered

    if _memory_command_registered:
        return

    _memory_command_registered = True
    logger.info("codex_chat_memory commands_registered")
    