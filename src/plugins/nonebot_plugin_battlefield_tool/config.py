# nonebot_plugin_battlefield_tool/config.py
from typing import Optional

from pydantic import BaseModel
from nonebot import get_driver


class Config(BaseModel):
    # 对应 _conf_schema.json
    battlefield_default_game: str = "bfv"
    battlefield_timeout_config: int = 15
    battlefield_img_quality: int = 90
    battlefield_bf_prompt: str = (
        "请根据以下评判标准和数据从多个方面评价用户的游戏水平，注意要结合人设和上下文，保证对话不冲突..."
    )
    # 原来是 str | None（Py3.10+ 写法），这里改成 Optional[str]
    battlefield_evaluation_provider: Optional[str] = None
    battlefield_ssc_token: str = ""


# 供插件内部使用
global_config = get_driver().config
plugin_config = Config.parse_obj(global_config.dict())
