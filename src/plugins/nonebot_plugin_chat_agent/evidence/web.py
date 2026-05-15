from __future__ import annotations

import re
from html import unescape
from urllib.parse import parse_qs, unquote, urlparse

import httpx
from bs4 import BeautifulSoup

from .source_quality import _extract_query_tokens, _rank_result, _source_preference_score

def _clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip()

def _normalize_duckduckgo_url(href: str) -> str:
    href = (href or "").strip()
    if not href:
        return ""
    if href.startswith("//"):
        return "https:" + href
    parsed = urlparse(href)
    if parsed.path == "/l/" or "uddg" in parsed.query:
        query = parse_qs(parsed.query)
        uddg = query.get("uddg", [""])[0]
        if uddg:
            return unquote(uddg)
    if href.startswith("/") and "uddg" not in parsed.query:
        return "https://duckduckgo.com" + href
    return href

def _clean_html_text(html_text: str) -> str:
    text = str(html_text or "")
    if not text:
        return ""
    text = re.sub(r"(?is)<(script|style|svg|img|picture|source|noscript)[^>]*>.*?</\1>", " ", text)
    text = re.sub(r"(?is)<(nav|header|footer|aside|form|button)[^>]*>.*?</\1>", " ", text)
    text = re.sub(r"!\[[^\]]*\]\([^)]+\)", " ", text)
    text = re.sub(r"(?is)<[^>]+>", " ", text)
    text = unescape(text)
    text = re.sub(r"https?://\S+\.(?:png|jpg|jpeg|webp|gif)\S*", " ", text, flags=re.I)
    text = re.sub(r"\b\S+\.(?:png|jpg|jpeg|webp|gif)\b", " ", text, flags=re.I)
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return ""
    dedup: list[str] = []
    seen: set[str] = set()
    for seg in re.split(r"(?<=[。！？!?])|\n", text):
        s = seg.strip()
        if not s:
            continue
        key = s[:80]
        if len(s) <= 24 and key in seen:
            continue
        seen.add(key)
        dedup.append(s)
    return " ".join(dedup).strip()

async def search_web(config, query: str) -> list[dict]:
    provider = str(getattr(config, "chat_agent_search_provider", "duckduckgo")).strip().lower()
    max_results = max(0, int(getattr(config, "chat_agent_web_max_results", 3)))
    timeout = int(getattr(config, "chat_agent_web_timeout", 15))
    user_agent = str(getattr(config, "chat_agent_web_user_agent", "Mozilla/5.0 HimariBot/1.0"))
    headers = {"User-Agent": user_agent}

    async def _duckduckgo() -> list[dict]:
        try:
            async with httpx.AsyncClient(timeout=timeout, headers=headers, follow_redirects=True, trust_env=False) as client:
                resp = await client.get("https://duckduckgo.com/html/", params={"q": query})
                resp.raise_for_status()
        except httpx.HTTPError:
            return []
        soup = BeautifulSoup(resp.text, "lxml")
        results = []
        for block in soup.select(".result")[:max_results]:
            link = block.select_one(".result__a")
            if not link:
                continue
            title = _clean_text(link.get_text(" ", strip=True))
            url = _normalize_duckduckgo_url(link.get("href") or "")
            snippet_node = block.select_one(".result__snippet")
            snippet = _clean_text(snippet_node.get_text(" ", strip=True)) if snippet_node else ""
            if not title or not url:
                continue
            results.append({"title": title, "url": url, "snippet": snippet})
        return sorted(results, key=lambda item: _rank_result(item, query))

    async def _searxng() -> list[dict]:
        base_url = str(getattr(config, "chat_agent_search_base_url", "")).strip()
        if not base_url:
            return []
        try:
            async with httpx.AsyncClient(timeout=timeout, headers=headers, follow_redirects=True, trust_env=False) as client:
                resp = await client.get(
                    f"{base_url.rstrip('/')}/search",
                    params={"q": query, "format": "json", "language": "zh-CN"},
                )
                resp.raise_for_status()
                data = resp.json()
        except (httpx.HTTPError, ValueError):
            return []
        results = []
        for item in data.get("results", [])[:max_results]:
            title = _clean_text(item.get("title", ""))
            url = item.get("url", "")
            snippet = _clean_text(item.get("content", "") or item.get("snippet", ""))
            if title and url:
                results.append({"title": title, "url": url, "snippet": snippet})
        return sorted(results, key=lambda item: _rank_result(item, query))

    raw_results = await (_searxng() if provider == "searxng" else _duckduckgo())
    if not raw_results:
        return []
    query_tokens = _extract_query_tokens(query)
    scored: list[tuple[int, float, dict]] = []
    for idx, item in enumerate(raw_results):
        url = str(item.get("url", ""))
        title = str(item.get("title", "")).lower()
        snippet = str(item.get("snippet", "")).lower()
        token_hit = any(token in title or token in snippet or token in url.lower() for token in query_tokens)
        score = _source_preference_score(url, query) + (0.05 if token_hit else 0.0)
        scored.append((idx, score, item))
    scored.sort(key=lambda x: (-x[1], x[0]))
    return [x[2] for x in scored]

async def read_url(config, url: str) -> dict | None:
    if not isinstance(url, str):
        return None
    url = url.strip()
    if not url.startswith(("http://", "https://")):
        return None
    timeout = int(getattr(config, "chat_agent_web_timeout", 15))
    user_agent = str(getattr(config, "chat_agent_web_user_agent", "Mozilla/5.0 HimariBot/1.0"))
    headers = {"User-Agent": user_agent}
    try:
        async with httpx.AsyncClient(timeout=timeout, headers=headers, follow_redirects=True, trust_env=False) as client:
            resp = await client.get(url)
            resp.raise_for_status()
    except httpx.HTTPError:
        return None

    soup = BeautifulSoup(resp.text, "lxml")
    for tag in soup(["script", "style", "nav", "footer", "header"]):
        tag.decompose()
    title = _clean_text(soup.title.get_text(" ", strip=True)) if soup.title else ""
    meta_description = ""
    meta = soup.find("meta", attrs={"name": "description"}) or soup.find("meta", attrs={"property": "og:description"})
    if meta:
        meta_description = _clean_text(meta.get("content", ""))
    text = _clean_html_text(str(soup))
    if not text:
        return None
    max_chars = max(0, int(getattr(config, "chat_agent_web_read_max_chars", 6000)))
    if max_chars and len(text) > max_chars:
        text = text[:max_chars].rstrip()
    return {"url": url, "title": title, "text": text, "meta_description": meta_description}
