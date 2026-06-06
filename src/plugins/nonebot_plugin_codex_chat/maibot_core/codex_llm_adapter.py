from __future__ import annotations

import importlib
import re
import sys
import traceback
import uuid
from dataclasses import dataclass
from typing import Any

try:
    from .common.logger import get_logger
except Exception:  # pragma: no cover - import compatibility for local smoke
    import logging

    def get_logger(name: str):
        return logging.getLogger(name)

try:
    from .llm_models.payload_content.tool_option import ToolCall as _ToolCall
except Exception:
    try:
        from src.llm_models.payload_content.tool_option import ToolCall as _ToolCall
    except Exception:
        _ToolCall = None  # type: ignore[assignment]

logger = get_logger("codex_llm_adapter")


_PLUGIN_CONFIG_CANDIDATES = (
    "src.plugins.nonebot_plugin_codex_chat.config",
    "nonebot_plugin_codex_chat.config",
)

_CODEX_PROVIDER_CANDIDATES = (
    "src.plugins.nonebot_plugin_codex_chat.codex_provider",
    "nonebot_plugin_codex_chat.codex_provider",
)

_TIMING_GATE_CONTINUE_PATTERNS: tuple[str, ...] = (
    r"选\W*continue",
    r"选择\W*continue",
    r"调用\W*continue",
    r"应进入回复流程",
    r"应该进入回复流程",
    r"进入回复流程",
    r"应回复",
    r"应该继续",
    r"应继续",
    r"继续发言",
)

_TIMING_GATE_NO_ACTION_PATTERNS: tuple[str, ...] = (
    r"选\W*no_action",
    r"选择\W*no_action",
    r"调用\W*no_action",
    r"本轮不回复",
    r"不继续发言",
    r"等待新消息",
    r"应等待",
    r"应停止",
    r"停止本轮",
)

_TIMING_GATE_WAIT_PATTERNS: tuple[str, ...] = (
    r"选\W*wait",
    r"选择\W*wait",
    r"调用\W*wait",
    r"保持等待",
    r"继续等待",
)

_TIMING_GATE_STRONG_CONTINUE_PATTERNS: tuple[str, ...] = (
    r"选\W*continue",
    r"选择\W*continue",
    r"调用\W*continue",
    r"`continue`",
    r"不该继续等待",
    r"不应继续等待",
    r"不适合继续等待",
    r"不能继续等待",
    r"不该继续沉默",
    r"不适合继续沉默",
    r"不能继续沉默",
    r"需要接话",
    r"需要回应",
    r"需要回复",
    r"在等回应",
    r"对方在等回应",
    r"等一个直接回应",
    r"直接被点名",
    r"直接点名互动",
    r"连续追问",
)

_PLANNER_REPLY_POSITIVE_PATTERNS: tuple[str, ...] = (
    r"应回复",
    r"应该回复",
    r"应当回复",
    r"优先回复",
    r"先回复",
    r"做回复",
    r"调用\s*reply",
    r"使用\s*reply",
    r"回复\s*msg_id",
    r"回\s*`?\s*msg_id",
    r"一句就够",
    r"在呢，[\u548b\u54c9]啦",
    r"我在，怎么了",
    r"建议回复",
    r"推荐回复",
    r"建议下一步.*回复",
    r"推荐内容",
    r"推荐回复内容",
    r"立刻回复",
    r"立刻回复一次",
    r"立刻发一条.*回复",
    r"发一条.*可见回复",
    r"很短的可见回复",
    r"短的可见回复",
    r"直接回应",
    r"等一个直接回应",
    r"不适合继续沉默",
    r"不该继续沉默",
    r"最合适的动作是发.*回复",
    r"最优先的是发.*回复",
    r"先解释刚.*没回",
    r"先解释刚.*没接话",
    r"顺手确认身份",
    r"我是绯玛丽",
    r"刚刚在看消息",
    r"刚上线",
)

_PLANNER_REPLY_NEGATIVE_PATTERNS: tuple[str, ...] = (
    r"不应回复",
    r"不要回复",
    r"无需回复",
    r"不需要回复",
    r"不继续发言",
    r"保持等待",
    r"等待新消息",
    r"调用\s*no_action",
    r"调用\s*finish",
    r"调用\s*wait",
    r"不发可见回复",
    r"不发送可见回复",
    r"保持安静",
    r"不回复",
)


@dataclass(slots=True)
class CodexGenerateResult:
    """Codex LLM 单次调用的统一结果。"""

    text: str = ""
    tool_calls: list[Any] | None = None
    ok: bool = True


def _build_timing_gate_tool_call(func_name: str) -> Any:
    """为 Timing Gate 构造一个最小的 ToolCall 对象。"""

    if _ToolCall is None:
        return None
    return _ToolCall(
        call_id=f"timing_gate_{uuid.uuid4().hex[:12]}",
        func_name=func_name,
        args={},
        extra_content=None,
    )


def _match_any_pattern(patterns: tuple[str, ...], lowered_text: str) -> bool:
    """判断 lowered_text 是否命中 patterns 中任意一个子串正则。"""

    return any(re.search(pattern, lowered_text) for pattern in patterns)


def _normalize_timing_gate_output(text: str) -> list[Any]:
    """对 Codex 在 Timing Gate 场景下返回的纯文本做保守规范化。

    仅在 ``request_type == "maisaka_timing_gate"`` 时由 ``generate_text`` 调用；
    其他请求类型不会进入本函数，行为完全不受影响。

    判定优先级：
    1. 强 continue 语义（"不该继续等待 / 不适合继续沉默 / 需要接话 / 在等回应" 等）
       一旦命中，立即返回 ``continue``，避免被同句中的 "继续等待 / 保持等待" 误判
       覆盖；
    2. 否则进入三个动作（continue / no_action / wait）的互斥判定：
       仅当唯一命中一个动作集合时构造对应的 ``ToolCall``；
       含糊（无命中）或冲突（命中多个）时返回空列表，
       由上游沿用原始 "无工具 → no_action" 行为；
    3. 不会修改原文本内容。
    """

    if not text or _ToolCall is None:
        return []

    lowered = text.lower()

    if _match_any_pattern(_TIMING_GATE_STRONG_CONTINUE_PATTERNS, lowered):
        tool_call = _build_timing_gate_tool_call("continue")
        if tool_call is None:
            return []
        return [tool_call]

    matches = {
        "continue": _match_any_pattern(_TIMING_GATE_CONTINUE_PATTERNS, lowered),
        "no_action": _match_any_pattern(_TIMING_GATE_NO_ACTION_PATTERNS, lowered),
        "wait": _match_any_pattern(_TIMING_GATE_WAIT_PATTERNS, lowered),
    }
    decided = [name for name, hit in matches.items() if hit]
    if len(decided) != 1:
        return []

    tool_call = _build_timing_gate_tool_call(decided[0])
    if tool_call is None:
        return []
    return [tool_call]


def _normalize_planner_output(text: str, *, extra: dict | None) -> list[Any]:
    """对 Codex 在 Planner 场景下返回的纯文本做保守规范化。

    仅在 ``request_type == "maisaka_planner"`` 时由 ``generate_text`` 调用；
    其他请求类型不会进入本函数，行为完全不受影响。

    判定规则：
    - 必须从 ``extra["anchor_message_id"]`` 取到非空锚点消息 ID，否则返回空列表；
    - 命中任意否定关键词（"不应回复 / 不要回复 / 等待新消息" 等）则返回空列表；
    - 命中任意肯定关键词（"应回复 / 优先回复 / 调用 reply / 在呢，咋啦" 等）
      且未命中否定关键词时，构造 ``ToolCall(func_name="reply", args={"msg_id": anchor_message_id})``；
    - 同时命中肯定与否定视为冲突，返回空列表；
    - 含糊文本（无任何命中）返回空列表，沿用原行为。
    """

    if not text or _ToolCall is None:
        return []

    anchor_message_id = ""
    if isinstance(extra, dict):
        raw_anchor = extra.get("anchor_message_id")
        if raw_anchor is not None:
            anchor_message_id = str(raw_anchor).strip()
    if not anchor_message_id:
        return []

    action = _extract_planner_action(text)
    if action == "reply":
        return [
            _ToolCall(
                call_id=f"codex_planner_reply_{uuid.uuid4().hex[:12]}",
                func_name="reply",
                args={"msg_id": anchor_message_id},
                extra_content=None,
            )
        ]
    if action in ("none", "finish"):
        return []

    lowered = text.lower()
    if _match_any_pattern(_PLANNER_REPLY_NEGATIVE_PATTERNS, lowered):
        return []

    if not _match_any_pattern(_PLANNER_REPLY_POSITIVE_PATTERNS, lowered):
        return []

    return [
        _ToolCall(
            call_id=f"codex_planner_reply_{uuid.uuid4().hex[:12]}",
            func_name="reply",
            args={"msg_id": anchor_message_id},
            extra_content=None,
        )
    ]


_PLANNER_ACTION_PATTERN = re.compile(
    r"^\s*ACTION\s*:\s*(reply|none|finish)\s*$",
    re.IGNORECASE,
)


def _extract_planner_action(text: str) -> str | None:
    """从 Planner 文本中解析最后一个非空行上的 ``ACTION:`` 协议。

    返回值：
    - ``"reply"`` / ``"none"`` / ``"finish"``：匹配到的指令（小写）
    - ``None``：最后非空行不是合法 ``ACTION:`` 行

    实现说明：
    - 仅检查文本中最后一个非空行（prompt 明确要求"最后一行必须只有 ACTION"）；
    - 若最后非空行不是 ``ACTION:``，视为模型未遵守协议，返回 None 让上层走 fallback；
    - 大小写不敏感；
    - 容错：若整行被反引号包裹（例如 `` `ACTION: reply` ``），先剥离反引号再匹配。
    """

    if not text:
        return None
    last_non_blank: str | None = None
    for raw_line in text.splitlines():
        stripped = raw_line.strip()
        if stripped:
            last_non_blank = stripped
    if last_non_blank is None:
        return None
    cleaned = last_non_blank.strip("`").strip()
    match = _PLANNER_ACTION_PATTERN.match(cleaned)
    if match is None:
        return None
    return match.group(1).lower()


def _get_plugin_config():
    """惰性解析 Codex Chat 插件配置。

    优先级：
    1. ``sys.modules`` 中已注册的 ``src.plugins.nonebot_plugin_codex_chat.config``
    2. ``sys.modules`` 中已注册的 ``nonebot_plugin_codex_chat.config``
    3. 尝试 ``importlib.import_module`` 加载两者

    Returns:
        ConfigModel: nonebot 插件配置对象。

    Raises:
        RuntimeError: 当所有候选模块都不可用时抛出。
    """
    errors: list[str] = []

    for module_name in _PLUGIN_CONFIG_CANDIDATES:
        module = sys.modules.get(module_name)
        if module is not None and hasattr(module, "get_config"):
            return module.get_config()

    for module_name in _PLUGIN_CONFIG_CANDIDATES:
        try:
            module = importlib.import_module(module_name)
            get_config = getattr(module, "get_config")
            return get_config()
        except Exception as exc:
            errors.append(f"{module_name}: {type(exc).__name__}: {exc}")

    raise RuntimeError(
        "Unable to load codex chat plugin config from candidates: "
        + " | ".join(errors)
    )


def _get_codex_provider_module():
    """惰性解析 codex_provider 模块。

    优先级：
    1. ``sys.modules`` 中已注册的候选模块
    2. ``importlib.import_module`` 尝试加载

    Returns:
        types.ModuleType: codex_provider 模块对象。

    Raises:
        RuntimeError: 当所有候选模块都不可用时抛出。
    """
    errors: list[str] = []

    for module_name in _CODEX_PROVIDER_CANDIDATES:
        module = sys.modules.get(module_name)
        if module is not None and hasattr(module, "ask_codex"):
            return module

    for module_name in _CODEX_PROVIDER_CANDIDATES:
        try:
            module = importlib.import_module(module_name)
            if hasattr(module, "ask_codex"):
                return module
        except Exception as exc:
            errors.append(f"{module_name}: {type(exc).__name__}: {exc}")

    raise RuntimeError(
        "Unable to load codex_provider from candidates: "
        + " | ".join(errors)
    )


async def generate_text(
    prompt: str,
    *,
    system_prompt: str | None = None,
    request_type: str = "",
    image_base64: str | None = None,
    image_url: str | None = None,
    extra: dict | None = None,
) -> CodexGenerateResult:
    config = _get_plugin_config()
    logger.info(f"maibot_codex_llm request_type={request_type}")

    try:
        provider = _get_codex_provider_module()
        ask_codex = provider.ask_codex
    except Exception as exc:
        logger.exception(
            f"maibot_codex_llm failed error={type(exc).__name__}: {exc}\n{traceback.format_exc()}"
        )
        return CodexGenerateResult(text="", tool_calls=None, ok=False)

    payload_parts: list[str] = []
    if system_prompt:
        payload_parts.append(f"[system]\n{system_prompt}")
    payload_parts.append(prompt)
    if image_url:
        payload_parts.append(f"[image_url]\n{image_url}")
    if image_base64:
        payload_parts.append("[image_base64]\n<base64 omitted>")
    if extra:
        payload_parts.append(f"[extra]\n{extra}")
    payload = "\n\n".join(payload_parts).strip()

    try:
        result = await ask_codex(config, payload)
        if not result.ok:
            logger.warning(f"maibot_codex_llm failed error={result.reason}")
            return CodexGenerateResult(text="", tool_calls=None, ok=False)
        text = (result.text or "").strip()
        logger.info(f"maibot_codex_llm success chars={len(text)}")

        tool_calls: list[Any] | None = None
        if request_type == "maisaka_timing_gate":
            tool_calls = _normalize_timing_gate_output(text)
            if tool_calls:
                decision = getattr(tool_calls[0], "func_name", "unknown")
                snippet = (text[:80] + "...") if len(text) > 80 else text
                logger.info(
                    f"maibot_codex_llm timing_gate decision={decision} "
                    f"request_type={request_type} text_chars={len(text)} snippet={snippet!r}"
                )
            else:
                logger.info(
                    f"maibot_codex_llm timing_gate decision=none request_type={request_type} "
                    f"text_chars={len(text)}"
                )
        elif request_type == "maisaka_planner":
            anchor_message_id = ""
            if isinstance(extra, dict):
                raw_anchor = extra.get("anchor_message_id")
                if raw_anchor is not None:
                    anchor_message_id = str(raw_anchor).strip()
            tool_calls = _normalize_planner_output(text, extra=extra)
            anchor_present = bool(anchor_message_id)
            if tool_calls:
                logger.info(
                    f"maibot_codex_llm planner decision=reply "
                    f"request_type={request_type} text_chars={len(text)} anchor_present={anchor_present}"
                )
            else:
                logger.info(
                    f"maibot_codex_llm planner decision=none request_type={request_type} "
                    f"text_chars={len(text)} anchor_present={anchor_present}"
                )

        return CodexGenerateResult(text=text, tool_calls=tool_calls, ok=True)
    except Exception as exc:
        logger.exception(f"maibot_codex_llm failed error={exc}")
        return CodexGenerateResult(text="", tool_calls=None, ok=False)
