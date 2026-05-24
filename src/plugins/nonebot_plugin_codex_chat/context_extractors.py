import json
from typing import Any

from nonebot import logger
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent

import re
from aiohttp import ClientSession

try:
    from src.plugins.analysis_bilibili.analysis_bilibili import (
        config as bili_config,
        b23_extract,
        bili_keyword,
    )
except Exception:
    bili_config = None
    b23_extract = None
    bili_keyword = None

_BILI_PATTERN = re.compile(
    r"(b23\.tv)|"
    r"(bili(22|23|33|2233)\.cn)|"
    r"(bilibili\.com)|"
    r"(?<![A-Za-z0-9])(?:av|cv)\d+(?![A-Za-z0-9])|"
    r"(?<![A-Za-z0-9])BV[A-Za-z0-9]{10}(?![A-Za-z0-9])|"
    r"(\[\[QQ小程序\]哔哩哔哩\])|"
    r"(QQ小程序&amp;#93;哔哩哔哩)|"
    r"(QQ小程序&#93;哔哩哔哩)",
    re.I,
)

_INTERESTING_JSON_KEYS = {
    "title",
    "desc",
    "description",
    "summary",
    "prompt",
    "text",
    "content",
    "app",
    "tag",
    "tags",
    "name",
}

def _is_image_url_or_file(text: str) -> bool:
    s = str(text or "").strip().lower()
    return s.endswith((
        ".jpg",
        ".jpeg",
        ".png",
        ".gif",
        ".bmp",
        ".jfif",
        ".webp",
    ))


def _flatten_bili_msg(obj) -> list[str]:
    result: list[str] = []

    if obj is None or obj is False:
        return result

    if isinstance(obj, str):
        s = obj.strip()
        if s and not _is_image_url_or_file(s):
            result.append(s)
        return result

    if isinstance(obj, (list, tuple)):
        for item in obj:
            result.extend(_flatten_bili_msg(item))
        return result

    return result

async def _extract_bilibili_context(event: GroupMessageEvent, config) -> tuple[str, str]:
    if not getattr(config, "codex_chat_extract_bilibili_context", True):
        return "", ""

    plain_text = event.get_plaintext().strip()
    raw_text = plain_text or str(event.message).strip()
    if not raw_text:
        return "", ""

    if not _BILI_PATTERN.search(raw_text):
        return "", ""

    logger.info(
        f"codex_chat context_extract source=bilibili matched=1 raw_len={len(raw_text)}"
    )

    if bili_keyword is None or b23_extract is None or bili_config is None:
        logger.warning("codex_chat context_extract source=bilibili unavailable=1")
        return "", ""

    group_id = str(getattr(event, "group_id", "") or "")
    trust_env = getattr(bili_config, "analysis_trust_env", False)
    max_chars = int(getattr(config, "codex_chat_bilibili_context_max_chars", 1200) or 1200)

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/116.0.0.0 Safari/537.36 Edg/116.0.1938.69"
        )
    }

    try:
        async with ClientSession(trust_env=trust_env, headers=headers) as session:
            text = raw_text

            if re.search(r"(b23\.tv)|(bili(22|23|33|2233)\.cn)", text, re.I):
                text = await b23_extract(text, session=session)

            msg = await bili_keyword(group_id, text, session=session)

    except Exception:
        logger.warning("codex_chat context_extract source=bilibili success=0", exc_info=True)
        return "", ""

    if not msg:
        logger.info("codex_chat context_extract source=bilibili empty_msg=1")
        return "", ""

    if isinstance(msg, str):
        logger.info(
            f"codex_chat context_extract source=bilibili msg_is_str=1 msg={msg[:120]!r}"
        )
        return "", ""

    lines = _flatten_bili_msg(msg)
    logger.info(
        f"codex_chat context_extract source=bilibili raw_type={type(msg).__name__} "
        f"lines_count={len(lines)}"
    )

    text = _unique_join(lines, max_chars)

    if not text:
        logger.info("codex_chat context_extract source=bilibili empty_text=1")
        return "", ""

    prompt = f"Bilibili 视频解析摘要：\n{text}"
    return text, prompt

def _clip(text: str, max_chars: int) -> str:
    text = str(text or "").strip()
    if max_chars <= 0:
        return ""
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "..."


def _clean_text(text: Any) -> str:
    if text is None:
        return ""
    s = str(text).strip()
    if not s:
        return ""
    # 过滤明显没用的大 URL
    if s.startswith(("http://", "https://")) and len(s) > 80:
        return ""
    return s


def _extract_text_from_message_content(obj: Any, depth: int = 0) -> list[str]:
    if depth > 5:
        return []

    result: list[str] = []

    if obj is None:
        return result

    if isinstance(obj, str):
        text = _clean_text(obj)
        if text:
            result.append(text)
        return result

    if isinstance(obj, list):
        for item in obj:
            result.extend(_extract_text_from_message_content(item, depth + 1))
        return result

    if isinstance(obj, dict):
        seg_type = obj.get("type")
        data = obj.get("data")

        # OneBot message segment: {"type": "text", "data": {"text": "..."}}
        if seg_type == "text" and isinstance(data, dict):
            text = _clean_text(data.get("text"))
            if text:
                result.append(text)
            return result

        # forward node: content / message
        for key in ("messages", "nodes", "content", "message", "text"):
            if key in obj:
                result.extend(_extract_text_from_message_content(obj.get(key), depth + 1))

        # sender name
        sender = obj.get("sender")
        if isinstance(sender, dict):
            name = _clean_text(sender.get("nickname") or sender.get("name"))
            if name:
                # 不单独作为触发文本，只用于 prompt 可读性；这里先不加也可以
                pass

        # 兜底提取 data 中的 text/title/desc
        if isinstance(data, dict):
            for key in ("content", "message", "text", "title", "desc", "summary", "prompt"):
                if key not in data:
                    continue
                value = data.get(key)
                if isinstance(value, (dict, list)):
                    result.extend(_extract_text_from_message_content(value, depth + 1))
                else:
                    text = _clean_text(value)
                    if text:
                        result.append(text)

        return result

    return result


def _extract_json_strings(obj: Any, depth: int = 0, max_items: int = 40) -> list[str]:
    if depth > 5 or max_items <= 0:
        return []

    result: list[str] = []

    if obj is None:
        return result

    if isinstance(obj, str):
        text = _clean_text(obj)
        if text and len(text) <= 300:
            result.append(text)
        return result[:max_items]

    if isinstance(obj, list):
        for item in obj[:20]:
            result.extend(_extract_json_strings(item, depth + 1, max_items - len(result)))
            if len(result) >= max_items:
                break
        return result[:max_items]

    if isinstance(obj, dict):
        for key, value in obj.items():
            key_s = str(key).lower()

            if key_s in _INTERESTING_JSON_KEYS:
                if isinstance(value, (str, int, float)):
                    text = _clean_text(value)
                    if text:
                        result.append(text)
                else:
                    result.extend(_extract_json_strings(value, depth + 1, max_items - len(result)))

            elif isinstance(value, (dict, list)):
                result.extend(_extract_json_strings(value, depth + 1, max_items - len(result)))

            if len(result) >= max_items:
                break

        return result[:max_items]

    return result


def _unique_join(lines: list[str], max_chars: int) -> str:
    seen = set()
    out: list[str] = []

    for line in lines:
        line = _clean_text(line)
        if not line or line in seen:
            continue
        seen.add(line)
        out.append(line)

    return _clip("\n".join(out), max_chars)


async def _extract_forward_context(bot: Bot, event: GroupMessageEvent, config) -> tuple[str, str]:
    if not getattr(config, "codex_chat_extract_forward_context", True):
        return "", ""

    max_chars = int(getattr(config, "codex_chat_forward_context_max_chars", 1500) or 1500)
    all_lines: list[str] = []

    for seg in event.message:
        if getattr(seg, "type", "") != "forward":
            continue

        forward_id = seg.data.get("id")
        if not forward_id:
            continue

        try:
            data = await bot.get_forward_msg(id=forward_id)
        except Exception:
            logger.warning("codex_chat context_extract source=forward success=0")
            continue

        lines = _extract_text_from_message_content(data)
        all_lines.extend(lines)

    text = _unique_join(all_lines, max_chars)
    if not text:
        return "", ""

    prompt = f"合并/搬运消息摘要：\n{text}"
    return text, prompt


async def _extract_json_context(event: GroupMessageEvent, config) -> tuple[str, str]:
    if not getattr(config, "codex_chat_extract_json_context", True):
        return "", ""

    max_chars = int(getattr(config, "codex_chat_json_context_max_chars", 1000) or 1000)
    all_lines: list[str] = []

    for seg in event.message:
        if getattr(seg, "type", "") != "json":
            continue

        raw = seg.data.get("data")
        if not raw:
            continue

        try:
            obj = json.loads(raw) if isinstance(raw, str) else raw
        except Exception:
            logger.warning("codex_chat context_extract source=json parse=0")
            continue

        all_lines.extend(_extract_json_strings(obj))

    text = _unique_join(all_lines, max_chars)
    if not text:
        return "", ""

    prompt = f"JSON/卡片分享摘要：\n{text}"
    return text, prompt


async def extract_message_context(bot: Bot, event: GroupMessageEvent, config) -> dict:
    if not getattr(config, "codex_chat_extract_message_context", True):
        return {"text": "", "prompt": "", "sources": []}

    if not isinstance(event, GroupMessageEvent):
        return {"text": "", "prompt": "", "sources": []}

    # 避免 bot 自己消息造成循环
    try:
        if int(event.user_id) == int(bot.self_id):
            return {"text": "", "prompt": "", "sources": []}
    except Exception:
        pass

    texts: list[str] = []
    prompts: list[str] = []
    sources: list[str] = []

    forward_text, forward_prompt = await _extract_forward_context(bot, event, config)
    if forward_text:
        texts.append(forward_text)
        prompts.append(forward_prompt)
        sources.append("forward")

    json_text, json_prompt = await _extract_json_context(event, config)
    if json_text:
        texts.append(json_text)
        prompts.append(json_prompt)
        sources.append("json")

    bili_text, bili_prompt = await _extract_bilibili_context(event, config)
    if bili_text:
        texts.append(bili_text)
        prompts.append(bili_prompt)
        sources.append("bilibili")

    return {
        "text": "\n".join(x for x in texts if x).strip(),
        "prompt": "\n\n".join(x for x in prompts if x).strip(),
        "sources": sources,
    }
