from __future__ import annotations

from nonebot import get_driver, logger, on_message
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, MessageEvent, MessageSegment, PrivateMessageEvent
from nonebot.rule import Rule
from nonebot.typing import T_State

from .config import get_chat_agent_config
from .runtime.context_pack import build_context_pack
from .clients.llm_client import chat_completions
from .skills.internal_actions import run_internal_skill_action
from .skills.internal_actions import get_registered_internal_actions
from .memory.memory import detect_feedback
from .stores.profile_store import init_profile_storage, upsert_user_seen
from .answer.prompt import build_system_prompt
from .stores.retrieval_store import init_retrieval_storage
from .runtime.runtime_state import get_chat_agent_lock
from .stores.storage import build_session_info, init_storage, save_memory, save_message
from .tools.utils import extract_group_prompt, extract_private_prompt, get_bot_nicknames, get_original_plain_text, sanitize_task_reply, strip_thinking, truncate_reply
from .answer import (
    build_definition_quality_fallback,
    build_sports_quality_fallback,
    definition_quality_reason,
    is_unknown_like_reply,
    should_retry_short_answer,
    sports_quality_reason,
)
from .answer.finalizer import build_web_evidence_messages, evaluate_web_evidence_reply
from .answer.finalizer import handle_unknown_like_retry
from .decision.classifier import (
    build_decision_classifier_messages,
    parse_decision_classifier_reply,
    validate_decision_candidate,
)
from .decision.policy import load_decision_policy


async def chat_agent_rule(bot: Bot, event: MessageEvent, state: T_State) -> bool:
    config = get_chat_agent_config()
    if not config.chat_agent_enable:
        return False

    if isinstance(event, GroupMessageEvent):
        prompt = extract_group_prompt(event, bot.self_id)
        if prompt is None:
            return False
        state["chat_agent_prompt"] = prompt
        state["chat_agent_is_group"] = True
        return True

    if isinstance(event, PrivateMessageEvent):
        prompt = extract_private_prompt(get_original_plain_text(event), get_bot_nicknames())
        if prompt is None:
            return False
        state["chat_agent_prompt"] = prompt
        state["chat_agent_is_group"] = False
        return True

    return False


chat_agent = on_message(rule=Rule(chat_agent_rule), priority=4, block=True)

driver = get_driver()


def _with_group_at(event: MessageEvent, is_group: bool, text: str):
    if not is_group:
        return text
    return MessageSegment.at(event.user_id) + MessageSegment.text(" " + text)


def _append_system(messages: list[dict], content: str) -> None:
    text = str(content or "").strip()
    if text:
        messages.append({"role": "system", "content": text})


def _should_sanitize_task_reply(prompt: str, context_pack: dict) -> bool:
    text = (prompt or "").strip()
    if any(token in text for token in ["你是谁", "自我介绍", "可爱语气", "安慰", "陪聊", "角色扮演"]):
        return False
    if context_pack.get("retrieval_context") or context_pack.get("web_context"):
        return True
    notes = str(context_pack.get("tool_notes", "") or "")
    return any(
        token in notes
        for token in [
            "embedding_retrieval=reliable",
            "web_score=",
            "reliable_context_not_found",
            "memory_reminder_ready",
        ]
    )




@driver.on_startup
async def _init_chat_agent_storage() -> None:
    config = get_chat_agent_config()
    config.ensure_data_dir()
    if config.chat_agent_enable_history or config.chat_agent_enable_feedback_memory:
        await init_storage(config)
    await init_profile_storage(config)
    await init_retrieval_storage(config)


@chat_agent.handle()
async def _(bot: Bot, event: MessageEvent, state: T_State):
    config = get_chat_agent_config()
    prompt = state.get("chat_agent_prompt", "").strip()
    is_group = bool(state.get("chat_agent_is_group", isinstance(event, GroupMessageEvent)))
    session_info = build_session_info(event)

    try:
        await upsert_user_seen(config, session_info)
    except Exception:
        pass

    if not prompt:
        await chat_agent.finish("叫我有什么事？" if is_group else "你想聊什么呀？")
        return

    lock = get_chat_agent_lock()
    if lock.locked():
        await chat_agent.finish(_with_group_at(event, is_group, config.chat_agent_locked_reply))
        return

    await lock.acquire()
    try:
        await chat_agent.send(_with_group_at(event, is_group, config.chat_agent_busy_reply))

        feedback = detect_feedback(prompt) if config.chat_agent_enable_feedback_memory else None
        if feedback is not None:
            try:
                await save_memory(config, session_info, feedback)
            except Exception:
                pass

        context_pack = await build_context_pack(config, session_info, prompt, bot=bot, event=event)
        if bool(context_pack.get("decision_classifier_observe_enabled", False)):
            try:
                catalog_text = str(context_pack.get("decision_classifier_catalog", "") or "").strip()
                if catalog_text:
                    messages = build_decision_classifier_messages(
                        str(context_pack.get("decision_classifier_prompt", prompt) or prompt),
                        catalog_text,
                    )
                    model_name = str(getattr(config, "chat_agent_decision_classifier_model", "") or "").strip() or None
                    timeout_s = max(3, int(getattr(config, "chat_agent_decision_classifier_timeout", 10) or 10))
                    max_tokens = max(64, int(getattr(config, "chat_agent_decision_classifier_max_tokens", 160) or 160))
                    raw = await chat_completions(
                        messages,
                        config,
                        model=model_name,
                        timeout=float(timeout_s),
                        max_tokens=max_tokens,
                    )
                    candidate = parse_decision_classifier_reply(raw)
                    if candidate is None:
                        logger.info(
                            f"decision_classifier_observe accepted=0 reason=parse_failed current_route={context_pack.get('decision_route','')}"
                        )
                    else:
                        policy = load_decision_policy(getattr(config, "chat_agent_decision_policy_path", None))
                        entries = context_pack.get("decision_classifier_entries", []) or []
                        validated = validate_decision_candidate(
                            candidate,
                            entries,
                            policy,
                            get_registered_internal_actions(),
                        )
                        if validated is None:
                            logger.info(
                                f"decision_classifier_observe accepted=0 reason=validation_failed current_route={context_pack.get('decision_route','')}"
                            )
                        else:
                            logger.info(
                                "decision_classifier_observe accepted=1 "
                                f"route={validated.route} skill={validated.skill_name or ''} "
                                f"action={validated.action_name or ''} confidence={candidate.confidence:.2f} "
                                f"current_route={context_pack.get('decision_route','')} reason={candidate.reason[:80]}"
                            )
            except Exception as e:
                logger.info(
                    f"decision_classifier_observe accepted=0 reason=llm_error current_route={context_pack.get('decision_route','')} error={type(e).__name__}"
                )
        action_name = str(context_pack.get("internal_skill_action", "")).strip()
        action_route = str(context_pack.get("internal_skill_route", "")).strip()
        if action_name and action_route == "direct_message":
            logger.info(f"internal_skill_action name={action_name} route=direct_message selected=1")
            result = await run_internal_skill_action(action_name)
            if result and result.image_url:
                logger.info(f"internal_skill_action name={action_name} success=1 type=image")
                await chat_agent.finish(MessageSegment.image(result.image_url))
                return
            if result and result.text:
                logger.info(f"internal_skill_action name={action_name} success=0 error=no_image")
                await chat_agent.finish(_with_group_at(event, is_group, result.text))
                return
            logger.info(f"internal_skill_action name={action_name} success=0 error=empty_result")
            await chat_agent.finish(_with_group_at(event, is_group, "该内部能力暂时不可用。"))
            return
        if context_pack.get("direct_reply"):
            reply = context_pack["direct_reply"]
            if _should_sanitize_task_reply(prompt, context_pack):
                reply = sanitize_task_reply(reply) or reply
            if config.chat_agent_enable_history:
                try:
                    await save_message(config, session_info, "user", prompt)
                    await save_message(config, session_info, "assistant", reply)
                except Exception:
                    pass
            await chat_agent.finish(_with_group_at(event, is_group, reply))
            return

        if str(context_pack.get("lightweight_mode", "")).strip() == "web_strategy":
            strategy_prompt = str(context_pack.get("lightweight_prompt", prompt) or prompt).strip()
            strategy_query = str(context_pack.get("web_strategy_query", strategy_prompt) or strategy_prompt).strip()
            strategy_context = str(context_pack.get("web_strategy_context", "") or "").strip()
            strategy_model = str(
                getattr(config, "chat_agent_lightweight_definition_model", "") or "llama32-finalizer-fast"
            ).strip()
            strategy_timeout = min(
                180.0,
                max(10.0, float(getattr(config, "chat_agent_web_strategy_timeout", 60.0) or 60.0)),
            )
            strategy_max_tokens = int(getattr(config, "chat_agent_web_strategy_max_tokens", 700) or 700)
            strategy_max_tokens = min(2048, max(128, strategy_max_tokens))
            strategy_messages = [
                {
                    "role": "system",
                    "content": (
                        "You answer in Chinese using the distilled web notes.\n"
                        "Give a practical answer in 2-5 short sentences.\n"
                        "Answer the user's actual question directly.\n"
                        "Do not summarize the source article itself.\n"
                        "Start with a concrete recommendation or conclusion.\n"
                        "Then give 2-4 short reasons from the notes.\n"
                        "If evidence is weak, say it is uncertain, but still provide a cautious recommendation when possible.\n"
                        "Avoid phrases like \"this article discusses\", \"the text mainly talks about\", or \"the document says\" unless the user asked to summarize an article.\n"
                        "This may include game strategy, tech-tree lines, country/civilization choices, weapon choices, or build recommendations.\n"
                        "For game questions, it is safe to recommend in-game countries, factions, tech-tree lines, weapons, builds, or openings.\n"
                        "Do not refuse unless the request is about real-world harm.\n"
                        "Prefer consensus from the notes.\n"
                        "Mention uncertainty if sources are weak or version-dependent.\n"
                        "Do not invent details not present in the notes."
                    ),
                },
                {
                    "role": "user",
                    "content": f"Question: {strategy_prompt}\nQuery: {strategy_query}\n\n{strategy_context}",
                },
            ]
            reply = ""
            should_save_assistant = False
            try:
                reply = await chat_completions(
                    strategy_messages,
                    config,
                    timeout=strategy_timeout,
                    model=strategy_model,
                    temperature=0.35,
                    top_p=0.7,
                    max_tokens=strategy_max_tokens,
                )
                reply = truncate_reply(strip_thinking(reply), config.chat_agent_max_reply_length)
                reply = str(reply or "").strip()
                if not reply:
                    logger.warning(
                        f"web_strategy empty reply model={strategy_model} timeout={strategy_timeout} "
                        f"max_tokens={strategy_max_tokens} context_chars={len(strategy_context)} "
                        f"prompt={strategy_prompt[:80]!r}"
                    )
                    reply = "\u6682\u65f6\u6ca1\u67e5\u5230\u7a33\u5b9a\u7684\u653b\u7565\u8d44\u6599\uff0c\u53ef\u4ee5\u6362\u4e2a\u66f4\u5177\u4f53\u7684\u95ee\u9898\u3002"
                else:
                    logger.info(
                        f"web_strategy success model={strategy_model} timeout={strategy_timeout} "
                        f"max_tokens={strategy_max_tokens} reply_chars={len(reply)} prompt={strategy_prompt[:80]!r}"
                    )
                    summary_prefixes = [
                        "\u8fd9\u7bc7\u6587\u7ae0",
                        "\u8fd9\u4e2a\u6587\u672c",
                        "\u8be5\u6587",
                        "\u8d44\u6599\u4e3b\u8981",
                        "\u6587\u4e2d\u63d0\u5230",
                    ]
                    if any(reply.startswith(prefix) for prefix in summary_prefixes):
                        logger.warning(
                            f"web_strategy summary_style_reply prompt={strategy_prompt[:80]!r} "
                            f"reply_prefix={reply[:40]!r}"
                        )
                should_save_assistant = bool(reply)
            except Exception as e:
                logger.warning(
                    f"web_strategy failed type={type(e).__name__} model={strategy_model} "
                    f"timeout={strategy_timeout} max_tokens={strategy_max_tokens} "
                    f"context_chars={len(strategy_context)} prompt={strategy_prompt[:80]!r} message={str(e)[:200]!r}"
                )
                reply = "\u6682\u65f6\u6ca1\u67e5\u5230\u7a33\u5b9a\u7684\u653b\u7565\u8d44\u6599\uff0c\u53ef\u4ee5\u6362\u4e2a\u66f4\u5177\u4f53\u7684\u95ee\u9898\u3002"
            if _should_sanitize_task_reply(prompt, context_pack):
                reply = sanitize_task_reply(reply) or reply
            if config.chat_agent_enable_history and reply and should_save_assistant:
                try:
                    await save_message(config, session_info, "user", prompt)
                    await save_message(config, session_info, "assistant", reply)
                except Exception:
                    pass
            await chat_agent.finish(_with_group_at(event, is_group, reply))
            return

        if str(context_pack.get("lightweight_mode", "")).strip() == "web_evidence":
            evidence_prompt = str(context_pack.get("lightweight_prompt", prompt) or prompt).strip()
            evidence_query = str(context_pack.get("web_evidence_query", evidence_prompt) or evidence_prompt).strip()
            evidence_context = str(context_pack.get("web_evidence_context", "") or "").strip()
            evidence_model = str(
                getattr(config, "chat_agent_lightweight_definition_model", "") or "llama32-finalizer-fast"
            ).strip()
            evidence_timeout = min(
                180.0,
                max(10.0, float(getattr(config, "chat_agent_web_strategy_timeout", 60.0) or 60.0)),
            )
            evidence_max_tokens = int(getattr(config, "chat_agent_web_strategy_max_tokens", 700) or 700)
            evidence_max_tokens = min(2048, max(128, evidence_max_tokens))
            tool_notes = str(context_pack.get("tool_notes", "") or "")
            answerable = "web_evidence_answerable=1" in tool_notes
            sports_stats_first = "web_evidence answer_style=sports_stats_first" in tool_notes
            definition_summary = "web_evidence answer_style=definition_summary" in tool_notes
            style_extra = ""
            if sports_stats_first:
                style_extra += (
                    "\n【体育回答要求】优先基于数据页/球员页/技术统计页回答。"
                    "用户问“最近表现”时，先总结最近表现，不要回答淘汰原因。"
                    "禁止根据新闻标题推测因果。不要编造具体得分/篮板/助攻数字；"
                    "若资料未给出明确数字，直接说明“当前资料没有给出可确认的具体数据”。"
                )
            if definition_summary:
                style_extra += (
                    "\n【定义回答要求】先给一句定义，再给1-2点特征。"
                    "避免宣传化措辞，回答不要过短。"
                )
            evidence_messages = build_web_evidence_messages(
                prompt=evidence_prompt,
                query=evidence_query,
                evidence_context=evidence_context,
                style_extra=style_extra,
            )
            reply = ""
            should_save_assistant = False
            try:
                reply = await chat_completions(
                    evidence_messages,
                    config,
                    timeout=evidence_timeout,
                    model=evidence_model,
                    temperature=0.35,
                    top_p=0.7,
                    max_tokens=evidence_max_tokens,
                )
                reply = truncate_reply(strip_thinking(reply), config.chat_agent_max_reply_length)
                reply = str(reply or "").strip()
                if not reply:
                    logger.warning(
                        f"web_evidence llm empty model={evidence_model} timeout={evidence_timeout} "
                        f"max_tokens={evidence_max_tokens} context_chars={len(evidence_context)} "
                        f"prompt={evidence_prompt[:80]!r}"
                    )
                    reply = "\u6682\u65f6\u6ca1\u67e5\u5230\u53ef\u9760\u8d44\u6599\uff0c\u53ef\u4ee5\u6362\u4e2a\u66f4\u5177\u4f53\u7684\u95ee\u9898\u3002"
                else:
                    logger.info(
                        f"web_evidence llm success model={evidence_model} timeout={evidence_timeout} "
                        f"max_tokens={evidence_max_tokens} reply_chars={len(reply)} prompt={evidence_prompt[:80]!r}"
                    )
                should_save_assistant = bool(reply)
            except Exception as e:
                logger.warning(
                    f"web_evidence llm failed type={type(e).__name__} model={evidence_model} "
                    f"timeout={evidence_timeout} max_tokens={evidence_max_tokens} "
                    f"context_chars={len(evidence_context)} prompt={evidence_prompt[:80]!r} message={str(e)[:200]!r}"
                )
                reply = "\u6682\u65f6\u6ca1\u67e5\u5230\u53ef\u9760\u8d44\u6599\uff0c\u53ef\u4ee5\u6362\u4e2a\u66f4\u5177\u4f53\u7684\u95ee\u9898\u3002"
            if evaluate_web_evidence_reply(
                reply,
                answerable=answerable,
                answer_style="",
                unknown_reply="璧勬枡涓嶈冻浠ョ‘璁?",
            ) == "unknown_like":
                logger.warning("web_evidence over_refusal=1 reply_matches_unknown=1 answerable=1")
                retry_fallback = build_definition_quality_fallback(evidence_context, evidence_prompt)
                retry_system_prompt = "褰撳墠鍙傝€冭祫鏂欏凡缁忚冻浠ユ敮鎸佸熀鏈粨璁恒€傜姝㈠洖澶嶈祫鏂欎笉瓒炽€傝鍩轰簬鍙傝€冭祫鏂欑粰鍑轰竴鍙ョ粨璁哄拰涓€鍒颁袱鐐逛緷鎹€?"

                async def _unknown_retry_call(messages: list[dict]) -> str:
                    return await chat_completions(
                        messages,
                        config,
                        timeout=evidence_timeout,
                        model=evidence_model,
                        temperature=0.2,
                        top_p=0.7,
                        max_tokens=evidence_max_tokens,
                    )

                def _clean_unknown_retry(text: str) -> str:
                    cleaned = truncate_reply(strip_thinking(text), config.chat_agent_max_reply_length)
                    return str(cleaned or "").strip()

                reply, _ = await handle_unknown_like_retry(
                    reply,
                    answerable=answerable,
                    evidence_messages=evidence_messages,
                    llm_call=_unknown_retry_call,
                    clean_reply=_clean_unknown_retry,
                    fallback_reply=retry_fallback,
                    unknown_reply="璧勬枡涓嶈冻浠ョ‘璁?",
                    retry_system_prompt=retry_system_prompt,
                )
            if evaluate_web_evidence_reply(
                reply,
                answerable=answerable,
                answer_style="",
                unknown_reply=None,
                min_chars=25,
            ) == "short_answer":
                logger.info(f"web_evidence short_answer_retry=1 reply_chars={len(str(reply or '').strip())}")
                retry_short_messages = list(evidence_messages)
                retry_short_messages.insert(
                    1,
                    {
                        "role": "system",
                        "content": "回答太短。请基于参考资料，用一句定义或结论 + 两点依据回答。不要宣传化，不要编造。",
                    },
                )
                try:
                    retry_short = await chat_completions(
                        retry_short_messages,
                        config,
                        timeout=evidence_timeout,
                        model=evidence_model,
                        temperature=0.25,
                        top_p=0.7,
                        max_tokens=evidence_max_tokens,
                    )
                    retry_short = truncate_reply(strip_thinking(retry_short), config.chat_agent_max_reply_length)
                    retry_short = str(retry_short or "").strip()
                    if retry_short:
                        short_reason = ""
                        if definition_summary:
                            short_reason = definition_quality_reason(retry_short)
                        elif sports_stats_first:
                            short_reason = sports_quality_reason(retry_short)
                        elif len(retry_short) < 45:
                            short_reason = "too_short"
                        if short_reason:
                            logger.info(
                                f"web_evidence retry_still_bad=1 kind=short_answer reason={short_reason} retry_chars={len(retry_short)}"
                            )
                        else:
                            reply = retry_short
                            logger.info(
                                f"web_evidence retry_success=1 kind=short_answer retry_chars={len(reply)}"
                            )
                except Exception:
                    pass
            definition_reason = (
                evaluate_web_evidence_reply(
                    reply,
                    answerable=answerable,
                    answer_style="definition_summary",
                    unknown_reply=None,
                    min_chars=45,
                )
                if answerable and definition_summary
                else ""
            )
            if definition_reason == "definition_quality":
                definition_reason = "definition_quality"
            elif definition_reason == "short_answer":
                definition_reason = "too_short"
            elif definition_reason == "ok":
                definition_reason = ""
            if definition_reason:
                logger.info(
                    f"web_evidence definition_quality_retry=1 reason={definition_reason} "
                    f"reply_chars={len(str(reply or '').strip())}"
                )
                retry_def_messages = list(evidence_messages)
                retry_def_messages.insert(
                    1,
                    {
                        "role": "system",
                        "content": "回答太短或结构不完整。请基于参考资料，用一句定义 + 两点特征回答；不要宣传化，不要编造。",
                    },
                )
                try:
                    retry_def = await chat_completions(
                        retry_def_messages,
                        config,
                        timeout=evidence_timeout,
                        model=evidence_model,
                        temperature=0.25,
                        top_p=0.7,
                        max_tokens=evidence_max_tokens,
                    )
                    retry_def = truncate_reply(strip_thinking(retry_def), config.chat_agent_max_reply_length)
                    retry_def = str(retry_def or "").strip()
                    if retry_def:
                        def_reason_retry = definition_quality_reason(retry_def)
                        if def_reason_retry:
                            logger.info(
                                f"web_evidence retry_still_bad=1 kind=definition_quality reason={def_reason_retry} retry_chars={len(retry_def)}"
                            )
                        else:
                            reply = retry_def
                            logger.info(f"web_evidence retry_success=1 kind=definition_quality retry_chars={len(reply)}")
                except Exception:
                    logger.info("web_evidence retry_still_bad=1 kind=definition_quality")
            definition_reason_final = (definition_quality_reason(reply) or "") if answerable and definition_summary else ""
            if definition_reason_final:
                reply = build_definition_quality_fallback(evidence_context, evidence_prompt)
                if len(reply) < 45:
                    reply = f"根据当前网页资料：{reply}。简单说，它是一款以精灵收集与养成为核心的冒险游戏；主要特征包括开放世界探索和宠物培养对战。"
                logger.info(f"web_evidence definition_quality_fallback=1 reason={definition_reason_final}")
            sports_reason = (
                evaluate_web_evidence_reply(
                    reply,
                    answerable=answerable,
                    answer_style="sports_stats_first",
                    unknown_reply=None,
                    min_chars=45,
                )
                if answerable and sports_stats_first
                else ""
            )
            if sports_reason == "sports_quality":
                sports_reason = "bad_generic"
            elif sports_reason == "short_answer":
                sports_reason = "too_short"
            elif sports_reason == "ok":
                sports_reason = ""
            if sports_reason:
                logger.info(f"web_evidence sports_quality_retry=1 reason={sports_reason}")
                retry_sports_messages = list(evidence_messages)
                retry_sports_messages.insert(
                    1,
                    {
                        "role": "system",
                        "content": "不要解释淘汰原因，不要使用标题推测因果，不要编造得分篮板助攻。若无具体数字，请说明当前资料没有提取到可确认的近期数据。",
                    },
                )
                try:
                    retry_sports = await chat_completions(
                        retry_sports_messages,
                        config,
                        timeout=evidence_timeout,
                        model=evidence_model,
                        temperature=0.2,
                        top_p=0.7,
                        max_tokens=evidence_max_tokens,
                    )
                    retry_sports = truncate_reply(strip_thinking(retry_sports), config.chat_agent_max_reply_length)
                    retry_sports = str(retry_sports or "").strip()
                    if retry_sports and not sports_quality_reason(retry_sports):
                        reply = retry_sports
                        logger.info(f"web_evidence retry_success=1 kind=sports_quality retry_chars={len(reply)}")
                    else:
                        reply = build_sports_quality_fallback(evidence_context)
                        logger.info("web_evidence retry_still_bad=1 kind=sports_quality reason=bad_generic")
                        logger.info("web_evidence sports_quality_fallback=1 reason=bad_generic")
                except Exception:
                    reply = build_sports_quality_fallback(evidence_context)
                    logger.info("web_evidence retry_still_bad=1 kind=sports_quality reason=retry_exception")
                    logger.info("web_evidence sports_quality_fallback=1 reason=retry_exception")
            if _should_sanitize_task_reply(prompt, context_pack):
                reply = sanitize_task_reply(reply) or reply
            if config.chat_agent_enable_history and reply and should_save_assistant:
                try:
                    await save_message(config, session_info, "user", prompt)
                    await save_message(config, session_info, "assistant", reply)
                except Exception:
                    pass
            await chat_agent.finish(_with_group_at(event, is_group, reply))
            return

        if str(context_pack.get("lightweight_mode", "")).strip() == "definition":
            lightweight_prompt = str(context_pack.get("lightweight_prompt", prompt) or prompt).strip()
            lightweight_messages = [
                {
                    "role": "system",
                    "content": (
                        "You explain technical concepts in Chinese.\n"
                        "Answer in 1-3 short sentences.\n"
                        "Only explain what the term is and its common use.\n"
                        "Do not mention author, company, year, license, latest version, price, news, "
                        "or history unless the user explicitly asks.\n"
                        "If you are not sure, say you are not sure.\n"
                        "Do not guess."
                    ),
                },
                {"role": "user", "content": lightweight_prompt or prompt},
            ]
            lightweight_model = str(
                getattr(config, "chat_agent_lightweight_definition_model", "") or "llama32-finalizer-fast"
            ).strip()
            lightweight_timeout = float(
                getattr(config, "chat_agent_lightweight_definition_timeout", 20.0) or 20.0
            )
            tool_notes = str(context_pack.get("tool_notes", "") or "")
            reply = ""
            should_save_assistant = False
            try:
                reply = await chat_completions(
                    lightweight_messages,
                    config,
                    timeout=lightweight_timeout,
                    model=lightweight_model,
                    temperature=0.2,
                    top_p=0.6,
                    max_tokens=180,
                )
                reply = truncate_reply(strip_thinking(reply), config.chat_agent_max_reply_length)
                reply = str(reply or "").strip()
                if not reply:
                    logger.warning(
                        f"lightweight definition empty reply model={lightweight_model} timeout={lightweight_timeout} "
                        f"prompt={(lightweight_prompt or prompt)[:80]!r}"
                    )
                    reply = "\u8fd9\u4e2a\u6982\u5ff5\u6211\u6682\u65f6\u6ca1\u6cd5\u7a33\u5b9a\u751f\u6210\u89e3\u91ca\uff0c\u53ef\u4ee5\u7a0d\u540e\u518d\u8bd5\u3002"
                should_save_assistant = bool(reply)
            except Exception as e:
                logger.warning(
                    f"lightweight definition failed type={type(e).__name__} model={lightweight_model} "
                    f"timeout={lightweight_timeout} "
                    "temperature=0.2 top_p=0.6 max_tokens=180 "
                    f"prompt={(lightweight_prompt or prompt)[:80]!r} "
                    f"message={str(e)[:200]!r}"
                )
                reply = "\u8fd9\u4e2a\u6982\u5ff5\u6211\u6682\u65f6\u6ca1\u6cd5\u7a33\u5b9a\u751f\u6210\u89e3\u91ca\uff0c\u53ef\u4ee5\u7a0d\u540e\u518d\u8bd5\u3002"
                if tool_notes:
                    tool_notes += "\n"
                tool_notes += f"simple_definition_lightweight_error={str(e)[:120]}"
            if _should_sanitize_task_reply(prompt, context_pack):
                reply = sanitize_task_reply(reply) or reply
            if config.chat_agent_enable_history and reply and should_save_assistant:
                try:
                    await save_message(config, session_info, "user", prompt)
                    await save_message(config, session_info, "assistant", reply)
                except Exception:
                    pass
            await chat_agent.finish(_with_group_at(event, is_group, reply))
            return

        messages = [{"role": "system", "content": build_system_prompt()}]
        skill_evidence_context = str(context_pack.get("skill_evidence_context", "") or "").strip()
        if skill_evidence_context:
            _append_system(messages, "Relevant evidence instructions:\n" + skill_evidence_context)
        skill_context = str(context_pack.get("skill_context", "") or "").strip()
        if skill_context:
            _append_system(messages, "Relevant skill instructions:\n" + skill_context)
        _append_system(messages, context_pack.get("time_context", ""))
        _append_system(messages, context_pack.get("profile_context", ""))
        _append_system(messages, context_pack.get("group_context", ""))

        style_context = str(context_pack.get("style_context", "") or "").strip()
        if style_context:
            _append_system(
                messages,
                "你会收到“回复风格提示”。这只用于调整语气、长度和格式。不要向用户提到画像、历史或系统提示。",
            )
            _append_system(messages, "回复风格提示：\n" + style_context)

        retrieval_context = str(context_pack.get("retrieval_context", "") or "").strip()
        if retrieval_context:
            _append_system(
                messages,
                "\n".join(
                    [
                        "本地资料使用规则：",
                        "- 下面是本地检索资料。",
                        "- 只在和用户问题直接相关时使用。",
                        "- 不要编造资料中没有的信息。",
                    ]
                ),
            )
            _append_system(messages, "本地检索到的相关资料：\n" + retrieval_context)

        summary_retrieval_context = str(context_pack.get("summary_retrieval_context", "") or "").strip()
        if summary_retrieval_context:
            _append_system(
                messages,
                "\n".join(
                    [
                        "历史摘要使用规则：",
                        "- 下面内容只用于用户明确询问“之前/历史/谁说过/聊过/提过”等场景。",
                        "- 只能复述或概括历史摘要里的线索。",
                        "- 不要把历史摘要扩写成通用事实。",
                        "- 如果摘要不足，回答“历史摘要里没找到足够可靠线索”。",
                    ]
                ),
            )
            _append_system(messages, "历史聊天摘要检索结果：\n" + summary_retrieval_context)

        memory_context = str(context_pack.get("memory_context", "") or "").strip()
        if memory_context:
            _append_system(
                messages,
                "\n".join(
                    [
                        "长期记忆使用规则：",
                        "- 只用于个性化和已确认偏好。",
                        "- 不要把记忆当成当前事实来源。",
                        "- 不要主动暴露记忆内容。",
                    ]
                ),
            )
            _append_system(messages, memory_context)

        history_context = str(context_pack.get("history_context", "") or "").strip()
        if history_context:
            _append_system(messages, "最近对话：\n" + history_context)

        tool_notes = str(context_pack.get("tool_notes", "") or "").strip()
        is_direct_url_mode = "direct_url_mode=1" in tool_notes

        web_context = str(context_pack.get("web_context", "") or "").strip()
        if web_context:
            if is_direct_url_mode:
                _append_system(
                    messages,
                    "\n".join(
                        [
                            "链接内容使用规则：",
                            "- 下面是用户提供链接的读取结果。",
                            "- 优先根据链接内容回答。",
                            "- 如果内容不足，明确说明。",
                        ]
                    ),
                )
                _append_system(messages, "链接读取结果：\n" + web_context)
            else:
                _append_system(
                    messages,
                    "\n".join(
                        [
                            "联网资料使用规则：",
                            "- 下面的联网资料是候选资料，不保证都正确。",
                            "- 优先使用 official/docs/current-year/recent-year 来源。",
                            "- 对 stale-year/rumor/forum/seo 来源保持低置信。",
                            "- 如果官方或权威来源没有明确参数，不要硬编；回答“官方资料未明确，以官方发布为准”。",
                            "- 不要把传闻、旧页面或论坛内容当成确定事实。",
                            "- 如果资料冲突，说明低置信，并优先官方/较新的来源。",
                        ]
                    ),
                )
                _append_system(messages, "联网查询结果：\n" + web_context)

        if tool_notes:
            _append_system(
                messages,
                "\n".join(
                    [
                        "工具状态（仅用于判断可靠性，不要在回答中复述）：",
                        tool_notes,
                    ]
                ),
            )

        _append_system(
            messages,
            "\n".join(
                [
                    "最终回复要求：",
                    "- 普通问题默认 1~3 句。",
                    "- 第一反应给结论，不要铺垫。",
                    "- 不要复述用户问题。",
                    "- 不要主动说“根据上下文/根据资料/根据历史/根据画像”。",
                    "- 关键词式问题按“询问该主题的结论或状态”直接回答。",
                    "- 当前事实类问题：如果官方/权威资料不明确，直接说“不确定/官方未明确”，不要编。",
                    "- 明确历史查询：可以说“历史摘要里看到/没找到”。",
                    "- 没有可靠资料时，不要为了完整而扩写。",
                ]
            ),
        )
        messages.append({"role": "user", "content": prompt})

        if config.chat_agent_enable_history:
            try:
                await save_message(config, session_info, "user", prompt)
            except Exception:
                pass

        reply = ""
        should_save_assistant = False
        try:
            reply = await chat_completions(messages, config)
            reply = truncate_reply(strip_thinking(reply), config.chat_agent_max_reply_length)
            should_save_assistant = bool(reply)
        except Exception:
            if context_pack.get("web_context"):
                reply = "我查到了一些相关资料，但模型接口暂时没有响应，稍后可以再试。"
            else:
                reply = config.chat_agent_llm_timeout_reply

        if reply and _should_sanitize_task_reply(prompt, context_pack):
            reply = sanitize_task_reply(reply) or reply

        if config.chat_agent_enable_history and reply and should_save_assistant:
            try:
                await save_message(config, session_info, "assistant", reply)
            except Exception:
                pass

        await chat_agent.finish(_with_group_at(event, is_group, reply or config.chat_agent_llm_timeout_reply))
        return
    finally:
        if lock.locked():
            lock.release()
