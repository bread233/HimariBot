from __future__ import annotations

import re


_HARDWARE_KEYWORDS = [
    "rtx",
    "geforce",
    "nvidia",
    "英伟达",
    "显卡",
    "gpu",
    "cpu",
    "型号",
    "系列",
    "5090",
    "5070",
    "5060",
    "5080",
    "4090",
    "4070",
    "ti",
    "super",
]

_CURRENT_FACT_KEYWORDS = [
    "存在吗",
    "有吗",
    "发布了吗",
    "属于什么",
    "什么系列",
    "最新",
    "现在",
    "当前",
    "价格",
    "多少钱",
    "发售",
    "发布时间",
]


def detect_fact_sensitive_question(text: str) -> dict | None:
    raw = (text or "").strip()
    if not raw:
        return None
    low = raw.lower()

    has_hardware = any(keyword in low for keyword in _HARDWARE_KEYWORDS)
    has_current = any(keyword in raw for keyword in _CURRENT_FACT_KEYWORDS)
    has_model = bool(re.search(r"\b\d{4}\b", low))

    if has_hardware and has_current:
        return {
            "reason": "current_fact",
            "reply": "这类新硬件/型号/系列信息容易变化，我不能只凭本地模型记忆断言。建议查官方或可靠来源确认；等接入联网查询后我可以帮你直接查。",
        }
    if "rtx" in low and has_model:
        return {
            "reason": "hardware",
            "reply": "这类新硬件/型号/系列信息容易变化，我不能只凭本地模型记忆断言。建议查官方或可靠来源确认；等接入联网查询后我可以帮你直接查。",
        }
    if any(keyword in raw for keyword in ["价格", "多少钱", "最新", "现在", "当前", "发售", "发布时间"]):
        if has_hardware or has_model:
            return {
                "reason": "price",
                "reply": "这类当前信息变化很快，我不能只凭本地模型记忆回答。需要联网查证后再给结论。",
            }
    return None
