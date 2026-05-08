from __future__ import annotations

from dataclasses import dataclass
import re


@dataclass
class ToolIntent:
    kind: str
    subject: str
    time_hint: str
    query_terms: str
    needs_reliable_context: bool
    needs_web: bool
    needs_time: bool
    needs_freshness: bool
    freshness_days: int | None
    prefer_official: bool
    allow_db_shortcut: bool
    query: str
    reason: str


def _normalize(text: str) -> str:
    return (text or "").strip().lower()


def _detect_subject(text: str) -> str:
    if any(k in text for k in ["我", "我自己", "本人"]):
        return "self"
    if any(k in text for k in ["群里", "大家", "有人", "谁"]):
        return "group"
    if "@" in text:
        return "mentioned_user"
    if any(k in text for k in ["某某", "群友", "他", "她", "那个人", "面包"]):
        return "named_user"
    return "unknown"


def _detect_time_hint(text: str) -> str:
    if any(k in text for k in ["刚才", "刚刚", "之前", "上次", "最近"]):
        return "recent"
    if any(k in text for k in ["今天", "今日"]):
        return "today"
    if "昨天" in text:
        return "yesterday"
    if any(k in text for k in ["今年", "当前年份", "现在是哪年"]):
        return "current_year"
    if any(k in text for k in ["现在几点", "当前时间"]):
        return "current_time"
    return "none"


def classify_tool_intent(prompt: str) -> ToolIntent:
    text = _normalize(prompt)
    subject = _detect_subject(text)
    time_hint = _detect_time_hint(text)
    en_tokens = re.findall(r"[a-z][a-z0-9_.-]*", text)
    query_terms = " ".join(sorted(set(en_tokens)))[:200]

    creative = (
        (any(k in text for k in ["写", "编", "生成", "起名", "取名", "讲"]) and any(k in text for k in ["笑话", "段子", "故事", "文案", "诗", "台词", "名字"]))
        or any(k in text for k in ["安慰我", "陪我聊", "聊聊", "角色扮演", "闲聊"])
    )
    if creative:
        return ToolIntent(
            kind="creative",
            subject=subject,
            time_hint=time_hint,
            query_terms=query_terms,
            needs_reliable_context=False,
            needs_web=False,
            needs_time=False,
            needs_freshness=False,
            freshness_days=None,
            prefer_official=False,
            allow_db_shortcut=False,
            query=prompt,
            reason="creative_markers",
        )

    if any(k in text for k in ["今年是哪年", "现在是哪年", "当前年份", "今天日期", "今天几号", "今天星期几", "现在几点", "当前时间"]):
        return ToolIntent(
            kind="time",
            subject=subject,
            time_hint=time_hint if time_hint != "none" else "current_year",
            query_terms=query_terms,
            needs_reliable_context=True,
            needs_web=False,
            needs_time=True,
            needs_freshness=False,
            freshness_days=None,
            prefer_official=False,
            allow_db_shortcut=False,
            query=prompt,
            reason="time_markers",
        )

    current_fact_markers = [
        "最新", "当前", "现在", "官方", "目前", "多少钱", "价格", "售价",
        "发布", "发售", "上线", "更新", "维护", "停服", "开服",
        "参数", "配置", "规格", "显存", "内存", "系列", "属于什么系列", "支持",
    ]
    if any(k in text for k in current_fact_markers):
        prefer_official_markers = ["官方", "官方最新", "chatgpt", "openai", "gemini", "google", "claude", "anthropic", "最新模型", "最新版本"]
        prefer_official = any(k in text for k in prefer_official_markers)
        freshness_days = 90 if prefer_official else 180
        return ToolIntent(
            kind="current_fact",
            subject=subject,
            time_hint=time_hint,
            query_terms=query_terms,
            needs_reliable_context=True,
            needs_web=True,
            needs_time=True,
            needs_freshness=True,
            freshness_days=freshness_days,
            prefer_official=prefer_official,
            allow_db_shortcut=False,
            query=prompt,
            reason="current_fact_markers",
        )

    local_markers = ["说", "说了", "说过", "讲", "提到", "聊", "测", "发", "问", "叫", "是谁", "什么"]
    identity_markers = ["我是谁", "我叫什么", "在群里叫什么", "你知道我", "谁是", "叫什么"]
    local_context = (
        (time_hint in {"recent", "today", "yesterday"} and any(k in text for k in local_markers))
        or any(k in text for k in identity_markers)
        or (
            subject in {"group", "named_user", "mentioned_user"}
            and any(k in text for k in ["刚才", "今天", "之前", "说了什么", "提到什么", "聊过什么", "怎么样"])
        )
    )
    if local_context:
        return ToolIntent(
            kind="local_context",
            subject=subject,
            time_hint=time_hint,
            query_terms=query_terms,
            needs_reliable_context=True,
            needs_web=False,
            needs_time=False,
            needs_freshness=False,
            freshness_days=None,
            prefer_official=False,
            allow_db_shortcut=True,
            query=prompt,
            reason="local_context_markers",
        )

    return ToolIntent(
        kind="static_or_unknown",
        subject=subject,
        time_hint=time_hint,
        query_terms=query_terms,
        needs_reliable_context=False,
        needs_web=False,
        needs_time=False,
        needs_freshness=False,
        freshness_days=None,
        prefer_official=False,
        allow_db_shortcut=True,
        query=prompt,
        reason="default",
    )
