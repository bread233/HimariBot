from __future__ import annotations

from pathlib import Path
import shutil

from nonebot import get_plugin_config
from pydantic import BaseModel, Field


_PACKAGE_CONFIG_DIR: Path = Path(__file__).resolve().parent / "config"
_RUNTIME_CONFIG_DIR: Path = Path.cwd() / "data" / "nonebot_chat_agent" / "config"


def _ensure_runtime_config_files() -> None:
    try:
        _RUNTIME_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        if not _PACKAGE_CONFIG_DIR.exists():
            return
        for template in _PACKAGE_CONFIG_DIR.glob("*.toml"):
            target = _RUNTIME_CONFIG_DIR / template.name
            if not target.exists():
                shutil.copy2(template, target)
    except Exception:
        # 插件配置加载阶段不要因为复制失败阻塞整个插件导入
        # maibot_core 后续完整初始化时仍会处理配置错误
        return


class ConfigModel(BaseModel):
    codex_chat_enable: bool = Field(default=True)
    codex_chat_command_priority: int = Field(default=9)
    codex_chat_timeout: int = Field(default=120)
    codex_chat_workdir: str = Field(default="/opt/codex")
    codex_chat_docker_container: str = Field(default="codexcli")
    codex_chat_model: str = Field(default="gpt-5.4-mini")
    codex_chat_allowed_groups: list[int] | str = Field(default_factory=list)

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


def get_config() -> ConfigModel:
    _ensure_runtime_config_files()
    return get_plugin_config(ConfigModel)
