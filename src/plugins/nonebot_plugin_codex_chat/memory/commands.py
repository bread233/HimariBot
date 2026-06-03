from __future__ import annotations

import json
import time
from typing import Any

from nonebot import get_driver, logger, on_command
from nonebot.adapters.onebot.v11 import Message, MessageEvent
from nonebot.params import CommandArg

from ..config import ConfigModel
from .episodes import generate_episode_for_memcell
from .query import (
    get_memcell_detail,
    get_memory_status,
    get_recent_group_episodes,
    get_recent_memcells,
    get_user_messages,
)
from .recall import build_long_memory_recall, build_memory_recall
from .consolidation import (
    generate_long_memory_candidates_preview,
    generate_and_save_long_memory_candidates,
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
        "episode": "episode",
        "抽取": "episode",
        "episodes": "episodes",
        "摘要": "episodes",
        "recall": "recall",
        "回忆": "recall",
        "consolidate-preview": "consolidate_preview",
        "consolidate_preview": "consolidate_preview",
        "preview-long": "consolidate_preview",
        "预览长期记忆": "consolidate_preview",
        "长期记忆预览": "consolidate_preview",
        "consolidate-save": "consolidate_save",
        "consolidate_save": "consolidate_save",
        "save-long": "consolidate_save",
        "保存长期记忆": "consolidate_save",
        "长期记忆保存": "consolidate_save",
        "long-recall": "long_recall",
        "long_recall": "long_recall",
        "长期回忆": "long_recall",
        "长期记忆": "long_recall",
        "long-memory": "long_recall",
        "long_memory": "long_recall",
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


async def _format_episode(args: list[str]) -> str:
    if not args:
        return "用法：/codex_memory episode <memcell_id> [--force]"

    force = False
    memcell_str = args[0]

    for arg in args[1:]:
        if arg == "--force":
            force = True

    try:
        memcell_id = int(memcell_str)
    except ValueError:
        return "用法：/codex_memory episode <memcell_id> [--force]"

    plugin_config = ConfigModel.parse_obj(get_driver().config.dict())

    try:
        result = await generate_episode_for_memcell(plugin_config, memcell_id, force)
    except Exception:
        logger.warning(
            f"codex_chat_memory episode_failed memcell_id={memcell_id}",
            exc_info=True,
        )
        return f"Episode 生成失败\nerror=exception memcell_id={memcell_id}"

    if not result.get("ok"):
        error = result.get("error", "unknown")
        return f"Episode 生成失败\nerror={error} memcell_id={memcell_id}"

    if result.get("skipped"):
        return (
            f"Episode 已存在\n"
            f"memcell_id={memcell_id}\n"
            f"使用 --force 可重新生成"
        )

    lines = [
        "Episode 已生成",
        f"memcell_id={memcell_id}",
        f"group_episode_saved={result.get('group_episode_saved', '?')}",
        f"user_episode_saved={result.get('user_episode_saved', '?')}",
        f"summary={_truncate(result.get('summary', ''), 200)}",
        f"topic={_truncate(result.get('topic', ''), 200)}",
    ]

    return "\n".join(lines)


def _format_episodes(args: list[str]) -> str:
    group_id = None
    limit = 5

    if len(args) >= 1:
        group_id = args[0]
    if len(args) >= 2:
        try:
            limit = int(args[1])
        except ValueError:
            limit = 5

    episodes = get_recent_group_episodes(group_id=group_id, limit=limit)

    if not episodes:
        target = f" group={group_id}" if group_id else ""
        return f"最近 Episodes{target}\n无数据"

    lines = ["最近 Episodes"]

    for ep in episodes:
        header = (
            f"#id={ep['id']} memcell={ep.get('memcell_id', '?')} "
            f"group={ep.get('group_id', '?')} "
            f"importance={ep.get('importance', 0)} "
            f"confidence={ep.get('confidence', 0.0)}"
        )
        topic = _truncate(ep.get("topic", ""), 200)
        summary = _truncate(ep.get("summary", ""), 200)

        lines.append(header)
        lines.append(f"topic={topic}")
        lines.append(f"summary={summary}")

    return "\n\n".join(lines)


def _format_recall(args: list[str], current_group_id: str | None = None) -> str:
    group_id = None
    user_id = None
    limit = 5

    positional_args = []
    i = 0
    while i < len(args):
        if args[i] == "--limit" and i + 1 < len(args):
            try:
                limit = int(args[i + 1])
            except ValueError:
                pass
            i += 2
        elif args[i].startswith("--limit="):
            try:
                limit = int(args[i][len("--limit="):])
            except ValueError:
                pass
            i += 1
        else:
            positional_args.append(args[i])
            i += 1

    # 位置参数：group_id, user_id
    if len(positional_args) >= 1 and positional_args[0]:
        group_id = positional_args[0]
    elif current_group_id:
        group_id = current_group_id

    if len(positional_args) >= 2 and positional_args[1]:
        user_id = positional_args[1]

    recall_text = build_memory_recall(
        group_id=group_id,
        user_id=user_id,
        limit=limit,
    )

    if not recall_text.strip():
        return "暂无可用记忆"

    return recall_text


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


def _parse_group_user_limit_args(
    args: list[str],
    current_group_id: str | None = None,
    default_limit: int = 20,
    max_limit: int = 50,
) -> tuple[str | None, str | None, int]:
    positional_args: list[str] = []
    limit = default_limit

    i = 0
    while i < len(args):
        if args[i] == "--limit" and i + 1 < len(args):
            try:
                limit = int(args[i + 1])
            except ValueError:
                pass
            i += 2
        elif args[i].startswith("--limit="):
            try:
                limit = int(args[i][len("--limit="):])
            except ValueError:
                pass
            i += 1
        else:
            positional_args.append(args[i])
            i += 1

    limit = max(1, min(limit, max_limit))

    group_id = None
    user_id = None
    if len(positional_args) >= 1 and positional_args[0]:
        group_id = positional_args[0]
    elif current_group_id:
        group_id = current_group_id
    if len(positional_args) >= 2 and positional_args[1]:
        user_id = positional_args[1]

    return group_id, user_id, limit


def _format_candidate_preview_result(result: dict, saved_mode: bool = False) -> str:
    ok = result.get("ok", False)
    skipped = result.get("skipped", False)
    reason = result.get("reason", "")
    group_id = result.get("group_id", "")
    user_id = result.get("user_id", "")
    ep_counts = result.get("episode_counts", {})
    candidates = result.get("candidates", [])
    candidate_count = len(candidates)

    title = "长期记忆已保存" if saved_mode else "长期记忆候选预览"
    lines = [
        title,
        f"ok={ok} skipped={skipped} reason={reason}",
        f"group_id={group_id} user_id={user_id}",
        f"episodes group={ep_counts.get('group', 0)} user={ep_counts.get('user', 0)}",
        f"candidates={candidate_count}",
    ]

    if ok and not skipped:
        for idx, c in enumerate(candidates[:10], 1):
            scope_type = c.get("scope_type", "?")
            memory_type = c.get("memory_type", "?")
            importance = c.get("importance", 0)
            confidence = c.get("confidence", 0.0)
            title = _truncate(c.get("title", ""), 80)
            summary = _truncate(c.get("summary", ""), 120)
            mem_ids = c.get("evidence_memcell_ids", [])
            ep_ids = c.get("evidence_episode_ids", [])

            lines.append(
                f"\n[{idx}] {scope_type}/{memory_type} "
                f"importance={importance} confidence={confidence}"
            )
            if title:
                lines.append(f"title={title}")
            lines.append(f"summary={summary}")
            if mem_ids or ep_ids:
                lines.append(
                    f"evidence episodes={ep_ids} memcells={mem_ids}"
                )

        remaining = candidate_count - 10
        if remaining > 0:
            lines.append(f"\n... 还有 {remaining} 条")

    if saved_mode:
        saved = result.get("saved", 0)
        skipped_save = result.get("skipped_save", 0)
        candidate_ids = result.get("candidate_ids", [])
        lines.append(f"saved={saved} skipped_save={skipped_save}")
        lines.append("status=approved")
        lines.append(f"candidate_ids={candidate_ids}")

    return "\n".join(lines)


def _build_greg(event: MessageEvent) -> str | None:
    raw = getattr(event, "group_id", None)
    return str(raw) if raw is not None else None


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
        elif subcommand == "episode":
            reply = await _format_episode(rest)
        elif subcommand == "episodes":
            reply = _format_episodes(rest)
        elif subcommand == "recall":
            group_id_default_raw = getattr(event, "group_id", None)
            group_id_default = str(group_id_default_raw) if group_id_default_raw is not None else None
            reply = _format_recall(rest, current_group_id=group_id_default)
        elif subcommand == "long_recall":
            current_gid = _build_greg(event)
            gid, uid, lim = _parse_group_user_limit_args(rest, current_gid, default_limit=10, max_limit=20)
            if not gid:
                reply = "缺少 group_id，请在群内使用或显式传入 group_id"
            else:
                recall_text = build_long_memory_recall(
                    group_id=gid,
                    user_id=uid,
                    limit=lim,
                    min_importance=0,
                    min_confidence=0.0,
                    max_chars=1200,
                )
                if not recall_text.strip():
                    reply = "暂无可用长期记忆"
                else:
                    reply = (
                        f"长期记忆 recall\n"
                        f"group_id={gid}\n"
                        f"user_id={uid or ''}\n"
                        f"limit={lim}\n\n"
                        f"{recall_text}"
                    )
        elif subcommand == "consolidate_preview":
            current_gid = _build_greg(event)
            gid, uid, lim = _parse_group_user_limit_args(rest, current_gid)
            if not gid:
                reply = "缺少 group_id，请在群内使用或显式传入 group_id"
            else:
                plugin_config = ConfigModel.parse_obj(get_driver().config.dict())
                result = await generate_long_memory_candidates_preview(
                    plugin_config, gid, uid, lim
                )
                reply = _format_candidate_preview_result(result)
        elif subcommand == "consolidate_save":
            current_gid = _build_greg(event)
            gid, uid, lim = _parse_group_user_limit_args(rest, current_gid)
            if not gid:
                reply = "缺少 group_id，请在群内使用或显式传入 group_id"
            else:
                plugin_config = ConfigModel.parse_obj(get_driver().config.dict())
                result = await generate_and_save_long_memory_candidates(
                    plugin_config, gid, uid, lim
                )
                reply = _format_candidate_preview_result(result, saved_mode=True)
        else:
            reply = (
                "用法：\n"
                "/codex_memory status\n"
                "/codex_memory recent [group_id] [limit]\n"
                "/codex_memory user <group_id> <user_id> [limit]\n"
                "/codex_memory memcell <memcell_id>\n"
                "/codex_memory episode <memcell_id> [--force]\n"
                "/codex_memory episodes [group_id] [limit]\n"
                "/codex_memory recall [group_id] [user_id] [--limit N]\n"
                "/codex_memory long-recall [group_id] [user_id] [--limit N]\n"
                "/codex_memory consolidate-preview [group_id] [user_id] [--limit N]\n"
                "/codex_memory consolidate-save [group_id] [user_id] [--limit N]"
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

