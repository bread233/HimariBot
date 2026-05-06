from __future__ import annotations

import re
from typing import Iterable

from nonebot import get_driver
from nonebot.adapters.onebot.v11 import GroupMessageEvent


def strip_thinking(text: str) -> str:
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S | re.I)
    text = re.sub(r"Thinking\.\.\..*?done thinking\.", "", text, flags=re.S | re.I)
    text = text.replace("</think>", "")
    return text.strip()


def truncate_reply(text: str, max_length: int) -> str:
    text = text.strip()
    if max_length > 0 and len(text) > max_length:
        return text[:max_length].rstrip()
    return text


def get_bot_nicknames() -> list[str]:
    nick = getattr(get_driver().config, "nickname", None)
    if not nick:
        return []
    if isinstance(nick, str):
        return [nick]
    return [str(item) for item in nick if str(item).strip()]


def get_original_plain_text(event) -> str:
    original_message = getattr(event, "original_message", None)
    if original_message is not None:
        try:
            return original_message.extract_plain_text()
        except Exception:
            pass
    raw_message = getattr(event, "raw_message", None)
    if raw_message:
        return str(raw_message)
    try:
        return event.message.extract_plain_text()
    except Exception:
        return ""


def extract_group_prompt(event: GroupMessageEvent, bot_self_id: str) -> str | None:
    original_message = getattr(event, "original_message", event.message)
    mentioned = False
    for seg in original_message:
        if seg.type == "at" and str(seg.data.get("qq")) == str(bot_self_id):
            mentioned = True
            break
    if not mentioned:
        return None
    prompt = "".join(seg.data.get("text", "") for seg in event.message if seg.type == "text").strip()
    return prompt if prompt else ""


def extract_private_prompt(text: str, nicknames: Iterable[str]) -> str | None:
    raw = text.lstrip()
    for nickname in nicknames:
        if not nickname:
            continue
        prefix = nickname.strip()
        if not prefix:
            continue
        if raw.startswith(prefix):
            rest = raw[len(prefix):].lstrip(" ,:：")
            return rest.strip()
    return None
