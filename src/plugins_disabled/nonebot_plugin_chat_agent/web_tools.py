from __future__ import annotations

import re
import json
import os
from datetime import datetime
from html import unescape
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

import httpx
from bs4 import BeautifulSoup
from nonebot import logger
from .evidence.official import (
    get_nodejs_latest_version as get_nodejs_latest_version,
    get_ruby_latest_version as get_ruby_latest_version,
    resolve_official_web_answer as resolve_official_web_answer,
)
from .evidence.web import (
    search_web as search_web,
    read_url as read_url,
    build_web_results as build_web_results,
    render_web_results_context as render_web_results_context,
    build_web_context as build_web_context,
)

_WEB_QUALITY_RULES_CACHE: dict[str, dict] = {}
_WEB_QUALITY_RULES_DEFAULT_PATH = "data/nonebot_chat_agent/web_quality_rules.json"
_WEB_QUALITY_RULES_DEFAULT_TEMPLATE = {
    "version": 1,
    "low_quality_keywords_extra": [],
    "official_domains_extra": [],
    "sports_trusted_domains_extra": [],
    "sports_low_quality_keywords_extra": [],
    "software_mismatch_keywords_extra": [],
    "entity_rules": {
        "ruby": {
            "official_domains": ["ruby-lang.org"],
            "mismatch_keywords": ["rubymine", "jetbrains", "破解版", "下载站"],
            "low_quality_keywords": [],
        },
        "roco_world": {
            "official_domains": ["rocom.qq.com", "taptap.cn", "baike.baidu.com", "wikipedia.org"],
            "mismatch_keywords": [],
            "low_quality_keywords": ["爱游戏", "igame", "体育"],
        },
    },
}

def _is_sports_recent_query(query: str) -> bool:
    text = str(query or "").lower()
    if not text:
        return False
    sports_markers = [
        "nba", "cba", "lakers", "warriors", "thunder", "lebron", "james", "curry", "doncic",
        "詹姆斯", "勒布朗", "湖人", "勇士", "雷霆", "东契奇", "库里", "球员", "球队",
        "最近", "近况", "表现", "数据", "最近一场", "对阵", "得分", "篮板", "助攻", "命中率", "战绩", "赛程", "赛后",
    ]
    return any(x in text for x in sports_markers)

def _is_software_version_query(query: str) -> bool:
    text = str(query or "").lower().strip()
    if not text:
        return False
    version_markers = [
        "latest version", "stable version", "release notes", "current version",
        "最新版", "最新版本", "当前版本", "稳定版", "发布版本", "release", "version",
    ]
    software_markers = [
        "ruby", "node", "nodejs", "node.js", "python", "postgresql", "redis", "docker", "go", "rust",
    ]
    return any(v in text for v in version_markers) and any(s in text for s in software_markers)

def _is_game_definition_query(query: str) -> bool:
    text = str(query or "").lower().strip()
    if not text:
        return False
    return ("是什么" in text or "什么游戏" in text or "介绍" in text) and any(
        x in text for x in ["游戏", "world", "王国", "roco", "洛克", "taptap"]
    )

def _rewrite_web_query_hints(query: str) -> str:
    q = str(query or "").strip()
    if not q:
        return q
    low = q.lower()
    if _is_software_version_query(q):
        if "ruby" in low:
            return f"{q} Ruby latest stable release ruby-lang.org downloads releases"
        return f"{q} latest stable release official release notes downloads"
    if _is_game_definition_query(q):
        return f"{q} 官方 TapTap 百科 wikipedia"
    return q
