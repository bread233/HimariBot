from __future__ import annotations

import re
import json
import os
from datetime import datetime
from html import unescape
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

import httpx
from bs4 import BeautifulSoup
from nonebot import logger

_WEB_QUALITY_RULES_CACHE: dict[str, dict] = {}
_WEB_QUALITY_RULES_DEFAULT_PATH = "data/nonebot_chat_agent/web_quality_rules.json"
_WEB_QUALITY_RULES_DEFAULT_TEMPLATE = {
    "version": 1,
    "low_quality_keywords_extra": [],
    "official_domains_extra": [],
    "sports_trusted_domains_extra": [],
    "sports_low_quality_keywords_extra": [],
    "software_mismatch_keywords_extra": [],
    "entity_rules": {
        "ruby": {
            "official_domains": ["ruby-lang.org"],
            "mismatch_keywords": ["rubymine", "jetbrains", "破解版", "下载站"],
            "low_quality_keywords": [],
        },
        "roco_world": {
            "official_domains": ["rocom.qq.com", "taptap.cn", "baike.baidu.com", "wikipedia.org"],
            "mismatch_keywords": [],
            "low_quality_keywords": ["爱游戏", "igame", "体育"],
        },
    },
}

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

def _is_sports_recent_query(query: str) -> bool:
    text = str(query or "").lower()
    if not text:
        return False
    sports_markers = [
        "nba", "cba", "lakers", "warriors", "thunder", "lebron", "james", "curry", "doncic",
        "詹姆斯", "勒布朗", "湖人", "勇士", "雷霆", "东契奇", "库里", "球员", "球队",
        "最近", "近况", "表现", "数据", "最近一场", "对阵", "得分", "篮板", "助攻", "命中率", "战绩", "赛程", "赛后",
    ]
    return any(x in text for x in sports_markers)

def _is_software_version_query(query: str) -> bool:
    text = str(query or "").lower().strip()
    if not text:
        return False
    version_markers = [
        "latest version", "stable version", "release notes", "current version",
        "最新版", "最新版本", "当前版本", "稳定版", "发布版本", "release", "version",
    ]
    software_markers = [
        "ruby", "node", "nodejs", "node.js", "python", "postgresql", "redis", "docker", "go", "rust",
    ]
    return any(v in text for v in version_markers) and any(s in text for s in software_markers)

def _is_game_definition_query(query: str) -> bool:
    text = str(query or "").lower().strip()
    if not text:
        return False
    return ("是什么" in text or "什么游戏" in text or "介绍" in text) and any(
        x in text for x in ["游戏", "world", "王国", "roco", "洛克", "taptap"]
    )

def _rewrite_web_query_hints(query: str) -> str:
    q = str(query or "").strip()
    if not q:
        return q
    low = q.lower()
    if _is_software_version_query(q):
        if "ruby" in low:
            return f"{q} Ruby latest stable release ruby-lang.org downloads releases"
        return f"{q} latest stable release official release notes downloads"
    if _is_game_definition_query(q):
        return f"{q} 官方 TapTap 百科 wikipedia"
    return q

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

def _split_text_chunks(text: str, chunk_size: int = 600, overlap: int = 80) -> list[str]:
    text = _clean_text(text)
    if not text:
        return []
    parts = [p.strip() for p in re.split(r"(?<=[。！？!?])|\n+", text) if p.strip()]
    chunks: list[str] = []
    current = ""
    for part in parts:
        if len(current) + len(part) + 1 <= chunk_size:
            current = f"{current} {part}".strip() if current else part
            continue
        if current:
            chunks.append(current)
            tail = current[-overlap:] if overlap > 0 else ""
            current = f"{tail} {part}".strip() if tail else part
        else:
            chunks.append(part[:chunk_size].strip())
            current = part[chunk_size - overlap :].strip() if len(part) > chunk_size else ""
    if current:
        chunks.append(current)
    uniq: list[str] = []
    seen: set[str] = set()
    for c in chunks:
        key = c[:200]
        if key in seen:
            continue
        seen.add(key)
        uniq.append(c)
        if len(uniq) >= 8:
            break
    return uniq

async def _rank_web_chunks(config, query: str, chunks: list[dict]) -> list[dict]:
    if not chunks:
        return []
    query_text = f"为这个问题检索最相关的网页资料：{query}"
    docs = [f"网页资料：标题：{c.get('title','')}\nURL：{c.get('url','')}\n内容：{c.get('content','')}" for c in chunks]
    try:
        from .embedding_client import cosine_similarity, embed_texts

        vectors = await embed_texts(config, [query_text] + docs)
        query_vector = vectors[0]
        ranked = []
        for idx, item in enumerate(chunks):
            score = cosine_similarity(query_vector, vectors[idx + 1])
            weighted = score + float(item.get("source_score", 0.0))
            row = dict(item)
            row["score"] = score
            row["weighted_score"] = weighted
            ranked.append(row)
        ranked.sort(key=lambda x: x.get("weighted_score", 0.0), reverse=True)
        filtered = [x for x in ranked if float(x.get("score", 0.0)) >= 0.45][:4]
        if filtered:
            return filtered
        if ranked:
            ranked[0]["web_low_confidence"] = True
            return ranked[:1]
        return []
    except Exception:
        fallback = [dict(item) for item in chunks]
        for row in fallback:
            row["score"] = 0.0
            row["weighted_score"] = float(row.get("source_score", 0.0))
        fallback.sort(key=lambda x: x.get("weighted_score", 0.0), reverse=True)
        return fallback[:4]

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

from .evidence.official import (
    OFFICIAL_WEB_RESOLVERS as OFFICIAL_WEB_RESOLVERS,
    _resolver_pattern_hit as _resolver_pattern_hit,
    get_nodejs_latest_version as get_nodejs_latest_version,
    get_ruby_latest_version as get_ruby_latest_version,
    resolve_official_web_answer as resolve_official_web_answer,
)

from .evidence.source_quality import (
    _get_web_quality_rules_path as _get_web_quality_rules_path,
    _normalize_rule_list as _normalize_rule_list,
    _normalize_domain_list as _normalize_domain_list,
    _bootstrap_web_quality_rules_file as _bootstrap_web_quality_rules_file,
    _load_web_quality_rules as _load_web_quality_rules,
    _rank_result as _rank_result,
    _extract_query_tokens as _extract_query_tokens,
    _source_preference_score as _source_preference_score,
    _generic_source_quality_adjustment as _generic_source_quality_adjustment,
    _sports_source_adjustment as _sports_source_adjustment,
    _extract_domain as _extract_domain,
    _extract_years as _extract_years,
    _is_current_sensitive_query as _is_current_sensitive_query,
    _freshness_score as _freshness_score,
    _authority_score as _authority_score,
    _source_flags as _source_flags,
)

async def build_web_results(config, query: str, intent_kind: str | None = None) -> list[dict]:
    try:
        query_for_search = _rewrite_web_query_hints(query)
        results = await search_web(config, query_for_search)
    except Exception:
        return []
    if not results:
        return []
    max_results = max(1, int(getattr(config, "chat_agent_web_max_results", 3)))
    snippet_max = int(getattr(config, "chat_agent_web_snippet_max_chars", 260))
    excerpt_max = int(getattr(config, "chat_agent_web_excerpt_max_chars", 400))
    current_sensitive = _is_current_sensitive_query(query, intent_kind=intent_kind)
    sports_recent_query = _is_sports_recent_query(query)
    software_version_query = _is_software_version_query(query)
    sports_source_boost_count = 0
    sports_low_quality_penalty_count = 0
    official_source_boost_count = 0
    generic_low_quality_penalty_count = 0
    entity_mismatch_penalty_count = 0
    rows: list[dict] = []
    for idx, item in enumerate(results[:max_results]):
        title = _clean_text(item.get("title", ""))
        url = _clean_text(item.get("url", ""))
        snippet = _clean_text(item.get("snippet", ""))
        if snippet_max > 0 and len(snippet) > snippet_max:
            snippet = snippet[:snippet_max].rstrip()
        page = None
        if url:
            try:
                page = await read_url(config, url)
            except Exception:
                page = None
        excerpt = ""
        if page:
            excerpt = _clean_text(f"{page.get('meta_description', '')} {page.get('text', '')}")
            if excerpt_max > 0 and len(excerpt) > excerpt_max:
                excerpt = excerpt[:excerpt_max].rstrip()
        score = float(item.get("score", 0.0) or 0.0)
        weighted_score = float(item.get("weighted_score", 0.0) or 0.0)
        if weighted_score == 0.0 and url:
            weighted_score = float(_source_preference_score(url, query))
        domain = _extract_domain(url)
        temp_item = {
            "title": title,
            "url": url,
            "domain": domain,
            "snippet": snippet,
            "excerpt": excerpt,
        }
        merged = " ".join([title, snippet, excerpt, url])
        extracted_years = _extract_years(merged)
        freshness = _freshness_score(temp_item, query, current_sensitive=current_sensitive)
        authority = _authority_score(temp_item, query, current_sensitive=current_sensitive)
        flags = _source_flags(temp_item, query, current_sensitive=current_sensitive)
        web_rank_score = float(weighted_score) + float(freshness) + float(authority)
        generic_adjust, official_boosted, generic_penalized, entity_mismatch_penalized = _generic_source_quality_adjustment(
            url, title, snippet, query, config=config
        )
        web_rank_score += float(generic_adjust)
        if official_boosted:
            official_source_boost_count += 1
        if generic_penalized:
            generic_low_quality_penalty_count += 1
        if entity_mismatch_penalized:
            entity_mismatch_penalty_count += 1
        sports_adjust = 0.0
        if sports_recent_query:
            sports_adjust, boosted, penalized = _sports_source_adjustment(url, title, snippet, config=config)
            web_rank_score += float(sports_adjust)
            if boosted:
                sports_source_boost_count += 1
            if penalized:
                sports_low_quality_penalty_count += 1
        if current_sensitive and ("official" in flags or "docs" in flags):
            web_rank_score += 0.05
        rows.append(
            {
                "title": title,
                "url": url,
                "domain": domain,
                "snippet": snippet,
                "excerpt": excerpt,
                "score": score,
                "weighted_score": weighted_score,
                "freshness_score": float(freshness),
                "authority_score": float(authority),
                "web_rank_score": float(web_rank_score),
                "source_flags": flags,
                "extracted_years": extracted_years,
                "sports_recent_query": 1 if sports_recent_query else 0,
                "sports_adjust": float(sports_adjust),
                "software_version_query": 1 if software_version_query else 0,
                "generic_adjust": float(generic_adjust),
                "_idx": idx,
            }
        )
    rows.sort(key=lambda r: (-float(r.get("web_rank_score", 0.0)), int(r.get("_idx", 0))))
    for r in rows:
        r.pop("_idx", None)
    if sports_recent_query:
        logger.info(
            f"web_results sports_recent_query=1 sports_source_boost_count={sports_source_boost_count} "
            f"sports_low_quality_penalty_count={sports_low_quality_penalty_count}"
        )
    if software_version_query:
        logger.info("web_results software_version_query=1")
    logger.info(
        f"web_results official_source_boost_count={official_source_boost_count} "
        f"generic_low_quality_penalty_count={generic_low_quality_penalty_count} "
        f"entity_mismatch_penalty_count={entity_mismatch_penalty_count}"
    )
    return rows

def render_web_results_context(results: list[dict], *, max_items: int = 3) -> str:
    if not results:
        return ""
    total_limit = 2500
    lines = ["Web result candidates:"]
    for i, row in enumerate(results[:max_items], 1):
        title = _clean_text(row.get("title", ""))
        url = _clean_text(row.get("url", ""))
        domain = _clean_text(row.get("domain", ""))
        snippet = _clean_text(row.get("snippet", ""))
        excerpt = _clean_text(row.get("excerpt", ""))
        if len(snippet) > 220:
            snippet = snippet[:220].rstrip()
        if len(excerpt) > 450:
            excerpt = excerpt[:450].rstrip()
        web_rank_score = float(row.get("web_rank_score", 0.0) or row.get("weighted_score", 0.0) or row.get("score", 0.0) or 0.0)
        freshness = float(row.get("freshness_score", 0.0) or 0.0)
        authority = float(row.get("authority_score", 0.0) or 0.0)
        years = row.get("extracted_years") or []
        flags = row.get("source_flags") or []
        lines.extend(
            [
                f"[{i}] {title or url}",
                f"Domain: {domain or 'unknown'}",
                f"URL: {url}",
                f"Rank: {web_rank_score:.3f}",
                f"Freshness: {freshness:.3f}",
                f"Authority: {authority:.3f}",
                f"Years: {','.join(str(y) for y in years) if years else ''}",
                f"Flags: {','.join(str(f) for f in flags) if flags else ''}",
                f"Snippet: {snippet}",
                f"Excerpt: {excerpt}",
                "",
            ]
        )
        if sum(len(x) + 1 for x in lines) > total_limit:
            break
    out = "\n".join(lines).strip()
    if len(out) > total_limit:
        return out[:total_limit].rstrip()
    return out

async def build_web_context(config, query: str) -> str:
    structured = await build_web_results(config, query, intent_kind=None)
    if structured:
        return render_web_results_context(structured, max_items=max(1, int(getattr(config, "chat_agent_web_max_results", 3))))
    try:
        results = await search_web(config, query)
    except Exception:
        return ""
    if not results:
        return ""

    max_results = max(1, int(getattr(config, "chat_agent_web_max_results", 3)))
    total_limit = max(0, int(getattr(config, "chat_agent_web_read_max_chars", 6000)))
    lines = ["以下是实时网页检索资料。请优先基于这些资料回答；如果资料不足，请说明资料不足，不要说“截至我知识更新”。"]
    chunks: list[dict] = []

    for item in results[:max_results]:
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
        merged = ""
        if snippet:
            merged += snippet + " "
        if page and page.get("meta_description"):
            merged += str(page.get("meta_description", "")) + " "
        if page and page.get("text"):
            merged += str(page.get("text", ""))
        merged = _clean_text(merged)
        page_chunks = _split_text_chunks(merged, chunk_size=600, overlap=80)
        if not page_chunks and merged:
            page_chunks = [merged[:600]]
        source_score = _source_preference_score(url, query)
        for chunk in page_chunks[:3]:
            chunks.append({"title": title or url, "url": url, "content": chunk, "source_score": source_score})

    ranked_chunks = await _rank_web_chunks(config, query, chunks)
    if not ranked_chunks:
        return ""

    total_len = sum(len(line) + 1 for line in lines)
    for idx, item in enumerate(ranked_chunks, 1):
        title = _clean_text(item.get("title", ""))
        url = _clean_text(item.get("url", ""))
        score = float(item.get("score", 0.0))
        content = _clean_text(item.get("content", ""))
        if len(content) > 700:
            content = content[:700].rstrip()
        block = "\n".join(
            [
                f"[{idx}] 标题：{title or url}",
                f"来源：{url}",
                f"相关度：{score:.2f}",
                "内容：",
                content,
                "",
            ]
        )
        if total_limit:
            remaining = max(0, total_limit - total_len)
            if remaining <= 0:
                break
            if len(block) > remaining:
                block = block[:remaining].rstrip()
        lines.append(block)
        total_len += len(block) + 1

    context = "\n".join(lines).strip()
    return context if context else ""
