from nonebot import get_plugin_config
from pydantic import BaseModel
from typing import Optional

class Config(BaseModel):
    cooldown_enable_persistence: Optional[bool] = False
    cooldown_save_interval: Optional[int] = 60

plugin_config: Config = get_plugin_config(Config)
