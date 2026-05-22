import os
from pydantic import BaseSettings, Field

class Config(BaseSettings):
    # Codex Chat 基本配置
    codex_chat_enable: bool = Field(default=True, env="CODEx_CHAT_ENABLE")
    codex_chat_command_priority: int = Field(default=9, env="CODEx_CHAT_COMMAND_PRIORITY")
    codex_chat_cd_seconds: int = Field(default=300, env="CODEx_CHAT_CD_SECONDS")
    codex_chat_timeout: int = Field(default=120, env="CODEx_CHAT_TIMEOUT")
    codex_chat_workdir: str = Field(default="/opt/codex", env="CODEx_CHAT_WORKDIR")
    codex_chat_docker_container: str = Field(default="codexcli", env="CODEx_CHAT_DOCKER_CONTAINER")
    codex_chat_model: str = Field(default="gpt-5.4-mini", env="CODEx_CHAT_MODEL")
    codex_chat_max_prompt_chars: int = Field(default=2000, env="CODEx_CHAT_MAX_PROMPT_CHARS")
    codex_chat_persona_path: str = Field(
        default="data/nonebot_chat_agent/personas/himari_codex.md",
        env="CODEx_CHAT_PERSONA_PATH"
    )

    # 白名单
    codex_chat_allowed_groups: list[int] = Field(default_factory=list, env="CODEx_CHAT_ALLOWED_GROUPS")
    # 兴趣评分阈值
    codex_chat_interest_threshold: int = Field(default=8, env="CODEx_CHAT_INTEREST_THRESHOLD")
    # Proactive 自动模式开关
    codex_chat_proactive_enabled: bool = Field(default=True, env="CODEx_CHAT_PROACTIVE_ENABLED")

    class Config:
        env_file = ".env.dev"
        env_file_encoding = "utf-8"