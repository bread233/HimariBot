# 兼容用的转发包，把顶层的 nonebot_plugin_alconna 映射到你自己的实现上

from src.service.nonebot_plugin_alconna import *  # noqa

# 顺便把常用对象导出来（不是必须，但更保险）
from src.service.nonebot_plugin_alconna.matcher import *  # noqa
from src.service.nonebot_plugin_alconna.rule import *  # noqa
from src.service.nonebot_plugin_alconna.consts import *  # noqa
