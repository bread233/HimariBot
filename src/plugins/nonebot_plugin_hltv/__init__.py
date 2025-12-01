#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from nonebot.plugin import PluginMetadata

from .config import ConfigModel
from . import matcher  # 导入 matcher 以注册命令

# 尝试加载 WebUI
try:
    from . import web_ui
    web_ui.init_web_ui()
except ImportError:
    pass
except Exception as e:
    from nonebot.log import logger
    logger.warning(f"HLTV WebUI 加载失败: {e}")

__plugin_meta__ = PluginMetadata(
    name="CS2/CSGO HLTV 信息查询",
    description="提供CS2/CSGO比赛数据、战队信息、选手数据查询功能。",
    usage=(
        "指令:\n"
        "/cs2比赛 - 查看当前CS2比赛\n"
        "/cs2战队 <战队名> - 查询战队信息\n"
        "/cs2结果 - 查看最近比赛结果\n"
        "/cs2排名 - 查看战队排名\n"
        "/cs2选手 <选手名> - 查询选手信息\n"
        "\n"
        "也支持在对话中自动识别CS2相关话题"
    ),
    type="application",
    homepage="https://github.com/KawakazeNotFound/nonebot-plugin-hltv",
    config=ConfigModel,
)

__all__ = ["__plugin_meta__"]


