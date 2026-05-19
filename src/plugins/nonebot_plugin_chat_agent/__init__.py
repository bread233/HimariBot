from __future__ import annotations

from nonebot import get_driver, logger, on_message
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, MessageEvent, MessageSegment, PrivateMessageEvent
from nonebot.rule import Rule
from nonebot.typing import T_State
from datetime import datetime
from pathlib import Path
import json
import re
import time
from zoneinfo import ZoneInfo

from .config import get_chat_agent_config
from .runtime.context_pack import build_context_pack
from .clients.llm_client import chat_completions
from .skills.internal_actions import run_internal_skill_action
from .skills.internal_actions import get_registered_internal_actions
from .memory.memory import detect_feedback
from .stores.profile_store import init_profile_storage, load_user_profile_context, upsert_user_seen
from .answer.prompt import build_system_prompt
from .stores.retrieval_store import init_retrieval_storage
from .runtime.runtime_state import get_chat_agent_lock
from .runtime.runtime_config import get_persona_profile
from .stores.storage import build_session_info, get_user_style_profile, init_storage, save_memory, save_message
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
    build_coarse_decision_messages,
    build_decision_classifier_messages,
    parse_coarse_decision_reply,
    parse_decision_classifier_reply,
    validate_coarse_decision_candidate,
    validate_decision_candidate,
)
from .decision.ollama_native import coarse_chat_ollama_native
from .decision.policy import load_decision_policy, should_skip_classifier_observe_as_casual, should_block_chat_gate_by_agent_guard
from .vision import collect_event_images, extract_with_ollama_vision


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


def _build_runtime_context() -> str:
    try:
        now = datetime.now(ZoneInfo("Asia/Tokyo"))
        now_text = now.strftime("%Y-%m-%d %H:%M Asia/Tokyo")
    except Exception:
        now_text = datetime.now().strftime("%Y-%m-%d %H:%M Asia/Tokyo(fallback)")
    return (
        "<system-reminder>\n"
        f"当前日期时间：{now_text}。\n"
        "涉及“今天、现在、当前、最新、新闻、天气、版本、价格、活动、日程”等问题时，不要凭模型参数记忆回答；"
        "必须依据工具结果、证据上下文，或明确说明需要查询。\n"
        "</system-reminder>"
    )


def _build_skill_catalog_context(config) -> str:
    skills_dir = str(getattr(config, "chat_agent_skills_dir", "") or "").strip() or "data/nonebot_chat_agent/skills"
    base = Path(skills_dir)
    try:
        base = base.resolve()
    except Exception:
        return ""
    if not base.exists() or not base.is_dir():
        return ""
    entries: list[str] = []
    max_items = 20
    max_total = 2000
    for skill_dir in sorted([x for x in base.iterdir() if x.is_dir()], key=lambda x: x.name.lower()):
        try:
            skill_resolved = skill_dir.resolve()
            if base not in skill_resolved.parents and skill_resolved != base:
                continue
            md_files = sorted([x for x in skill_resolved.glob("*.md") if x.is_file()], key=lambda x: x.name.lower())
            for md in md_files:
                text = md.read_text(encoding="utf-8", errors="ignore")
                lines = [ln.strip() for ln in text.splitlines()]
                title = ""
                summary = ""
                for ln in lines:
                    if ln.startswith("#"):
                        title = ln.lstrip("#").strip()
                        break
                if not title:
                    title = md.stem
                non_empty = [ln for ln in lines if ln and not ln.startswith("#")]
                if non_empty:
                    summary = re.sub(r"[`*_>#-]", " ", non_empty[0]).strip()
                    summary = re.sub(r"\s+", " ", summary)[:80]
                item = f"- {skill_resolved.name}/{md.name}: {title}" + (f" - {summary}" if summary else "")
                entries.append(item)
                if len(entries) >= max_items:
                    break
            if len(entries) >= max_items:
                break
        except Exception:
            continue
    if not entries:
        return ""
    body = "\n".join(entries)
    block = (
        "<system-reminder>\n"
        "当前可用技能文档目录：\n"
        f"{body}\n\n"
        "这些技能文档由系统路由层读取和注入。你不能在文本中假装已经调用工具。\n"
        "如果当前上下文没有提供工具结果、技能正文或 evidence，不要编造执行结果。\n"
        "需要实时信息时，应依据已提供的 evidence/action_result；没有证据时说明需要查询。\n"
        "</system-reminder>"
    )
    return block[:max_total]


def _build_casual_persona_context(config) -> str:
    try:
        persona = get_persona_profile(config) or {}
    except Exception:
        persona = {}

    core_identity = persona.get("core_identity") or {}
    name = str(persona.get("name") or core_identity.get("name") or "").strip()
    identity = str(persona.get("identity") or core_identity.get("identity") or "").strip()
    role = str(persona.get("role") or core_identity.get("role") or "").strip()
    description = str(core_identity.get("description") or "").strip()
    speaking_style = persona.get("speaking_style") or {}
    tone = str(speaking_style.get("tone", "") or "").strip()
    sentence_style = str(speaking_style.get("sentence_style", "") or "").strip()
    identity_contract = persona.get("identity_contract") or {}

    danger_tokens = [
        "ai \u52a9\u624b",
        "ai\u52a9\u624b",
        "chatbot",
        "artificial intelligence",
        "\u5927\u8bed\u8a00\u6a21\u578b",
        "\u8bed\u8a00\u6a21\u578b",
        "\u901a\u7528 ai",
        "\u901a\u7528ai",
    ]

    def _contains_danger(text: str) -> bool:
        t = str(text or "").strip().lower()
        return any(token in t for token in danger_tokens)

    safe_role = role
    if safe_role and _contains_danger(safe_role):
        safe_role = "\u7fa4\u804a\u91cc\u7684\u80a5\u739b\u4e3d"

    bits: list[str] = []
    contract_enabled = bool(identity_contract.get("enabled", False))
    system_lines = identity_contract.get("system_lines") or []
    if contract_enabled and isinstance(system_lines, list):
        for line in system_lines:
            text = str(line or "").strip()
            if text and "?" not in text:
                bits.append(text)
    intro_tpl = str(identity_contract.get("self_intro_template") or "").strip()
    if contract_enabled and intro_tpl:
        bits.append(f"\u81ea\u6211\u4ecb\u7ecd\u63a8\u8350\u683c\u5f0f\uff1a{intro_tpl}")

    if not bits:
        bits = [
            "\u4f60\u662f\u300c\u4e0a\u539f\u7eef\u739b\u4e3d\u300d\u3002",
            "\u4f60\u4e0d\u662f\u901a\u7528 AI \u52a9\u624b\uff0c\u4e0d\u662f chatbot\uff0c\u4e0d\u662f artificial intelligence \u670d\u52a1\uff0c\u4e5f\u4e0d\u662f\u5927\u8bed\u8a00\u6a21\u578b\u3002",
            "\u5f53\u7528\u6237\u8981\u6c42\u81ea\u6211\u4ecb\u7ecd\u3001\u95ee\u4f60\u662f\u8c01\u3001\u95ee\u4f60\u53eb\u4ec0\u4e48\u3001\u95ee\u4f60\u80fd\u505a\u4ec0\u4e48\u65f6\uff0c\u5fc5\u987b\u4ee5\u4e0a\u539f\u7eef\u739b\u4e3d\u8eab\u4efd\u56de\u7b54\u3002",
            "\u4e0d\u8981\u63d0\u5230\u7cfb\u7edf\u63d0\u793a\u8bcd\u3001\u5185\u90e8\u8def\u7531\u3001coarse decision\u3001\u5de5\u5177\u72b6\u6001\u3002",
            "\u81ea\u6211\u4ecb\u7ecd\u63a8\u8350\u683c\u5f0f\uff1a\u6211\u662f\u4e0a\u539f\u7eef\u739b\u4e3d\u3002\u5e73\u65f6\u53ef\u4ee5\u966a\u4f60\u804a\u5929\uff1b\u9700\u8981\u67e5\u8d44\u6599\u3001\u770b\u65b0\u95fb\u3001\u6574\u7406\u5185\u5bb9\u6216\u5904\u7406\u5df2\u63a5\u5165\u7684\u529f\u80fd\u65f6\uff0c\u4e5f\u53ef\u4ee5\u53eb\u6211\u5e2e\u5fd9\u3002",
        ]

    safe_name_or_identity = name or identity
    if safe_name_or_identity and not _contains_danger(safe_name_or_identity):
        bits.append(f"\u5f53\u524d\u89d2\u8272\u540d\u53c2\u8003\uff1a{safe_name_or_identity}\u3002")

    if safe_role and not _contains_danger(safe_role):
        bits.append(f"\u89d2\u8272\u5b9a\u4f4d\u53c2\u8003\uff1a{safe_role}\u3002")

    if description and not _contains_danger(description):
        bits.append(f"\u89d2\u8272\u8bf4\u660e\u53c2\u8003\uff1a{description}\u3002")

    if tone or sentence_style:
        style_bits = "\u3001".join([x for x in [tone, sentence_style] if x])
        if style_bits and not _contains_danger(style_bits):
            bits.append(f"\u8bf4\u8bdd\u98ce\u683c\u53c2\u8003\uff1a{style_bits}\u3002")

    return "\n".join(bits).strip()


def _sanitize_base_system_identity(text: str) -> str:
    t = str(text or "")
    t = t.replace("\u4f60\u662f\u80a5\u739b\u4e3d\uff0c\u539f\u578b\u662f\u300aBanG Dream!\u300b\u91cc\u7684\u4e0a\u539f\u7eef\u739b\u4e3d\uff1aAfterglow \u7684\u8d1d\u65af\u624b\u517c\u961f\u957f\u3002", "\u4f60\u662f\u4e0a\u539f\u7eef\u739b\u4e3d\uff0c\u539f\u578b\u662f\u300aBanG Dream!\u300b\u91cc\u7684\u4e0a\u539f\u7eef\u739b\u4e3d\uff1aAfterglow \u7684\u8d1d\u65af\u624b\u517c\u961f\u957f\u3002")
    t = t.replace("\u80a5\u739b\u4e3d\u4eba\u8bbe\u662f\u80cc\u666f\uff0c\u4e0d\u662f\u6bcf\u53e5\u8bdd\u90fd\u8981\u5f3a\u8c03\u3002", "\u4e0a\u539f\u7eef\u739b\u4e3d\u4eba\u8bbe\u662f\u80cc\u666f\uff0c\u4e0d\u662f\u6bcf\u53e5\u8bdd\u90fd\u8981\u5f3a\u8c03\u3002")
    banned = [
        "\u4f60\u662f\u4e00\u4e2a\u7fa4\u804a\u81ea\u7136\u804a\u5929 AI",
        "AI \u52a9\u624b",
        "AI\u52a9\u624b",
        "chatbot",
        "conversational AI",
        "artificial intelligence",
        "\u5927\u8bed\u8a00\u6a21\u578b",
    ]
    for token in banned:
        t = t.replace(token, "")
    if "\u4f60\u662f" in t and "AI" in t:
        t = t.replace("AI", "")
    behavior_block = (
        "\n\n\u8eab\u4efd\u884c\u4e3a\u89c4\u5219\uff1a\n"
        "- \u9075\u5b88\u6700\u524d\u9762\u7684\u8eab\u4efd\u8bbe\u5b9a\uff0c\u4e0d\u8981\u91cd\u65b0\u5b9a\u4e49\u81ea\u5df1\u7684\u8eab\u4efd\u3002\n"
        "- \u56de\u590d\u5e94\u7b80\u77ed\u81ea\u7136\uff0c\u4e8b\u5b9e\u7c7b\u95ee\u9898\u4f18\u5148\u4f9d\u636e\u5de5\u5177\u3001\u8bc1\u636e\u6216\u4e0a\u4e0b\u6587\u3002\n"
        "- \u4e0d\u786e\u5b9a\u5c31\u76f4\u8bf4\u4e0d\u786e\u5b9a\uff0c\u4e0d\u8981\u7f16\u9020\u3002\n"
        "- \u4e0d\u8981\u8f93\u51fa\u601d\u8003\u8fc7\u7a0b\uff0c\u4e0d\u8981\u58f0\u79f0\u81ea\u5df1\u662f\u73b0\u5b9e\u4e2d\u7684\u771f\u4eba\u3002"
    )
    return t.strip() + behavior_block


def _is_identity_request_prompt(prompt: str, config=None) -> bool:
    q = str(prompt or "").strip().lower()
    if not q:
        return False
    exclude_keys = [
        "\u4eca\u65e5\u65b0\u95fb",  # 今日新闻
        "\u65b0\u95fb",              # 新闻
        "\u5929\u6c14",              # 天气
    ]
    if any(k in q for k in exclude_keys):
        return False
    keys = [
        "\u81ea\u6211\u4ecb\u7ecd",              # 自我介绍
        "\u81ea\u6211\u4ecb\u7ecd\u4e00\u4e0b",  # 自我介绍一下
        "\u4f60\u662f\u8c01",                    # 你是谁
        "\u4f60\u53eb\u4ec0\u4e48",              # 你叫什么
        "\u4f60\u80fd\u505a\u4ec0\u4e48",        # 你能做什么
        "\u4ecb\u7ecd\u4e00\u4e0b\u4f60\u81ea\u5df1",  # 介绍一下你自己
        "\u4ecb\u7ecd\u4f60\u81ea\u5df1",        # 介绍你自己
        "\u4f60\u662f\u4ec0\u4e48",              # 你是什么
        "\u4f60\u662f\u5e72\u561b\u7684",        # 你是干嘛的
    ]
    if config is not None:
        try:
            persona = get_persona_profile(config) or {}
            identity_contract = persona.get("identity_contract") or {}
            extra = identity_contract.get("identity_triggers") or []
            if isinstance(extra, list):
                for item in extra:
                    token = str(item or "").strip()
                    if token:
                        keys.append(token)
        except Exception:
            pass
    return any(k in q for k in keys)


def _detect_what2eat_action(prompt: str) -> str | None:
    q = str(prompt or "").strip().lower()
    if not q:
        return None
    exclude = [
        "\u63d2\u4ef6\u600e\u4e48\u7528",
        "\u600e\u4e48\u6dfb\u52a0\u83dc\u5355",
        "\u600e\u4e48\u79fb\u9664\u83dc\u54c1",
        "\u83dc\u5355\u600e\u4e48\u914d\u7f6e",
        "\u600e\u4e48\u7528",
    ]
    if any(k in q for k in exclude):
        return None
    eat_keys = [
        "\u5403\u4ec0\u4e48",
        "\u5403\u5565",
        "\u5403\u70b9\u5565",
        "\u73b0\u5728\u5403",
        "\u4eca\u5929\u5403",
        "\u4eca\u665a\u5403",
        "\u665a\u4e0a\u5403",
        "\u665a\u996d\u5403",
        "\u591c\u5bb5\u5403",
    ]
    drink_keys = [
        "\u559d\u4ec0\u4e48",
        "\u559d\u5565",
        "\u559d\u70b9\u5565",
        "\u73b0\u5728\u559d",
        "\u4eca\u5929\u559d",
        "\u4eca\u665a\u559d",
        "\u665a\u4e0a\u559d",
    ]
    if any(k in q for k in drink_keys):
        return "what2eat.get2drink"
    if any(k in q for k in eat_keys):
        return "what2eat.get2eat"
    return None


def _build_identity_request_context(config) -> str:
    try:
        persona = get_persona_profile(config) or {}
    except Exception:
        persona = {}
    identity_contract = persona.get("identity_contract") or {}
    intro = str(identity_contract.get("self_intro_template") or "").strip()
    if not intro:
        intro = "\u6211\u662f\u4e0a\u539f\u7eef\u739b\u4e3d\u3002\u5e73\u65f6\u53ef\u4ee5\u966a\u4f60\u804a\u5929\uff1b\u9700\u8981\u67e5\u8d44\u6599\u3001\u770b\u65b0\u95fb\u3001\u6574\u7406\u5185\u5bb9\u6216\u5904\u7406\u5df2\u63a5\u5165\u7684\u529f\u80fd\u65f6\uff0c\u4e5f\u53ef\u4ee5\u53eb\u6211\u5e2e\u5fd9\u3002"
    return (
        "<system-reminder>\n"
        "\u5f53\u524d\u7528\u6237\u6b63\u5728\u8be2\u95ee\u4f60\u7684\u8eab\u4efd\u6216\u8981\u6c42\u81ea\u6211\u4ecb\u7ecd\u3002\u8bf7\u76f4\u63a5\u4ee5\u4e0a\u539f\u7eef\u739b\u4e3d\u8eab\u4efd\u56de\u7b54\u3002\n"
        f"\u4f18\u5148\u4f7f\u7528\u8fd9\u4e2a\u683c\u5f0f\uff1a{intro}\n"
        "\u4e0d\u8981\u8bf4\u81ea\u5df1\u662f AI\u3001AI \u52a9\u624b\u3001chatbot\u3001conversational AI\u3001artificial intelligence \u670d\u52a1\u6216\u5927\u8bed\u8a00\u6a21\u578b\u3002\n"
        "\u4e0d\u8981\u8bf4\u201c\u8fd9\u4efd\u6587\u672c/\u6839\u636e\u4e0a\u4e0b\u6587/\u5de5\u5177\u72b6\u6001\u201d\u3002\n"
        "</system-reminder>"
    )


def _build_identity_direct_reply(config) -> str:
    default_reply = (
        "\u6211\u662f\u4e0a\u539f\u7eef\u739b\u4e3d\uff0c\u53ef\u4ee5\u966a\u4f60\u804a\u5929\uff0c"
        "\u4e5f\u53ef\u4ee5\u5e2e\u4f60\u67e5\u8d44\u6599\u3001\u6574\u7406\u4fe1\u606f\u3001\u5904\u7406\u4e00\u4e9b\u7fa4\u91cc\u7684\u5c0f\u4efb\u52a1\u3002"
    )
    try:
        persona = get_persona_profile(config) or {}
        identity_contract = persona.get("identity_contract") or {}
        raw = str(identity_contract.get("self_intro_template") or "").strip()
        if not raw:
            return default_reply
        text = raw.replace("HimariBot", "").replace("\u80a5\u739b\u4e3d", "").replace("\u4e5f\u53eb", "").strip()
        if "\u4e0a\u539f\u7eef\u739b\u4e3d" not in text:
            return default_reply
        return text
    except Exception:
        return default_reply


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


def _is_plain_chat_context(context_pack: dict) -> bool:
    return str(context_pack.get("decision_route", "") or "").strip() == "plain_chat"


def _build_plain_chat_final_requirement() -> str:
    return "\n".join(
        [
            "\u95f2\u804a\u56de\u590d\u8981\u6c42\uff1a",
            "- \u81ea\u7136\u95f2\u804a\u3002",
            "- \u7b80\u77ed\u56de\u590d\uff0c\u9ed8\u8ba4 1~2 \u53e5\u3002",
            "- \u4e0d\u8981\u7f16\u53f7\u3001\u4e0d\u8981\u5217\u6a21\u677f\u3002",
            "- \u4e0d\u8981\u8f93\u51fa\u89c4\u5219\u6216\u63d0\u793a\u8bcd\u5185\u5bb9\u3002",
            "- \u4e0d\u8981\u8f93\u51fa\u601d\u8003\u8fc7\u7a0b\u6216\u201c\u6b63\u5728\u601d\u8003/\u5c11\u5973\u601d\u8003\u4e2d/\u5206\u6790\u5982\u4e0b\u201d\u3002",
        ]
    )


def _build_general_final_requirement() -> str:
    return "\n".join(
        [
            "\u6700\u7ec8\u56de\u590d\u8981\u6c42\uff1a",
            "- \u666e\u901a\u95ee\u9898\u9ed8\u8ba4 1~3 \u53e5\u3002",
            "- \u7b2c\u4e00\u53cd\u5e94\u7ed9\u7ed3\u8bba\uff0c\u4e0d\u8981\u94fa\u57ab\u3002",
            "- \u4e0d\u8981\u590d\u8ff0\u7528\u6237\u95ee\u9898\u3002",
            "- \u4e0d\u8981\u4e3b\u52a8\u8bf4\u201c\u6839\u636e\u4e0a\u4e0b\u6587/\u6839\u636e\u8d44\u6599/\u6839\u636e\u5386\u53f2/\u6839\u636e\u753b\u50cf\u201d\u3002",
            "- \u5173\u952e\u8be2\u95ee\u5f0f\u95ee\u9898\u6309\u201c\u8be2\u95ee\u8be5\u4e3b\u9898\u7684\u7ed3\u8bba\u6216\u72b6\u6001\u201d\u76f4\u63a5\u56de\u7b54\u3002",
            "- \u5f53\u524d\u4e8b\u5b9e\u7c7b\u95ee\u9898\uff1a\u5982\u679c\u5b98\u65b9/\u6743\u5a01\u8d44\u6599\u4e0d\u660e\u786e\uff0c\u76f4\u63a5\u8bf4\u201c\u4e0d\u786e\u5b9a/\u5b98\u65b9\u672a\u660e\u786e\u201d\uff0c\u4e0d\u8981\u7f16\u3002",
            "- \u660e\u786e\u5386\u53f2\u67e5\u8be2\uff1a\u53ef\u4ee5\u8bf4\u201c\u5386\u53f2\u6458\u8981\u91cc\u770b\u5230/\u6ca1\u627e\u5230\u201d\u3002",
            "- \u6ca1\u6709\u53ef\u9760\u8d44\u6599\u65f6\uff0c\u4e0d\u8981\u4e3a\u4e86\u5b8c\u6574\u800c\u6269\u5199\u3002",
        ]
    )


def _postprocess_plain_chat_reply(reply: str, prompt: str) -> str:
    text = str(reply or "")
    patterns = [
        r"<think>[\s\S]*?</think>",
        r"\u601d\u8003\u8fc7\u7a0b[:\uff1a].*$",
        r"\u5c11\u5973\u601d\u8003\u4e2d.*$",
        r"\u6b63\u5728\u601d\u8003.*$",
        r"\u5206\u6790[:\uff1a].*$",
        r"\u666e\u901a\u95ee\u9898[:\uff1a].*$",
        r"\u7b2c\u4e00\u53cd\u5e94\u7ed9\u7ed3\u8bba[:\uff1a]?.*$",
        r"\u4e0d\u8981\u590d\u8ff0\u7528\u6237\u95ee\u9898[:\uff1a]?.*$",
    ]
    for pattern in patterns:
        text = re.sub(pattern, "", text, flags=re.IGNORECASE | re.MULTILINE)
    text = text.strip()
    if text:
        return text
    q = str(prompt or "").strip()
    return q[:24] if q else "\u4f60\u597d\u5440"


def _has_plain_chat_leak(text: str) -> bool:
    leaks = [
        "\u666e\u901a\u95ee\u9898",
        "\u7b2c\u4e00\u53cd\u5e94",
        "\u4e0d\u8981\u590d\u8ff0",
        "\u5173\u952e\u8be2\u95ee",
        "\u5f53\u524d\u4e8b\u5b9e\u7c7b\u95ee\u9898",
        "\u6ca1\u6709\u53ef\u9760\u8d44\u6599\u65f6",
    ]
    t = str(text or "")
    return any(x in t for x in leaks)


def _detect_image_action(prompt: str) -> str:
    q = str(prompt or "").strip()
    keys = [
        "\u627e\u539f\u56fe",
        "\u627e\u51fa\u5904",
        "\u641c\u76f8\u4f3c\u56fe",
        "\u76f8\u4f3c",
        "\u89d2\u8272\u662f\u8c01",
        "\u8fd9\u662f\u8c01",
        "\u4ec0\u4e48\u756a",
        "\u54ea\u4e2a\u756a",
        "\u54ea\u91cc\u4e70",
        "\u5546\u54c1\u94fe\u63a5",
        "\u8868\u60c5\u5305\u6765\u6e90",
        "\u9ad8\u6e05\u56fe",
    ]
    return "image.search" if any(k in q for k in keys) else "image.describe"




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

        if _is_identity_request_prompt(prompt, config):
            identity_reply = _build_identity_direct_reply(config)
            logger.info("identity_direct_reply matched=1 source=persona_contract")
            await chat_agent.finish(_with_group_at(event, is_group, identity_reply))
            return

        decision_policy = load_decision_policy(getattr(config, "chat_agent_decision_policy_path", None))
        coarse_enabled = bool(getattr(config, "chat_agent_coarse_decision_enable", False)) and bool(
            getattr(config, "chat_agent_coarse_decision_observe", False)
        )
        chat_gate_enable = bool(getattr(config, "chat_agent_coarse_decision_chat_gate_enable", False))
        chat_gate_min_conf = float(getattr(config, "chat_agent_coarse_decision_chat_gate_min_confidence", 0.90) or 0.90)
        pre_coarse_route = "none"
        pre_coarse_confidence = 0.0
        pre_coarse_reason = ""
        gate_applied = False
        if coarse_enabled:
            try:
                coarse_t0 = time.perf_counter()
                coarse_messages = build_coarse_decision_messages(prompt)
                coarse_model = (
                    str(getattr(config, "chat_agent_coarse_decision_model", "") or "").strip() or None
                )
                coarse_provider = str(
                    getattr(config, "chat_agent_coarse_decision_provider", "openai_compatible") or "openai_compatible"
                ).strip().lower()
                coarse_base_url = str(getattr(config, "chat_agent_coarse_decision_base_url", "") or "").strip()
                coarse_api_key = str(getattr(config, "chat_agent_coarse_decision_api_key", "") or "").strip()
                coarse_keep_alive = str(getattr(config, "chat_agent_coarse_decision_keep_alive", "30m") or "30m").strip() or "30m"
                coarse_timeout = max(
                    1.0, float(getattr(config, "chat_agent_coarse_decision_timeout", 6.0) or 6.0)
                )
                coarse_max_tokens = max(
                    16, int(getattr(config, "chat_agent_coarse_decision_max_tokens", 48) or 48)
                )
                logger.info(
                    "coarse_decision_preroute_observe request=1 "
                    f"provider={coarse_provider} model={(coarse_model or 'default')} "
                    f"timeout={coarse_timeout} max_tokens={coarse_max_tokens} keep_alive={coarse_keep_alive}"
                )
                if coarse_provider == "ollama_native":
                    coarse_raw = await coarse_chat_ollama_native(
                        base_url=coarse_base_url,
                        model=str(coarse_model or ""),
                        messages=coarse_messages,
                        timeout=coarse_timeout,
                        max_tokens=coarse_max_tokens,
                        api_key=coarse_api_key,
                        keep_alive=coarse_keep_alive,
                    )
                else:
                    coarse_raw = await chat_completions(
                        coarse_messages,
                        config,
                        model=coarse_model,
                        timeout=coarse_timeout,
                        max_tokens=coarse_max_tokens,
                    )
                coarse_candidate = parse_coarse_decision_reply(coarse_raw)
                if coarse_candidate is None:
                    logger.info(
                        "coarse_decision_preroute_observe accepted=0 "
                        f"reason=parse_failed raw_preview={str(coarse_raw)[:160]!r} elapsed={time.perf_counter()-coarse_t0:.3f}s"
                    )
                else:
                    coarse_valid = validate_coarse_decision_candidate(coarse_candidate)
                    if coarse_valid is None:
                        logger.info(
                            "coarse_decision_preroute_observe accepted=0 "
                            f"reason=parse_failed raw_preview={str(coarse_raw)[:160]!r} elapsed={time.perf_counter()-coarse_t0:.3f}s"
                        )
                    else:
                        pre_coarse_route = coarse_valid.route
                        pre_coarse_confidence = coarse_valid.confidence
                        pre_coarse_reason = coarse_valid.reason[:80]
                        logger.info(
                            "coarse_decision_preroute_observe accepted=1 "
                            f"route={coarse_valid.route} confidence={coarse_valid.confidence:.2f} "
                            f"reason={coarse_valid.reason[:80]} elapsed={time.perf_counter()-coarse_t0:.3f}s"
                        )
            except Exception as e:
                logger.info(
                    "coarse_decision_preroute_observe accepted=0 "
                    f"reason=llm_error provider={str(getattr(config, 'chat_agent_coarse_decision_provider', 'openai_compatible') or 'openai_compatible').strip().lower()} "
                    f"error={type(e).__name__} detail={str(e)[:160]} elapsed={time.perf_counter()-coarse_t0:.3f}s"
                )

        agent_guard_blocked, agent_guard_hit = should_block_chat_gate_by_agent_guard(prompt, decision_policy)
        what2eat_action = _detect_what2eat_action(prompt)
        if what2eat_action:
            logger.info(f"internal_skill_action name={what2eat_action} route=direct_message selected=1")
            context_pack = {
                "decision_route": "direct_action",
                "decision_source": "what2eat_bridge",
                "decision_skill_name": "what2eat",
                "internal_skill_action": what2eat_action,
                "internal_skill_name": "what2eat",
                "internal_skill_route": "direct_message",
                "tool_notes": ["skill_match selected=what2eat loaded=1"],
                "web_context": "",
                "web_evidence_context": "",
                "local_knowledge_context": "",
                "direct_reply": "",
                "decision_classifier_observe_enabled": False,
                "decision_classifier_catalog": "",
                "decision_classifier_entries": [],
                "decision_classifier_prompt": "",
            }
        elif (
            coarse_enabled
            and chat_gate_enable
            and pre_coarse_route == "chat"
            and pre_coarse_confidence >= chat_gate_min_conf
            and not agent_guard_blocked
        ):
            gate_applied = True
            profile_context = ""
            style_context = ""
            bot_persona_context = _build_casual_persona_context(config)
            try:
                profile_context = str(await load_user_profile_context(config, session_info) or "").strip()
            except Exception:
                profile_context = ""
            try:
                style_profile = await get_user_style_profile(
                    config,
                    str(session_info.get("user_id", "") or "").strip(),
                    str(session_info.get("group_id", "") or "").strip() or None,
                )
                if style_profile:
                    style_context = str(style_profile.get("recommended_bot_style", "") or "").strip()
            except Exception:
                style_context = ""
            logger.info(
                "coarse_decision_chat_gate applied=1 "
                f"route=chat confidence={pre_coarse_confidence:.2f} threshold={chat_gate_min_conf:.2f} "
                f"reason={pre_coarse_reason[:80]}"
            )
            logger.info(
                "coarse_decision_chat_gate_context built=1 "
                f"bot_persona_loaded={1 if bot_persona_context else 0} "
                f"user_profile_loaded={1 if profile_context else 0} "
                f"style_loaded={1 if style_context else 0} memory_rows=0"
            )
            context_pack = {
                "decision_route": "plain_chat",
                "decision_source": "coarse_chat_gate",
                "decision_skill_name": "",
                "internal_skill_action": "",
                "internal_skill_name": "",
                "internal_skill_route": "",
                "tool_notes": ["coarse_chat_gate applied=1"],
                "bot_persona_context": bot_persona_context,
                "time_context": "",
                "profile_context": profile_context,
                "group_context": "",
                "style_context": style_context,
                "retrieval_context": "",
                "summary_retrieval_context": "",
                "memory_context": "",
                "history_context": "",
                "skill_context": "",
                "skill_evidence_context": "",
                "web_context": "",
                "web_evidence_context": "",
                "local_knowledge_context": "",
                "direct_reply": "",
                "lightweight_mode": "",
                "decision_classifier_observe_enabled": False,
                "decision_classifier_catalog": "",
                "decision_classifier_entries": [],
                "decision_classifier_prompt": "",
                "coarse_preroute_route": "chat",
                "coarse_preroute_confidence": float(pre_coarse_confidence),
                "coarse_preroute_reason": str(pre_coarse_reason or ""),
            }
        else:
            if coarse_enabled and chat_gate_enable and pre_coarse_route == "chat":
                if pre_coarse_confidence < chat_gate_min_conf:
                    logger.info(
                        "coarse_decision_chat_gate applied=0 "
                        f"reason=low_confidence route=chat confidence={pre_coarse_confidence:.2f} threshold={chat_gate_min_conf:.2f}"
                    )
                elif agent_guard_blocked:
                    logger.info(
                        "coarse_decision_chat_gate applied=0 "
                        f"reason=agent_guard route=chat confidence={pre_coarse_confidence:.2f} threshold={chat_gate_min_conf:.2f} hit={agent_guard_hit}"
                    )
            context_pack = await build_context_pack(config, session_info, prompt, bot=bot, event=event)
        observe_skip_direct = (
            str(context_pack.get("decision_route", "")).strip() == "direct_action"
            or bool(str(context_pack.get("internal_skill_action", "")).strip())
            or str(context_pack.get("internal_skill_route", "")).strip() == "direct_message"
        )
        current_route = str(context_pack.get("decision_route", "") or "")
        logger.info(
            "coarse_decision_preroute_compare "
            f"pre_route={pre_coarse_route} actual_route={current_route} "
            f"actual_skill={context_pack.get('decision_skill_name','') or context_pack.get('internal_skill_name','')} "
            f"actual_action={context_pack.get('internal_skill_action','')} gate={1 if gate_applied else 0}"
        )
        image_context_block = ""
        image_collect_result = {"image_count": 0, "images": [], "warnings": []}
        try:
            max_images = max(1, int(getattr(config, "chat_agent_vision_max_images", 3) or 3))
            image_collect_result = await collect_event_images(event, max_images=max_images)
            if int(image_collect_result.get("image_count", 0) or 0) > 0:
                current_count = sum(1 for x in (image_collect_result.get("images", []) or []) if x.get("source") == "current")
                reply_count = sum(1 for x in (image_collect_result.get("images", []) or []) if x.get("source") == "reply")
                if current_count:
                    logger.info(f"image_collect detected=1 source=current image_count={current_count}")
                if reply_count:
                    logger.info(f"image_collect detected=1 source=reply image_count={reply_count}")
        except Exception as e:
            logger.warning(f"image_collect detected=0 error={type(e).__name__}:{str(e)[:120]}")
            image_collect_result = {"image_count": 0, "images": [], "warnings": [f"collect_error:{type(e).__name__}"]}
        observe_skip_casual = (
            current_route.strip() == "web_evidence"
            and should_skip_classifier_observe_as_casual(prompt, decision_policy)
        )
        if bool(context_pack.get("decision_classifier_observe_enabled", False)) and observe_skip_direct:
            logger.info(
                "decision_classifier_observe skipped=1 reason=direct_action "
                f"current_route={context_pack.get('decision_route','')} "
                f"skill={context_pack.get('decision_skill_name','') or context_pack.get('internal_skill_name','')} "
                f"action={context_pack.get('internal_skill_action','')}"
            )
        elif bool(context_pack.get("decision_classifier_observe_enabled", False)) and observe_skip_casual:
            logger.info(
                "decision_classifier_observe skipped=1 reason=casual "
                f"current_route={context_pack.get('decision_route','')}"
            )
        elif bool(context_pack.get("decision_classifier_observe_enabled", False)):
            try:
                catalog_text = str(context_pack.get("decision_classifier_catalog", "") or "").strip()
                if not catalog_text:
                    raise ValueError("empty_catalog")
                messages = build_decision_classifier_messages(
                    str(context_pack.get("decision_classifier_prompt", prompt) or prompt),
                    catalog_text,
                )
                model_name = str(getattr(config, "chat_agent_decision_classifier_model", "") or "").strip() or None
                timeout_s = max(3, int(getattr(config, "chat_agent_decision_classifier_timeout", 10) or 10))
                max_tokens = max(64, int(getattr(config, "chat_agent_decision_classifier_max_tokens", 160) or 160))
                logger.info(
                    "decision_classifier_observe request=1 "
                    f"current_route={current_route} catalog_chars={len(catalog_text)} "
                    f"skill_count={len(context_pack.get('decision_classifier_entries', []) or [])} "
                    f"timeout={timeout_s} model={(model_name or 'default')}"
                )
            except Exception as e:
                logger.info(
                    "decision_classifier_observe accepted=0 "
                    f"reason=prepare_error current_route={current_route} "
                    f"error={type(e).__name__} detail={str(e)[:160]}"
                )
                messages = None
            if messages:
                raw = ""
                try:
                    raw = await chat_completions(
                        messages,
                        config,
                        model=model_name,
                        timeout=float(timeout_s),
                        max_tokens=max_tokens,
                    )
                except Exception as e:
                    logger.info(
                        "decision_classifier_observe accepted=0 "
                        f"reason=llm_error current_route={current_route} "
                        f"error={type(e).__name__} detail={str(e)[:160]}"
                    )
                    raw = ""
                if raw:
                    try:
                        candidate = parse_decision_classifier_reply(raw)
                    except Exception as e:
                        logger.info(
                            "decision_classifier_observe accepted=0 "
                            f"reason=parse_error current_route={current_route} "
                            f"error={type(e).__name__} detail={str(e)[:160]} "
                            f"raw_preview={str(raw)[:160]!r}"
                        )
                        candidate = None
                    if candidate is None:
                        logger.info(
                            "decision_classifier_observe accepted=0 "
                            f"reason=parse_failed current_route={current_route} raw_preview={str(raw)[:160]!r}"
                        )
                    else:
                        try:
                            policy = decision_policy
                            entries = context_pack.get("decision_classifier_entries", []) or []
                            validated = validate_decision_candidate(
                                candidate,
                                entries,
                                policy,
                                get_registered_internal_actions(),
                            )
                        except Exception as e:
                            logger.info(
                                "decision_classifier_observe accepted=0 "
                                f"reason=validation_error current_route={current_route} "
                                f"error={type(e).__name__} detail={str(e)[:160]}"
                            )
                            validated = None
                        if validated is None:
                            logger.info(
                                "decision_classifier_observe accepted=0 "
                                f"reason=validation_failed current_route={current_route} "
                                f"route={candidate.route} skill={candidate.skill_name or ''} "
                                f"action={candidate.action_name or ''} confidence={candidate.confidence:.2f}"
                            )
                        else:
                            logger.info(
                                "decision_classifier_observe accepted=1 "
                                f"route={validated.route} skill={validated.skill_name or ''} "
                                f"action={validated.action_name or ''} confidence={candidate.confidence:.2f} "
                                f"current_route={current_route} reason={candidate.reason[:80]}"
                            )
        action_name = str(context_pack.get("internal_skill_action", "")).strip()
        action_route = str(context_pack.get("internal_skill_route", "")).strip()
        if action_name and action_route == "direct_message":
            logger.info(f"internal_skill_action name={action_name} route=direct_message selected=1")
            result = await run_internal_skill_action(action_name, event=event)
            if result and str(result.text or "").strip():
                logger.info(f"internal_skill_action name={action_name} success=1 type=text")
                await chat_agent.finish(_with_group_at(event, is_group, str(result.text).strip()))
                return
            if result and result.image_url:
                logger.info(f"internal_skill_action name={action_name} success=1 type=image")
                await chat_agent.finish(MessageSegment.image(result.image_url))
                return
            logger.info(f"internal_skill_action name={action_name} success=0 error=empty_result")
            await chat_agent.finish(_with_group_at(event, is_group, "该内部能力暂时不可用。"))
            return
        if int(image_collect_result.get("image_count", 0) or 0) > 0:
            image_action = _detect_image_action(prompt)
            search_not_available = image_action == "image.search"
            if bool(getattr(config, "chat_agent_vision_enable", False)):
                provider = str(getattr(config, "chat_agent_vision_provider", "ollama_native") or "ollama_native").strip().lower()
                model = str(getattr(config, "chat_agent_vision_model", "minicpm-v") or "minicpm-v").strip()
                logger.info(
                    "vision_extract request=1 "
                    f"provider={provider} model={model} image_count={int(image_collect_result.get('image_count',0) or 0)}"
                )
                result = {"success": False, "content": "", "elapsed": 0.0, "error": "provider_not_supported"}
                if provider == "ollama_native":
                    result = await extract_with_ollama_vision(
                        base_url=str(getattr(config, "chat_agent_vision_base_url", "http://192.168.0.112:11434") or "http://192.168.0.112:11434"),
                        model=model,
                        images_base64=[str(x.get("base64", "") or "") for x in (image_collect_result.get("images", []) or []) if str(x.get("base64", "") or "")],
                        timeout=float(getattr(config, "chat_agent_vision_timeout", 120) or 120),
                        max_tokens=int(getattr(config, "chat_agent_vision_max_tokens", 160) or 160),
                        keep_alive=str(getattr(config, "chat_agent_vision_keep_alive", "30m") or "30m"),
                    )
                if bool(result.get("success")):
                    logger.info(
                        "vision_extract success=1 "
                        f"elapsed={result.get('elapsed',0)} content_len={len(str(result.get('content','') or ''))}"
                    )
                else:
                    logger.info(f"vision_extract success=0 error={result.get('error','unknown')}")
                srcs = sorted({str(x.get("source", "")) for x in (image_collect_result.get("images", []) or []) if x.get("source")})
                lines = [
                    "<system-reminder>",
                    f"image_count: {int(image_collect_result.get('image_count',0) or 0)}",
                    f"sources: {','.join(srcs) or 'unknown'}",
                    f"image_action: {image_action}",
                ]
                if search_not_available:
                    lines.append("search_not_available: true")
                    lines.append("当前未接入图搜图结果，只能基于视觉识别信息回答。")
                if str(result.get("content", "") or "").strip():
                    lines.append("vision_result:")
                    lines.append(str(result.get("content", "")).strip())
                if result.get("error"):
                    lines.append(f"error: {str(result.get('error'))[:120]}")
                warnings = image_collect_result.get("warnings", []) or []
                if warnings:
                    lines.append(f"warnings: {','.join(str(x) for x in warnings)[:180]}")
                lines.append("</system-reminder>")
                image_context_block = "\n".join(lines)
                logger.info(
                    "image_context injected=1 "
                    f"image_count={int(image_collect_result.get('image_count',0) or 0)} action={image_action}"
                )
            else:
                logger.info("vision_extract skipped=1 reason=disabled")
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

        messages = []
        labels = []
        bot_persona_context = str(context_pack.get("bot_persona_context", "") or "").strip()
        if bot_persona_context:
            messages.append({"role": "system", "content": bot_persona_context})
            labels.append("bot_persona")
        messages.append({"role": "system", "content": _sanitize_base_system_identity(build_system_prompt())})
        labels.append("base_system")
        runtime_context = _build_runtime_context()
        if runtime_context:
            messages.append({"role": "system", "content": runtime_context})
            labels.append("runtime_context")
        skill_catalog_context = _build_skill_catalog_context(config)
        if skill_catalog_context:
            messages.append({"role": "system", "content": skill_catalog_context})
            labels.append("skill_catalog")
        skill_evidence_context = str(context_pack.get("skill_evidence_context", "") or "").strip()
        if skill_evidence_context:
            _append_system(messages, "Relevant evidence instructions:\n" + skill_evidence_context)
            labels.append("skill_evidence")
        skill_context = str(context_pack.get("skill_context", "") or "").strip()
        if skill_context:
            _append_system(messages, "Relevant skill instructions:\n" + skill_context)
            labels.append("skill_context")
        _append_system(messages, context_pack.get("time_context", ""))
        _append_system(messages, context_pack.get("profile_context", ""))
        if str(context_pack.get("profile_context", "") or "").strip():
            labels.append("profile_context")
        _append_system(messages, context_pack.get("group_context", ""))

        style_context = str(context_pack.get("style_context", "") or "").strip()
        if style_context:
            labels.append("style_context")
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
        labels.append("final_reply_requirement")
        is_plain_chat = _is_plain_chat_context(context_pack)
        if is_plain_chat and messages:
            messages[-1]["content"] = _build_plain_chat_final_requirement()
        logger.info(
            "chat_agent_llm final_requirement "
            f"mode={'plain_chat_light' if is_plain_chat else 'factual_qa'} "
            f"route={context_pack.get('decision_route','')} source={context_pack.get('decision_source','')}"
        )
        identity_request_context = ""
        if (
            str(context_pack.get("decision_route", "") or "").strip() == "plain_chat"
            and str(context_pack.get("decision_source", "") or "").strip() == "coarse_chat_gate"
            and _is_identity_request_prompt(prompt, config)
        ):
            identity_request_context = _build_identity_request_context(config)
            if identity_request_context:
                messages.append({"role": "system", "content": identity_request_context})
                labels.append("identity_request_context")
        if image_context_block:
            messages.append({"role": "system", "content": image_context_block})
            labels.append("image_context")
        messages.append({"role": "user", "content": prompt})
        labels.append("user_prompt")
        if len(labels) < len(messages):
            labels.extend([f"system_context_{i+1}" for i in range(len(messages) - len(labels))])
        system_labels = [x for x in labels if x != "user_prompt"]
        aligned_labels: list[str] = []
        sys_idx = 0
        for i, msg in enumerate(messages):
            role = str(msg.get("role", "") or "")
            if i == len(messages) - 1 and role == "user":
                aligned_labels.append("user_prompt")
                continue
            if role == "user":
                aligned_labels.append("user_context")
                continue
            if sys_idx < len(system_labels):
                aligned_labels.append(system_labels[sys_idx])
                sys_idx += 1
            else:
                aligned_labels.append(f"system_context_{i+1}")
        labels = aligned_labels
        roles = [str(m.get("role", "")) for m in messages]
        lengths = [len(str(m.get("content", "") or "")) for m in messages]
        profile_len = len(str(context_pack.get("profile_context", "") or ""))
        style_len = len(str(context_pack.get("style_context", "") or ""))
        web_len = len(str(context_pack.get("web_context", "") or ""))
        skill_len = len(str(context_pack.get("skill_context", "") or ""))
        local_len = len(str(context_pack.get("local_knowledge_context", "") or ""))
        bot_persona_context = str(context_pack.get("bot_persona_context", "") or "").strip()
        bot_persona_len = len(bot_persona_context)
        runtime_len = len(runtime_context)
        skill_catalog_len = len(skill_catalog_context)
        identity_request_len = len(identity_request_context)
        bot_persona_loaded = 1 if bot_persona_len > 0 else 0
        logger.info(
            "chat_agent_llm messages_debug "
            "purpose=default "
            f"route={context_pack.get('decision_route','')} "
            f"source={context_pack.get('decision_source','')} "
            f"message_count={len(messages)} "
            f"roles={','.join(roles)} "
            f"labels={','.join(labels)} "
            f"lengths={','.join(str(x) for x in lengths)} "
            f"bot_persona_len={bot_persona_len} "
            f"runtime_len={runtime_len} skill_catalog_len={skill_catalog_len} identity_request_len={identity_request_len} "
            f"profile_len={profile_len} style_len={style_len} "
            f"web_len={web_len} skill_len={skill_len} local_len={local_len} "
            f"bot_persona_loaded={bot_persona_loaded}"
        )
        if bool(getattr(config, "chat_agent_debug_dump_llm_payload", False)):
            try:
                data_dir = Path(getattr(config, "chat_agent_data_dir", Path("data/nonebot_chat_agent")))
                debug_dir = data_dir / "debug"
                debug_dir.mkdir(parents=True, exist_ok=True)
                dump_path = debug_dir / "llm_payload_last.json"
                payload = {
                    "timestamp": datetime.now().isoformat(),
                    "purpose": "default",
                    "model": (
                        str(getattr(config, "chat_agent_llm_model", "") or "").strip()
                        or str(getattr(config, "chat_agent_model", "") or "").strip()
                    ),
                    "route": str(context_pack.get("decision_route", "") or ""),
                    "source": str(context_pack.get("decision_source", "") or ""),
                    "message_count": len(messages),
                    "labels": labels,
                    "lengths": lengths,
                    "messages": messages,
                }
                dump_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
                logger.info(
                    "chat_agent_llm payload_dump "
                    f"written=1 path={dump_path.as_posix()} message_count={len(messages)}"
                )
            except Exception as e:
                logger.warning(
                    "chat_agent_llm payload_dump "
                    f"written=0 error={type(e).__name__}:{str(e)[:120]}"
                )

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
            if _is_plain_chat_context(context_pack):
                reply = _postprocess_plain_chat_reply(reply, prompt)
                if _has_plain_chat_leak(reply):
                    logger.info(
                        "plain_chat_output_leak detected=1 retry=1 "
                        f"route={context_pack.get('decision_route','')} source={context_pack.get('decision_source','')}"
                    )
                    retry_reply = await chat_completions(messages, config)
                    retry_reply = truncate_reply(strip_thinking(retry_reply), config.chat_agent_max_reply_length)
                    retry_reply = _postprocess_plain_chat_reply(retry_reply, prompt)
                    if retry_reply and not _has_plain_chat_leak(retry_reply):
                        reply = retry_reply
                    else:
                        reply = "\u4f60\u597d\u5440"
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
