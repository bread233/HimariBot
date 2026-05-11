from __future__ import annotations

from .fact_guard import detect_fact_sensitive_question
from .group_tools import get_group_info_context, get_group_member_seen_context
from .memory import build_memory_reminder_for_user, format_memories_for_prompt
from .math_tools import detect_numeric_compare
from .profile_store import load_user_profile_context
from .retrieval import build_embedding_retrieval_context, build_retrieval_context, score_text_overlap
from .storage import get_user_style_profile, load_memories, load_recent_messages
from .tool_router import should_use_web_tool
from .tool_intent import classify_tool_intent
from .question_intent import detect_question_like
from .url_tools import build_direct_url_context, extract_urls
from .web_tools import build_web_context, build_web_results, render_web_results_context, resolve_official_web_answer
from .skill_store import render_skill_context, select_relevant_skills, skills_to_evidence_items
from .evidence_pack import render_evidence_context
from nonebot import logger
from datetime import datetime
import re
from urllib.parse import urlparse
from datetime import date

try:
    from .summary_retrieval import retrieve_daily_summaries
except ImportError:
    retrieve_daily_summaries = None


def _is_context_question(prompt: str) -> bool:
    text = (prompt or "").strip()
    return any(
        token in text
        for token in [
            "我刚才说了什么",
            "我刚刚说了什么",
            "我之前说了什么",
            "我刚才在测什么",
            "我刚刷了啥",
            "在测什么",
        ]
    )


def _is_self_identity_question(prompt: str) -> bool:
    text = (prompt or "").strip()
    patterns = [
        "我是谁",
        "我是谁啊",
        "你知道我是谁吗",
        "你知道我叫什么吗",
        "我叫什么",
        "我在群里叫什么",
    ]
    return any(pattern in text for pattern in patterns)


def _is_creative_or_chat_prompt(prompt: str) -> bool:
    text = (prompt or "").strip()
    return any(
        token in text
        for token in [
            "写个",
            "讲个",
            "来个",
            "编个",
            "冷笑话",
            "笑话",
            "故事",
            "段子",
            "安慰我",
            "陪我聊",
            "聊聊",
            "夸夸我",
            "鼓励我",
            "吐槽一下",
            "自我介绍",
        ]
    )


def _needs_reliable_context(prompt: str) -> bool:
    text = (prompt or "").strip()
    if _is_creative_or_chat_prompt(text):
        return False
    return any(
        token in text
        for token in [
            "我是谁",
            "我叫什么",
            "我在群里叫什么",
            "刚才",
            "刚刚",
            "之前",
            "说了什么",
            "在测什么",
            "什么",
            "多少",
            "多少钱",
            "价格",
            "参数",
            "配置",
            "规格",
            "显存",
            "内存",
            "发布",
            "发售",
            "最新",
            "现在",
            "当前",
            "属于",
            "系列",
            "支持",
            "区别",
            "对比",
            "是真的吗",
            "有吗",
            "存在",
            "查",
            "搜索",
            "资料",
        ]
    )


def _is_explicit_history_query(prompt: str) -> bool:
    text = (prompt or "").strip()
    return any(
        token in text
        for token in [
            "之前",
            "以前",
            "历史",
            "说过",
            "聊过",
            "提过",
            "记得",
            "谁说",
            "谁提",
            "有没有人说",
            "上次",
            "前面",
            "过去",
        ]
    )


def _extract_last_user_message(history: list[dict], current_prompt: str) -> str | None:
    current = (current_prompt or "").strip()
    for item in reversed(history):
        if item.get("role") != "user":
            continue
        content = str(item.get("content", "")).strip()
        if not content or content == current:
            continue
        plain = content.split("：", 1)[-1].strip() if "：" in content else content
        if plain:
            return plain
    return None


def _should_web_mode(config, prompt: str) -> tuple[bool, str, bool]:
    web_mode = str(getattr(config, "chat_agent_web_mode", "auto")).lower()
    tool_router_enabled = bool(getattr(config, "chat_agent_enable_tool_router", True))
    web_enabled = bool(getattr(config, "chat_agent_enable_web", False))
    route = should_use_web_tool(prompt) if tool_router_enabled and web_mode == "auto" else None
    guard = detect_fact_sensitive_question(prompt) if getattr(config, "chat_agent_enable_fact_guard", True) else None
    if web_mode == "off":
        return False, prompt, False
    if web_mode == "always":
        if _is_context_question(prompt):
            return False, prompt, False
        return web_enabled, prompt, False
    if route or guard:
        return web_enabled, (route or {}).get("query") or (guard.get("search_query") if guard else None) or prompt, True
    return False, prompt, False


def _extract_domain(url: str) -> str:
    try:
        host = (urlparse(str(url or "").strip()).netloc or "").lower()
    except Exception:
        return ""
    return host[4:] if host.startswith("www.") else host


def _extract_result_blocks(raw_context: str) -> list[dict]:
    lines = (raw_context or "").splitlines()
    if not lines:
        return []
    blocks: list[dict] = []
    current: list[str] = []
    for line in lines[1:]:
        if re.match(r"^\[\d+\]\s*", line.strip()):
            if current:
                blocks.append({"lines": current[:]})
            current = [line]
        elif current:
            current.append(line)
    if current:
        blocks.append({"lines": current[:]})
    parsed: list[dict] = []
    for idx, block in enumerate(blocks):
        block_lines = block.get("lines", [])
        text = "\n".join(block_lines)
        text_norm = text.replace("\uFF1A", ":")
        m = (
            re.search(r"URL:\s*(\S+)", text_norm, re.IGNORECASE)
            or re.search(r"url:\s*(\S+)", text_norm)
            or re.search(r"source-domain:\s*(\S+)", text_norm, re.IGNORECASE)
            or re.search(r"source:\s*(\S+)", text_norm, re.IGNORECASE)
            or re.search(r"domain:\s*(\S+)", text_norm, re.IGNORECASE)
        )
        url = m.group(1).strip() if m else ""
        parsed.append(
            {
                "idx": idx,
                "lines": block_lines[:],
                "title_line": block_lines[0] if block_lines else "",
                "url": url,
                "domain": _extract_domain(url),
                "snippet": text,
            }
        )
    return parsed


def _build_source_keywords(intent, prompt: str, web_query: str) -> set[str]:
    merged = " ".join(
        [
            str(getattr(intent, "subject", "") or ""),
            str(getattr(intent, "query_terms", "") or ""),
            str(web_query or ""),
            str(prompt or ""),
        ]
    ).lower()
    return {tok for tok in re.findall(r"[\w.-]{2,}", merged, flags=re.UNICODE) if len(tok) > 1}


def _score_web_source(block: dict, keywords: set[str], current_year: int) -> float:
    domain = str(block.get("domain", "") or "").lower()
    url = str(block.get("url", "") or "").lower()
    title = str(block.get("title_line", "") or "").lower()
    snippet = str(block.get("snippet", "") or "").lower()
    score = 0.0
    if domain:
        score += 0.03

    token_bonus = 0.0
    for field in (domain, url, title, snippet):
        if field and any(k in field for k in keywords):
            token_bonus += 0.05
    score += min(0.20, token_bonus)

    hi_signals = [
        "official", "docs", "documentation", "help", "support", "developer", "developers",
        "blog", "news", "release", "releases", "announcement", "update", "version",
        "changelog", "patch-notes", "status",
    ]
    low_signals = ["wiki", "fandom", "reddit", "forum", "zhihu", "csdn", "game8"]
    bag = f"{url}\n{title}\n{snippet}"
    if any(s in bag for s in hi_signals):
        score += 0.08
    if any(s in bag for s in low_signals):
        score -= 0.08

    years = [int(y) for y in re.findall(r"20\d{2}", bag)]
    if years:
        gap = current_year - max(years)
        if gap >= 4:
            score -= 0.20
        elif gap >= 2:
            score -= 0.10

    return max(0.0, min(1.0, score))


def _rank_web_context_lines(raw_context: str, intent, prompt: str, web_query: str) -> tuple[str, list[str], float, str]:
    lines = (raw_context or "").splitlines()
    if not lines:
        return raw_context, [], 0.0, "neutral"
    header = lines[0]
    blocks = _extract_result_blocks(raw_context)
    if not blocks:
        return raw_context, [], 0.0, "neutral"
    keywords = _build_source_keywords(intent, prompt, web_query)
    current_year = datetime.now().year
    for block in blocks:
        block["source_score"] = _score_web_source(block, keywords, current_year)
    blocks.sort(key=lambda b: (float(b.get("source_score", 0.0)), -int(b.get("idx", 0))), reverse=True)

    top_domains = [str(b.get("domain", "")) for b in blocks if b.get("domain")][:5]
    top_source_score = float(blocks[0].get("source_score", 0.0)) if blocks else 0.0
    source_rank = "generic_ranked" if blocks else "neutral"

    out = [header]
    for i, block in enumerate(blocks, 1):
        body = [ln for ln in block.get("lines", []) if not ln.startswith("Source-Domain:") and not ln.startswith("Source-Score:")]
        if body:
            body[0] = re.sub(r"^\[\d+\]", f"[{i}]", body[0], count=1)
        out.extend(body)
        out.append(f"Source-Domain: {block.get('domain') or 'unknown'}")
        out.append(f"Source-Score: {float(block.get('source_score', 0.0)):.2f}")
        out.append("")
    return "\n".join(out).strip(), top_domains, top_source_score, source_rank


def _apply_web_source_ranking(raw_context: str, intent, prompt: str, web_query: str, tool_notes: list[str]) -> tuple[str, float]:
    ranked_context, top_domains, top_source_score, source_rank = _rank_web_context_lines(raw_context, intent, prompt, web_query)
    tool_notes.append(f"web_source_rank={source_rank}")
    tool_notes.append(f"web_source_domains={','.join(top_domains)}")
    tool_notes.append(f"web_top_source_score={top_source_score:.2f}")
    return ranked_context, top_source_score


async def _build_ranked_web_context(config, query: str, intent, prompt: str, tool_notes: list[str]) -> tuple[str, dict]:
    try:
        results = await build_web_results(config, query, intent_kind=str(getattr(intent, "kind", "") or ""))
    except Exception:
        results = []
    if results:
        current_year = datetime.now().year
        scored = sorted(results, key=lambda x: -float(x.get("web_rank_score", x.get("weighted_score", 0.0)) or 0.0))
        top = scored[0] if scored else {}
        top_domain = str(top.get("domain", "") or "")
        top_years = top.get("extracted_years") or []
        top_freshness = float(top.get("freshness_score", 0.0) or 0.0)
        top_authority = float(top.get("authority_score", 0.0) or 0.0)
        top_flags = top.get("source_flags") or []
        current_sensitive = bool("current-sensitive" in top_flags or getattr(intent, "kind", "") == "current_fact")

        top3 = scored[:3]
        official = any(float(x.get("authority_score", 0.0) or 0.0) >= 0.30 or any(f in (x.get("source_flags") or []) for f in ["official", "docs", "nvidia-official"]) for x in top3)
        current = any(float(x.get("freshness_score", 0.0) or 0.0) >= 0.18 or any(y in (x.get("extracted_years") or []) for y in [current_year, current_year - 1]) for x in top3)
        newest_year = max([y for x in top3 for y in (x.get("extracted_years") or [])], default=None)
        if official:
            gate = "official"
            gate_adjust = 0.08
        elif current:
            gate = "current"
            gate_adjust = 0.04
        elif current_sensitive and newest_year is not None and newest_year <= current_year - 2:
            gate = "stale"
            gate_adjust = -0.15
        else:
            gate = "unknown"
            gate_adjust = -0.03 if current_sensitive else 0.0

        tool_notes.append(f"web_current_sensitive={str(bool(current_sensitive)).lower()}")
        tool_notes.append(f"web_top_domain={top_domain}")
        tool_notes.append(f"web_top_years={','.join(str(y) for y in top_years[:3])}")
        tool_notes.append(f"web_top_freshness={top_freshness:.3f}")
        tool_notes.append(f"web_top_authority={top_authority:.3f}")
        tool_notes.append(f"web_freshness_gate={gate}")
        tool_notes.append(f"web_source_flags={','.join(str(f) for f in top_flags[:6])}")

        top_domains = [str(x.get("domain", "")) for x in scored if x.get("domain")][:5]
        top_score = float(scored[0].get("web_rank_score", 0.0) or 0.0) if scored else 0.0
        tool_notes.append("web_source_rank=structured_ranked_v2")
        tool_notes.append(f"web_source_domains={','.join(top_domains)}")
        tool_notes.append(f"web_top_source_score={top_score:.2f}")
        return render_web_results_context(scored, max_items=3), {"gate": gate, "gate_adjust": gate_adjust}

    try:
        raw_context = await build_web_context(config, query)
    except Exception:
        raw_context = ""
    if raw_context:
        ranked, top_domains, top_score, _ = _rank_web_context_lines(raw_context, intent, prompt, query)
        tool_notes.append("web_source_rank=fallback_text_ranked")
        tool_notes.append(f"web_source_domains={','.join(top_domains)}")
        tool_notes.append(f"web_top_source_score={top_score:.2f}")
        tool_notes.append("web_freshness_gate=unknown")
        return ranked, {"gate": "unknown", "gate_adjust": 0.0}
    tool_notes.append("web_source_rank=neutral")
    tool_notes.append("web_source_domains=")
    tool_notes.append("web_top_source_score=0.00")
    tool_notes.append("web_freshness_gate=unknown")
    return "", {"gate": "unknown", "gate_adjust": 0.0}


def _render_summary_retrieval_context(result: dict, max_items: int = 3) -> str:
    if not result or not result.get("reliable"):
        return ""
    candidates = result.get("results") or []
    if not candidates:
        return ""

    lines = ["Historical chat memory candidates:"]
    for i, row in enumerate(candidates[:max_items], start=1):
        score = float(row.get("score", 0.0))
        overlap = int(row.get("overlap_count", 0))
        terms = ",".join(row.get("matched_terms") or [])
        lines.append(f"[{i}] score={score:.4f} overlap={overlap} terms={terms}")

        date = str(row.get("summary_date", ""))
        lines.append(f"Date: {date}" if date else "Date: unknown")

        group_id = str(row.get("group_id", ""))
        if group_id:
            lines.append(f"Group: {group_id}")

        user_id = str(row.get("user_id", ""))
        if user_id:
            lines.append(f"User: {user_id}")

        nickname = str(row.get("nickname", ""))
        if nickname:
            lines.append(f"Nickname: {nickname}")

        group_card = str(row.get("group_card", ""))
        if group_card:
            lines.append(f"Group card: {group_card}")

        lines.append("Summary:")
        head = str(row.get("summary_text_head", ""))
        if len(head) > 600:
            head = head[:600] + "..."
        lines.append(head)
        lines.append("")

    out = "\n".join(lines).strip()
    if len(out) > 2500:
        return out[:2500] + "\n...(truncated)"
    return out


def _render_style_profile_context(profile: dict) -> str:
    if not profile:
        return ""
    recommended = str(profile.get("recommended_bot_style", "") or "").strip()

    lines = [
        "Reply style guidance:",
        "- Use this only to adjust tone/length/format.",
        "- Prefer 1-3 sentences for normal questions.",
        "- Start with the conclusion; avoid long preamble.",
        "- Do not mention this profile or any history to the user.",
        "- Do not treat this as historical facts; do not quote history unless explicitly asked.",
        "- Do not expand keyword-like queries into encyclopedic explanations.",
        "- If web/current_fact is needed, keep a brief uncertainty note.",
        "",
    ]

    if recommended:
        lines.append("Recommended reply style:")
        lines.append(recommended)

    out = "\n".join(lines).strip()
    if len(out) > 500:
        return out[:500]
    return out


def _is_simple_definition_question(prompt: str, intent_kind: str | None) -> bool:
    text = str(prompt or "").strip().lower()
    if not text:
        return False
    if len(text) < 2 or len(text) > 40:
        return False
    if str(intent_kind or "").strip() in {"local_context", "time"}:
        return False

    block_terms = [
        "最新", "版本", "latest", "version", "现在", "今天", "价格", "新闻", "谁说过", "之前", "历史", "聊过",
        "发布", "发售", "更新", "多少钱", "参数", "规格", "显存",
    ]
    if any(t in text for t in block_terms):
        return False

    def_markers = ["是什么", "是啥", "什么是", "什么意思", "是什么东西", "是做什么的"]
    if not any(t in text for t in def_markers):
        return False
    return True


def _is_community_strategy_question(prompt: str, intent_kind: str | None) -> bool:
    text = str(prompt or "").strip().lower()
    if not text:
        return False
    if len(text) < 4 or len(text) > 80:
        return False
    if str(intent_kind or "").strip() in {"local_context", "time"}:
        return False
    if _is_explicit_history_query(prompt) or _is_simple_definition_question(prompt, intent_kind):
        return False
    if extract_urls(prompt):
        return False
    if detect_numeric_compare(prompt) is not None:
        return False

    exclude_markers = [
        "\u6700\u65b0", "\u7248\u672c", "latest", "version", "\u4ef7\u683c", "\u65b0\u95fb",
        "\u4eca\u5929", "\u73b0\u5728", "\u5f53\u524d", "\u591a\u5c11", "\u53c2\u6570", "\u89c4\u683c",
    ]
    if any(t in text for t in exclude_markers):
        return False

    strategy_markers = [
        "\u4ecb\u7ecd", "\u63a8\u8350", "\u73a9\u6cd5", "\u600e\u4e48\u73a9", "\u653b\u7565",
        "\u65b0\u624b", "\u5f00\u5c40", "\u65b9\u6848", "\u8def\u7ebf", "\u5e2e\u6211\u9009",
        "\u9009\u54ea\u4e2a", "\u914d\u7f6e", "\u600e\u4e48\u914d", "\u804c\u4e1a", "\u56fd\u5bb6",
        "\u89d2\u8272", "\u600e\u4e48\u9009", "\u9009\u4ec0\u4e48", "\u600e\u4e48\u9009\u62e9",
        "\u6b66\u5668", "\u88c5\u5907", "\u6d41\u6d3e", "\u52a0\u70b9", "\u6280\u80fd",
        "\u9635\u5bb9", "\u914d\u961f", "\u51fa\u88c5", "\u79d1\u6280\u7ebf", "\u5766\u514b\u7ebf",
        "\u804c\u4e1a\u9009\u62e9",
    ]
    return any(t in text for t in strategy_markers)


async def _build_web_strategy_distilled_context(config, query: str) -> tuple[str, int]:
    try:
        results = await build_web_results(config, query, intent_kind="community_strategy")
    except Exception:
        return "", 0
    if not results:
        return "", 0
    top = results[:5]
    notes = ["Web distilled notes:", f"- Query: {query}", "- Top sources:"]
    snippets: list[str] = []
    for i, row in enumerate(top, 1):
        title = str(row.get("title", "") or "").strip()
        domain = str(row.get("domain", "") or "").strip() or "unknown"
        snippet = str(row.get("snippet", "") or "").strip()
        if len(snippet) > 220:
            snippet = snippet[:220] + "..."
        if snippet:
            snippets.append(snippet.lower())
        notes.append(f"  {i}. {title} / {domain} / {snippet}")

    token_map = {
        "beginner": "\u65b0\u624b",
        "opening": "\u5f00\u5c40",
        "build": "\u6784\u5efa",
        "focus": "\u91cd\u70b9",
        "economy": "\u7ecf\u6d4e",
        "industry": "\u5de5\u4e1a",
        "guide": "\u6307\u5357",
        "tips": "\u6280\u5de7",
        "meta": "meta",
    }
    hint_hits: list[str] = []
    blob = " ".join(snippets)
    for k, v in token_map.items():
        if k in blob:
            hint_hits.append(v)
    hint_hits = hint_hits[:5]
    notes.append("- Consensus hints:")
    if hint_hits:
        for h in hint_hits:
            notes.append(f"  - {h}")
    else:
        notes.append("  - \u4f18\u5148\u53c2\u8003\u591a\u6765\u6e90\u91cd\u590d\u63d0\u5230\u7684\u5efa\u8bae")
    notes.append("- Caveats:")
    notes.append("  - Community guides can be version or DLC dependent.")
    out = "\n".join(notes).strip()
    if len(out) > 1500:
        out = out[:1500]
    return out, len(top)


def _build_web_strategy_queries(prompt: str) -> list[str]:
    raw = str(prompt or "").strip()
    text = raw.lower()
    queries: list[str] = []

    def _push(q: str) -> None:
        q = str(q or "").strip()
        if q and q not in queries:
            queries.append(q)

    if any(k in text for k in ["\u94a2\u94c1\u96c4\u5fc3", "hoi4"]):
        _push("\u94a2\u94c1\u96c4\u5fc34 \u65b0\u624b \u56fd\u5bb6 \u63a8\u8350 \u73a9\u6cd5 \u653b\u7565")
        _push("HOI4 beginner country guide recommended countries")
    if any(k in text for k in ["\u6587\u660e6", "civ6", "civilization 6"]):
        _push("\u6587\u660e6 \u65b0\u624b \u56fd\u5bb6 \u63a8\u8350 \u653b\u7565")
        _push("Civilization 6 beginner civilization guide recommended civ")
    if any(k in text for k in ["\u7fa4\u661f", "stellaris"]):
        _push("\u7fa4\u661f \u65b0\u624b \u653b\u7565 \u5f00\u5c40 \u73a9\u6cd5")
        _push("Stellaris beginner guide opening tips")
    if any(k in text for k in ["wot", "\u5766\u514b\u4e16\u754c", "world of tanks"]):
        _push("\u5766\u514b\u4e16\u754c \u65b0\u624b \u63a8\u8350 \u79d1\u6280\u7ebf \u5766\u514b\u7ebf")
        _push("World of Tanks beginner tech tree line recommendation")
    if any(k in text for k in ["\u71d5\u4e91\u5341\u516d\u58f0", "where winds meet"]):
        _push("\u71d5\u4e91\u5341\u516d\u58f0 \u65b0\u624b \u6b66\u5668 \u63a8\u8350 \u9009\u62e9 \u653b\u7565")
        _push("Where Winds Meet beginner weapon guide recommended weapons")

    _push(raw)
    return queries


def _is_bad_web_strategy_result(row: dict, query_blob: str) -> bool:
    title = str((row or {}).get("title", "") or "").strip()
    url = str((row or {}).get("url", "") or "").strip()
    snippet = str((row or {}).get("snippet", "") or "").strip()
    text = f"{title} {url} {snippet}".lower()
    q = str(query_blob or "").strip().lower()

    keep_aliases = [
        "hoi4",
        "civilization 6",
        "civ6",
        "stellaris",
        "world of tanks",
        "wot",
        "where winds meet",
        "\u94a2\u94c1\u96c4\u5fc3",
        "\u6587\u660e6",
        "\u7fa4\u661f",
        "\u5766\u514b\u4e16\u754c",
        "\u71d5\u4e91\u5341\u516d\u58f0",
    ]
    if any(k in text and (k in q or any(x in q for x in keep_aliases)) for k in keep_aliases):
        return False

    bad_terms = [
        "ticket",
        "tickets",
        "promo",
        "promos",
        "price",
        "prices",
        "hotel",
        "travel",
        "trip",
        "tour",
        "tourist",
        "attraction",
        "booking",
        "\u95e8\u7968",
        "\u7968\u4ef7",
        "\u9152\u5e97",
        "\u65c5\u6e38",
        "\u666f\u70b9",
        "\u9884\u8ba2",
        "\u4f18\u60e0",
        "\u4fc3\u9500",
    ]
    if any(t in text for t in bad_terms):
        return True

    if any(x in text for x in ["red giant", "altec"]) and any(x in q for x in ["weapon", "guide", "\u6b66\u5668", "\u653b\u7565"]):
        return True

    return False


async def _build_web_strategy_distilled_context_multi(config, queries: list[str]) -> tuple[str, int, list[str], list[str], str]:
    logger.info(f"web_strategy search start queries={queries[:3]!r}")
    merged: list[dict] = []
    errors: list[str] = []
    used_queries: list[str] = []
    seen = set()

    for q in queries:
        qs = str(q or "").strip()
        if not qs:
            continue
        used_queries.append(qs)
        try:
            results = await build_web_results(config, qs, intent_kind="community_strategy")
            logger.info(f"web_strategy query result_count={len(results or [])} query={qs[:120]!r}")
        except Exception as e:
            errors.append(str(e)[:120])
            logger.warning(f"web_strategy query error query={qs[:120]!r} message={str(e)[:200]!r}")
            continue
        for row in results or []:
            title = str(row.get("title", "") or "").strip()
            url = str(row.get("url", "") or "").strip()
            if _is_bad_web_strategy_result(row, " || ".join(queries)):
                logger.info(f"web_strategy filtered title={title[:80]!r} reason='bad_source_signal'")
                continue
            key = (title.lower(), url.lower())
            if key in seen:
                continue
            seen.add(key)
            merged.append(row)
        if len(merged) >= 5:
            break

    if not merged:
        logger.info(
            f"web_strategy distilled result_count=0 top_titles=[] chars=0 used_queries={used_queries[:3]!r}"
        )
        return "", 0, used_queries, [], (errors[0] if errors else "")

    top = merged[:5]
    notes = [
        "Web strategy evidence:",
        "- User wants a practical recommendation, not an article summary.",
        "- Answer should choose or recommend directly when evidence supports it.",
        "- Do not say \"the article discusses\" unless the user asks for article summary.",
        f"- Query: {' || '.join(used_queries[:3])}",
        "- Top source snippets:",
    ]
    snippets: list[str] = []
    top_titles: list[str] = []
    for i, row in enumerate(top, 1):
        title = str(row.get("title", "") or "").strip()
        domain = str(row.get("domain", "") or "").strip() or "unknown"
        snippet = str(row.get("snippet", "") or "").strip()
        if len(snippet) > 220:
            snippet = snippet[:220] + "..."
        if title:
            top_titles.append(title[:60])
        if snippet:
            snippets.append(snippet.lower())
        notes.append(f"  {i}. title: {title}")
        notes.append(f"     domain: {domain}")
        notes.append(f"     snippet: {snippet}")

    token_map = {
        "beginner": "\u65b0\u624b",
        "opening": "\u5f00\u5c40",
        "build": "\u6784\u5efa",
        "focus": "\u91cd\u70b9",
        "economy": "\u7ecf\u6d4e",
        "industry": "\u5de5\u4e1a",
        "guide": "\u6307\u5357",
        "tips": "\u6280\u5de7",
        "meta": "meta",
    }
    hint_hits: list[str] = []
    blob = " ".join(snippets)
    for k, v in token_map.items():
        if k in blob:
            hint_hits.append(v)
    hint_hits = hint_hits[:5]
    notes.append("- Consensus hints:")
    if hint_hits:
        for h in hint_hits:
            notes.append(f"  - {h}")
    else:
        notes.append("  - \u4f18\u5148\u53c2\u8003\u591a\u6765\u6e90\u91cd\u590d\u63d0\u5230\u7684\u5efa\u8bae")
    notes.append("- Caveats:")
    notes.append("  - Community guides can be version or DLC dependent.")
    out = "\n".join(notes).strip()
    if len(out) > 1500:
        out = out[:1500]
    logger.info(
        f"web_strategy distilled result_count={len(merged)} top_titles={top_titles[:3]!r} "
        f"chars={len(out)} used_queries={used_queries[:3]!r}"
    )
    return out, len(top), used_queries, top_titles[:3], (errors[0] if errors else "")


def _has_local_evidence_for_question(
    *,
    direct_reply: str | None,
    retrieval_context: str,
    summary_retrieval_context: str,
    history_context: str,
    memory_context: str,
    simple_definition_hit: bool,
    explicit_history_hit: bool,
) -> bool:
    if str(direct_reply or "").strip():
        return True
    if simple_definition_hit or explicit_history_hit:
        return True
    return False


async def _build_generic_web_evidence_context(config, query: str) -> tuple[str, int, list[str], float, str]:
    q = str(query or "").strip()
    if not q:
        return "", 0, [], 0.0, "empty_query"
    logger.info(f"web_evidence search start query={q[:120]!r}")
    try:
        results = await build_web_results(config, q, intent_kind="evidence_route")
        logger.info(f"web_evidence query result_count={len(results or [])} query={q[:120]!r}")
    except Exception as e:
        msg = str(e)[:200]
        logger.warning(f"web_evidence query error query={q[:120]!r} message={msg!r}")
        return "", 0, [], 0.0, msg
    merged: list[dict] = []
    top_score = 0.0
    today = date.today()
    freshness_sensitive = _is_freshness_sensitive_prompt(q)
    seen = set()
    for row in results or []:
        title = str((row or {}).get("title", "") or "").strip()
        url = str((row or {}).get("url", "") or "").strip()
        domain = str((row or {}).get("domain", "") or "").strip()
        snippet = str((row or {}).get("snippet", "") or "").strip()
        if not title and not snippet:
            continue
        key = ((title or "").lower(), (url or "").lower())
        if key in seen:
            continue
        seen.add(key)
        score = float(row.get("weighted_score", row.get("score", 0.0)) or 0.0)
        authority = float(row.get("authority_score", 0.0) or 0.0)
        flags = [str(x).lower() for x in (row.get("source_flags") or [])]
        official = bool("official" in flags or "docs" in flags or authority >= 0.30)
        recency_days, recency_source = _extract_recency_days("\n".join([title, snippet, url]), today)
        freshness_weight = 0.0
        if recency_days is not None:
            if recency_days <= 365:
                freshness_weight = 0.20
            elif recency_days <= 730:
                freshness_weight = 0.05
            else:
                freshness_weight = -0.10
        official_weight = 0.35 if (official and score >= 0.15) else 0.0
        final_score = score + official_weight + freshness_weight
        if score > top_score:
            top_score = score
        if len(snippet) > 240:
            snippet = snippet[:240] + "..."
        merged.append(
            {
                "title": title,
                "url": url,
                "domain": domain,
                "snippet": snippet,
                "score": score,
                "official": official,
                "recency_days": recency_days,
                "recency_source": recency_source,
                "final_score": final_score,
            }
        )
        if len(merged) >= 5:
            break
    if not merged:
        logger.info("web_evidence distilled result_count=0 top_titles=[] chars=0")
        return "", 0, [], top_score, ""
    merged.sort(
        key=lambda x: (
            float(x.get("final_score", 0.0)),
            float(x.get("score", 0.0)),
            1 if x.get("official") else 0,
        ),
        reverse=True,
    )
    if freshness_sensitive and not any((x.get("recency_days") is not None and int(x.get("recency_days")) <= 365) for x in merged[:5]):
        logger.info("web_evidence freshness_sensitive_no_recent=1")
        return "", len(merged[:5]), [str(x.get("title", ""))[:60] for x in merged[:3]], top_score, "no_recent_within_1y"
    notes = [
        "\u5df2\u67e5\u5230\u7684\u7f51\u9875\u8d44\u6599\uff1a",
        "- \u8fd9\u662f\u4e00\u4e2a\u9700\u8981\u4f9d\u636e\u8d44\u6599\u7684\u95ee\u9898\u3002",
        "- \u8bf7\u57fa\u4e8e\u4e0b\u9762\u7684\u641c\u7d22\u7ed3\u679c\u6458\u8981\u56de\u7b54\u3002",
        "- \u82e5\u6458\u8981\u4e0d\u8db3\uff0c\u4e0d\u8981\u4ec5\u51ed\u6a21\u578b\u8bb0\u5fc6\u4e0b\u7ed3\u8bba\u3002",
        f"- \u68c0\u7d22\u95ee\u9898\uff1a{q}",
        "- \u641c\u7d22\u7ed3\u679c\u6458\u8981\uff1a",
    ]
    top_titles: list[str] = []
    for i, row in enumerate(merged[:5], 1):
        title = str(row.get("title", "") or "")
        domain = str(row.get("domain", "") or "") or "unknown"
        snippet = str(row.get("snippet", "") or "")
        recency_days = row.get("recency_days")
        recency_source = str(row.get("recency_source", "") or "")
        official = "\u662f" if row.get("official") else "\u5426"
        recency_text = "\u672a\u8bc6\u522b"
        recency_source_text = recency_source or "\u672a\u8bc6\u522b"
        if recency_days is not None:
            recency_text = f"{int(recency_days)}\u5929\u524d"
        top_titles.append(title[:60] if title else "")
        notes.append(f"  {i}. \u6807\u9898\uff1a{title}")
        notes.append(f"     \u6765\u6e90\u57df\u540d\uff1a{domain}")
        notes.append(f"     \u6458\u8981\uff1a{snippet}")
        notes.append(f"     \u8d44\u6599\u65e5\u671f\uff1a{recency_text}")
        notes.append(f"     \u65e5\u671f\u6765\u6e90\uff1a{recency_source_text}")
        notes.append(f"     \u662f\u5426\u5b98\u65b9\uff1a{official}")
    notes.extend(
        [
            "- \u56de\u7b54\u8981\u6c42\uff1a",
            "  - \u5148\u7ed9\u51fa\u8c28\u614e\u7ed3\u8bba\u3002",
            "  - \u82e5\u8bc1\u636e\u8f83\u5f31\uff0c\u8981\u660e\u786e\u8bf4\u51fa\u4e0d\u786e\u5b9a\u6027\u3002",
            "  - \u4e0d\u8981\u7f16\u9020\u6458\u8981\u91cc\u6ca1\u6709\u7684\u4e8b\u5b9e\u3002",
        ]
    )
    out = "\n".join(notes).strip()
    if len(out) > 1800:
        out = out[:1800]
    logger.info(
        f"web_evidence distilled result_count={len(merged[:5])} top_titles={top_titles[:3]!r} chars={len(out)} top_score={top_score:.3f}"
    )
    return out, len(merged[:5]), [t for t in top_titles[:3] if t], top_score, ""


def _is_freshness_sensitive_prompt(prompt: str) -> bool:
    text = str(prompt or "").lower()
    markers = [
        "\u6700\u65b0", "\u6700\u8fd1", "\u8fd1\u671f", "\u8fd1\u51b5", "\u8fd1\u6765", "\u5f53\u524d", "\u8fd9\u8d5b\u5b63", "\u672c\u8d5b\u5b63", "\u4eca\u5e74", "\u4eca\u5929", "\u73b0\u5728",
        "\u7248\u672c", "\u4ef7\u683c", "\u591a\u5c11\u94b1", "\u8868\u73b0", "\u65b0\u95fb", "latest", "current", "this season",
        "price", "news", "version", "recent",
    ]
    return any(m in text for m in markers)


def _extract_recency_days(text: str, today: date) -> tuple[int | None, str]:
    s = str(text or "")
    if not s:
        return None, ""
    m = re.search(r"(20\d{2})[-/](\d{1,2})[-/](\d{1,2})", s)
    if m:
        try:
            d = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            return max(0, (today - d).days), "yyyy-mm-dd"
        except Exception:
            pass
    m = re.search(r"(20\d{2})\s*\u5e74\s*(\d{1,2})\s*\u6708\s*(\d{1,2})\s*\u65e5", s)
    if m:
        try:
            d = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            return max(0, (today - d).days), "yyyy\u5e74m\u6708d\u65e5"
        except Exception:
            pass
    m = re.search(r"(20\d{2})\s*\u5e74", s)
    if m:
        try:
            d = date(int(m.group(1)), 7, 1)
            return max(0, (today - d).days), "yyyy\u5e74"
        except Exception:
            pass
    m = re.search(r"(\d+)\s*days?\s*ago", s, re.IGNORECASE)
    if m:
        return int(m.group(1)), "x_days_ago"
    m = re.search(r"(\d+)\s*months?\s*ago", s, re.IGNORECASE)
    if m:
        return int(m.group(1)) * 30, "x_months_ago"
    m = re.search(r"(\d+)\s*years?\s*ago", s, re.IGNORECASE)
    if m:
        return int(m.group(1)) * 365, "x_years_ago"
    return None, ""


def _build_simple_definition_reply(prompt: str) -> str:
    text = str(prompt or "").strip().lower()
    if "nodejs" in text or "node.js" in text or re.search(r"\bnode\b", text):
        return "Node.js 是一个基于 Chrome V8 引擎的 JavaScript 运行时，常用于服务端开发。"
    if "python" in text:
        return "Python 是一门通用编程语言，以语法简洁、生态丰富著称。"
    if "docker" in text:
        return "Docker 是一个容器化平台，用来打包、分发和运行应用及其依赖。"
    if re.search(r"\bnpm\b", text):
        return "npm 是 Node.js 的包管理工具，用于安装和管理 JavaScript 依赖。"
    return "这是一个概念解释类问题，我暂时没法稳定生成回答，可以稍后再试。"


def _build_explicit_history_direct_reply(prompt: str, summary_context: str, history_context: str) -> str:
    summary_text = str(summary_context or "").strip()
    if summary_text:
        lines = [line.strip() for line in summary_text.splitlines() if line.strip()]
        picked = []
        for line in lines:
            if line.startswith("[") and "]" in line:
                picked.append(line)
            elif line.startswith("Summary:"):
                continue
            elif line.startswith("Date:") or line.startswith("Group:") or line.startswith("User:"):
                continue
            elif len(line) > 5:
                picked.append(line)
            if len(picked) >= 3:
                break
        if picked:
            return "\u6211\u627e\u5230\u4e00\u4e9b\u76f8\u5173\u7684\u5386\u53f2\u8bb0\u5f55\uff1a\n- " + "\n- ".join(picked[:3])

    history_text = str(history_context or "").strip()
    if history_text:
        rows = [line.strip() for line in history_text.splitlines() if line.strip()]
        if rows:
            return "\u6211\u627e\u5230\u4e86\u76f8\u5173\u7684\u6700\u8fd1\u5bf9\u8bdd\uff1a\n- " + "\n- ".join(rows[-3:])

    trimmed = str(prompt or "").strip()
    if len(trimmed) > 20:
        trimmed = trimmed[:20] + "..."
    return f"\u6682\u65f6\u6ca1\u67e5\u5230\u4e0e\u201c{trimmed}\u201d\u76f8\u5173\u7684\u5386\u53f2\u8bb0\u5f55\u3002"


async def build_context_pack(config, session_info: dict, prompt: str, bot=None, event=None) -> dict:
    intent = classify_tool_intent(prompt)
    question_intent = detect_question_like(prompt)
    skill_prompt = prompt
    if question_intent.is_question_like:
        skill_prompt = (
            f"{prompt} question {question_intent.category} "
            f"{'web_eligible' if question_intent.web_eligible else 'local_only'}"
        )
    group_id_raw = session_info.get("group_id")
    group_id = str(group_id_raw).strip() if group_id_raw is not None else ""
    selected_skills = await select_relevant_skills(
        config,
        skill_prompt,
        intent.kind,
        group_id=group_id or None,
        limit=3,
    )
    skill_context = render_skill_context(selected_skills)
    skill_evidence_items = skills_to_evidence_items(selected_skills)
    skill_evidence_context = render_evidence_context(skill_evidence_items, budget_chars=1200, limit=3)
    if intent.needs_time:
        now = datetime.now()
        time_context = (
            "当前时间信息：\n"
            f"- 当前日期：{now:%Y-%m-%d}\n"
            f"- 当前年份：{now:%Y}\n"
            f"- 当前本地时间：{now:%Y-%m-%d %H:%M:%S}"
        )
    else:
        time_context = ""
    session_id = session_info["session_id"]
    history_limit = int(getattr(config, "chat_agent_history_max_messages", 10))
    memory_limit = int(getattr(config, "chat_agent_memory_max_results", 5))
    web_enabled = bool(getattr(config, "chat_agent_enable_web", False))
    is_identity_question = _is_self_identity_question(prompt)

    try:
        profile_context = await load_user_profile_context(config, session_info)
    except Exception:
        profile_context = ""

    if is_identity_question and profile_context:
        identity_hint_lines = [
            "",
            "身份回答要求：",
            "- 用户正在问自己的身份/昵称。",
            "- 请只基于本轮提供的“说话者画像”和“当前发言人在群内”资料回答。",
            "- 如果问题是“我在群里叫什么”，请优先回答当前群昵称/群名片；如果群名片为空，请回答当前显示的是 QQ 昵称。",
            "- 不要推测群里有没有其他人。",
            "- 不要编造没有提供的信息。",
            "- 不要回答“不知道”，除非上下文里完全没有 QQ、昵称、群昵称信息。",
            "- 回答要简短。",
        ]
        profile_context = profile_context.rstrip() + "\n" + "\n".join(identity_hint_lines)

    group_context = ""
    if bot is not None and event is not None and session_info.get("session_type") == "group":
        parts = []
        try:
            info_context = await get_group_info_context(bot, event, session_info)
        except Exception:
            info_context = ""
        if info_context:
            parts.append(info_context)
        try:
            member_context = await get_group_member_seen_context(bot, event, session_info)
        except Exception:
            member_context = ""
        if member_context:
            parts.append(member_context)
        group_context = "\n\n".join(parts).strip()

    try:
        history = await load_recent_messages(config, session_id, history_limit)
    except Exception:
        history = []

    if _is_context_question(prompt):
        last_user = _extract_last_user_message(history, prompt)
        if last_user:
            return {
                "direct_reply": f"你刚才说：{last_user}",
                "should_call_llm": False,
                "web_used": False,
                "time_context": time_context,
                "profile_context": profile_context,
                "group_context": group_context,
                "retrieval_context": "",
                "style_context": "",
                "summary_retrieval_context": "",
                "history_context": "",
                "memory_context": "",
                "web_context": "",
                "tool_notes": "",
            }

    try:
        memories = await load_memories(config, session_id, memory_limit)
    except Exception:
        memories = []

    memory_context = format_memories_for_prompt(memories)
    memory_reminder = build_memory_reminder_for_user(memories, prompt)
    if memory_reminder:
        memory_context = f"{memory_context}\n\n{memory_reminder}".strip() if memory_context else memory_reminder

    math_result = detect_numeric_compare(prompt)
    urls = extract_urls(prompt)

    history_lines = []
    for item in history:
        role = item.get("role")
        content = str(item.get("content", "")).strip()
        if not content:
            continue
        if role == "user":
            if session_info["session_type"] == "group":
                nick = item.get("nickname") or "用户"
                content = f"{nick}：{content}"
            else:
                content = f"用户：{content}"
        elif role == "assistant":
            content = f"助手：{content}"
        history_lines.append(content)
    history_context = "\n".join(history_lines[-history_limit:]).strip()

    retrieval_context = ""
    retrieval_score = 0.0
    retrieval_threshold = float(getattr(config, "chat_agent_retrieval_min_score", 0.45))
    embedding_status = "empty"
    if math_result is not None:
        retrieval_context = "确定性计算结果：" + str(math_result.get("result_text", "")).strip()
        retrieval_score = 1.0
        tool_notes_embed = [
            "math_tool=numeric_compare",
            f"math_result={math_result.get('comparison', '')}",
        ]
        embedding_status = "math"
    elif bool(getattr(config, "chat_agent_enable_embedding_retrieval", True)):
        embedding_candidates = [
            {"source": "profile", "content": profile_context},
            {"source": "group", "content": group_context},
        ]
        for item in memories:
            content = str(item.get("content", "")).strip()
            if not content:
                continue
            row_type = str(item.get("memory_type", "memory") or "memory")
            source = "correction" if row_type == "correction" else "memory"
            embedding_candidates.append({"source": source, "content": content})
        if not any(c["source"] in {"memory", "correction"} and c["content"] for c in embedding_candidates):
            embedding_candidates.append({"source": "memory", "content": memory_context})
        embedding_candidates.append({"source": "history", "content": history_context})
        embedding_result = await build_embedding_retrieval_context(config, prompt, embedding_candidates)
        embedding_status = str(embedding_result.get("status", "error"))
        tool_note = embedding_result.get("notes") or ""
        if tool_note:
            tool_notes_embed = [f"embedding_retrieval={embedding_status}", tool_note]
        else:
            tool_notes_embed = [f"embedding_retrieval={embedding_status}"]
        if embedding_status in {"reliable", "candidate"}:
            tool_notes_embed.append(f"embedding_source={embedding_result.get('source', '')}")
            tool_notes_embed.append(f"embedding_score={float(embedding_result.get('score', 0.0)):.4f}")
            tool_notes_embed.append(f"embedding_margin={float(embedding_result.get('margin', 0.0)):.4f}")
        retrieval_score = float(embedding_result.get("score", 0.0) or 0.0)
        if embedding_status == "reliable":
            retrieval_context = str(embedding_result.get("content", "")).strip()
    else:
        tool_notes_embed = ["embedding_retrieval=disabled"]

    if not retrieval_context:
        retrieval = build_retrieval_context(
            prompt,
            profile_context,
            group_context,
            memory_context,
            history_context,
            min_score=retrieval_threshold,
        )
        retrieval_context = retrieval["content"] if retrieval["source"] == "db" else ""
        retrieval_score = float(retrieval.get("score", 0.0) or 0.0)

    web_relevance_threshold = float(getattr(config, "chat_agent_web_relevance_min_score", 0.35))
    web_final_threshold = float(getattr(config, "chat_agent_web_final_min_score", 0.30))
    should_web, web_query, route_like = _should_web_mode(config, prompt)
    needs_reliable_context = _needs_reliable_context(prompt)

    web_context = ""
    style_context = ""
    summary_retrieval_context = ""
    tool_notes = []
    tool_notes.extend(tool_notes_embed)
    if selected_skills:
        tool_notes.append("selected_skills=" + ",".join(skill.key for skill in selected_skills))
    tool_notes.append(f"skill_evidence_items={len(skill_evidence_items)}")
    tool_notes.append(f"skill_evidence_chars={len(skill_evidence_context)}")
    tool_notes.append(f"intent={intent.kind}")
    tool_notes.append(f"question_like={1 if question_intent.is_question_like else 0}")
    tool_notes.append(f"question_category={question_intent.category}")
    tool_notes.append(f"question_web_eligible={1 if question_intent.web_eligible else 0}")
    tool_notes.append(f"question_matched_terms={','.join(question_intent.matched_terms[:8])}")

    style_profile = None
    style_profile_error = ""
    style_profile_group_exact = False
    try:
        current_user_id = str(session_info.get("user_id", "") or "").strip()
        current_group_id = str(session_info.get("group_id", "") or "").strip()
        if current_user_id:
            style_profile = await get_user_style_profile(
                config,
                current_user_id,
                current_group_id if current_group_id else None,
            )
            if style_profile:
                style_context = _render_style_profile_context(style_profile)
                style_profile_group_exact = bool(
                    current_group_id and str(style_profile.get("group_id", "") or "") == current_group_id
                )
    except Exception as e:
        style_profile_error = str(e)[:120]

    if style_profile_error:
        tool_notes.append(f"style_profile_error={style_profile_error}")
    else:
        tool_notes.append(f"style_profile_hit={str(bool(style_profile)).lower()}")
        if style_profile:
            tool_notes.append(f"style_profile_group_exact={str(style_profile_group_exact).lower()}")
            tool_notes.append(f"style_profile_message_count={int(style_profile.get('message_count', 0) or 0)}")
            tool_notes.append(f"style_profile_peer_reply_count={int(style_profile.get('peer_reply_count', 0) or 0)}")

    if not _is_explicit_history_query(prompt):
        tool_notes.append("summary_retrieval_skipped=not_explicit_history_query")
    elif retrieve_daily_summaries and getattr(config, "chat_agent_embedding_base_url", "") and getattr(config, "chat_agent_embedding_model", "") and prompt:
        if intent.kind not in ("creative", "time"):
            tool_notes.append("summary_retrieval_triggered=true")
            try:
                sr_result = await retrieve_daily_summaries(
                    config,
                    prompt,
                    top_k=3,
                    candidate_limit=None,
                    min_score=0.60,
                    min_margin=0.04,
                    overlap_min_score=0.50,
                    min_overlap=2,
                    strong_score=0.68,
                    weak_margin_floor=0.02,
                )
                if sr_result.get("reliable"):
                    summary_retrieval_context = _render_summary_retrieval_context(sr_result)

                tool_notes.append(f"summary_retrieval_candidate_count={sr_result.get('candidate_count', 0)}")
                tool_notes.append(f"summary_retrieval_reliable={str(sr_result.get('reliable', False)).lower()}")
                tool_notes.append(f"summary_retrieval_by={sr_result.get('reliable_by', '')}")
                tool_notes.append(f"summary_retrieval_reason={sr_result.get('gate_reason', '')}")
                tool_notes.append(f"summary_retrieval_top1_score={float(sr_result.get('top1_score', 0.0)):.4f}")
                tool_notes.append(f"summary_retrieval_margin={float(sr_result.get('margin', 0.0)):.4f}")
                tool_notes.append(f"summary_retrieval_overlap={int(sr_result.get('top1_overlap_count', 0))}")
                terms = (sr_result.get("top1_matched_terms") or [])[:6]
                tool_notes.append(f"summary_retrieval_terms={','.join(terms)}")
            except Exception as e:
                tool_notes.append(f"summary_retrieval_error={str(e)[:120]}")

    tool_notes.append(f"subject={intent.subject}")
    tool_notes.append(f"time_hint={intent.time_hint}")
    tool_notes.append(f"intent_reason={intent.reason}")
    if intent.needs_freshness:
        now = datetime.now()
        tool_notes.append("freshness_required")
        tool_notes.append(f"current_date={now:%Y-%m-%d}")
        tool_notes.append(f"freshness_days={intent.freshness_days}")
    if intent.prefer_official:
        tool_notes.append("prefer_official=true")
    web_used = False

    if urls and math_result is None:
        try:
            direct_url_context = await build_direct_url_context(config, prompt, urls)
        except Exception:
            direct_url_context = ""
        if direct_url_context:
            web_context = direct_url_context
            web_used = True
            tool_notes.append("direct_url_read=1")
            tool_notes.append(f"direct_url_count={len(urls[:2])}")
        else:
            web_context = "直接 URL 读取失败：未获取到可用页面信息。"
            tool_notes.append("direct_url_read=1")
            tool_notes.append(f"direct_url_count={len(urls[:2])}")

    if urls and math_result is None:
        tool_notes.append("direct_url_mode=1")
    elif math_result is not None:
        tool_notes.append("math_tool=numeric_compare")
    elif intent.kind == "current_fact" and not _is_explicit_history_query(prompt):
        official_answer = await resolve_official_web_answer(
            web_query or prompt,
            intent_kind=intent.kind,
            timeout=8.0,
        )
        if official_answer and str(official_answer.get("confidence", "")).lower() == "high":
            resolver_key = str(official_answer.get("resolver_key", official_answer.get("kind", "official_answer")))
            tool_notes.append(f"current_fact_direct_answer={resolver_key}")
            tool_notes.append("current_fact_direct_confidence=high")
            tool_notes.append(
                f"current_fact_direct_source={official_answer.get('source', '')}"
            )
            return {
                "direct_reply": str(official_answer.get("answer", "")).strip(),
                "should_call_llm": False,
                "web_used": False,
                "time_context": time_context,
                "profile_context": profile_context,
                "group_context": group_context,
                "retrieval_context": retrieval_context,
                "style_context": style_context,
                "summary_retrieval_context": summary_retrieval_context,
                "history_context": history_context,
                "memory_context": memory_context,
                "web_context": "",
                "tool_notes": "\n".join(tool_notes).strip(),
            }
    if _is_explicit_history_query(prompt):
        try:
            direct_history_reply = _build_explicit_history_direct_reply(
                prompt, summary_retrieval_context, history_context
            )
            tool_notes.append("explicit_history_direct_reply=1")
            return {
                "direct_reply": direct_history_reply,
                "should_call_llm": False,
                "web_used": False,
                "time_context": time_context,
                "profile_context": profile_context,
                "group_context": group_context,
                "retrieval_context": retrieval_context,
                "style_context": style_context,
                "summary_retrieval_context": summary_retrieval_context,
                "history_context": history_context,
                "memory_context": memory_context,
                "web_context": "",
                "tool_notes": "\n".join(tool_notes).strip(),
            }
        except Exception:
            tool_notes.append("explicit_history_direct_reply_error=1")
            return {
                "direct_reply": "\u5386\u53f2\u67e5\u8be2\u6682\u65f6\u4e0d\u53ef\u7528\uff0c\u53ef\u4ee5\u7a0d\u540e\u518d\u8bd5\u3002",
                "should_call_llm": False,
                "web_used": False,
                "time_context": time_context,
                "profile_context": profile_context,
                "group_context": group_context,
                "retrieval_context": "",
                "style_context": "",
                "summary_retrieval_context": "",
                "history_context": "",
                "memory_context": "",
                "web_context": "",
                "tool_notes": "\n".join(tool_notes).strip(),
            }
    if _is_community_strategy_question(prompt, intent.kind):
        strategy_query = str(prompt or "").strip()
        strategy_queries = _build_web_strategy_queries(strategy_query)
        distilled_context, strategy_count, used_queries, top_titles, strategy_error = await _build_web_strategy_distilled_context_multi(
            config, strategy_queries
        )
        tool_notes.append("web_strategy=1")
        tool_notes.append(f"web_strategy_query={strategy_query}")
        tool_notes.append(f"web_strategy_queries={' || '.join(used_queries[:5])}")
        tool_notes.append(f"web_strategy_result_count={strategy_count}")
        tool_notes.append(f"web_strategy_top_titles={' || '.join(top_titles)}")
        tool_notes.append(f"web_strategy_distilled_chars={len(distilled_context)}")
        if strategy_error:
            tool_notes.append(f"web_strategy_error={strategy_error}")
        if not distilled_context:
            return {
                "direct_reply": "\u6682\u65f6\u6ca1\u67e5\u5230\u7a33\u5b9a\u7684\u653b\u7565\u8d44\u6599\uff0c\u53ef\u4ee5\u6362\u4e2a\u66f4\u5177\u4f53\u7684\u95ee\u9898\u3002",
                "should_call_llm": False,
                "web_used": True,
                "time_context": time_context,
                "profile_context": profile_context,
                "group_context": group_context,
                "retrieval_context": "",
                "style_context": "",
                "summary_retrieval_context": "",
                "history_context": "",
                "memory_context": "",
                "web_context": "",
                "tool_notes": "\n".join(tool_notes).strip(),
            }
        return {
            "direct_reply": None,
            "should_call_llm": True,
            "web_used": True,
            "time_context": time_context,
            "profile_context": profile_context,
            "group_context": group_context,
            "retrieval_context": "",
            "style_context": "",
            "summary_retrieval_context": "",
            "history_context": "",
            "memory_context": "",
            "web_context": "",
            "lightweight_mode": "web_strategy",
            "lightweight_prompt": prompt,
            "web_strategy_query": strategy_query,
            "web_strategy_context": distilled_context,
            "tool_notes": "\n".join(tool_notes).strip(),
        }
    if (
        str(prompt or "").strip()
        and not _is_explicit_history_query(prompt)
        and not _is_community_strategy_question(prompt, intent.kind)
        and not urls
        and math_result is None
        and intent.kind != "local_context"
    ):
        tool_notes.append("evidence_gate=1")
        local_ok = _has_local_evidence_for_question(
            direct_reply=None,
            retrieval_context=retrieval_context,
            summary_retrieval_context=summary_retrieval_context,
            history_context=history_context,
            memory_context=memory_context,
            simple_definition_hit=False,
            explicit_history_hit=False,
        )
        if not local_ok:
            evidence_query = str(web_query or prompt or "").strip()
            evidence_context, evidence_count, evidence_titles, top_score, evidence_error = await _build_generic_web_evidence_context(
                config, evidence_query
            )
            tool_notes.append("web_evidence=1")
            tool_notes.append(f"web_evidence_query={evidence_query}")
            tool_notes.append(f"web_evidence_result_count={evidence_count}")
            tool_notes.append(f"web_evidence_top_titles={' || '.join(evidence_titles)}")
            tool_notes.append(f"web_evidence_context_chars={len(evidence_context)}")
            tool_notes.append(f"web_evidence_top_score={top_score:.3f}")
            if evidence_error:
                tool_notes.append(f"web_evidence_error={evidence_error[:120]}")
            min_score = 0.35
            if evidence_context and top_score >= min_score:
                tool_notes.append("evidence_gate_source=web")
                return {
                    "direct_reply": None,
                    "should_call_llm": True,
                    "web_used": True,
                    "time_context": time_context,
                    "profile_context": profile_context,
                    "group_context": group_context,
                    "retrieval_context": "",
                    "style_context": "",
                    "summary_retrieval_context": "",
                    "history_context": "",
                    "memory_context": "",
                    "web_context": "",
                    "lightweight_mode": "web_evidence",
                    "lightweight_prompt": prompt,
                    "web_evidence_query": evidence_query,
                    "web_evidence_context": evidence_context,
                    "tool_notes": "\n".join(tool_notes).strip(),
                }
            if evidence_context and top_score < min_score:
                tool_notes.append("web_evidence_low_score=1")
            tool_notes.append("evidence_gate_source=none")
            tool_notes.append("evidence_gate_no_answer=1")
            unknown_reply = "\u6682\u65f6\u6ca1\u67e5\u5230\u53ef\u9760\u8d44\u6599\uff0c\u6211\u4e0d\u77e5\u9053\u3002"
            if evidence_error == "no_recent_within_1y":
                unknown_reply = "\u6682\u65f6\u6ca1\u67e5\u5230\u4e00\u5e74\u5185\u7684\u53ef\u9760\u8d44\u6599\uff0c\u6211\u4e0d\u77e5\u9053\u3002"
            return {
                "direct_reply": unknown_reply,
                "should_call_llm": False,
                "web_used": True,
                "time_context": time_context,
                "profile_context": profile_context,
                "group_context": group_context,
                "retrieval_context": "",
                "style_context": "",
                "summary_retrieval_context": "",
                "history_context": "",
                "memory_context": "",
                "web_context": "",
                "tool_notes": "\n".join(tool_notes).strip(),
            }
        tool_notes.append("evidence_gate_source=local")
    if intent.kind == "local_context":
        tool_notes.append("evidence_gate=1")
        tool_notes.append("evidence_gate_source=local")
        tool_notes.append("evidence_gate_no_answer=1")
        return {
            "direct_reply": "\u672c\u5730\u8bb0\u5f55\u91cc\u6682\u65f6\u6ca1\u67e5\u5230\u53ef\u9760\u4fe1\u606f\uff0c\u6211\u4e0d\u77e5\u9053\u3002",
            "should_call_llm": False,
            "web_used": False,
            "time_context": time_context,
            "profile_context": profile_context,
            "group_context": group_context,
            "retrieval_context": "",
            "style_context": "",
            "summary_retrieval_context": "",
            "history_context": "",
            "memory_context": "",
            "web_context": "",
            "tool_notes": "\n".join(tool_notes).strip(),
        }
    if _is_simple_definition_question(prompt, intent.kind):
        tool_notes.append("simple_definition_routed_to_evidence=1")
    if is_identity_question:
        tool_notes.append("identity_question_no_web")
    elif intent.kind == "current_fact":
        if web_enabled:
            web_context, web_meta = await _build_ranked_web_context(config, web_query, intent, prompt, tool_notes)
            if web_context:
                web_relevance_score = score_text_overlap(prompt, web_context)
                gate_adjust = float((web_meta or {}).get("gate_adjust", 0.0) or 0.0)
                web_final_score = max(0.0, min(1.0, web_relevance_score + gate_adjust))
                tool_notes.append(f"web_relevance_score={web_relevance_score:.2f}")
                tool_notes.append(f"web_final_score={web_final_score:.2f}")
                if web_final_score >= web_final_threshold:
                    web_used = True
                    tool_notes.append(f"web_score={web_relevance_score:.2f}")
                elif web_relevance_score < 0.15:
                    web_context = ""
                    tool_notes.append("web_low_relevance_or_stale")
            if not web_context:
                tool_notes.append("web_search_failed")
        else:
            tool_notes.append("web_disabled")
    elif needs_reliable_context:
        if retrieval_context and retrieval_score >= retrieval_threshold:
            tool_notes.append("retrieval_source=db")
            tool_notes.append(f"retrieval_score={retrieval_score:.2f}")
            if should_web and web_enabled and route_like and embedding_status != "reliable":
                web_context, _ = await _build_ranked_web_context(config, web_query, intent, prompt, tool_notes)
                if web_context:
                    web_score = score_text_overlap(prompt, web_context)
                    web_final_score = web_score
                    if web_score >= web_relevance_threshold and web_final_score >= web_final_threshold:
                        web_used = True
                        tool_notes.append(f"web_score={web_score:.2f}")
                    else:
                        web_context = ""
                        tool_notes.append("web_low_relevance_or_stale")
                if not web_context:
                    tool_notes.append("web_search_failed")
        else:
            if should_web and web_enabled:
                web_context, _ = await _build_ranked_web_context(config, web_query, intent, prompt, tool_notes)
                if web_context:
                    web_score = score_text_overlap(prompt, web_context)
                    web_final_score = web_score
                    if web_score >= web_relevance_threshold and web_final_score >= web_final_threshold:
                        web_used = True
                        tool_notes.append(f"web_score={web_score:.2f}")
                    else:
                        web_context = ""
                        tool_notes.append("web_low_relevance_or_stale")
                if not web_context:
                    tool_notes.append("web_search_failed")
                    if str(getattr(config, "chat_agent_web_mode", "auto")).lower() == "auto" and route_like:
                        tool_notes.append("fact_sensitive_no_web")
            elif should_web and not web_enabled:
                tool_notes.append("web_disabled")
    else:
        tool_notes.append("free_generation_no_web")

    if (
        intent.needs_reliable_context
        and not time_context
        and retrieval_score < retrieval_threshold
        and not web_context
        and not retrieval_context
        and not summary_retrieval_context
    ):
        tool_notes.append("reliable_context_not_found")
        tool_notes.append("没有找到足够可靠的资料，请直接说明资料不足，不要编造。")

    if memory_reminder:
        tool_notes.append("memory_reminder_ready")

    return {
        "direct_reply": None,
        "should_call_llm": True,
        "web_used": web_used,
        "time_context": time_context,
        "profile_context": profile_context,
        "group_context": group_context,
        "retrieval_context": retrieval_context,
        "style_context": style_context,
        "skill_context": skill_context,
        "skill_evidence_context": skill_evidence_context,
        "summary_retrieval_context": summary_retrieval_context,
        "history_context": history_context,
        "memory_context": memory_context,
        "web_context": web_context,
        "question_like": question_intent.is_question_like,
        "question_category": question_intent.category,
        "question_web_eligible": question_intent.web_eligible,
        "tool_notes": "\n".join(tool_notes).strip(),
    }
