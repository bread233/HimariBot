from __future__ import annotations

import re

import httpx
from nonebot import logger

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


async def get_ruby_latest_version(timeout: float = 8.0) -> dict | None:
    candidates = [
        "https://www.ruby-lang.org/en/downloads/",
        "https://www.ruby-lang.org/zh_cn/downloads/",
    ]
    pattern = re.compile(r"\bRuby\s+(\d+\.\d+\.\d+)\b", re.I)
    for endpoint in candidates:
        try:
            async with httpx.AsyncClient(timeout=float(timeout), trust_env=False, follow_redirects=True) as client:
                resp = await client.get(endpoint)
                resp.raise_for_status()
                html = str(resp.text or "")
        except Exception:
            continue
        matches = pattern.findall(html)
        if not matches:
            continue
        # 取页面中出现的第一个语义版本，宁可保守
        version = str(matches[0]).strip()
        if not version:
            continue
        return {
            "kind": "ruby_latest",
            "answer": f"Ruby 最新稳定版是 {version}。",
            "version": version,
            "source": endpoint,
            "confidence": "high",
        }
    return None


OFFICIAL_WEB_RESOLVERS = [
    {
        "key": "nodejs_latest",
        "intent_kind": "current_fact",
        "entity_patterns": ["nodejs", "node.js", r"\bnode\b"],
        "query_patterns": ["latest", "version", "\u6700\u65b0\u7248", "\u6700\u65b0", "\u7248\u672c"],
        "handler": get_nodejs_latest_version,
    },
    {
        "key": "ruby_latest",
        "intent_kind": "current_fact",
        "entity_patterns": [r"\bruby\b", "ruby", "ruby语言", "ruby 语言"],
        "query_patterns": ["latest", "version", "stable", "release", "\u6700\u65b0\u7248", "\u6700\u65b0", "\u7248\u672c", "\u7a33\u5b9a\u7248"],
        "handler": get_ruby_latest_version,
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
        logger.info("official_resolver skip reason=empty_query")
        return None
    any_candidate = False
    for resolver in OFFICIAL_WEB_RESOLVERS:
        if str(resolver.get("intent_kind", "")).strip() != str(intent_kind or "").strip():
            continue
        any_candidate = True
        key = str(resolver.get("key", "")).strip() or "unknown"
        if not _resolver_pattern_hit(q, resolver.get("entity_patterns") or []):
            logger.info(f"official_resolver={key} miss reason=entity_pattern")
            continue
        query_hit = _resolver_pattern_hit(q, resolver.get("query_patterns") or [])
        if not query_hit:
            logger.info(f"official_resolver={key} miss reason=query_pattern")
            continue
        handler = resolver.get("handler")
        if not callable(handler):
            logger.info(f"official_resolver={key} miss reason=handler_not_callable")
            continue
        try:
            result = await handler(timeout=timeout)
        except Exception as e:
            logger.warning(f"official_resolver={key} miss reason=handler_error message={str(e)[:120]!r}")
            continue
        if not isinstance(result, dict):
            logger.info(f"official_resolver={key} miss reason=invalid_result")
            continue
        if str(result.get("confidence", "")).lower() != "high":
            logger.info(f"official_resolver={key} miss reason=low_confidence")
            continue
        out = dict(result)
        out["resolver_key"] = str(resolver.get("key", "")).strip()
        out["matched"] = True
        logger.info(f"official_resolver={key} success")
        return out
    if any_candidate:
        logger.info("official_resolver miss reason=no_resolver_matched")
    else:
        logger.info("official_resolver skip reason=no_intent_candidate")
    return None

