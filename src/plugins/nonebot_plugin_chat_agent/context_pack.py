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
from .url_tools import build_direct_url_context, extract_urls
from .web_tools import build_web_context, build_web_results, render_web_results_context, resolve_official_web_answer
from datetime import datetime
import re
from urllib.parse import urlparse

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


async def build_context_pack(config, session_info: dict, prompt: str, bot=None, event=None) -> dict:
    intent = classify_tool_intent(prompt)
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
    tool_notes.append(f"intent={intent.kind}")

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
        if intent.kind not in ("creative", "time", "current_fact"):
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
    elif intent.kind == "current_fact":
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
    elif is_identity_question:
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
        "summary_retrieval_context": summary_retrieval_context,
        "history_context": history_context,
        "memory_context": memory_context,
        "web_context": web_context,
        "tool_notes": "\n".join(tool_notes).strip(),
    }
