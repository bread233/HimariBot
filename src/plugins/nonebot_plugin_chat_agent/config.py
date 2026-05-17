from __future__ import annotations

from pathlib import Path

from nonebot import get_driver
from pydantic import BaseModel, Field


class ChatAgentConfig(BaseModel):
    chat_agent_enable: bool = Field(default=True)
    chat_agent_enable_history: bool = Field(default=True)
    chat_agent_enable_feedback_memory: bool = Field(default=False)
    chat_agent_enable_fact_guard: bool = Field(default=True)
    chat_agent_enable_web: bool = Field(default=False)
    chat_agent_enable_tool_router: bool = Field(default=True)
    chat_agent_web_mode: str = Field(default="auto")
    chat_agent_busy_reply: str = Field(default="少女思考中···")
    chat_agent_locked_reply: str = Field(default="正在思考中，请稍后再问。")
    chat_agent_llm_timeout_reply: str = Field(default="模型接口暂时没有响应。")
    chat_agent_base_url: str = Field(default="http://127.0.0.1:11434/v1")
    chat_agent_api_key: str = Field(default="ollama")
    chat_agent_model: str = Field(default="qwen3:1.7b")
    chat_agent_think: bool = Field(default=False)
    chat_agent_timeout: int = Field(default=120)
    chat_agent_llm_provider: str = Field(default="openai_compatible")
    chat_agent_llm_base_url: str = Field(default="")
    chat_agent_llm_api_key: str = Field(default="")
    chat_agent_llm_model: str = Field(default="")
    chat_agent_llm_timeout: int = Field(default=0)
    chat_agent_llm_max_tokens: int = Field(default=0)
    chat_agent_llm_extra_body: str = Field(default="")
    chat_agent_finalizer_llm_base_url: str = Field(default="")
    chat_agent_finalizer_llm_api_key: str = Field(default="")
    chat_agent_finalizer_llm_model: str = Field(default="")
    chat_agent_finalizer_llm_timeout: int = Field(default=0)
    chat_agent_finalizer_llm_max_tokens: int = Field(default=0)
    chat_agent_finalizer_llm_extra_body: str = Field(default="")
    chat_agent_decision_llm_base_url: str = Field(default="")
    chat_agent_decision_llm_api_key: str = Field(default="")
    chat_agent_decision_llm_model: str = Field(default="")
    chat_agent_decision_llm_timeout: int = Field(default=0)
    chat_agent_decision_llm_max_tokens: int = Field(default=0)
    chat_agent_decision_llm_extra_body: str = Field(default="")
    chat_agent_lightweight_definition_model: str = Field(default="llama32-finalizer-fast")
    chat_agent_lightweight_definition_timeout: float = Field(default=20.0)
    chat_agent_web_strategy_timeout: float = Field(default=60.0)
    chat_agent_web_strategy_max_tokens: int = Field(default=700)
    chat_agent_max_tokens: int = Field(default=512)
    chat_agent_max_reply_length: int = Field(default=500)
    chat_agent_history_max_messages: int = Field(default=10)
    chat_agent_history_max_rows_per_session: int = Field(default=200)
    chat_agent_memory_max_results: int = Field(default=5)
    chat_agent_memory_max_rows: int = Field(default=500)
    chat_agent_search_provider: str = Field(default="duckduckgo")
    chat_agent_search_base_url: str = Field(default="")
    chat_agent_web_timeout: int = Field(default=15)
    chat_agent_web_max_results: int = Field(default=3)
    chat_agent_web_read_max_chars: int = Field(default=6000)
    chat_agent_web_user_agent: str = Field(default="Mozilla/5.0 HimariBot/1.0")
    chat_agent_log_dir: str = Field(default="/app/log")
    chat_agent_retrieval_min_score: float = Field(default=0.45)
    chat_agent_web_relevance_min_score: float = Field(default=0.35)
    chat_agent_web_final_min_score: float = Field(default=0.30)
    chat_agent_enable_embedding_retrieval: bool = Field(default=True)
    chat_agent_embedding_base_url: str = Field(default="http://192.168.0.112:11434")
    chat_agent_embedding_model: str = Field(default="hf.co/Qwen/Qwen3-Embedding-0.6B-GGUF:Q8_0")
    chat_agent_embedding_timeout: int = Field(default=30)
    chat_agent_embedding_reliable_score: float = Field(default=0.68)
    chat_agent_embedding_candidate_score: float = Field(default=0.60)
    chat_agent_embedding_min_margin: float = Field(default=0.05)
    chat_agent_db_path: Path = Field(default=Path("data/nonebot_chat_agent/agent.sqlite3"))
    chat_agent_data_dir: Path = Field(default=Path("data/nonebot_chat_agent"))
    chat_agent_enable_skills: bool = Field(default=True)
    chat_agent_skills_dir: Path = Field(default=Path("data/nonebot_chat_agent/skills"))
    chat_agent_skills_max_active: int = Field(default=3)
    chat_agent_skills_max_body_chars: int = Field(default=4000)
    chat_agent_skill_web_allow_names: str = Field(default="news,weather")
    chat_agent_skill_web_block_names: str = Field(default="pptx,docx,pdf,xlsx")
    chat_agent_skill_evidence_enable: bool = Field(default=True)
    chat_agent_news_skill_max_sources: int = Field(default=1)
    chat_agent_news_skill_read_max_chars: int = Field(default=6000)
    chat_agent_weather_skill_read_max_chars: int = Field(default=1200)
    chat_agent_decision_policy_path: Path = Field(default=Path("data/nonebot_chat_agent/decision_policy.json"))
    chat_agent_decision_classifier_enable: bool = Field(default=False)
    chat_agent_decision_classifier_observe: bool = Field(default=False)
    chat_agent_decision_classifier_max_skills: int = Field(default=10)
    chat_agent_decision_classifier_max_catalog_chars: int = Field(default=2000)
    chat_agent_decision_classifier_timeout: int = Field(default=3)
    chat_agent_decision_classifier_max_tokens: int = Field(default=160)
    chat_agent_decision_classifier_model: str = Field(default="")
    chat_agent_coarse_decision_enable: bool = Field(default=False)
    chat_agent_coarse_decision_observe: bool = Field(default=False)
    chat_agent_coarse_decision_model: str = Field(default="")
    chat_agent_coarse_decision_timeout: float = Field(default=6.0)
    chat_agent_coarse_decision_max_tokens: int = Field(default=96)

    def ensure_data_dir(self) -> Path:
        self.chat_agent_data_dir.mkdir(parents=True, exist_ok=True)
        return self.chat_agent_data_dir


_cached_config: ChatAgentConfig | None = None


def _as_bool(value, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y", "on"}:
        return True
    if text in {"0", "false", "no", "n", "off"}:
        return False
    return default


def get_chat_agent_config() -> ChatAgentConfig:
    global _cached_config
    if _cached_config is not None:
        return _cached_config
    driver = get_driver()
    config = driver.config
    def _cfg(name: str, env: str, default):
        value = getattr(config, name, None)
        if value is not None and str(value).strip() != "":
            return value
        import os
        env_value = os.getenv(env)
        if env_value is not None and str(env_value).strip() != "":
            return env_value
        return default

    data_dir = getattr(config, "chat_agent_data_dir", "data/nonebot_chat_agent")
    _cached_config = ChatAgentConfig(
        chat_agent_enable=_as_bool(getattr(config, "chat_agent_enable", True), True),
        chat_agent_enable_history=_as_bool(getattr(config, "chat_agent_enable_history", True), True),
        chat_agent_enable_feedback_memory=_as_bool(getattr(config, "chat_agent_enable_feedback_memory", False), False),
        chat_agent_enable_fact_guard=_as_bool(getattr(config, "chat_agent_enable_fact_guard", True), True),
        chat_agent_enable_web=_as_bool(getattr(config, "chat_agent_enable_web", False), False),
        chat_agent_enable_tool_router=_as_bool(getattr(config, "chat_agent_enable_tool_router", True), True),
        chat_agent_web_mode=str(getattr(config, "chat_agent_web_mode", "auto")),
        chat_agent_busy_reply=str(getattr(config, "chat_agent_busy_reply", "少女思考中···")),
        chat_agent_locked_reply=str(getattr(config, "chat_agent_locked_reply", "正在思考中，请稍后再问。")),
        chat_agent_llm_timeout_reply=str(getattr(config, "chat_agent_llm_timeout_reply", "模型接口暂时没有响应。")),
        chat_agent_base_url=str(getattr(config, "chat_agent_base_url", "http://127.0.0.1:11434/v1")),
        chat_agent_api_key=str(getattr(config, "chat_agent_api_key", "ollama")),
        chat_agent_model=str(getattr(config, "chat_agent_model", "qwen3:1.7b")),
        chat_agent_think=_as_bool(getattr(config, "chat_agent_think", False), False),
        chat_agent_timeout=int(getattr(config, "chat_agent_timeout", 120)),
        chat_agent_llm_provider=str(_cfg("chat_agent_llm_provider", "CHAT_AGENT_LLM_PROVIDER", "openai_compatible")),
        chat_agent_llm_base_url=str(_cfg("chat_agent_llm_base_url", "CHAT_AGENT_LLM_BASE_URL", "")),
        chat_agent_llm_api_key=str(_cfg("chat_agent_llm_api_key", "CHAT_AGENT_LLM_API_KEY", "")),
        chat_agent_llm_model=str(_cfg("chat_agent_llm_model", "CHAT_AGENT_LLM_MODEL", "")),
        chat_agent_llm_timeout=int(_cfg("chat_agent_llm_timeout", "CHAT_AGENT_LLM_TIMEOUT", 0)),
        chat_agent_llm_max_tokens=int(_cfg("chat_agent_llm_max_tokens", "CHAT_AGENT_LLM_MAX_TOKENS", 0)),
        chat_agent_llm_extra_body=str(_cfg("chat_agent_llm_extra_body", "CHAT_AGENT_LLM_EXTRA_BODY", "")),
        chat_agent_finalizer_llm_base_url=str(_cfg("chat_agent_finalizer_llm_base_url", "CHAT_AGENT_FINALIZER_LLM_BASE_URL", "")),
        chat_agent_finalizer_llm_api_key=str(_cfg("chat_agent_finalizer_llm_api_key", "CHAT_AGENT_FINALIZER_LLM_API_KEY", "")),
        chat_agent_finalizer_llm_model=str(_cfg("chat_agent_finalizer_llm_model", "CHAT_AGENT_FINALIZER_LLM_MODEL", "")),
        chat_agent_finalizer_llm_timeout=int(_cfg("chat_agent_finalizer_llm_timeout", "CHAT_AGENT_FINALIZER_LLM_TIMEOUT", 0)),
        chat_agent_finalizer_llm_max_tokens=int(_cfg("chat_agent_finalizer_llm_max_tokens", "CHAT_AGENT_FINALIZER_LLM_MAX_TOKENS", 0)),
        chat_agent_finalizer_llm_extra_body=str(_cfg("chat_agent_finalizer_llm_extra_body", "CHAT_AGENT_FINALIZER_LLM_EXTRA_BODY", "")),
        chat_agent_decision_llm_base_url=str(_cfg("chat_agent_decision_llm_base_url", "CHAT_AGENT_DECISION_LLM_BASE_URL", "")),
        chat_agent_decision_llm_api_key=str(_cfg("chat_agent_decision_llm_api_key", "CHAT_AGENT_DECISION_LLM_API_KEY", "")),
        chat_agent_decision_llm_model=str(_cfg("chat_agent_decision_llm_model", "CHAT_AGENT_DECISION_LLM_MODEL", "")),
        chat_agent_decision_llm_timeout=int(_cfg("chat_agent_decision_llm_timeout", "CHAT_AGENT_DECISION_LLM_TIMEOUT", 0)),
        chat_agent_decision_llm_max_tokens=int(_cfg("chat_agent_decision_llm_max_tokens", "CHAT_AGENT_DECISION_LLM_MAX_TOKENS", 0)),
        chat_agent_decision_llm_extra_body=str(_cfg("chat_agent_decision_llm_extra_body", "CHAT_AGENT_DECISION_LLM_EXTRA_BODY", "")),
        chat_agent_lightweight_definition_model=str(
            getattr(config, "chat_agent_lightweight_definition_model", "llama32-finalizer-fast")
        ),
        chat_agent_lightweight_definition_timeout=float(
            getattr(config, "chat_agent_lightweight_definition_timeout", 20.0)
        ),
        chat_agent_web_strategy_timeout=float(
            getattr(config, "chat_agent_web_strategy_timeout", 60.0)
        ),
        chat_agent_web_strategy_max_tokens=int(
            getattr(config, "chat_agent_web_strategy_max_tokens", 700)
        ),
        chat_agent_max_tokens=int(getattr(config, "chat_agent_max_tokens", 512)),
        chat_agent_max_reply_length=int(getattr(config, "chat_agent_max_reply_length", 500)),
        chat_agent_history_max_messages=int(getattr(config, "chat_agent_history_max_messages", 10)),
        chat_agent_history_max_rows_per_session=int(getattr(config, "chat_agent_history_max_rows_per_session", 200)),
        chat_agent_memory_max_results=int(getattr(config, "chat_agent_memory_max_results", 5)),
        chat_agent_memory_max_rows=int(getattr(config, "chat_agent_memory_max_rows", 500)),
        chat_agent_search_provider=str(getattr(config, "chat_agent_search_provider", "duckduckgo")),
        chat_agent_search_base_url=str(getattr(config, "chat_agent_search_base_url", "")),
        chat_agent_web_timeout=int(getattr(config, "chat_agent_web_timeout", 15)),
        chat_agent_web_max_results=int(getattr(config, "chat_agent_web_max_results", 3)),
        chat_agent_web_read_max_chars=int(getattr(config, "chat_agent_web_read_max_chars", 6000)),
        chat_agent_web_user_agent=str(getattr(config, "chat_agent_web_user_agent", "Mozilla/5.0 HimariBot/1.0")),
        chat_agent_log_dir=str(getattr(config, "chat_agent_log_dir", "/app/log")),
        chat_agent_retrieval_min_score=float(getattr(config, "chat_agent_retrieval_min_score", 0.45)),
        chat_agent_web_relevance_min_score=float(getattr(config, "chat_agent_web_relevance_min_score", 0.35)),
        chat_agent_web_final_min_score=float(getattr(config, "chat_agent_web_final_min_score", 0.30)),
        chat_agent_enable_embedding_retrieval=_as_bool(getattr(config, "chat_agent_enable_embedding_retrieval", True), True),
        chat_agent_embedding_base_url=str(getattr(config, "chat_agent_embedding_base_url", "http://192.168.0.112:11434")),
        chat_agent_embedding_model=str(getattr(config, "chat_agent_embedding_model", "hf.co/Qwen/Qwen3-Embedding-0.6B-GGUF:Q8_0")),
        chat_agent_embedding_timeout=int(getattr(config, "chat_agent_embedding_timeout", 30)),
        chat_agent_embedding_reliable_score=float(getattr(config, "chat_agent_embedding_reliable_score", 0.68)),
        chat_agent_embedding_candidate_score=float(getattr(config, "chat_agent_embedding_candidate_score", 0.60)),
        chat_agent_embedding_min_margin=float(getattr(config, "chat_agent_embedding_min_margin", 0.05)),
        chat_agent_db_path=Path(getattr(config, "chat_agent_db_path", "data/nonebot_chat_agent/agent.sqlite3")),
        chat_agent_data_dir=Path(data_dir),
        chat_agent_enable_skills=_as_bool(
            _cfg("chat_agent_enable_skills", "CHAT_AGENT_ENABLE_SKILLS", True),
            True,
        ),
        chat_agent_skills_dir=Path(
            str(_cfg("chat_agent_skills_dir", "CHAT_AGENT_SKILLS_DIR", "data/nonebot_chat_agent/skills"))
        ),
        chat_agent_skills_max_active=int(
            _cfg("chat_agent_skills_max_active", "CHAT_AGENT_SKILLS_MAX_ACTIVE", 3)
        ),
        chat_agent_skills_max_body_chars=int(
            _cfg("chat_agent_skills_max_body_chars", "CHAT_AGENT_SKILLS_MAX_BODY_CHARS", 4000)
        ),
        chat_agent_skill_web_allow_names=str(
            _cfg("chat_agent_skill_web_allow_names", "CHAT_AGENT_SKILL_WEB_ALLOW_NAMES", "news,weather")
        ),
        chat_agent_skill_web_block_names=str(
            _cfg("chat_agent_skill_web_block_names", "CHAT_AGENT_SKILL_WEB_BLOCK_NAMES", "pptx,docx,pdf,xlsx")
        ),
        chat_agent_skill_evidence_enable=_as_bool(
            _cfg("chat_agent_skill_evidence_enable", "CHAT_AGENT_SKILL_EVIDENCE_ENABLE", True),
            True,
        ),
        chat_agent_news_skill_max_sources=int(
            _cfg("chat_agent_news_skill_max_sources", "CHAT_AGENT_NEWS_SKILL_MAX_SOURCES", 1)
        ),
        chat_agent_news_skill_read_max_chars=int(
            _cfg("chat_agent_news_skill_read_max_chars", "CHAT_AGENT_NEWS_SKILL_READ_MAX_CHARS", 6000)
        ),
        chat_agent_weather_skill_read_max_chars=int(
            _cfg("chat_agent_weather_skill_read_max_chars", "CHAT_AGENT_WEATHER_SKILL_READ_MAX_CHARS", 1200)
        ),
        chat_agent_decision_policy_path=Path(
            str(_cfg("chat_agent_decision_policy_path", "CHAT_AGENT_DECISION_POLICY_PATH", "data/nonebot_chat_agent/decision_policy.json"))
        ),
        chat_agent_decision_classifier_enable=_as_bool(
            _cfg("chat_agent_decision_classifier_enable", "CHAT_AGENT_DECISION_CLASSIFIER_ENABLE", False),
            False,
        ),
        chat_agent_decision_classifier_observe=_as_bool(
            _cfg("chat_agent_decision_classifier_observe", "CHAT_AGENT_DECISION_CLASSIFIER_OBSERVE", False),
            False,
        ),
        chat_agent_decision_classifier_max_skills=int(
            _cfg("chat_agent_decision_classifier_max_skills", "CHAT_AGENT_DECISION_CLASSIFIER_MAX_SKILLS", 10)
        ),
        chat_agent_decision_classifier_max_catalog_chars=int(
            _cfg(
                "chat_agent_decision_classifier_max_catalog_chars",
                "CHAT_AGENT_DECISION_CLASSIFIER_MAX_CATALOG_CHARS",
                2000,
            )
        ),
        chat_agent_decision_classifier_timeout=int(
            _cfg("chat_agent_decision_classifier_timeout", "CHAT_AGENT_DECISION_CLASSIFIER_TIMEOUT", 3)
        ),
        chat_agent_decision_classifier_max_tokens=int(
            _cfg("chat_agent_decision_classifier_max_tokens", "CHAT_AGENT_DECISION_CLASSIFIER_MAX_TOKENS", 160)
        ),
        chat_agent_decision_classifier_model=str(
            _cfg("chat_agent_decision_classifier_model", "CHAT_AGENT_DECISION_CLASSIFIER_MODEL", "")
        ),
        chat_agent_coarse_decision_enable=_as_bool(
            _cfg("chat_agent_coarse_decision_enable", "CHAT_AGENT_COARSE_DECISION_ENABLE", False),
            False,
        ),
        chat_agent_coarse_decision_observe=_as_bool(
            _cfg("chat_agent_coarse_decision_observe", "CHAT_AGENT_COARSE_DECISION_OBSERVE", False),
            False,
        ),
        chat_agent_coarse_decision_model=str(
            _cfg("chat_agent_coarse_decision_model", "CHAT_AGENT_COARSE_DECISION_MODEL", "")
        ),
        chat_agent_coarse_decision_timeout=float(
            _cfg("chat_agent_coarse_decision_timeout", "CHAT_AGENT_COARSE_DECISION_TIMEOUT", 6)
        ),
        chat_agent_coarse_decision_max_tokens=int(
            _cfg("chat_agent_coarse_decision_max_tokens", "CHAT_AGENT_COARSE_DECISION_MAX_TOKENS", 96)
        ),
    )
    _cached_config.ensure_data_dir()
    return _cached_config
