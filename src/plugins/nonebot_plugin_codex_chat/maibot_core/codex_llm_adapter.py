from __future__ import annotations

import importlib
import json
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
    r"返回\W*no_action",
    r"应\W*no_action",
    r"按\W*no_action",
    # fix33a: 兼容模型不按 ACTION+ARGS 协议、只在文本里写裸 token 的退化样本。
    # ``\b`` 要求两侧为非单词字符（_ 算单词字符），所以 ``no_action`` /
    # ``no_action`` / ``(no_action)`` / `` no_action，`` 都会被命中。
    r"\bno_action\b",
    r"\bno_reply\b",
    # ``no action`` / ``no-action`` / ``no_action`` / ``no reply`` / ``no-reply`` /
    # ``no_reply`` 空格/连字符/下划线变体也一并兜底，避免模型把 token 拆写。
    r"no[\s\-_]+action",
    r"no[\s\-_]+reply",
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

# fix24: Planner ACTION + ARGS 协议白名单
# 仅白名单内的 ACTION 会被路由到对应工具；不在白名单内的
# 一律按 invalid_action 丢弃。``none`` 用于"不调用任何工具"；``finish`` 用于"结束本轮"。
_ALLOWED_PLANNER_ACTION_TOOLS: frozenset[str] = frozenset(
    {
        "reply",
        "finish",
        "view_complex_message",
        "query_jargon",
        "query_memory",
        "query_person_profile",
        "tool_search",
        "send_image",
        "send_emoji",
        "none",
    }
)

# 显式拒绝列表（当前为空）
_DISALLOWED_PLANNER_ACTION_TOOLS: frozenset[str] = frozenset()

# ACTION 行匹配：``ACTION: <identifier>``（大小写不敏感，允许反引号包裹）
_PLANNER_ACTION_LINE_PATTERN = re.compile(
    r"^\s*ACTION\s*:\s*([A-Za-z_][A-Za-z0-9_]*)\s*$",
    re.IGNORECASE,
)

# ARGS 行匹配：``ARGS: {<json>}``（贪婪至行尾，必须是 JSON object）
_PLANNER_ARGS_LINE_PATTERN = re.compile(
    r"^\s*ARGS\s*:\s*(\{.*\})\s*$",
    re.IGNORECASE,
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
    # fix24: 新 prompt 中明确指示 model 使用的关键词
    r"直接回一句",
    r"短回复",
    r"接住互动",
    r"接住对话",
    r"应接住对话",
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


def _build_timing_gate_tool_call(func_name: str, args: dict[str, Any] | None = None) -> Any:
    """为 Timing Gate 构造一个最小的 ToolCall 对象。"""

    if _ToolCall is None:
        return None
    return _ToolCall(
        call_id=f"timing_gate_{uuid.uuid4().hex[:12]}",
        func_name=func_name,
        args=dict(args) if args else {},
        extra_content=None,
    )


_TIMING_GATE_DEFAULT_WAIT_SECONDS = 30


def _resolve_timing_gate_wait_seconds(parsed_args: dict[str, Any] | None) -> int:
    """把 ARGS 里的 ``seconds`` 规范化为 ``int``，缺省或非法值时回退 30，且不低于 0。"""

    fallback = _TIMING_GATE_DEFAULT_WAIT_SECONDS
    if not isinstance(parsed_args, dict):
        return fallback
    raw = parsed_args.get("seconds")
    if raw is None:
        return fallback
    try:
        seconds = int(raw)
    except (TypeError, ValueError):
        return fallback
    return max(0, seconds)


def _extract_last_timing_gate_action_and_args(text: str) -> tuple[str | None, dict[str, Any] | None]:
    """从下到上扫描，取最后一个 ACTION + ARGS 对。"""
    if not text:
        return None, None

    lines = text.splitlines()
    action: str | None = None
    parsed_args: dict[str, Any] = {}

    last_action_idx = -1
    for i in range(len(lines) - 1, -1, -1):
        stripped = lines[i].strip()
        if not stripped:
            continue
        cleaned = stripped.strip("`").strip()
        m = _PLANNER_ACTION_LINE_PATTERN.match(cleaned)
        if m is not None:
            raw_action = m.group(1).lower()
            if raw_action in _TIMING_GATE_PROTOCOL_ACTIONS:
                action = "no_action" if raw_action == "none" else raw_action
                last_action_idx = i
                break

    if action is None:
        return None, None

    for j in range(last_action_idx + 1, len(lines)):
        stripped = lines[j].strip()
        if not stripped:
            continue
        cleaned = stripped.strip("`").strip()
        m_args = _PLANNER_ARGS_LINE_PATTERN.match(cleaned)
        if m_args is not None:
            try:
                decoded = json.loads(m_args.group(1))
            except (TypeError, ValueError):
                decoded = None
            if isinstance(decoded, dict):
                parsed_args = decoded
            break

    return action, parsed_args


def _parse_timing_gate_fallback_text_action(
    text: str,
    available_tool_names: set[str],
) -> tuple[str | None, dict[str, Any] | None]:
    """从 fallback LLM 文本响应中解析 Timing Gate action/args。"""
    if not text or not available_tool_names:
        logger.info(f"maibot_timing_fallback_text_action_parse_failed reason=empty_input text_chars={len(text)}")
        return None, None

    action, args = _extract_last_timing_gate_action_and_args(text)
    if action is not None and action in available_tool_names:
        logger.info(f"maibot_timing_fallback_text_action_parsed action={action} args={args or {}}")
        return action, args or {}

    json_obj = _extract_json_from_last_line(text)
    if json_obj is not None:
        raw_action = json_obj.get("action") or json_obj.get("name")
        if raw_action and isinstance(raw_action, str):
            raw_action = raw_action.strip().lower()
            if raw_action in available_tool_names:
                action = "no_action" if raw_action == "none" else raw_action
                args = json_obj.get("args") or json_obj.get("arguments") or {}
                if not isinstance(args, dict):
                    args = {}
                logger.info(f"maibot_timing_fallback_text_action_parsed action={action} args={args}")
                return action, args

    logger.info(f"maibot_timing_fallback_text_action_parse_failed reason=no_valid_action text_chars={len(text)}")
    return None, None


def _resolve_tool_call_args(args_raw: Any) -> dict[str, Any]:
    """将 OpenAI-like arguments 规范化为 dict。"""
    if isinstance(args_raw, dict):
        return args_raw
    if isinstance(args_raw, str):
        try:
            decoded = json.loads(args_raw)
            if isinstance(decoded, dict):
                return decoded
        except (TypeError, ValueError):
            pass
    return {}


_PLANNER_FALLBACK_TOOL_NAMES: frozenset[str] = frozenset(
    {"reply", "send_emoji", "send_image", "no_action"}
)


def _normalize_planner_tool_calls_list(
    raw_calls: list[dict],
    valid_names: set[str],
) -> list[Any] | None:
    """规范化并校验 tool_calls 列表，返回 ``ToolCall`` 对象列表。

    规则：
    1. 缺 ``id`` 时生成 ``call_xxx``。
    2. ``type`` 缺失时补 ``"function"``（不校验）。
    3. ``function`` 缺失或 ``function.name`` 缺失则丢弃。
    4. ``function.name`` 不在 ``valid_names`` 中则丢弃。
    5. ``function.arguments`` 如果是 ``None`` 或空字符串 -> ``"{}"``。
    6. ``function.arguments`` 如果是 ``dict`` -> ``json.dumps(ensure_ascii=False)``。
    7. ``reply`` 必须有 ``msg_id``，否则丢弃。
    """
    if _ToolCall is None or not raw_calls:
        return None

    results: list[Any] = []
    for item in raw_calls:
        if not isinstance(item, dict):
            continue

        call_id = str(item.get("id") or "").strip()
        if not call_id:
            call_id = f"call_{uuid.uuid4().hex[:12]}"

        func = item.get("function")
        if not isinstance(func, dict):
            name = str(item.get("name") or "").strip()
            if not name:
                continue
            func = {"name": name, "arguments": item.get("arguments")}

        name = str(func.get("name") or "").strip()
        if not name or name not in valid_names:
            continue

        args = _resolve_tool_call_args(func.get("arguments"))

        if name == "reply":
            msg_id = str((args or {}).get("msg_id") or "").strip()
            if not msg_id:
                logger.info("maibot_planner_normalize_reply_missing_msg_id")
                continue

        results.append(_ToolCall(
            call_id=call_id,
            func_name=name,
            args=args or {},
            extra_content=None,
        ))

    return results if results else None


def _parse_planner_fallback_text_tool_calls(
    text: str,
    available_tool_names: set[str] | None = None,
) -> list[Any] | None:
    """从 fallback LLM 文本响应中解析 Planner tool_calls。

    解析链（依次尝试，任一成功即返回）：
    1. 多策略 JSON 提取（``_extract_embedded_planner_json``）→ 规范化 tool_calls。
    2. 从 JSON 中提取单工具（``name`` + ``arguments``）。
    3. ``ACTION:`` + ``ARGS:`` 文本协议。
    """
    if not text:
        logger.info("maibot_planner_fallback_text_tool_parse_failed reason=empty")
        return None

    valid_names = available_tool_names if available_tool_names else _PLANNER_FALLBACK_TOOL_NAMES
    if not valid_names:
        logger.info("maibot_planner_fallback_text_tool_parse_failed reason=no_valid_names")
        return None

    # --- 1) 多策略 JSON 提取 ---
    json_obj = _extract_embedded_planner_json(text)
    if json_obj is not None:
        # a) tool_calls 数组
        raw_calls = json_obj.get("tool_calls")
        if isinstance(raw_calls, list) and raw_calls:
            normalized = _normalize_planner_tool_calls_list(raw_calls, valid_names)
            if normalized:
                logger.info(
                    "maibot_planner_json_recovered source=embedded_json tool_count=%d",
                    len(normalized),
                )
                return normalized
            logger.info("maibot_planner_fallback_text_tool_parse_failed reason=no_valid_tool_in_list")
            return None

        # b) 单工具格式
        func_name = (json_obj.get("name") or "").strip()
        if func_name in valid_names:
            args = _resolve_tool_call_args(json_obj.get("arguments"))
            if _ToolCall is not None:
                if func_name == "reply":
                    msg_id = str((args or {}).get("msg_id") or "").strip()
                    if not msg_id:
                        logger.info("maibot_planner_fallback_reply_missing_msg_id name=reply")
                        return None
                return [_ToolCall(
                    call_id=f"planner_fb_{uuid.uuid4().hex[:12]}",
                    func_name=func_name,
                    args=args,
                )]

    # --- 2) ACTION/ARGS 文本协议 ---
    action, parsed_args, error = _extract_planner_action_and_args(text)
    if action is not None:
        if error is not None:
            logger.info(
                "maibot_planner_fallback_text_tool_parse_failed reason=action_error action=%s error=%s",
                action, error,
            )
            return None
        if action not in valid_names:
            logger.info(
                "maibot_planner_fallback_text_tool_parse_failed reason=action_not_allowed action=%s",
                action,
            )
            return None
        if _ToolCall is not None:
            if action == "reply":
                msg_id = str((parsed_args or {}).get("msg_id") or "").strip()
                if not msg_id:
                    logger.info("maibot_planner_fallback_reply_missing_msg_id name=reply")
                    return None
            logger.info("maibot_planner_action_args_recovered action=%s", action)
            return [_ToolCall(
                call_id=f"planner_fb_{uuid.uuid4().hex[:12]}",
                func_name=action,
                args=parsed_args or {},
            )]

    logger.info("maibot_planner_fallback_text_tool_parse_failed reason=no_json_found")
    return None


def _match_any_pattern(patterns: tuple[str, ...], lowered_text: str) -> bool:
    """判断 lowered_text 是否命中 patterns 中任意一个子串正则。"""

    return any(re.search(pattern, lowered_text) for pattern in patterns)


_TIMING_GATE_PROTOCOL_ACTIONS: frozenset[str] = frozenset(
    {"continue", "no_action", "wait", "none"}
)


def _extract_timing_gate_action_and_args(
    text: str,
) -> tuple[str | None, dict[str, Any] | None]:
    """从 Timing Gate 文本中解析 ``ACTION:`` + ``ARGS:`` 协议。

    与 Planner 共用同一组正则 ``_PLANNER_ACTION_LINE_PATTERN`` /
    ``_PLANNER_ARGS_LINE_PATTERN``（语法一致）；从下到上扫描，
    取最后一个非空 ``ACTION:`` 行，再向下取最近一个非空 ``ARGS:`` 行。

    Returns:
        ``(action, parsed_args)``：
        - action: 标准化小写 ACTION 名（``none`` 已被映射为 ``no_action``）；
          当且仅当未找到 ``ACTION:`` 行时为 ``None``（让上层走中文 fallback）。
        - parsed_args: 解析后的 JSON object（``dict``）；缺省/无 ARGS 行时为
          ``{}``；JSON 解析失败时退回到 ``{}``（lenient，不让 ARGS 坏掉一次好 ACTION）。
    """

    if not text:
        return None, None

    action: str | None = None
    parsed_args: dict[str, Any] = {}
    args_seen = False
    for raw_line in text.splitlines():
        stripped = raw_line.strip()
        if not stripped:
            continue
        cleaned = stripped.strip("`").strip()
        if action is None:
            m = _PLANNER_ACTION_LINE_PATTERN.match(cleaned)
            if m is not None:
                raw_action = m.group(1).lower()
                if raw_action in _TIMING_GATE_PROTOCOL_ACTIONS:
                    action = "no_action" if raw_action == "none" else raw_action
                else:
                    return None, None
        else:
            m_args = _PLANNER_ARGS_LINE_PATTERN.match(cleaned)
            if m_args is not None and not args_seen:
                args_seen = True
                try:
                    decoded = json.loads(m_args.group(1))
                except (TypeError, ValueError):
                    decoded = None
                if isinstance(decoded, dict):
                    parsed_args = decoded

    return action, parsed_args


def _normalize_timing_gate_output(text: str) -> list[Any]:
    """对 Codex 在 Timing Gate 场景下返回的纯文本做保守规范化。

    仅在 ``request_type == "maisaka_timing_gate"`` 时由 ``generate_text`` 调用；
    其他请求类型不会进入本函数，行为完全不受影响。

    判定优先级：
    1. ``ACTION:`` + ``ARGS:`` 协议：模型若明确给出 ``continue`` / ``no_action``
       / ``wait``（``none`` 等价于 ``no_action``），立即按协议构造 ``ToolCall``；
       未知 ACTION 名（既不在白名单也不在中文 fallback）→ ``[]`` 触发上层
       3 次重试，让 reasoning_engine 重新提示模型走正确协议。
    2. 强 continue 语义（"不该继续等待 / 不适合继续沉默 / 需要接话 / 在等回应" 等）
       一旦命中，立即返回 ``continue``，避免被同句中的 "继续等待 / 保持等待" 误判
       覆盖；
    3. 否则进入三个动作（continue / no_action / wait）的互斥判定：
       仅当唯一命中一个动作集合时构造对应的 ``ToolCall``；
       含糊（无命中）或冲突（命中多个）时返回空列表，
       由上游沿用原始 "无工具 → no_action" 行为；
    4. 不会修改原文本内容。
    """

    if not text or _ToolCall is None:
        return []

    protocol_action, protocol_args = _extract_timing_gate_action_and_args(text)
    if protocol_action is not None:
        if protocol_action == "wait":
            wait_seconds = _resolve_timing_gate_wait_seconds(protocol_args)
            call_args: dict[str, Any] = {"seconds": wait_seconds}
        else:
            call_args = dict(protocol_args) if protocol_args else {}
        tool_call = _build_timing_gate_tool_call(protocol_action, call_args)
        if tool_call is None:
            return []
        return [tool_call]

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


def _strip_code_fence(text: str) -> str:
    """Remove optional markdown code fence wrapping from *text*."""
    stripped = text.strip()
    if stripped.startswith("```"):
        first_nl = stripped.find("\n")
        if first_nl != -1:
            stripped = stripped[first_nl + 1 :]
        if stripped.endswith("```"):
            stripped = stripped[:-3]
        stripped = stripped.strip()
    return stripped


def _find_code_fence_json(text: str) -> dict | None:
    """Try to extract JSON from a markdown code fence anywhere in *text*.

    Scans for ``` opening fence, extracts content up to closing ```,
    and attempts to parse as JSON dict.
    """
    lines = text.splitlines()
    in_fence = False
    fence_content: list[str] = []
    for line in lines:
        stripped_line = line.strip()
        if not in_fence:
            if stripped_line.startswith("```"):
                in_fence = True
                fence_content = []
            continue
        if stripped_line == "```":
            inner = "\n".join(fence_content).strip()
            if inner.startswith("{"):
                try:
                    parsed = json.loads(inner)
                    if isinstance(parsed, dict):
                        return parsed
                except Exception:
                    pass
            in_fence = False
            fence_content = []
        else:
            fence_content.append(line)
    return None


def _extract_json_from_last_line(text: str) -> dict | None:
    """从 text 的最后一个非空行提取 JSON 对象。

    规则：JSON 必须出现在最后一个非空行（允许 code-fence 包裹）。
    如果最后一个非空行不是合法 JSON 对象，返回 ``None``。
    """
    # 1) 先尝试整段 code-fence 清理后的 JSON
    candidate = _strip_code_fence(text)
    if candidate.startswith("{"):
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            pass

    # 2) 尝试从文本中任意位置的 code-fence 提取 JSON
    fence_result = _find_code_fence_json(text)
    if fence_result is not None:
        return fence_result

    # 3) 扫描最后一个非空行，必须是 JSON
    lines = text.splitlines()
    for raw_line in reversed(lines):
        stripped = raw_line.strip()
        if not stripped:
            continue
        # 第一个遇到的非空行必须是 JSON
        if stripped.startswith("{") and stripped.endswith("}"):
            try:
                parsed = json.loads(stripped)
                if isinstance(parsed, dict):
                    return parsed
            except Exception:
                pass
        # 非空行不是合法 JSON → 立即返回 None
        return None
    return None


def _find_balanced_braces_fragments(text: str) -> list[str]:
    """从文本中提取所有顶层 ``{...}`` 片段，字符串感知（跳过字符串内的括号）。"""
    fragments: list[str] = []
    depth = 0
    start = -1
    i = 0
    while i < len(text):
        ch = text[i]
        if ch == '"':
            i += 1
            while i < len(text):
                if text[i] == '\\':
                    i += 2
                    continue
                if text[i] == '"':
                    break
                i += 1
        elif ch == '{':
            if depth == 0:
                start = i
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0 and start >= 0:
                fragments.append(text[start:i + 1])
                start = -1
        i += 1
    return fragments


def _extract_embedded_planner_json(text: str) -> dict | None:
    """多策略从 Planner 文本中提取 JSON 对象。

    1) 尝试整段纯文本（含 code-fence 清理后）为 JSON。
    2) 尝试最后一个非空行为 JSON。
    3) 字符串感知的平衡括号扫描：取所有 ``{...}`` 片段，从后往前尝试 ``json.loads``。
    """
    if not text:
        return None

    # 策略 1：整段（先清理 code-fence）
    candidate = _strip_code_fence(text)
    if candidate.startswith("{"):
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            pass

    # 策略 2：最后一个非空行
    for raw_line in reversed(text.splitlines()):
        stripped = raw_line.strip()
        if not stripped:
            continue
        if stripped.startswith("{") and stripped.endswith("}"):
            try:
                parsed = json.loads(stripped)
                if isinstance(parsed, dict):
                    return parsed
            except Exception:
                pass
        break

    # 策略 3：平衡括号片段（从后往前）
    for fragment in reversed(_find_balanced_braces_fragments(text)):
        try:
            parsed = json.loads(fragment)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            continue

    return None


def _extract_planner_tool_calls_json(
    text: str,
) -> list[Any] | None:
    """尝试从 Planner 文本中解析 OpenAI-like ``tool_calls`` JSON。

    支持的格式：
    - 整段为纯 JSON / code-fence 包裹的 JSON
    - 分析文本之后最后一行是 JSON 对象

    返回 ``None`` 表示文本不含合法 tool_calls JSON，
    调用方应回退到 ACTION/ARGS 协议。
    """
    if not text or _ToolCall is None:
        return None

    parsed = _extract_json_from_last_line(text)
    if parsed is None:
        return None

    raw_calls = parsed.get("tool_calls")
    if not isinstance(raw_calls, list):
        return None

    if not raw_calls:
        return []

    results: list[Any] = []
    for item in raw_calls:
        if not isinstance(item, dict):
            continue

        item_type = str(item.get("type") or "").strip()
        if item_type != "function":
            logger.debug(
                "codex_planner_tool_calls_json_bad_type type=%s", item_type or "(missing)",
            )
            continue

        func = item.get("function")
        if not isinstance(func, dict):
            continue
        name = str(func.get("name") or "").strip()
        if not name:
            continue
        if name not in _ALLOWED_PLANNER_ACTION_TOOLS:
            logger.debug(
                "codex_planner_tool_calls_json_unknown_tool name=%s", name,
            )
            continue

        raw_args = func.get("arguments")
        args_dict: dict[str, Any] = {}
        if raw_args is None or raw_args == "":
            pass
        elif isinstance(raw_args, str):
            stripped_args = raw_args.strip()
            if not stripped_args:
                pass
            else:
                try:
                    parsed_args = json.loads(stripped_args)
                except Exception:
                    logger.debug(
                        "codex_planner_tool_calls_json_bad_args name=%s raw=%s",
                        name,
                        stripped_args[:120],
                    )
                    continue
                if not isinstance(parsed_args, dict):
                    logger.debug(
                        "codex_planner_tool_calls_json_args_not_dict name=%s got=%s",
                        name,
                        type(parsed_args).__name__,
                    )
                    continue
                args_dict = parsed_args
        elif isinstance(raw_args, dict):
            args_dict = raw_args
        else:
            logger.debug(
                "codex_planner_tool_calls_json_args_unsupported_type name=%s got=%s",
                name,
                type(raw_args).__name__,
            )
            continue

        call_id = str(item.get("id") or "").strip()
        if not call_id:
            call_id = f"codex_planner_{name}_{uuid.uuid4().hex[:12]}"

        results.append(
            _ToolCall(
                call_id=call_id,
                func_name=name,
                args=args_dict,
                extra_content=None,
            )
        )

    if len(results) > 1:
        logger.info(
            "codex_planner_tool_calls_json_multiple count=%d using_first=True",
            len(results),
        )

    return results if results else None


def _normalize_planner_output(text: str, *, extra: dict | None) -> list[Any]:
    """对 Codex 在 Planner 场景下返回的纯文本做保守规范化。

    仅在 ``request_type == "maisaka_planner"`` 时由 ``generate_text`` 调用；
    其他请求类型不会进入本函数，行为完全不受影响。

    fix34k 协议升级：优先解析 OpenAI-like ``tool_calls`` JSON；
    若非合法 JSON，回退到 ``ACTION:`` + ``ARGS:`` 文本协议；
    若无 ACTION 行，再回退到中文 positive/negative 关键词。
    """

    if not text or _ToolCall is None:
        return []

    anchor_message_id = ""
    latest_at_bot_msg_id = ""
    if isinstance(extra, dict):
        raw_anchor = extra.get("anchor_message_id")
        if raw_anchor is not None:
            anchor_message_id = str(raw_anchor).strip()
        raw_at_bot = extra.get("latest_at_current_bot_msg_id")
        if raw_at_bot is not None:
            latest_at_bot_msg_id = str(raw_at_bot).strip()
    if latest_at_bot_msg_id and latest_at_bot_msg_id != anchor_message_id:
        logger.info(
            "maisaka_reply_anchor_corrected from=%s to=%s reason=at_current_bot_detected",
            anchor_message_id,
            latest_at_bot_msg_id,
        )
        anchor_message_id = latest_at_bot_msg_id

    # --- fix34k: 优先尝试 OpenAI-like tool_calls JSON ---
    json_calls = _extract_planner_tool_calls_json(text)
    if json_calls is not None:
        if not json_calls:
            logger.info("codex_planner_tool_calls_json_empty")
            return []
        first = json_calls[0]
        name = getattr(first, "func_name", None)
        if name == "none":
            return []
        if name in ("reply", "view_complex_message") and not anchor_message_id:
            logger.warning(
                "codex_planner_json_dropped action=%s reason=no_anchor_message_id",
                name,
            )
            return []
        logger.info(
            "codex_planner_json_accepted action=%s anchor_present=%s "
            "args_keys=%s",
            name,
            bool(anchor_message_id),
            sorted(getattr(first, "args", None) or {}),
        )
        return _build_planner_tool_call(
            name, dict(getattr(first, "args", None) or {}), anchor_message_id,
        )

    # --- 回退: ACTION/ARGS 文本协议 ---
    action, parsed_args, error = _extract_planner_action_and_args(text)
    if action is not None:
        if error is not None:
            logger.info(
                "codex_planner_action_rejected action=%s reason=%s",
                action,
                error,
            )
            return []
        args_keys = sorted(parsed_args.keys()) if isinstance(parsed_args, dict) else []
        logger.info(
            "codex_planner_action_accepted action=%s anchor_present=%s "
            "args_valid=%s args_keys=%s",
            action,
            bool(anchor_message_id),
            True,
            args_keys,
        )
        if not anchor_message_id and action in ("reply", "view_complex_message"):
            logger.warning(
                "codex_planner_action_dropped action=%s reason=no_anchor_message_id",
                action,
            )
            return []
        return _build_planner_tool_call(action, parsed_args, anchor_message_id)

    if not anchor_message_id:
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


def _extract_planner_action_and_args(
    text: str,
) -> tuple[str | None, dict[str, Any] | None, str | None]:
    """从 Planner 文本中解析 ``ACTION:`` + ``ARGS:`` 协议。

    协议位置不限，但 prompt 要求"最后两行必须是 ACTION / ARGS"；
    本函数从下到上扫描，定位最后一个非空 ``ACTION:`` 行，再向下取最近一个
    非空 ``ARGS:`` 行。

    Returns:
        ``(action, args, error)``：
        - action: 标准化小写 ACTION 名；当且仅当未找到 ``ACTION:`` 行时为 ``None``。
        - args: 解析后的 JSON object（``dict``）；缺省/无 ARGS 行时为 ``{}``；
          解析失败或非 dict 时为 ``None``。
        - error: 错误标识；``"invalid_action"`` / ``"invalid_args"`` / ``None``。
    """

    if not text:
        return None, None, None

    lines = text.splitlines()
    action_line_idx = -1
    action: str | None = None
    for idx, raw in enumerate(lines):
        stripped = raw.strip()
        if not stripped:
            continue
        cleaned = stripped.strip("`").strip()
        m = _PLANNER_ACTION_LINE_PATTERN.match(cleaned)
        if m is None:
            continue
        action_line_idx = idx
        action = m.group(1).lower()

    if action is None or action_line_idx < 0:
        return None, None, None

    if action in _DISALLOWED_PLANNER_ACTION_TOOLS:
        return action, None, "invalid_action"
    if action not in _ALLOWED_PLANNER_ACTION_TOOLS:
        return action, None, "invalid_action"

    for raw in lines[action_line_idx + 1:]:
        stripped = raw.strip()
        if not stripped:
            continue
        cleaned = stripped.strip("`").strip()
        m = _PLANNER_ARGS_LINE_PATTERN.match(cleaned)
        if m is None:
            break
        try:
            parsed = json.loads(m.group(1))
        except Exception:
            return action, None, "invalid_args"
        if not isinstance(parsed, dict):
            return action, None, "invalid_args"
        return action, parsed, None

    return action, {}, None


def _build_planner_tool_call(
    action: str,
    args: dict[str, Any] | None,
    anchor_message_id: str,
) -> list[Any]:
    """根据 ACTION + ARGS 构造 ToolCall。失败时返回 ``[]`` 并写日志。

    - ``action == "none"`` -> ``[]``（明确不调用任何工具）
    - ``action == "reply"`` -> 必须有 ``anchor_message_id``；自动注入 ``msg_id`` 和
      ``set_quote=True``（除非调用方已经显式给出 ``set_quote``）。
    - ``action == "view_complex_message"`` -> 必须有 ``anchor_message_id``；
      自动注入 ``msg_id``。
    - ``action == "query_jargon"`` -> 必须有非空 ``words`` 列表；``str`` 会被归一为单元素列表。
    - ``action == "query_memory"`` -> 必须满足 ``query``（非空 str）或
      ``time_start`` + ``time_end`` 同时存在。
    - ``action == "query_person_profile"`` -> 必须有 ``person_id`` 或 ``person_name``。
    - ``action == "tool_search"`` -> 必须有非空 ``query`` 字符串。
    - ``action == "send_image"`` -> 必须有非空 ``msg_id`` 或非空 ``media_index``；
      ``index`` 可选，必须能转 int，非法值回退 0。
    - ``action == "send_emoji"`` -> 可选 ``emotion`` 参数（非字符串会被转为字符串）；
      无参数时发送随机表情。
    - ``action == "finish"`` -> 直接构造 ``finish`` 工具调用，args 透传。
    """

    if _ToolCall is None:
        return []

    if action == "none":
        return []

    if action == "reply":
        if not anchor_message_id:
            logger.warning(
                "codex_planner_action_dropped action=reply reason=no_anchor_message_id"
            )
            return []
        merged: dict[str, Any] = dict(args or {})
        merged["msg_id"] = anchor_message_id
        merged.setdefault("set_quote", True)
        return [
            _ToolCall(
                call_id=f"codex_planner_reply_{uuid.uuid4().hex[:12]}",
                func_name="reply",
                args=merged,
                extra_content=None,
            )
        ]

    if action == "finish":
        return [
            _ToolCall(
                call_id=f"codex_planner_finish_{uuid.uuid4().hex[:12]}",
                func_name="finish",
                args=dict(args or {}),
                extra_content=None,
            )
        ]

    if action == "view_complex_message":
        if not anchor_message_id:
            logger.warning(
                "codex_planner_action_dropped action=view_complex_message "
                "reason=no_anchor_message_id"
            )
            return []
        merged = dict(args or {})
        merged.setdefault("msg_id", anchor_message_id)
        return [
            _ToolCall(
                call_id=f"codex_planner_view_{uuid.uuid4().hex[:12]}",
                func_name="view_complex_message",
                args=merged,
                extra_content=None,
            )
        ]

    if action == "query_jargon":
        merged = dict(args or {})
        words = merged.get("words")
        if isinstance(words, str) and words.strip():
            merged["words"] = [words.strip()]
            words = merged["words"]
        if not isinstance(words, list) or not words:
            logger.warning(
                "codex_planner_action_dropped action=query_jargon reason=invalid_words"
            )
            return []
        normalized: list[str] = []
        for item in words:
            if isinstance(item, str) and item.strip():
                normalized.append(item.strip())
        if not normalized:
            logger.warning(
                "codex_planner_action_dropped action=query_jargon reason=empty_words"
            )
            return []
        merged["words"] = normalized
        return [
            _ToolCall(
                call_id=f"codex_planner_jargon_{uuid.uuid4().hex[:12]}",
                func_name="query_jargon",
                args=merged,
                extra_content=None,
            )
        ]

    if action == "query_memory":
        merged = dict(args or {})
        query = merged.get("query")
        time_start = merged.get("time_start")
        time_end = merged.get("time_end")
        has_query = isinstance(query, str) and query.strip() != ""
        has_time_range = (
            isinstance(time_start, str)
            and time_start.strip() != ""
            and isinstance(time_end, str)
            and time_end.strip() != ""
        )
        if not (has_query or has_time_range):
            logger.warning(
                "codex_planner_action_dropped action=query_memory "
                "reason=missing_query_or_time_range"
            )
            return []
        if has_query and isinstance(query, str):
            merged["query"] = query.strip()
        return [
            _ToolCall(
                call_id=f"codex_planner_memory_{uuid.uuid4().hex[:12]}",
                func_name="query_memory",
                args=merged,
                extra_content=None,
            )
        ]

    if action == "query_person_profile":
        merged = dict(args or {})
        person_id = merged.get("person_id")
        person_name = merged.get("person_name")
        valid_id = isinstance(person_id, str) and person_id.strip() != ""
        valid_name = isinstance(person_name, str) and person_name.strip() != ""
        if not (valid_id or valid_name):
            logger.warning(
                "codex_planner_action_dropped action=query_person_profile "
                "reason=missing_person_id_or_name"
            )
            return []
        return [
            _ToolCall(
                call_id=f"codex_planner_profile_{uuid.uuid4().hex[:12]}",
                func_name="query_person_profile",
                args=merged,
                extra_content=None,
            )
        ]

    if action == "tool_search":
        merged = dict(args or {})
        query = merged.get("query")
        if not (isinstance(query, str) and query.strip()):
            logger.warning(
                "codex_planner_action_dropped action=tool_search reason=missing_query"
            )
            return []
        merged["query"] = query.strip()
        return [
            _ToolCall(
                call_id=f"codex_planner_search_{uuid.uuid4().hex[:12]}",
                func_name="tool_search",
                args=merged,
                extra_content=None,
            )
        ]

    if action == "send_image":
        merged = dict(args or {})
        msg_id = str(merged.get("msg_id") or "").strip()
        media_index = str(merged.get("media_index") or "").strip()
        if not msg_id and not media_index:
            logger.warning(
                "codex_planner_action_dropped action=send_image "
                "reason=missing_msg_id_or_media_index"
            )
            return []
        if msg_id:
            merged["msg_id"] = msg_id
        else:
            merged.pop("msg_id", None)
        if media_index:
            merged["media_index"] = media_index
        else:
            merged.pop("media_index", None)
        raw_index = merged.get("index")
        if raw_index is not None:
            try:
                merged["index"] = int(raw_index)
            except (TypeError, ValueError):
                merged["index"] = 0
        return [
            _ToolCall(
                call_id=f"codex_planner_send_image_{uuid.uuid4().hex[:12]}",
                func_name="send_image",
                args=merged,
                extra_content=None,
            )
        ]

    if action == "send_emoji":
        merged = dict(args or {})
        emotion = merged.get("emotion")
        if emotion is not None:
            merged["emotion"] = str(emotion).strip()
        else:
            merged.pop("emotion", None)
        return [
            _ToolCall(
                call_id=f"codex_planner_send_emoji_{uuid.uuid4().hex[:12]}",
                func_name="send_emoji",
                args=merged,
                extra_content=None,
            )
        ]

    return []


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
