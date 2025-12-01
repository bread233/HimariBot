"""
兼容用 tools 模块

转发 src.service.nonebot_plugin_alconna.uniseg.tools 里的实现，
确保 from nonebot_plugin_alconna.uniseg.tools import image_fetch 能正常工作。
"""
from src.service.nonebot_plugin_alconna.uniseg.tools import *  # type: ignore
