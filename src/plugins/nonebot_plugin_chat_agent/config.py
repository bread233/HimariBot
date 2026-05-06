from __future__ import annotations

from pathlib import Path

from nonebot import get_driver
from pydantic import BaseModel, Field


class ChatAgentConfig(BaseModel):
    chat_agent_enable: bool = Field(default=True)
    chat_agent_enable_history: bool = Field(default=True)
    chat_agent_base_url: str = Field(default="http://127.0.0.1:11434/v1")
    chat_agent_api_key: str = Field(default="ollama")
    chat_agent_model: str = Field(default="qwen3:1.7b")
    chat_agent_think: bool = Field(default=False)
    chat_agent_timeout: int = Field(default=120)
    chat_agent_max_tokens: int = Field(default=512)
    chat_agent_max_reply_length: int = Field(default=500)
    chat_agent_history_max_messages: int = Field(default=10)
    chat_agent_history_max_rows_per_session: int = Field(default=200)
    chat_agent_db_path: Path = Field(default=Path("data/nonebot_chat_agent/agent.sqlite3"))
    chat_agent_data_dir: Path = Field(default=Path("data/nonebot_chat_agent"))

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
    data_dir = getattr(config, "chat_agent_data_dir", "data/nonebot_chat_agent")
    _cached_config = ChatAgentConfig(
        chat_agent_enable=_as_bool(getattr(config, "chat_agent_enable", True), True),
        chat_agent_enable_history=_as_bool(getattr(config, "chat_agent_enable_history", True), True),
        chat_agent_base_url=str(getattr(config, "chat_agent_base_url", "http://127.0.0.1:11434/v1")),
        chat_agent_api_key=str(getattr(config, "chat_agent_api_key", "ollama")),
        chat_agent_model=str(getattr(config, "chat_agent_model", "qwen3:1.7b")),
        chat_agent_think=_as_bool(getattr(config, "chat_agent_think", False), False),
        chat_agent_timeout=int(getattr(config, "chat_agent_timeout", 120)),
        chat_agent_max_tokens=int(getattr(config, "chat_agent_max_tokens", 512)),
        chat_agent_max_reply_length=int(getattr(config, "chat_agent_max_reply_length", 500)),
        chat_agent_history_max_messages=int(getattr(config, "chat_agent_history_max_messages", 10)),
        chat_agent_history_max_rows_per_session=int(getattr(config, "chat_agent_history_max_rows_per_session", 200)),
        chat_agent_db_path=Path(getattr(config, "chat_agent_db_path", "data/nonebot_chat_agent/agent.sqlite3")),
        chat_agent_data_dir=Path(data_dir),
    )
    _cached_config.ensure_data_dir()
    return _cached_config
