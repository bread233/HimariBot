"""
兼容用 uniseg 包

把 src.service.nonebot_plugin_alconna.uniseg 里的内容转出来，
给依赖 pip 版 nonebot_plugin_alconna 的插件使用。
"""
from src.service.nonebot_plugin_alconna.uniseg import *  # type: ignore
