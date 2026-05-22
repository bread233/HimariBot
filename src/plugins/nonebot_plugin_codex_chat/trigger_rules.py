import re
from typing import Tuple

def is_group_allowed(group_id: int, allowed_groups: list[int]) -> bool:
    """群白名单判断"""
    return group_id in allowed_groups

def score_interest_text(text: str) -> int:
    """
    兴趣评分逻辑（简化版，可根据 QQ-Enhancer 正则扩展）
    包括：
      - 问句/标点
      - 技术/文化/新闻/活动关键词
      - 长度加成
      - 简单随机扰动
    """
    score = 0

    # 问句/标点加分
    if re.search(r"[?？!！]", text):
        score += 2

    # 示例兴趣关键词
    keywords = ["python", "游戏", "新闻", "活动", "漫画", "动漫", "技术", "教程"]
    for kw in keywords:
        if kw in text:
            score += 1

    # 长度加成
    if len(text) > 20:
        score += 1

    # 小幅稳定随机扰动
    score += 0  # 可留接口后续改成固定扰动

    return score

def should_trigger(group_id: int, text: str, config) -> Tuple[bool, int]:
    """
    判定是否触发：
    - 白名单
    - Proactive 开关
    - 兴趣评分阈值
    """
    if not config.codex_chat_proactive_enabled:
        return False, 0

    if not is_group_allowed(group_id, config.codex_chat_allowed_groups):
        return False, 0

    score = score_interest_text(text)
    return score >= config.codex_chat_interest_threshold, score