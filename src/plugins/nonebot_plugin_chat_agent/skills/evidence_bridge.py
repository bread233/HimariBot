from __future__ import annotations

from urllib.parse import quote
import re


_URL_PATTERN = re.compile(r"https?://[^\s)>\]\"']+")
_CJK_LOCATION_PATTERN = re.compile(
    r"(?:查一下|查下|查询|看看|看下|帮我查一下|帮我查下|请查一下|请查下|请问|想查一下)?\s*"
    r"([\u4e00-\u9fff]{2,20})\s*(?:的)?\s*天气"
)
_EN_IN_PATTERN = re.compile(r"\bweather\s+in\s+([a-zA-Z][a-zA-Z\s\-]{1,40})\b", re.IGNORECASE)
_EN_POST_PATTERN = re.compile(r"\b([a-zA-Z][a-zA-Z\s\-]{1,40})\s+weather\b", re.IGNORECASE)


def extract_urls_from_skill_body(body: str) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for m in _URL_PATTERN.findall(str(body or "")):
        u = m.strip().rstrip(".,;，。；")
        if not u or u in seen:
            continue
        seen.add(u)
        out.append(u)
    return out


def _domain(url: str) -> str:
    text = str(url or "").lower()
    m = re.match(r"https?://([^/]+)", text)
    return m.group(1) if m else ""


def select_news_source_urls(skill, prompt: str, max_sources: int = 1) -> list[str]:
    urls = extract_urls_from_skill_body(getattr(skill, "body", ""))
    if not urls:
        return []
    q = str(prompt or "").lower()
    max_count = max(1, int(max_sources or 1))
    topic_pref = []
    if any(k in q for k in ["科技", "science", "tech"]):
        topic_pref = ["stdaily.com"]
    elif any(k in q for k in ["体育", "sport", "比赛"]):
        topic_pref = ["sports.cctv.com"]
    elif any(k in q for k in ["娱乐", "明星", "电影", "综艺", "entertainment"]):
        topic_pref = ["ent.sina.com.cn"]
    elif any(k in q for k in ["财经", "经济", "finance", "business"]):
        topic_pref = ["ce.cn"]
    elif any(k in q for k in ["国际", "world", "global"]):
        topic_pref = ["chinanews.com", "cgtn.com"]

    default_pref = [
        "xinhuanet.com",
        "people.com.cn",
        "ce.cn",
        "chinanews.com",
        "cgtn.com",
        "stdaily.com",
        "sports.cctv.com",
        "ent.sina.com.cn",
    ]
    pref = topic_pref + [d for d in default_pref if d not in topic_pref]

    ranked = sorted(
        urls,
        key=lambda u: next((i for i, dom in enumerate(pref) if dom in _domain(u)), 10_000),
    )
    return ranked[:max_count]


def extract_weather_location(prompt: str) -> str | None:
    text = str(prompt or "").strip()
    if not text:
        return None
    m = _CJK_LOCATION_PATTERN.search(text)
    if m:
        loc = (m.group(1) or "").strip()
        if loc and loc not in {
            "今天",
            "明天",
            "后天",
            "现在",
            "帮我查一下",
            "帮我查下",
            "查一下",
            "查下",
            "查询",
            "看看",
            "看下",
            "请查一下",
            "请查下",
        }:
            return loc
    m = _EN_IN_PATTERN.search(text)
    if m:
        return (m.group(1) or "").strip()
    m = _EN_POST_PATTERN.search(text)
    if m:
        return (m.group(1) or "").strip()
    return None


def build_weather_url(location: str) -> str:
    loc = quote(str(location or "").strip())
    return f"https://wttr.in/{loc}?format=3"


async def build_skill_evidence_context(skill, prompt: str, config, read_url_func) -> tuple[str, list[str]]:
    name = str(getattr(skill, "name", "") or "").strip().lower()
    notes: list[str] = []
    if name == "news":
        max_sources = int(getattr(config, "chat_agent_news_skill_max_sources", 1) or 1)
        max_chars = int(getattr(config, "chat_agent_news_skill_read_max_chars", 6000) or 6000)
        urls = select_news_source_urls(skill, prompt, max_sources=max_sources)
        if not urls:
            notes.append("skill_evidence_bridge name=news used=1 source_count=0")
            return "新闻技能已命中，但当前技能说明中没有可用来源链接。", notes
        url = urls[0]
        try:
            text = await read_url_func(config, url)
            payload = str(text or "").strip()
            if max_chars > 0 and len(payload) > max_chars:
                payload = payload[:max_chars]
            notes.append("skill_evidence_bridge name=news used=1 source_count=1")
            return f"[Skill Evidence: news]\nSource: {url}\n{payload}".strip(), notes
        except Exception as e:
            notes.append("skill_evidence_bridge name=news used=1 source_count=1 read_error=1")
            return f"[Skill Evidence: news]\nSource: {url}\n来源读取失败：{str(e)[:120]}", notes
    if name == "weather":
        max_chars = int(getattr(config, "chat_agent_weather_skill_read_max_chars", 1200) or 1200)
        loc = extract_weather_location(prompt)
        if not loc:
            notes.append("skill_evidence_bridge name=weather used=1 need_location=1")
            return "要查询天气请先提供城市或地区，例如：东京天气 / weather in Tokyo。", notes
        url = build_weather_url(loc)
        try:
            text = await read_url_func(config, url)
            payload = str(text or "").strip()
            if max_chars > 0 and len(payload) > max_chars:
                payload = payload[:max_chars]
            notes.append("skill_evidence_bridge name=weather used=1 source_count=1")
            return f"[Skill Evidence: weather]\nSource: {url}\n{payload}".strip(), notes
        except Exception as e:
            notes.append("skill_evidence_bridge name=weather used=1 source_count=1 read_error=1")
            return f"[Skill Evidence: weather]\nSource: {url}\n来源读取失败：{str(e)[:120]}", notes
    return "", notes
