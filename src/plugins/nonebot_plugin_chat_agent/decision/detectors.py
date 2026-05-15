from __future__ import annotations

def _is_context_question(prompt: str) -> bool:
    text = (prompt or "").strip()
    return any(
        token in text
        for token in [
            "我刚才说了什么",
            "我刚刚说了什么",
            "我之前说了什么",
            "我刚才在测什么",
            "我刚刷了啥",
            "在测什么",
        ]
    )


def _is_self_identity_question(prompt: str) -> bool:
    text = (prompt or "").strip()
    patterns = [
        "我是谁",
        "我是谁啊",
        "你知道我是谁吗",
        "你知道我叫什么吗",
        "我叫什么",
        "我在群里叫什么",
    ]
    return any(pattern in text for pattern in patterns)


def _is_creative_or_chat_prompt(prompt: str) -> bool:
    text = (prompt or "").strip()
    return any(
        token in text
        for token in [
            "写个",
            "讲个",
            "来个",
            "编个",
            "冷笑话",
            "笑话",
            "故事",
            "段子",
            "安慰我",
            "陪我聊",
            "聊聊",
            "夸夸我",
            "鼓励我",
            "吐槽一下",
            "自我介绍",
        ]
    )


def _needs_reliable_context(prompt: str) -> bool:
    text = (prompt or "").strip()
    if _is_creative_or_chat_prompt(text):
        return False
    return any(
        token in text
        for token in [
            "我是谁",
            "我叫什么",
            "我在群里叫什么",
            "之前",
            "说了什么",
            "在测什么",
            "什么",
            "多少",
            "多少钱",
            "价格",
            "参数",
            "配置",
            "规格",
            "显存",
            "内存",
            "发布",
            "发售",
            "最新",
            "现在",
            "当前",
            "属于",
            "系列",
            "支持",
            "区别",
            "对比",
            "是真的吗",
            "有吗",
            "存在",
            "查",
            "搜索",
            "资料",
        ]
    )


def _is_explicit_history_query(prompt: str) -> bool:
    text = (prompt or "").strip()
    return any(
        token in text
        for token in [
            "刚才",
            "刚刚",
            "之前",
            "以前",
            "历史",
            "说过",
            "聊过",
            "提过",
            "记得",
            "谁说",
            "谁提",
            "有没有人说",
            "上次",
            "前面",
            "过去",
        ]
    )


def _is_simple_definition_question(prompt: str, intent_kind: str | None) -> bool:
    text = str(prompt or "").strip().lower()
    if not text:
        return False
    if len(text) < 2 or len(text) > 40:
        return False
    if str(intent_kind or "").strip() in {"local_context", "time"}:
        return False

    block_terms = [
        "最新", "版本", "latest", "version", "现在", "今天", "价格", "新闻", "谁说过", "之前", "历史", "聊过",
        "发布", "发售", "更新", "多少钱", "参数", "规格", "显存",
    ]
    if any(t in text for t in block_terms):
        return False

    def_markers = ["是什么", "是啥", "什么是", "什么意思", "是什么东西", "是做什么的"]
    if not any(t in text for t in def_markers):
        return False
    return True


def _is_community_strategy_question(prompt: str, intent_kind: str | None) -> bool:
    text = str(prompt or "").strip().lower()
    if not text:
        return False
    if len(text) < 4 or len(text) > 80:
        return False
    if str(intent_kind or "").strip() in {"local_context", "time"}:
        return False
    if _is_explicit_history_query(prompt) or _is_simple_definition_question(prompt, intent_kind):
        return False
    if extract_urls(prompt):
        return False
    if detect_numeric_compare(prompt) is not None:
        return False

    exclude_markers = [
        "\u6700\u65b0", "\u7248\u672c", "latest", "version", "\u4ef7\u683c", "\u65b0\u95fb",
        "\u4eca\u5929", "\u73b0\u5728", "\u5f53\u524d", "\u591a\u5c11", "\u53c2\u6570", "\u89c4\u683c",
    ]
    if any(t in text for t in exclude_markers):
        return False

    strategy_markers = [
        "\u4ecb\u7ecd", "\u63a8\u8350", "\u73a9\u6cd5", "\u600e\u4e48\u73a9", "\u653b\u7565",
        "\u65b0\u624b", "\u5f00\u5c40", "\u65b9\u6848", "\u8def\u7ebf", "\u5e2e\u6211\u9009",
        "\u9009\u54ea\u4e2a", "\u914d\u7f6e", "\u600e\u4e48\u914d", "\u804c\u4e1a", "\u56fd\u5bb6",
        "\u89d2\u8272", "\u600e\u4e48\u9009", "\u9009\u4ec0\u4e48", "\u600e\u4e48\u9009\u62e9",
        "\u6b66\u5668", "\u88c5\u5907", "\u6d41\u6d3e", "\u52a0\u70b9", "\u6280\u80fd",
        "\u9635\u5bb9", "\u914d\u961f", "\u51fa\u88c5", "\u79d1\u6280\u7ebf", "\u5766\u514b\u7ebf",
        "\u804c\u4e1a\u9009\u62e9",
    ]
    return any(t in text for t in strategy_markers)


def _is_freshness_sensitive_prompt(prompt: str) -> bool:
    text = str(prompt or "").lower()
    markers = [
        "\u6700\u65b0", "\u6700\u8fd1", "\u8fd1\u671f", "\u8fd1\u51b5", "\u8fd1\u6765", "\u5f53\u524d", "\u8fd9\u8d5b\u5b63", "\u672c\u8d5b\u5b63", "\u4eca\u5e74", "\u4eca\u5929", "\u73b0\u5728",
        "\u7248\u672c", "\u4ef7\u683c", "\u591a\u5c11\u94b1", "\u8868\u73b0", "\u65b0\u95fb", "latest", "current", "this season",
        "price", "news", "version", "recent",
    ]
    return any(m in text for m in markers)


def _is_sports_recent_query(prompt: str) -> bool:
    text = str(prompt or "").lower()
    if not text:
        return False
    markers = [
        "nba", "cba", "lakers", "warriors", "thunder", "lebron", "james", "curry", "doncic",
        "詹姆斯", "勒布朗", "湖人", "勇士", "雷霆", "东契奇", "库里", "球员", "球队",
        "最近", "近况", "表现", "数据", "最近一场", "对阵", "得分", "篮板", "助攻", "命中率", "战绩", "赛程", "赛后",
    ]
    return any(m in text for m in markers)


def _is_software_version_query(prompt: str) -> bool:
    text = str(prompt or "").lower()
    if not text:
        return False
    version_markers = ["最新版", "最新版本", "当前版本", "稳定版", "latest", "version", "release", "stable"]
    software_markers = ["ruby", "node", "nodejs", "node.js", "python", "postgresql", "redis", "docker", "go", "rust"]
    return any(m in text for m in version_markers) and any(s in text for s in software_markers)


def _is_definition_query(prompt: str) -> bool:
    q = str(prompt or "").strip().lower()
    if not q:
        return False
    if _is_software_version_query(q):
        return False
    return any(
        term in q
        for term in (
            "是什么",
            "是什麼",
            "是啥",
            "什么游戏",
            "什麼遊戲",
            "介绍",
            "简介",
            "百科",
            "what is",
            "who is",
        )
    )
