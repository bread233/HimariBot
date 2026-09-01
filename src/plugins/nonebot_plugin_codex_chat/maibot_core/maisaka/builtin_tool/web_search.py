"""web_search 内置工具 — SearXNG + Codex CLI --search fallback。"""

import asyncio
import json
import time
from typing import Any, Optional

import aiohttp

from src.core.tooling import ToolExecutionContext, ToolExecutionResult, ToolInvocation, ToolSpec

from .context import BuiltinToolRuntimeContext


logger = __import__("nonebot").logger


def get_tool_spec() -> ToolSpec:
    return ToolSpec(
        name="web_search",
        description="联网搜索实时外部信息，例如天气、新闻、赛程、比分、价格、版本、公告、活动等。",
        parameters_schema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "搜索关键词，应简洁明确。",
                },
            },
            "required": ["query"],
        },
        provider_name="maisaka_builtin",
        provider_type="builtin",
    )


async def handle_tool(
    tool_ctx: BuiltinToolRuntimeContext,
    invocation: ToolInvocation,
    context: Optional[ToolExecutionContext] = None,
) -> ToolExecutionResult:
    del context
    raw_query = invocation.arguments.get("query")
    if not isinstance(raw_query, str) or not raw_query.strip():
        return tool_ctx.build_failure_result(
            invocation.tool_name,
            "web_search 需要提供非空的 `query` 字符串参数。",
        )

    query = raw_query.strip()
    logger.info(f"codex_chat_web_search_start query={query}")

    from src.plugins.nonebot_plugin_codex_chat.config import get_config as _get_plugin_config
    config = _get_plugin_config()

    searxng_url = (config.codex_chat_searxng_url or "").strip()
    timeout = max(1, int(config.codex_chat_searxng_timeout) if config.codex_chat_searxng_timeout else 8)
    max_results = max(1, int(config.codex_chat_web_search_max_results) if config.codex_chat_web_search_max_results else 5)
    fallback_codexcli = bool(config.codex_chat_web_search_fallback_codexcli)

    logger.info(
        f"codex_chat_web_search_config searxng_url_set={'true' if searxng_url else 'false'} "
        f"timeout={timeout} max_results={max_results} fallback_codexcli={str(fallback_codexcli).lower()}"
    )

    if searxng_url:
        result = await _search_searxng(searxng_url, query, timeout, max_results)
        if result is not None:
            return result

    if fallback_codexcli:
        return await _search_codexcli(query, config)

    return tool_ctx.build_failure_result(
        invocation.tool_name,
        json.dumps({"provider": "none", "query": query, "error": "所有搜索方式均不可用"}, ensure_ascii=False),
    )


async def _search_searxng(
    base_url: str, query: str, timeout: int, max_results: int,
) -> Optional[ToolExecutionResult]:
    base = base_url.rstrip("/")
    url = f"{base}/search"
    params = {"q": query, "format": "json", "language": "zh-CN", "safesearch": "0"}

    logger.info(f"codex_chat_web_search_searxng_start url={url} query={query}")
    started = time.perf_counter()

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=timeout)) as resp:
                if resp.status < 200 or resp.status >= 300:
                    elapsed = time.perf_counter() - started
                    logger.warning(
                        f"codex_chat_web_search_searxng_failed error=http_{resp.status} elapsed={elapsed:.3f}"
                    )
                    return None
                data = await resp.json()
    except asyncio.TimeoutError:
        logger.warning(f"codex_chat_web_search_searxng_failed error=timeout")
        return None
    except json.JSONDecodeError as exc:
        logger.warning(f"codex_chat_web_search_searxng_failed error=json_parse_failed detail={exc}")
        return None
    except aiohttp.ClientError as exc:
        logger.warning(f"codex_chat_web_search_searxng_failed error=request_failed detail={exc}")
        return None
    except Exception as exc:
        logger.warning(f"codex_chat_web_search_searxng_failed error=unexpected detail={exc}")
        return None

    elapsed = time.perf_counter() - started
    raw_results = data.get("results") if isinstance(data, dict) else None
    if not isinstance(raw_results, list) or not raw_results:
        logger.warning(
            f"codex_chat_web_search_searxng_failed error=empty_results elapsed={elapsed:.3f}"
        )
        return None

    items = []
    for item in raw_results[:max_results]:
        title = str(item.get("title") or "").strip()
        content = str(item.get("content") or "").strip()
        url_val = str(item.get("url") or "").strip()
        engine = str(item.get("engine") or "").strip()
        if not title and not content and not url_val:
            continue
        items.append({"title": title, "content": content, "url": url_val, "engine": engine})

    if not items:
        logger.warning(
            f"codex_chat_web_search_searxng_failed error=all_fields_empty elapsed={elapsed:.3f}"
        )
        return None

    logger.info(f"codex_chat_web_search_searxng_success elapsed={elapsed:.3f} results={len(items)}")

    lines = [f"provider=searxng", f"query={query}", "results:"]
    for i, item in enumerate(items, 1):
        lines.append("")
        lines.append(f"{i}. {item['title']}")
        lines.append(f"   {item['content']}")
        lines.append(f"   {item['url']}")
        lines.append(f"   engine: {item['engine']}")

    return ToolExecutionResult(
        tool_name="web_search",
        success=True,
        content="\n".join(lines),
        structured_content={"provider": "searxng", "query": query, "results": items},
    )


async def _search_codexcli(query: str, config: Any) -> ToolExecutionResult:
    logger.info(f"codex_chat_web_search_codexcli_start query={query}")
    started = time.perf_counter()

    prompt = (
        "请联网搜索以下问题，给出简短准确结论，并尽量包含来源名称。不要输出 JSON，不要闲聊。\n"
        f"查询：{query}"
    )

    try:
        process = await asyncio.create_subprocess_exec(
            "docker",
            "exec",
            "-i",
            config.codex_chat_docker_container,
            "codex",
            "--search",
            "exec",
            "-m",
            config.codex_chat_model,
            "-s",
            "read-only",
            "-C",
            config.codex_chat_workdir,
            "--skip-git-repo-check",
            "-",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError:
        elapsed = time.perf_counter() - started
        logger.warning(f"codex_chat_web_search_codexcli_failed error=docker_not_found elapsed={elapsed:.3f}")
        return ToolExecutionResult(
            tool_name="web_search",
            success=False,
            content=json.dumps({"provider": "none", "query": query, "error": "docker_not_found"}, ensure_ascii=False),
        )

    try:
        stdout, stderr = await asyncio.wait_for(
            process.communicate(input=prompt.encode("utf-8")),
            timeout=config.codex_chat_timeout,
        )
    except asyncio.TimeoutError:
        process.kill()
        await process.wait()
        elapsed = time.perf_counter() - started
        logger.warning(f"codex_chat_web_search_codexcli_failed error=timeout elapsed={elapsed:.3f}")
        return ToolExecutionResult(
            tool_name="web_search",
            success=False,
            content=json.dumps({"provider": "none", "query": query, "error": "timeout"}, ensure_ascii=False),
        )

    out_text = stdout.decode("utf-8", errors="ignore").strip()
    if process.returncode != 0 or not out_text:
        elapsed = time.perf_counter() - started
        logger.warning(
            f"codex_chat_web_search_codexcli_failed error=process_error "
            f"returncode={process.returncode} elapsed={elapsed:.3f}"
        )
        return ToolExecutionResult(
            tool_name="web_search",
            success=False,
            content=json.dumps({"provider": "none", "query": query, "error": "process_error"}, ensure_ascii=False),
        )

    elapsed = time.perf_counter() - started
    logger.info(f"codex_chat_web_search_codexcli_success elapsed={elapsed:.3f} chars={len(out_text)}")

    return ToolExecutionResult(
        tool_name="web_search",
        success=True,
        content=json.dumps({"provider": "codexcli", "query": query, "summary": out_text}, ensure_ascii=False),
        structured_content={"provider": "codexcli", "query": query, "summary": out_text},
    )
