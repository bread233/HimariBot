from __future__ import annotations

import re
from datetime import datetime
from html import unescape
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


def _extract_query_tokens(query: str) -> set[str]:
    text = str(query or "").lower()
    tokens = {t for t in re.findall(r"[a-z][a-z0-9_.-]{1,}", text) if len(t) >= 3}
    mapped: set[str] = set()
    zh_map = {
        "英伟达": ["nvidia"],
        "微软": ["microsoft", "windows"],
        "苹果": ["apple", "ios"],
        "显卡": ["gpu", "driver"],
        "驱动": ["driver", "download"],
        "内测": ["insider", "beta", "preview"],
        "最新": ["latest", "release", "version"],
    }
    for zh, ex in zh_map.items():
        if zh in text:
            mapped.update(ex)
    return tokens | mapped


def _source_preference_score(url: str, query: str) -> float:
    parsed = urlparse(str(url or "").strip())
    host = (parsed.netloc or "").lower()
    path = (parsed.path or "").lower()
    if not host:
        return 0.0
    q = str(query or "").lower()
    query_tokens = _extract_query_tokens(query)
    signals = f"{host} {path} {q}"
    score = 0.0

    official_terms = [
        "official", "support", "docs", "documentation", "developer", "download", "downloads",
        "release", "releases", "release notes", "changelog", "version history",
        "官网", "官方网站", "版本", "发布", "发布说明", "下载", "支持", "文档",
    ]
    hit_terms = sum(1 for t in official_terms if t in signals)
    score += min(hit_terms, 4) * 0.06

    path_signals = ["support", "docs", "developer", "download", "downloads", "releases", "changelog", "blog"]
    for t in path_signals:
        if t in host:
            score += 0.04
        if f"/{t}" in path or f"-{t}" in path:
            score += 0.03

    if query_tokens:
        token_hits = 0
        for t in query_tokens:
            if t in host or t in path or t in q:
                token_hits += 1
        score += min(token_hits, 4) * 0.05

    third_party_hosts = [
        "zhihu.com", "csdn.net", "jianshu.com", "baijiahao", "bilibili.com", "youtube.com", "reddit.com", "wikipedia.org"
    ]
    if any(t in host for t in third_party_hosts):
        score -= 0.08

    return score


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


async def get_nodejs_latest_version(timeout: float = 8.0) -> dict | None:
    endpoint = "https://nodejs.org/dist/index.json"
    try:
        async with httpx.AsyncClient(timeout=float(timeout), trust_env=False, follow_redirects=True) as client:
            resp = await client.get(endpoint)
            resp.raise_for_status()
            data = resp.json()
    except Exception:
        return None

    if not isinstance(data, list):
        return None

    pattern = re.compile(r"^v\d+\.\d+\.\d+$")
    version = ""
    for item in data:
        if not isinstance(item, dict):
            continue
        raw = str(item.get("version", "")).strip()
        if pattern.match(raw):
            version = raw
            break
    if not version:
        return None

    return {
        "kind": "nodejs_latest",
        "answer": f"Node.js 最新版是 {version}。",
        "version": version,
        "source": endpoint,
        "confidence": "high",
    }


OFFICIAL_WEB_RESOLVERS = [
    {
        "key": "nodejs_latest",
        "intent_kind": "current_fact",
        "entity_patterns": ["nodejs", "node.js", r"\bnode\b"],
        "query_patterns": ["latest", "version", "\u6700\u65b0\u7248", "\u6700\u65b0", "\u7248\u672c"],
        "handler": get_nodejs_latest_version,
    },
]


def _resolver_pattern_hit(text: str, patterns: list[str]) -> bool:
    body = str(text or "").lower()
    if not body:
        return False
    for pattern in patterns or []:
        token = str(pattern or "").strip()
        if not token:
            continue
        try:
            if re.search(token, body):
                return True
        except re.error:
            if token.lower() in body:
                return True
    return False


async def resolve_official_web_answer(
    query: str,
    *,
    intent_kind: str | None = None,
    timeout: float = 8.0,
) -> dict | None:
    q = str(query or "").strip()
    if not q:
        return None
    for resolver in OFFICIAL_WEB_RESOLVERS:
        if str(resolver.get("intent_kind", "")).strip() != str(intent_kind or "").strip():
            continue
        if not _resolver_pattern_hit(q, resolver.get("entity_patterns") or []):
            continue
        query_hit = _resolver_pattern_hit(q, resolver.get("query_patterns") or [])
        if not query_hit:
            continue
        handler = resolver.get("handler")
        if not callable(handler):
            continue
        try:
            result = await handler(timeout=timeout)
        except Exception:
            continue
        if not isinstance(result, dict):
            continue
        if str(result.get("confidence", "")).lower() != "high":
            continue
        out = dict(result)
        out["resolver_key"] = str(resolver.get("key", "")).strip()
        out["matched"] = True
        return out
    return None


def _extract_domain(url: str) -> str:
    try:
        host = (urlparse(str(url or "").strip()).netloc or "").lower()
    except Exception:
        return ""
    return host[4:] if host.startswith("www.") else host


def _extract_years(text: str) -> list[int]:
    s = str(text or "")
    if not s:
        return []
    current_year = datetime.now().year
    years: set[int] = set()
    for raw in re.findall(r"\b(20\d{2})\b", s):
        try:
            y = int(raw)
        except Exception:
            continue
        if 2018 <= y <= current_year + 1:
            years.add(y)
    return sorted(years, reverse=True)


def _is_current_sensitive_query(query: str, intent_kind: str | None = None) -> bool:
    if str(intent_kind or "").strip() == "current_fact":
        return True

    q = _clean_text(query)
    if not q:
        return False

    low = q.lower()

    time_terms = [
        "最新",
        "现在",
        "目前",
        "今年",
        "发布",
        "上市",
        "价格",
        "显存",
        "规格",
        "参数",
        "版本",
        "型号",
        "支持吗",
        "有没有",
        "多少",
        "变了吗",
        "还能用吗",
        "能用了吗",
        "latest",
        "current",
        "now",
        "release",
        "price",
        "spec",
        "specs",
        "version",
        "model",
        "support",
        "available",
    ]
    if any(t in q or t in low for t in time_terms):
        return True

    model_patterns = [
        r"[A-Za-z]{2,}[ -]?\d{2,}",
        r"[A-Z]{2,}\d{3,}",
        r"\d+\.\d+(?:\.\d+)?",
    ]
    if any(re.search(p, q) for p in model_patterns):
        return True

    status_terms = [
        "支持吗",
        "支持不",
        "发布了吗",
        "上市了吗",
        "有了吗",
        "怎么样",
        "现在是啥",
        "is available",
        "supported",
        "support",
        "released",
        "available",
    ]
    if any(t in q or t in low for t in status_terms):
        return True

    return False


def _freshness_score(item: dict, query: str, current_sensitive: bool = False) -> float:
    current_year = datetime.now().year
    merged = " ".join(
        [
            str(item.get("title", "") or ""),
            str(item.get("snippet", "") or ""),
            str(item.get("excerpt", "") or ""),
            str(item.get("url", "") or ""),
        ]
    )
    years = _extract_years(merged)
    newest_year = years[0] if years else None

    score = 0.0
    if newest_year is not None:
        if newest_year >= current_year:
            score += 0.30
        elif newest_year == current_year - 1:
            score += 0.18
        elif newest_year == current_year - 2:
            score += 0.05
        else:
            score -= 0.20 if current_sensitive else 0.05

    low = (str(item.get("title", "")) + " " + str(item.get("snippet", "")) + " " + str(item.get("excerpt", ""))).lower()
    hint_terms = [
        "latest",
        "new",
        "current",
        "release",
        "spec",
        "specs",
        "version",
        "发布",
        "最新",
        "规格",
        "显存",
        "参数",
        "版本",
    ]
    if any(t in low for t in hint_terms):
        score += 0.05

    rumor_terms = [
        "rumor",
        "leak",
        "unconfirmed",
        "预测",
        "爆料",
        "传闻",
        "预计",
        "可能",
        "未经证实",
    ]
    if any(t in low for t in rumor_terms):
        score -= 0.15 if current_sensitive else 0.05

    return max(-0.40, min(0.50, score))


def _authority_score(item: dict, query: str, current_sensitive: bool = False) -> float:
    domain = str(item.get("domain", "") or _extract_domain(str(item.get("url", "") or ""))).lower()
    q = str(query or "").lower()

    official_domains = {
        "nvidia.com",
        "nvidia.cn",
        "amd.com",
        "intel.com",
        "microsoft.com",
        "apple.com",
        "python.org",
        "docs.python.org",
        "nodejs.org",
        "cloudflare.com",
        "developers.cloudflare.com",
    }
    doc_domains = {
        "docs.python.org",
        "developers.cloudflare.com",
        "learn.microsoft.com",
        "developer.apple.com",
        "developer.nvidia.com",
    }

    if any(domain == d or domain.endswith("." + d) for d in official_domains):
        return 0.35
    if any(domain == d or domain.endswith("." + d) for d in doc_domains):
        return 0.30
    if domain.endswith("wikipedia.org"):
        return 0.12

    forum_domains = {
        "reddit.com",
        "zhihu.com",
        "tieba.baidu.com",
        "baidu.com",
        "csdn.net",
        "cnblogs.com",
        "qastack.cn",
    }
    if any(domain == d or domain.endswith("." + d) for d in forum_domains):
        return -0.12 if current_sensitive else -0.05

    is_rtx_query = any(k in q for k in ["rtx", "nvidia", "geforce", "英伟达", "显卡", "显存"])
    if is_rtx_query:
        reputable = {
            "techpowerup.com",
            "videocardz.com",
            "tomshardware.com",
            "pcgamer.com",
        }
        if any(domain == d or domain.endswith("." + d) for d in reputable):
            return 0.10
        rumor_sites = {
            "wccftech.com",
        }
        if any(domain == d or domain.endswith("." + d) for d in rumor_sites):
            return -0.10 if current_sensitive else -0.05

    if current_sensitive and domain.endswith("stackoverflow.com"):
        return -0.06

    return 0.0


def _source_flags(item: dict, query: str, current_sensitive: bool = False) -> list[str]:
    flags: list[str] = []
    if current_sensitive:
        flags.append("current-sensitive")

    domain = str(item.get("domain", "") or _extract_domain(str(item.get("url", "") or ""))).lower()
    if any(domain == d or domain.endswith("." + d) for d in ["nvidia.com", "nvidia.cn"]):
        flags.extend(["official", "nvidia-official"])
    elif any(domain == d or domain.endswith("." + d) for d in ["python.org", "nodejs.org", "cloudflare.com"]):
        flags.append("official")
    elif any(domain == d or domain.endswith("." + d) for d in ["docs.python.org", "developers.cloudflare.com", "learn.microsoft.com"]):
        flags.extend(["docs", "official"])

    merged = " ".join(
        [
            str(item.get("title", "") or ""),
            str(item.get("snippet", "") or ""),
            str(item.get("excerpt", "") or ""),
            str(item.get("url", "") or ""),
        ]
    )
    years = _extract_years(merged)
    current_year = datetime.now().year
    if not years:
        flags.append("no-year")
    else:
        newest_year = years[0]
        if newest_year >= current_year:
            flags.append("current-year")
        elif newest_year == current_year - 1:
            flags.append("recent-year")
        elif newest_year <= current_year - 2:
            flags.append("stale-year")

    low = merged.lower()
    if any(t in low for t in ["rumor", "leak", "unconfirmed", "预测", "爆料", "传闻", "预计", "未经证实"]):
        flags.append("rumor")
    if any(domain == d or domain.endswith("." + d) for d in ["reddit.com", "zhihu.com", "tieba.baidu.com", "csdn.net", "cnblogs.com", "qastack.cn"]):
        flags.append("forum")
    if any(domain == d or domain.endswith("." + d) for d in ["baidu.com"]):
        flags.append("seo")

    seen: set[str] = set()
    out: list[str] = []
    for f in flags:
        if f in seen:
            continue
        seen.add(f)
        out.append(f)
    return out


async def build_web_results(config, query: str, intent_kind: str | None = None) -> list[dict]:
    try:
        results = await search_web(config, query)
    except Exception:
        return []
    if not results:
        return []
    max_results = max(1, int(getattr(config, "chat_agent_web_max_results", 3)))
    snippet_max = int(getattr(config, "chat_agent_web_snippet_max_chars", 260))
    excerpt_max = int(getattr(config, "chat_agent_web_excerpt_max_chars", 400))
    current_sensitive = _is_current_sensitive_query(query, intent_kind=intent_kind)
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
                "_idx": idx,
            }
        )
    rows.sort(key=lambda r: (-float(r.get("web_rank_score", 0.0)), int(r.get("_idx", 0))))
    for r in rows:
        r.pop("_idx", None)
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
