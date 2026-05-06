from __future__ import annotations

import re


_RECENT_CONTEXT_MARKERS = [
    "刚才",
    "刚刚",
    "之前",
    "我说",
    "我刚才",
    "我们刚才",
    "记得",
    "在测什么",
]

_QUERY_MARKERS = [
    "吗",
    "？",
    "?",
    "什么",
    "多少",
    "多少钱",
    "价格",
    "参数",
    "配置",
    "规格",
    "显存",
    "内存",
    "多大",
    "几g",
    "几gb",
    "存在",
    "有吗",
    "发布",
    "发售",
    "什么时候",
    "哪年",
    "最新",
    "现在",
    "当前",
    "属于",
    "系列",
    "支持",
    "区别",
    "对比",
    "哪个更强",
    "是真的吗",
    "多少显存",
    "多少内存",
]

_QUESTION_RE = re.compile(r"[?？]|吗|什么|多少|价格|参数|配置|规格|显存|内存|发布|发售|最新|现在|当前|属于|系列|支持|区别|对比|更强|是真的吗")
_ENTITY_RE = re.compile(r"([a-z]+[0-9][a-z0-9.\-]*|[0-9]+(?:\.[0-9]+)+[a-z]{0,3})", re.I)

_EXTERNAL_FACT_MARKERS = [
    "更新",
    "今天更新",
    "维护",
    "停服",
    "开服",
    "最新",
    "现在",
    "当前",
    "多少钱",
    "价格",
    "发布",
    "发售",
    "什么时候",
    "哪年",
    "参数",
    "配置",
    "规格",
    "显存",
    "属于什么系列",
    "是真的吗",
]


def _looks_like_recent_context(prompt: str) -> bool:
    text = (prompt or "").strip()
    return any(marker in text for marker in _RECENT_CONTEXT_MARKERS)


def _looks_like_query(prompt: str) -> bool:
    text = (prompt or "").strip()
    return bool(_QUESTION_RE.search(text)) or any(marker in text for marker in _QUERY_MARKERS)


def _has_entity(prompt: str) -> bool:
    text = (prompt or "").strip()
    return bool(_ENTITY_RE.search(text))


def _looks_like_external_fact(prompt: str) -> bool:
    text = (prompt or "").strip()
    return any(marker in text for marker in _EXTERNAL_FACT_MARKERS)


def _build_query(prompt: str) -> str:
    text = (prompt or "").strip()
    if not text:
        return ""
    if re.search(r"[a-z]+[0-9]", text, re.I):
        return f"{text} official"
    return text


def should_use_web_tool(prompt: str) -> dict | None:
    text = (prompt or "").strip()
    if not text:
        return None
    if _looks_like_recent_context(text):
        return None
    if not _looks_like_query(text):
        return None
    if not (_has_entity(text) or _looks_like_external_fact(text)):
        return None

    lowered = text.lower()
    if any(token in lowered for token in ["多少钱", "价格", "售价"]):
        reason = "price"
    elif any(token in lowered for token in ["哪个更强", "对比", "区别"]):
        reason = "comparison"
    elif any(token in lowered for token in ["是什么", "属于", "系列", "参数", "配置", "规格", "显存", "内存", "多大", "几g", "几gb", "支持"]):
        reason = "product_spec"
    elif any(token in lowered for token in ["发布", "发售", "什么时候", "哪年", "最新", "现在", "当前", "存在", "有吗"]):
        reason = "current_fact"
    else:
        reason = "definition"

    return {"reason": reason, "query": _build_query(text)}
