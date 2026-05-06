from __future__ import annotations

import re


_CORRECTION_KEYWORDS = [
    "你错了",
    "不对",
    "不是这样",
    "别瞎说",
    "你在胡说",
    "你又编",
    "实际上",
    "应该是",
    "以后",
    "记住",
    "明明是",
    "没查",
    "乱说",
    "别乱说",
    "不要乱说",
    "不是",
    "属于",
]

_PRAISE_KEYWORDS = [
    "这次不错",
    "这次可以",
    "答得好",
    "说得对",
    "就是这样",
    "靠谱",
    "保持这样",
]

_GENERIC_STOPWORDS = {
    "用户",
    "纠正",
    "提醒",
    "不要",
    "不是",
    "以后",
    "应该",
    "可以",
    "这个",
    "那个",
    "什么",
    "怎么",
    "没有",
    "知道",
    "如果",
    "已经",
    "当前",
    "回答",
    "问题",
    "模型",
    "旧知识",
    "乱说",
    "一个",
    "一下",
    "因为",
    "所以",
    "但是",
    "然后",
    "就是",
}


def _extract_english_tokens(text: str) -> list[str]:
    return [token for token in re.findall(r"[a-z0-9]+", text.lower()) if len(token) >= 3]


def _extract_chinese_phrases(text: str) -> list[str]:
    phrases = re.findall(r"[\u4e00-\u9fff]+", text)
    result = []
    for phrase in phrases:
        if len(phrase) < 2:
            continue
        for size in range(2, min(4, len(phrase)) + 1):
            for start in range(0, len(phrase) - size + 1):
                token = phrase[start : start + size]
                if token in _GENERIC_STOPWORDS:
                    continue
                result.append(token)
    return result


def _normalized_tokens(text: str) -> set[str]:
    raw = (text or "").lower()
    raw = re.sub(r"\s+", "", raw)
    tokens = set(_extract_english_tokens(raw))
    tokens.update(_extract_chinese_phrases(raw))
    return {token for token in tokens if token not in _GENERIC_STOPWORDS}


def _has_meaningful_overlap(prompt: str, content: str) -> bool:
    prompt_tokens = _normalized_tokens(prompt)
    content_tokens = _normalized_tokens(content)
    if not prompt_tokens or not content_tokens:
        return False
    overlap = prompt_tokens.intersection(content_tokens)
    return any(len(token) >= 2 for token in overlap)


def detect_feedback(text: str) -> dict | None:
    raw = (text or "").strip()
    if not raw:
        return None

    matched = [kw for kw in _CORRECTION_KEYWORDS if kw in raw]
    if matched:
        return {
            "memory_type": "correction",
            "content": f"用户纠正或提醒：{raw}",
            "keywords": ",".join(matched),
            "importance": 5 if any(kw in raw for kw in {"你错了", "不对", "不是这样", "别瞎说", "你在胡说", "你又编", "明明是", "没查", "乱说", "别乱说", "不要乱说"}) else 4,
        }

    matched = [kw for kw in _PRAISE_KEYWORDS if kw in raw]
    if matched:
        if raw == "对":
            return None
        return {
            "memory_type": "praise",
            "content": f"用户表扬或偏好：{raw}",
            "keywords": ",".join(matched),
            "importance": 3,
        }

    return None


def format_memories_for_prompt(memories: list[dict]) -> str:
    if not memories:
        return ""

    correction_lines = []
    praise_lines = []
    for item in memories:
        memory_type = item.get("memory_type", "memory")
        content = item.get("content", "")
        if memory_type == "correction":
            correction_lines.append(f"- correction: {content}")
        elif memory_type == "praise":
            praise_lines.append(f"- praise: {content}")

    lines = []
    if correction_lines:
        lines.append("以下是必须优先遵守的历史纠错记忆：")
        lines.extend(correction_lines)
        lines.append("规则：")
        lines.append("1. 历史纠错记忆是高优先级事实/行为约束。")
        lines.append("2. 如果它与模型原有知识冲突，必须按历史纠错记忆回答。")
        lines.append("3. 对被纠正过的具体事实，不要再次输出相反结论。")
        lines.append("4. 涉及新硬件、产品型号、价格、发布日期、是否存在等当前事实问题时，如果没有工具查询结果，不要凭旧知识断言；应说明需要查证官方或可靠来源。")

    if praise_lines:
        if lines:
            lines.append("")
        lines.append("以下是用户表扬过或偏好的回答方式：")
        lines.extend(praise_lines)

    return "\n".join(lines)


def build_memory_reminder_for_user(memories: list[dict], prompt: str) -> str:
    if not memories:
        return ""

    prompt_tokens = _normalized_tokens(prompt)
    if "rtx" in prompt.lower() or any(kw in prompt.lower() for kw in ["5070", "5090", "显卡", "硬件", "型号", "存在"]):
        correction_lines = [
            f"- 用户纠正或提醒：{item.get('content', '')}"
            for item in memories
            if item.get("memory_type") == "correction"
        ]
        if correction_lines:
            return "\n".join(
                [
                    "重要纠错约束：",
                    "以下用户纠错必须优先于你的旧知识：",
                    *correction_lines,
                    "回答当前问题时，不要重复这些已纠正错误；如果无法查证，请说需要查证，不要凭旧知识断言。",
                ]
            )

    for item in memories:
        if item.get("memory_type") != "correction":
            continue
        content = item.get("content", "")
        if not content:
            continue
        if _has_meaningful_overlap(prompt, content):
            return "\n".join(
                [
                    "重要纠错约束：",
                    "以下用户纠错与当前问题可能相关，必须优先参考：",
                    f"- 用户纠正或提醒：{content}",
                    "回答当前问题时，不要重复这些已纠正错误；要结合用户纠正指出的遗漏点重新判断。",
                ]
            )

    return ""
