from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation


_COMPARE_HINTS = [
    "哪个大",
    "谁大",
    "更大",
    "大吗",
    "小吗",
    "比较",
    "大于",
    "小于",
    ">",
    "<",
    "=",
]


def _detect_claim(text: str, a_str: str, b_str: str) -> str | None:
    compact = re.sub(r"\s+", "", text)

    if f"{a_str}比{b_str}大" in compact or f"{a_str}>{b_str}" in compact:
        return ">"
    if f"{a_str}比{b_str}小" in compact or f"{a_str}<{b_str}" in compact:
        return "<"
    if f"{a_str}比{b_str}等于" in compact or f"{a_str}={b_str}" in compact:
        return "="

    if "大于" in text or ">" in text:
        return ">"
    if "小于" in text or "<" in text:
        return "<"
    if "等于" in text or "相等" in text or "=" in text:
        return "="
    return None


def detect_numeric_compare(prompt: str) -> dict | None:
    text = (prompt or "").strip()
    if not text:
        return None

    if "月" in text or "日" in text:
        return None
    if "元" in text or "价格" in text:
        return None

    if not any(hint in text for hint in _COMPARE_HINTS):
        return None

    nums = re.findall(r"[-+]?\d+(?:\.\d+)?", text)
    if len(nums) != 2:
        return None

    a_str, b_str = nums[0], nums[1]
    try:
        a = Decimal(a_str)
        b = Decimal(b_str)
    except InvalidOperation:
        return None

    if a > b:
        comparison = ">"
        larger = a_str
        smaller = b_str
    elif a < b:
        comparison = "<"
        larger = b_str
        smaller = a_str
    else:
        comparison = "="
        larger = a_str
        smaller = b_str

    claim = _detect_claim(text, a_str, b_str)
    claim_correct = None if claim is None else (claim == comparison)

    if claim is None:
        if comparison == "=":
            result_text = f"按十进制数值比较，{a_str} = {b_str}，两者相等。"
        else:
            result_text = f"按十进制数值比较，{a_str} {comparison} {b_str}，所以 {larger} 更大。"
    else:
        prefix = "对。" if claim_correct else "不对。"
        if comparison == "=":
            result_text = f"{prefix}按十进制数值比较，{a_str} = {b_str}，两者相等。"
        elif comparison == ">":
            result_text = f"{prefix}按十进制数值比较，{a_str} > {b_str}，所以 {a_str} 更大、{b_str} 更小。"
        else:
            result_text = f"{prefix}按十进制数值比较，{a_str} < {b_str}，所以 {b_str} 更大、{a_str} 更小。"

    return {
        "tool": "numeric_compare",
        "a": a_str,
        "b": b_str,
        "comparison": comparison,
        "claim": claim,
        "claim_correct": claim_correct,
        "larger": larger,
        "smaller": smaller,
        "result_text": result_text,
    }
