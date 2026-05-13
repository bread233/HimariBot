import json
import os
from pathlib import Path

from nonebot import logger

_RUNTIME_JSON_CACHE: dict[str, dict] = {}

_RAG_POLICY_DEFAULT_PATH = "data/nonebot_chat_agent/rag_policy.json"
_PERSONA_PROFILE_DEFAULT_PATH = "data/nonebot_chat_agent/personas/himari.json"

_DEFAULT_RAG_POLICY = {
    "version": 1,
    "default": {
        "strict_grounding": True,
        "allow_param_memory": False,
        "unknown_reply": "资料里没有明确说明。",
        "max_evidence_chunks": 5,
        "min_final_score": 0.35,
        "system_prompt": "你必须严格基于提供的证据回答。证据不足时明确说不知道，不能编造事实。",
    },
    "routes": {
        "web_evidence": {
            "strict_grounding": True,
            "unknown_reply": "我查到了相关网页，但资料不足以确认。",
        },
        "web_strategy": {
            "strict_grounding": True,
            "unknown_reply": "我查到了相关网页，但资料不足以确认。",
        },
        "knowledge_evidence": {
            "strict_grounding": True,
            "unknown_reply": "知识库里没有明确说明。",
        },
        "sports_evidence": {
            "strict_grounding": True,
            "unknown_reply": "当前资料里没有明确的最近比赛数据。",
        },
    },
    "packs": {},
}

_DEFAULT_PERSONA_PROFILE = {
    "version": 1,
    "persona_key": "himari",
    "display_name": "上原绯玛丽",
    "enabled": True,
    "core_identity": {
        "name": "上原绯玛丽",
        "role": "群聊里的 AI 助手",
        "description": "轻松、简洁、结论优先，但绝不编造事实。",
    },
    "speaking_style": {
        "language": "zh-CN",
        "tone": "轻松、简洁、结论优先",
        "sentence_style": "短句优先，少长篇解释",
        "emoji_policy": "少量使用，不刷屏",
        "avoid": [],
    },
    "behavior_rules": {
        "answer_first": True,
        "ask_less_confirmations": True,
        "unknown_policy": "不知道就直接说不知道，不能编。",
        "evidence_priority": "涉及事实和资料时必须优先依据证据。",
    },
    "route_overrides": {
        "casual_chat": {"style_strength": "high"},
        "web_evidence": {"style_strength": "low", "must_follow_rag_policy": True},
        "knowledge_evidence": {"style_strength": "low", "must_follow_rag_policy": True},
        "official_resolver": {"style_strength": "very_low", "must_be_precise": True},
    },
}


def _bootstrap_json_file(path: str, template: dict) -> None:
    p = Path(path).expanduser()
    if p.exists():
        logger.info(f"json_config bootstrap_skip_exists path={str(p)!r}")
        return
    payload = json.dumps(template, ensure_ascii=False, indent=2) + "\n"
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


def _get_runtime_json_path(config, attr_name: str, env_name: str, default_path: str) -> str:
    cfg_path = str(getattr(config, attr_name, "") or "").strip()
    if cfg_path:
        return cfg_path
    env_path = str(os.getenv(env_name, "") or "").strip()
    if env_path:
        return env_path
    return default_path


def _load_runtime_json(path: str, default_dict: dict, logger_name: str) -> dict:
    try:
        resolved = str(Path(path).expanduser().resolve())
    except Exception:
        resolved = str(path)
    cache_key = f"{logger_name}:{resolved}"
    if cache_key in _RUNTIME_JSON_CACHE:
        return _RUNTIME_JSON_CACHE[cache_key]

    parsed = dict(default_dict)
    p = Path(path).expanduser()
    if not p.exists():
        _bootstrap_json_file(path, default_dict)
        logger.info(f"{logger_name} loaded=0 path={path!r} reason=not_found")
        _RUNTIME_JSON_CACHE[cache_key] = parsed
        return parsed
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning(f"{logger_name} invalid_json path={path!r} message={str(e)[:200]!r}")
        _RUNTIME_JSON_CACHE[cache_key] = parsed
        return parsed
    if not isinstance(raw, dict):
        logger.warning(f"{logger_name} invalid_root path={path!r} root_type={type(raw).__name__}")
        _RUNTIME_JSON_CACHE[cache_key] = parsed
        return parsed

    parsed.update(raw)
    logger.info(f"{logger_name} loaded=1 path={path!r}")
    _RUNTIME_JSON_CACHE[cache_key] = parsed
    return parsed


def get_rag_policy(config) -> dict:
    path = _get_runtime_json_path(
        config,
        "chat_agent_rag_policy_path",
        "CHAT_AGENT_RAG_POLICY_PATH",
        _RAG_POLICY_DEFAULT_PATH,
    )
    return _load_runtime_json(path, _DEFAULT_RAG_POLICY, "rag_policy")


def get_persona_profile(config) -> dict:
    path = _get_runtime_json_path(
        config,
        "chat_agent_persona_profile_path",
        "CHAT_AGENT_PERSONA_PROFILE_PATH",
        _PERSONA_PROFILE_DEFAULT_PATH,
    )
    return _load_runtime_json(path, _DEFAULT_PERSONA_PROFILE, "persona_profile")
