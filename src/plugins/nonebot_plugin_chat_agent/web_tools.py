from __future__ import annotations

import re
from urllib.parse import parse_qs, unquote, urlparse

import httpx
from bs4 import BeautifulSoup


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


def _rank_result(item: dict, query: str) -> tuple[int, int]:
    url = str(item.get("url", "")).lower()
    title = str(item.get("title", "")).lower()
    q = str(query or "").lower()
    if "nvidia" in q or "rtx" in q or "geforce" in q or "英伟达" in q:
        if "nvidia.com" in url:
            return (0, 0)
        if "amd.com" in url or "intel.com" in url:
            return (1, 0)
        if "wikipedia.org" in url or "baike.baidu.com" in url:
            return (2, 0)
        if any(token in url for token in ["tom.", "zol.", "ithome.", "pcpop.", "mydrivers.", "baidu.com"]):
            return (4, 0)
        return (3, 0)
    if "wikipedia.org" in url or "baike.baidu.com" in url:
        return (1, 0)
    if "nvidia.com" in url:
        return (0, 0)
    if any(token in url for token in ["tom.", "zol.", "ithome.", "pcpop.", "mydrivers.", "baidu.com"]):
        return (3, 0)
    if title:
        return (2, 0)
    return (4, 0)


async def search_web(config, query: str) -> list[dict]:
    provider = str(getattr(config, "chat_agent_search_provider", "duckduckgo")).strip().lower()
    max_results = max(0, int(getattr(config, "chat_agent_web_max_results", 3)))
    timeout = int(getattr(config, "chat_agent_web_timeout", 15))
    user_agent = str(getattr(config, "chat_agent_web_user_agent", "Mozilla/5.0 HimariBot/1.0"))
    headers = {"User-Agent": user_agent}

    async def _duckduckgo() -> list[dict]:
        try:
            async with httpx.AsyncClient(timeout=timeout, headers=headers, follow_redirects=True) as client:
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
            async with httpx.AsyncClient(timeout=timeout, headers=headers, follow_redirects=True) as client:
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

    if provider == "searxng":
        return await _searxng()
    return await _duckduckgo()


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
        async with httpx.AsyncClient(timeout=timeout, headers=headers, follow_redirects=True) as client:
            resp = await client.get(url)
            resp.raise_for_status()
    except httpx.HTTPError:
        return None

    soup = BeautifulSoup(resp.text, "lxml")
    for tag in soup(["script", "style", "nav", "footer", "header"]):
        tag.decompose()
    title = _clean_text(soup.title.get_text(" ", strip=True)) if soup.title else ""
    text = _clean_text(soup.get_text(" ", strip=True))
    if not text:
        return None
    max_chars = max(0, int(getattr(config, "chat_agent_web_read_max_chars", 6000)))
    if max_chars and len(text) > max_chars:
        text = text[:max_chars].rstrip()
    return {"url": url, "title": title, "text": text}


async def build_web_context(config, query: str) -> str:
    try:
        results = await search_web(config, query)
    except Exception:
        return ""
    if not results:
        return ""

    max_results = max(1, int(getattr(config, "chat_agent_web_max_results", 3)))
    total_limit = max(0, int(getattr(config, "chat_agent_web_read_max_chars", 6000)))
    per_item_limit = max(200, total_limit // max_results) if total_limit else 0
    lines = ["联网查询结果："]
    total_len = len(lines[0]) + 1
    count = 0
    for idx, item in enumerate(results[:max_results], 1):
        if total_limit and total_len >= total_limit:
            break
        title = _clean_text(item.get("title", ""))
        url = _clean_text(item.get("url", ""))
        snippet = _clean_text(item.get("snippet", ""))
        if not url:
            continue
        page = None
        try:
            page = await read_url(config, url)
        except Exception:
            page = None
        block_lines = [f"[{idx}] {title or url}", f"URL: {url}"]
        if snippet:
            block_lines.append(f"摘要: {snippet}")
        if page and page.get("text"):
            text = page.get("text", "")
            if per_item_limit and len(text) > per_item_limit:
                text = text[:per_item_limit].rstrip()
            block_lines.append(f"正文摘录: {text}")
        block_lines.append("")
        block = "\n".join(block_lines)
        if total_limit:
            remaining = max(0, total_limit - total_len)
            if remaining <= 0:
                break
            if len(block) > remaining:
                block = block[:remaining].rstrip()
        lines.append(block)
        total_len += len(block) + 1
        count += 1

    context = "\n".join(lines).strip()
    return context if context else ""
