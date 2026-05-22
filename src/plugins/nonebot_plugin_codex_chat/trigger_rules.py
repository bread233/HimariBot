import re
from typing import Tuple

def is_group_allowed(group_id: int, allowed_groups: list[int]) -> bool:
    """群白名单判断"""
    return group_id in allowed_groups

def score_interest_text(text: str) -> int:
    """
    兴趣评分逻辑（QQ-Enhancer 风格加权版）
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
    if re.fullmatch(r"(哈+|hh+|呵呵+|嘿嘿+|233+|6+|草+|乐+)", lower):
        return 0
    if re.match(r"^[!/\.#]", t):
        return 0
    if re.fullmatch(r"(菜单|help|帮助|签到|打卡|功能|指令|命令)", lower):
        return 0
    if re.search(r"(色图|涩图|av视频|AV视频|\br18\b|开车|黄图|色情|porn|hentai)", lower, flags=re.I):
        return 0

    score = 0
    matched = False
    rules = [
        (r"(怎么回事|发生什么|有新瓜|什么瓜|真的假的|笑死|乐子|抽象|绷不住|离谱|太怪了|逆天)", 5),
        (r"(python|docker|linux|git|github|报错|bug|代码|模型|ai|llm|prompt|服务器|容器|数据库|网络|部署)", 6),
        (r"(失败|异常|错误|启动失败|起不来|挂了|崩了|连不上|超时)", 2),
        (r"(游戏|动画|漫画|番剧|角色|剧情|攻略|活动|抽卡|联动|视频|up主)", 4),
        (r"(新闻|热搜|公告|更新|爆料|发布|版本|新活动)", 3),
        (r"(比赛|赛事|直播|开播|活动|更新|维护|兑换码)", 5),
        (r"(吗|呢|为什么|怎么|如何|啥|什么|有没有|谁知道|求问|请问|[?？])", 2),
        (r"(绷|典|乐|蚌埠住了|笑死|离谱|逆天|抽象)", 3),
    ]
    for pattern, weight in rules:
        if re.search(pattern, lower, flags=re.I):
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

    score = score_interest_text(text)
    return score >= config.codex_chat_interest_threshold, score
