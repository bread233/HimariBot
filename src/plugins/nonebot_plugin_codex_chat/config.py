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
    codex_chat_extract_message_context: bool = True
    codex_chat_extract_forward_context: bool = True
    codex_chat_extract_json_context: bool = True
    codex_chat_extract_bilibili_context: bool = True
    codex_chat_bilibili_context_max_chars: int = 1200
    codex_chat_forward_context_max_chars: int = 1500
    codex_chat_json_context_max_chars: int = 1000
    codex_chat_persona_path: str = Field(
        default="data/nonebot_chat_agent/personas/himari_codex.md",
    )

    # Proactive 兴趣正则，可在 .env.dev 覆盖
    codex_chat_active_interest_pattern: str = Field(
        default=r"怎么回事|发生什么|有新瓜|什么瓜|真的假的|笑死|乐子|抽象|绷不住|离谱|太怪了|逆天"
    )
    codex_chat_technical_interest_pattern: str = Field(
        default=r"python|docker|linux|git|github|报错|bug|代码|模型|ai|llm|prompt|服务器|容器|数据库|网络|部署"
    )
    codex_chat_technical_error_pattern: str = Field(
        default=r"失败|异常|错误|启动失败|起不来|挂了|崩了|连不上|超时"
    )
    codex_chat_culture_interest_pattern: str = Field(
        default=r"游戏|动画|漫画|番剧|角色|剧情|攻略|活动|抽卡|联动|视频|up主"
    )
    codex_chat_news_interest_pattern: str = Field(
        default=r"新闻|热搜|公告|更新|爆料|发布|版本|新活动"
    )
    codex_chat_activity_interest_pattern: str = Field(
        default=r"比赛|赛事|直播|开播|活动|更新|维护|兑换码"
    )
    codex_chat_question_pattern: str = Field(
        default=r"吗|呢|为什么|怎么|如何|啥|什么|有没有|谁知道|求问|请问|[?？]"
    )
    codex_chat_sharp_reply_pattern: str = Field(
        default=r"绷|典|乐|蚌埠住了|笑死|离谱|逆天|抽象"
    )
    codex_chat_life_interest_pattern: str = Field(
        default=r""
    )

    codex_chat_low_value_pattern: str = Field(
        default=r"^(\?|？|。|\.|,|，|哈+|啊+|哦+|嗯+|1|6|66|666|草|艹|笑死|哈哈哈*)$"
    )
    codex_chat_zero_pattern: str = Field(
        default=r"色图|涩图|av视频|AV视频|\br18\b|开车|黄图|色情|porn|hentai"
    )
    codex_chat_service_request_pattern: str = Field(
        default=r"帮我|请问|怎么|如何|为什么|能不能|可以吗|求|查一下|搜一下|写|做|修|装|配置|教程|解释|分析|总结|发给我|告诉我"
    )

    # 白名单
    codex_chat_allowed_groups: list[int] | str = Field(default_factory=list)
    codex_chat_owner_ids: list[int] | str = Field(default_factory=list)
    # 兴趣评分阈值
    codex_chat_interest_threshold: int = Field(default=8)
    # Proactive 自动模式开关
    codex_chat_proactive_enabled: bool = Field(default=True)
    codex_chat_proactive_min_interval_seconds: int = Field(default=60)
    codex_chat_interest_skill_path: str = Field(
        default="data/nonebot_chat_agent/codex_chat/interest_rules.md",
    )
    codex_chat_interest_skill_reload_seconds: int = Field(default=10)

    # Episode 自动抽取配置（默认关闭）
    codex_chat_memory_episode_auto_enabled: bool = False
    codex_chat_memory_episode_auto_interval_seconds: int = 300
    codex_chat_memory_episode_auto_limit_per_tick: int = 1
    codex_chat_memory_episode_auto_recent_limit: int = 20
    codex_chat_memory_episode_auto_min_age_seconds: int = 180

    # Memory recall 注入配置（默认关闭）
    codex_chat_memory_recall_enabled: bool = False
    codex_chat_memory_recall_limit: int = 5
    codex_chat_memory_recall_include_user: bool = True
    codex_chat_memory_recall_min_importance: int = 0
    codex_chat_memory_recall_min_confidence: float = 0.0
    codex_chat_memory_recall_max_chars: int = 1200

    # Long memory recall 注入配置（默认关闭）
    codex_chat_memory_long_recall_enabled: bool = False
    codex_chat_memory_long_recall_limit: int = 10
    codex_chat_memory_long_recall_min_importance: int = 0
    codex_chat_memory_long_recall_min_confidence: float = 0.0
    codex_chat_memory_long_recall_max_chars: int = 1200

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
