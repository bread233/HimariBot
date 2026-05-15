from __future__ import annotations

import json
import os
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from nonebot import logger

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

def _clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip()

def _get_web_quality_rules_path(config) -> str:
    cfg_path = str(getattr(config, "chat_agent_web_quality_rules_path", "") or "").strip()
    if cfg_path:
        return cfg_path
    env_path = str(os.getenv("CHAT_AGENT_WEB_QUALITY_RULES_PATH", "") or "").strip()
    if env_path:
        return env_path
    return _WEB_QUALITY_RULES_DEFAULT_PATH

def _normalize_rule_list(value) -> set[str]:
    if not isinstance(value, list):
        return set()
    out: set[str] = set()
    for item in value:
        s = str(item or "").strip().lower()
        if s:
            out.add(s)
    return out

def _normalize_domain_list(value) -> set[str]:
    raw = _normalize_rule_list(value)
    out: set[str] = set()
    for d in raw:
        if d.startswith("www."):
            d = d[4:]
        out.add(d)
    return out

def _bootstrap_web_quality_rules_file(path: str) -> None:
    p = Path(path).expanduser()
    if p.exists():
        logger.info(f"json_config bootstrap_skip_exists path={str(p)!r}")
        return
    payload = json.dumps(_WEB_QUALITY_RULES_DEFAULT_TEMPLATE, ensure_ascii=False, indent=2) + "\n"
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(p.suffix + ".tmp")
        tmp.write_text(payload, encoding="utf-8")
        try:
            os.replace(str(tmp), str(p))
        except Exception:
            if not p.exists():
                p.write_text(payload, encoding="utf-8")
            if tmp.exists():
                try:
                    tmp.unlink()
                except Exception:
                    pass
        logger.info(f"json_config bootstrap_created path={str(p)!r}")
    except Exception as e:
        logger.warning(f"json_config bootstrap_failed path={str(p)!r} message={str(e)[:200]!r}")

def _load_web_quality_rules(config) -> dict:
    path = _get_web_quality_rules_path(config)
    try:
        resolved = str(Path(path).expanduser().resolve())
    except Exception:
        resolved = str(path)
    if resolved in _WEB_QUALITY_RULES_CACHE:
        return _WEB_QUALITY_RULES_CACHE[resolved]

    empty = {
        "low_quality_keywords_extra": set(),
        "official_domains_extra": set(),
        "sports_trusted_domains_extra": set(),
        "sports_low_quality_keywords_extra": set(),
        "software_mismatch_keywords_extra": set(),
        "entity_rules": {},
    }
    p = Path(path).expanduser()
    if not p.exists():
        _bootstrap_web_quality_rules_file(path)
        _WEB_QUALITY_RULES_CACHE[resolved] = empty
        return empty
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning(f"web_quality_rules invalid_json path={path!r} message={str(e)[:160]!r}")
        _WEB_QUALITY_RULES_CACHE[resolved] = empty
        return empty
    if not isinstance(data, dict):
        logger.warning(f"web_quality_rules invalid_root path={path!r} root_type={type(data).__name__}")
        _WEB_QUALITY_RULES_CACHE[resolved] = empty
        return empty

    entity_rules: dict[str, dict[str, set[str]]] = {}
    raw_entity_rules = data.get("entity_rules")
    if isinstance(raw_entity_rules, dict):
        for k, v in raw_entity_rules.items():
            key = str(k or "").strip().lower()
            if not key or not isinstance(v, dict):
                continue
            entity_rules[key] = {
                "official_domains": _normalize_domain_list(v.get("official_domains")),
                "mismatch_keywords": _normalize_rule_list(v.get("mismatch_keywords")),
                "low_quality_keywords": _normalize_rule_list(v.get("low_quality_keywords")),
            }

    parsed = {
        "low_quality_keywords_extra": _normalize_rule_list(data.get("low_quality_keywords_extra")),
        "official_domains_extra": _normalize_domain_list(data.get("official_domains_extra")),
        "sports_trusted_domains_extra": _normalize_domain_list(data.get("sports_trusted_domains_extra")),
        "sports_low_quality_keywords_extra": _normalize_rule_list(data.get("sports_low_quality_keywords_extra")),
        "software_mismatch_keywords_extra": _normalize_rule_list(data.get("software_mismatch_keywords_extra")),
        "entity_rules": entity_rules,
    }
    _WEB_QUALITY_RULES_CACHE[resolved] = parsed
    return parsed

def _rank_result(item: dict, query: str) -> tuple[int, int]:
    url = str(item.get("url", "")).lower()
    title = str(item.get("title", "")).lower()
    q = str(query or "").lower()
    if "nvidia" in q or "rtx" in q or "geforce" in q or "英伟达" in q:
        if "nvidia.com" in url:
            return (0, 0)
        if "amd.com" in url or "intel.com" in url:
            return (1, 0)
        if "wikipedia.org" in url or "baike.baidu.com" in url:
            return (2, 0)
        if any(token in url for token in ["tom.", "zol.", "ithome.", "pcpop.", "mydrivers.", "baidu.com"]):
            return (4, 0)
        return (3, 0)
    if "wikipedia.org" in url or "baike.baidu.com" in url:
        return (1, 0)
    if "nvidia.com" in url:
        return (0, 0)
    if any(token in url for token in ["tom.", "zol.", "ithome.", "pcpop.", "mydrivers.", "baidu.com"]):
        return (3, 0)
    if title:
        return (2, 0)
    return (4, 0)

def _extract_query_tokens(query: str) -> set[str]:
    text = str(query or "").lower()
    tokens = {t for t in re.findall(r"[a-z][a-z0-9_.-]{1,}", text) if len(t) >= 3}
    mapped: set[str] = set()
    zh_map = {
        "英伟达": ["nvidia"],
        "微软": ["microsoft", "windows"],
        "苹果": ["apple", "ios"],
        "显卡": ["gpu", "driver"],
        "驱动": ["driver", "download"],
        "内测": ["insider", "beta", "preview"],
        "最新": ["latest", "release", "version"],
    }
    for zh, ex in zh_map.items():
        if zh in text:
            mapped.update(ex)
    return tokens | mapped

def _source_preference_score(url: str, query: str) -> float:
    parsed = urlparse(str(url or "").strip())
    host = (parsed.netloc or "").lower()
    path = (parsed.path or "").lower()
    if not host:
        return 0.0
    q = str(query or "").lower()
    query_tokens = _extract_query_tokens(query)
    signals = f"{host} {path} {q}"
    score = 0.0

    official_terms = [
        "official", "support", "docs", "documentation", "developer", "download", "downloads",
        "release", "releases", "release notes", "changelog", "version history",
        "官网", "官方网站", "版本", "发布", "发布说明", "下载", "支持", "文档",
    ]
    hit_terms = sum(1 for t in official_terms if t in signals)
    score += min(hit_terms, 4) * 0.06

    path_signals = ["support", "docs", "developer", "download", "downloads", "releases", "changelog", "blog"]
    for t in path_signals:
        if t in host:
            score += 0.04
        if f"/{t}" in path or f"-{t}" in path:
            score += 0.03

    if query_tokens:
        token_hits = 0
        for t in query_tokens:
            if t in host or t in path or t in q:
                token_hits += 1
        score += min(token_hits, 4) * 0.05

    third_party_hosts = [
        "zhihu.com", "csdn.net", "jianshu.com", "baijiahao", "bilibili.com", "youtube.com", "reddit.com", "wikipedia.org"
    ]
    if any(t in host for t in third_party_hosts):
        score -= 0.08

    return score

def _generic_source_quality_adjustment(url: str, title: str, snippet: str, query: str, config=None) -> tuple[float, bool, bool, bool]:
    host = (urlparse(str(url or "")).netloc or "").lower()
    path = (urlparse(str(url or "")).path or "").lower()
    merged = f"{host} {path} {str(title or '').lower()} {str(snippet or '').lower()} {str(query or '').lower()}"
    boost = 0.0
    penalty = 0.0
    boosted = False
    low_quality_penalized = False
    entity_mismatch_penalized = False

    official_like_domains = {
        "ruby-lang.org", "nodejs.org", "python.org", "postgresql.org", "redis.io", "docs.docker.com",
        "docker.com", "go.dev", "rust-lang.org", "rocom.qq.com", "taptap.cn",
        "wikipedia.org", "baike.baidu.com", "steampowered.com", "playstation.com", "nintendo.com", "xbox.com",
    }
    rules = _load_web_quality_rules(config) if config is not None else {}
    official_like_domains = official_like_domains | set(rules.get("official_domains_extra", set()))
    if any(d in host for d in official_like_domains):
        boost += 0.28
        boosted = True

    if "rocom.qq.com" in host:
        boost += 0.22
        boosted = True
    if "taptap.cn" in host:
        boost += 0.18
        boosted = True

    low_quality_signals = [
        "aiyouxi", "igame", "wanbo", "mangosports", "bsport", "b-sport", "hth", "huatihui",
        "milan", "crown", "bandao", "kaiyun", "leyu", "jiuyou",
        "qiutan-sports", "home-qiutan-sports", "sports-livezone", "blog-xmsports", "zh-", "outline-cn-igame",
        "sports-news/a", "news-20", "crack", "破解版", "中文破解版", "激活版", "下载站", "软件园",
        "万博", "芒果体育", "爱游戏", "华体", "华体会", "米兰体育", "皇冠", "半岛", "开云", "乐鱼", "九游", "体育app下载",
        "xclient", "myqqjd", "ymkuzhan",
    ]
    low_quality_signals = set(low_quality_signals) | set(rules.get("low_quality_keywords_extra", set()))
    if any(s in merged for s in low_quality_signals):
        penalty -= 0.70
        low_quality_penalized = True

    if _is_software_version_query(query):
        mismatch_extras = set(rules.get("software_mismatch_keywords_extra", set()))
        software_release_signals = ["release", "releases", "release notes", "changelog", "latest", "stable", "version", "downloads"]
        if any(s in merged for s in software_release_signals) and any(d in host for d in official_like_domains):
            boost += 0.25
            boosted = True
        if "ruby" in str(query or "").lower():
            mismatch_signals = set(["rubymine", "jetbrains", "rails", "plugin", "ide", "破解版", "crack"]) | mismatch_extras
            entity_rules = (rules.get("entity_rules", {}) or {}).get("ruby", {})
            mismatch_signals = mismatch_signals | set(entity_rules.get("mismatch_keywords", set()))
            official_like_domains = official_like_domains | set(entity_rules.get("official_domains", set()))
            if any(s in merged for s in mismatch_signals):
                penalty -= 0.80
                entity_mismatch_penalized = True

    if "roco" in str(query or "").lower() or "洛克王国世界" in str(query or ""):
        entity_rules = (rules.get("entity_rules", {}) or {}).get("roco_world", {})
        official_like_domains = official_like_domains | set(entity_rules.get("official_domains", set()))
        roco_low = set(entity_rules.get("low_quality_keywords", set()))
        if any(s in merged for s in roco_low):
            penalty -= 0.60
            low_quality_penalized = True

    return boost + penalty, boosted, low_quality_penalized, entity_mismatch_penalized

def _sports_source_adjustment(url: str, title: str, snippet: str, config=None) -> tuple[float, bool, bool]:
    host = (urlparse(str(url or "")).netloc or "").lower()
    path = (urlparse(str(url or "")).path or "").lower()
    merged = f"{host} {path} {str(title or '').lower()} {str(snippet or '').lower()}"

    boost = 0.0
    boosted = False
    quality_domains = [
        "nba.com", "espn.com", "basketball-reference.com", "statmuse.com",
        "nba.hupu.com", "qiumiwu.com", "slamdunk.sports.sina.com.cn",
        "sports.cctv.com", "sports.qq.com", "sports.sina.com.cn",
    ]
    rules = _load_web_quality_rules(config) if config is not None else {}
    quality_domains = set(quality_domains) | set(rules.get("sports_trusted_domains_extra", set()))
    strong_stats_signals = ["player", "players", "stats", "stat", "game log", "gamelog", "boxscore", "数据", "技术统计"]
    if any(d in host for d in quality_domains) and any(s in merged for s in strong_stats_signals):
        boost += 0.35
        boosted = True
    elif any(d in host for d in quality_domains):
        boost += 0.18
        boosted = True
    if "qiumiwu.com" in host and "/player/" in path and "/stat" in path:
        boost += 0.22
        boosted = True
    if "nba.hupu.com" in host and "/players/" in path:
        boost += 0.20
        boosted = True
    if "slamdunk.sports.sina.com.cn" in host and "/player" in path and "stat" in path:
        boost += 0.20
        boosted = True
    if "basketball-reference.com" in host and "/players/" in path and "gamelog" in path:
        boost += 0.20
        boosted = True
    if "statmuse.com" in host and "/nba" in path:
        boost += 0.18
        boosted = True
    if "nba.com" in host and "stats" in path:
        boost += 0.18
        boosted = True
    if "espn.com" in host and "/nba/player" in path and "gamelog" in path:
        boost += 0.18
        boosted = True

    penalty = 0.0
    penalized = False
    low_quality_signals = [
        "aiyouxi", "igame", "wanbo", "mangosports", "bsport", "b-sport",
        "hth", "milan", "leyu", "kaiyun", "jiuyou", "crown", "huatihui", "bandao",
        "qiutan-sports", "home-qiutan-sports", "sports-livezone", "blog-xmsports", "zh-", "sports-news/a", "news-20",
        "华体", "华体会", "皇冠", "米兰体育", "开云", "乐鱼", "半岛", "万博", "芒果体育", "爱游戏", "球探壳站", "体育app下载",
    ]
    low_quality_signals = set(low_quality_signals) | set(rules.get("sports_low_quality_keywords_extra", set()))
    if any(s in merged for s in low_quality_signals):
        penalty -= 0.60
        penalized = True
    generic_seo = ["从天赋少年到传奇", "全球偶像", "伟大历程", "巅峰揭秘"]
    if any(s.lower() in merged for s in generic_seo):
        penalty -= 0.35
        penalized = True
    return boost + penalty, boosted, penalized

def _extract_domain(url: str) -> str:
    try:
        host = (urlparse(str(url or "").strip()).netloc or "").lower()
    except Exception:
        return ""
    return host[4:] if host.startswith("www.") else host

def _extract_years(text: str) -> list[int]:
    s = str(text or "")
    if not s:
        return []
    current_year = datetime.now().year
    years: set[int] = set()
    for raw in re.findall(r"\b(20\d{2})\b", s):
        try:
            y = int(raw)
        except Exception:
            continue
        if 2018 <= y <= current_year + 1:
            years.add(y)
    return sorted(years, reverse=True)

def _is_current_sensitive_query(query: str, intent_kind: str | None = None) -> bool:
    if str(intent_kind or "").strip() == "current_fact":
        return True

    q = _clean_text(query)
    if not q:
        return False

    low = q.lower()

    time_terms = [
        "最新",
        "现在",
        "目前",
        "今年",
        "发布",
        "上市",
        "价格",
        "显存",
        "规格",
        "参数",
        "版本",
        "型号",
        "支持吗",
        "有没有",
        "多少",
        "变了吗",
        "还能用吗",
        "能用了吗",
        "latest",
        "current",
        "now",
        "release",
        "price",
        "spec",
        "specs",
        "version",
        "model",
        "support",
        "available",
    ]
    if any(t in q or t in low for t in time_terms):
        return True

    model_patterns = [
        r"[A-Za-z]{2,}[ -]?\d{2,}",
        r"[A-Z]{2,}\d{3,}",
        r"\d+\.\d+(?:\.\d+)?",
    ]
    if any(re.search(p, q) for p in model_patterns):
        return True

    status_terms = [
        "支持吗",
        "支持不",
        "发布了吗",
        "上市了吗",
        "有了吗",
        "怎么样",
        "现在是啥",
        "is available",
        "supported",
        "support",
        "released",
        "available",
    ]
    if any(t in q or t in low for t in status_terms):
        return True

    return False


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


def _freshness_score(item: dict, query: str, current_sensitive: bool = False) -> float:
    current_year = datetime.now().year
    merged = " ".join(
        [
            str(item.get("title", "") or ""),
            str(item.get("snippet", "") or ""),
            str(item.get("excerpt", "") or ""),
            str(item.get("url", "") or ""),
        ]
    )
    years = _extract_years(merged)
    newest_year = years[0] if years else None

    score = 0.0
    if newest_year is not None:
        if newest_year >= current_year:
            score += 0.30
        elif newest_year == current_year - 1:
            score += 0.18
        elif newest_year == current_year - 2:
            score += 0.05
        else:
            score -= 0.20 if current_sensitive else 0.05

    low = (str(item.get("title", "")) + " " + str(item.get("snippet", "")) + " " + str(item.get("excerpt", ""))).lower()
    hint_terms = [
        "latest",
        "new",
        "current",
        "release",
        "spec",
        "specs",
        "version",
        "发布",
        "最新",
        "规格",
        "显存",
        "参数",
        "版本",
    ]
    if any(t in low for t in hint_terms):
        score += 0.05

    rumor_terms = [
        "rumor",
        "leak",
        "unconfirmed",
        "预测",
        "爆料",
        "传闻",
        "预计",
        "可能",
        "未经证实",
    ]
    if any(t in low for t in rumor_terms):
        score -= 0.15 if current_sensitive else 0.05

    return max(-0.40, min(0.50, score))

def _authority_score(item: dict, query: str, current_sensitive: bool = False) -> float:
    domain = str(item.get("domain", "") or _extract_domain(str(item.get("url", "") or ""))).lower()
    q = str(query or "").lower()

    official_domains = {
        "nvidia.com",
        "nvidia.cn",
        "amd.com",
        "intel.com",
        "microsoft.com",
        "apple.com",
        "python.org",
        "docs.python.org",
        "nodejs.org",
        "cloudflare.com",
        "developers.cloudflare.com",
    }
    doc_domains = {
        "docs.python.org",
        "developers.cloudflare.com",
        "learn.microsoft.com",
        "developer.apple.com",
        "developer.nvidia.com",
    }

    if any(domain == d or domain.endswith("." + d) for d in official_domains):
        return 0.35
    if any(domain == d or domain.endswith("." + d) for d in doc_domains):
        return 0.30
    if domain.endswith("wikipedia.org"):
        return 0.12

    forum_domains = {
        "reddit.com",
        "zhihu.com",
        "tieba.baidu.com",
        "baidu.com",
        "csdn.net",
        "cnblogs.com",
        "qastack.cn",
    }
    if any(domain == d or domain.endswith("." + d) for d in forum_domains):
        return -0.12 if current_sensitive else -0.05

    is_rtx_query = any(k in q for k in ["rtx", "nvidia", "geforce", "英伟达", "显卡", "显存"])
    if is_rtx_query:
        reputable = {
            "techpowerup.com",
            "videocardz.com",
            "tomshardware.com",
            "pcgamer.com",
        }
        if any(domain == d or domain.endswith("." + d) for d in reputable):
            return 0.10
        rumor_sites = {
            "wccftech.com",
        }
        if any(domain == d or domain.endswith("." + d) for d in rumor_sites):
            return -0.10 if current_sensitive else -0.05

    if current_sensitive and domain.endswith("stackoverflow.com"):
        return -0.06

    return 0.0

def _source_flags(item: dict, query: str, current_sensitive: bool = False) -> list[str]:
    flags: list[str] = []
    if current_sensitive:
        flags.append("current-sensitive")

    domain = str(item.get("domain", "") or _extract_domain(str(item.get("url", "") or ""))).lower()
    if any(domain == d or domain.endswith("." + d) for d in ["nvidia.com", "nvidia.cn"]):
        flags.extend(["official", "nvidia-official"])
    elif any(domain == d or domain.endswith("." + d) for d in ["python.org", "nodejs.org", "cloudflare.com"]):
        flags.append("official")
    elif any(domain == d or domain.endswith("." + d) for d in ["docs.python.org", "developers.cloudflare.com", "learn.microsoft.com"]):
        flags.extend(["docs", "official"])

    merged = " ".join(
        [
            str(item.get("title", "") or ""),
            str(item.get("snippet", "") or ""),
            str(item.get("excerpt", "") or ""),
            str(item.get("url", "") or ""),
        ]
    )
    years = _extract_years(merged)
    current_year = datetime.now().year
    if not years:
        flags.append("no-year")
    else:
        newest_year = years[0]
        if newest_year >= current_year:
            flags.append("current-year")
        elif newest_year == current_year - 1:
            flags.append("recent-year")
        elif newest_year <= current_year - 2:
            flags.append("stale-year")

    low = merged.lower()
    if any(t in low for t in ["rumor", "leak", "unconfirmed", "预测", "爆料", "传闻", "预计", "未经证实"]):
        flags.append("rumor")
    if any(domain == d or domain.endswith("." + d) for d in ["reddit.com", "zhihu.com", "tieba.baidu.com", "csdn.net", "cnblogs.com", "qastack.cn"]):
        flags.append("forum")
    if any(domain == d or domain.endswith("." + d) for d in ["baidu.com"]):
        flags.append("seo")

    seen: set[str] = set()
    out: list[str] = []
    for f in flags:
        if f in seen:
            continue
        seen.add(f)
        out.append(f)
    return out

