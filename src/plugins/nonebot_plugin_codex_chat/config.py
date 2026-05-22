from __future__ import annotations

from nonebot import get_plugin_config
from pydantic import BaseModel, Field


class ConfigModel(BaseModel):
    # Codex Chat 基本配置
    codex_chat_enable: bool = Field(default=True)
    codex_chat_command_priority: int = Field(default=9)
    codex_chat_cd_seconds: int = Field(default=300)
    codex_chat_timeout: int = Field(default=120)
    codex_chat_workdir: str = Field(default="/opt/codex")
    codex_chat_docker_container: str = Field(default="codexcli")
    codex_chat_model: str = Field(default="gpt-5.4-mini")
    codex_chat_max_prompt_chars: int = Field(default=2000)
    codex_chat_persona_path: str = Field(
        default="data/nonebot_chat_agent/personas/himari_codex.md",
    )

    # 白名单
    codex_chat_allowed_groups: list[int] | str = Field(default_factory=list)
    codex_chat_owner_ids: list[int] | str = Field(default_factory=list)
    # 兴趣评分阈值
    codex_chat_interest_threshold: int = Field(default=8)
    # Proactive 自动模式开关
    codex_chat_proactive_enabled: bool = Field(default=True)
    codex_chat_proactive_min_interval_seconds: int = Field(default=60)

    class Config:
        extra = "ignore"

    @staticmethod
    def _parse_int_list(value) -> list[int]:
        if value is None:
            return []
        if isinstance(value, (list, tuple, set)):
            out: list[int] = []
            for item in value:
                s = str(item or "").strip()
                if not s:
                    continue
                try:
                    out.append(int(s))
                except Exception:
                    continue
            return out
        text = str(value or "").strip()
        if not text:
            return []
        normalized = text.replace("，", ",").replace(" ", ",")
        parts = [p.strip() for p in normalized.split(",") if p.strip()]
        out: list[int] = []
        for p in parts:
            try:
                out.append(int(p))
            except Exception:
                continue
        return out

    @property
    def allowed_groups_list(self) -> list[int]:
        return self._parse_int_list(self.codex_chat_allowed_groups)

    @property
    def owner_ids_list(self) -> list[int]:
        return self._parse_int_list(self.codex_chat_owner_ids)


def get_config() -> ConfigModel:
    return get_plugin_config(ConfigModel)
