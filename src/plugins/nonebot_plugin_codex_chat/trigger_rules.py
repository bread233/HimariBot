import re
from typing import Tuple

def is_group_allowed(group_id: int, allowed_groups: list[int]) -> bool:
    """群白名单判断"""
    return group_id in allowed_groups

def _regex_hit(pattern: str, text: str) -> bool:
    pattern = str(pattern or "").strip()
    if not pattern:
        return False
    try:
        return re.search(pattern, text, flags=re.I) is not None
    except re.error:
        return False


def _pattern(config, name: str, default: str = "") -> str:
    if config is None:
        return default
    return str(getattr(config, name, default) or default)


def score_interest_text(text: str, config=None) -> int:
    """
    兴趣评分逻辑（QQ-Enhancer 风格加权版，支持 .env.dev 配置正则）
    """
    t = str(text or "").strip()
    if not t or len(t) < 2:
        return 0

    lower = t.lower()
    compact = re.sub(r"[\s\W_]+", "", t, flags=re.UNICODE)
    if not compact:
        return 0

    if re.fullmatch(r"\d+", t):
        return 0

    low_value_pattern = _pattern(
        config,
        "codex_chat_low_value_pattern",
        r"^(\?|？|。|\.|,|，|哈+|啊+|哦+|嗯+|1|6|66|666|草|艹|笑死|哈哈哈*)$",
    )
    if _regex_hit(low_value_pattern, lower):
        return 0

    zero_pattern = _pattern(
        config,
        "codex_chat_zero_pattern",
        r"色图|涩图|av视频|AV视频|\br18\b|开车|黄图|色情|porn|hentai",
    )
    if _regex_hit(zero_pattern, lower):
        return 0

    rules = [
        (_pattern(config, "codex_chat_active_interest_pattern",
                  r"怎么回事|发生什么|有新瓜|什么瓜|真的假的|笑死|乐子|抽象|绷不住|离谱|太怪了|逆天"), 5),
        (_pattern(config, "codex_chat_technical_interest_pattern",
                  r"python|docker|linux|git|github|报错|bug|代码|模型|ai|llm|prompt|服务器|容器|数据库|网络|部署"), 6),
        (_pattern(config, "codex_chat_technical_error_pattern",
                  r"失败|异常|错误|启动失败|起不来|挂了|崩了|连不上|超时"), 2),
        (_pattern(config, "codex_chat_culture_interest_pattern",
                  r"游戏|动画|漫画|番剧|角色|剧情|攻略|活动|抽卡|联动|视频|up主"), 6),
        (_pattern(config, "codex_chat_news_interest_pattern",
                  r"新闻|热搜|公告|更新|爆料|发布|版本|新活动"), 3),
        (_pattern(config, "codex_chat_activity_interest_pattern",
                  r"比赛|赛事|直播|开播|活动|更新|维护|兑换码"), 8),
        (_pattern(config, "codex_chat_question_pattern",
                  r"吗|呢|为什么|怎么|如何|啥|什么|有没有|谁知道|求问|请问|[?？]"), 2),
        (_pattern(config, "codex_chat_sharp_reply_pattern",
                  r"绷|典|乐|蚌埠住了|笑死|离谱|逆天|抽象"), 3),
        (_pattern(config, "codex_chat_life_interest_pattern", r""), 5),
    ]

    score = 0
    matched = False
    for pattern, weight in rules:
        if _regex_hit(pattern, lower):
            score += weight
            matched = True

    if not matched:
        return 0

    n = len(t)
    if 8 <= n <= 80:
        score += 1
    elif 80 < n <= 200:
        score += 2

    score += sum(ord(c) for c in t) % 4
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

    if not is_group_allowed(group_id, config.allowed_groups_list):
        return False, 0

    score = score_interest_text(text, config=config)
    return score >= config.codex_chat_interest_threshold, score
