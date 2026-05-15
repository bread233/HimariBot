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


def sanitize_task_reply(text: str) -> str:
    raw = (text or "").strip()
    if not raw:
        return ""
    original = raw

    def _count_cjk(value: str) -> int:
        return len(re.findall(r"[\u4e00-\u9fff]", value or ""))

    # Remove common emoji blocks.
    raw = re.sub(r"[\U0001F300-\U0001FAFF\U00002700-\U000027BF\U000024C2-\U0001F251]", "", raw)
    # Remove simple kaomoji / emoticons.
    raw = re.sub(r"[\(（][^()\n]{1,12}[\)）]", "", raw)
    raw = re.sub(r"(?:\^_\^|T_T|QAQ|QwQ|>_<|=\s*=|:D|:\)|:-\)|:\(|:-\()", "", raw, flags=re.I)

    # Remove obvious cutesy fillers.
    raw = re.sub(r"(嘿嘿+|啦+|嘛+|哟+|呀+)", "", raw)
    raw = re.sub(r"哦[~～]+", "哦", raw)

    # Trim chatty tails often appended to task answers.
    raw = re.sub(r"(记得哦|轻松搞定[~～]?|有需要再聊[~～]?|随时找我[~～]?|一起加油[~～]?|继续加油[~～]?)$", "", raw)

    raw = re.sub(r"[ \t]{2,}", " ", raw)
    raw = re.sub(r"\n{3,}", "\n\n", raw)
    cleaned = raw.strip(" \n\t~～")

    if len(cleaned) < 6 and len(original) >= 20:
        return original.strip()

    orig_cjk = _count_cjk(original)
    cleaned_cjk = _count_cjk(cleaned)
    if orig_cjk > 0 and cleaned_cjk < max(1, int(orig_cjk * 0.3)):
        return original.strip()

    return cleaned


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
