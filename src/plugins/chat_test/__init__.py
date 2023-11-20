import nonebot
from nonebot.adapters import Bot
from nonebot import on_command
from nonebot.plugin import PluginMetadata
from nonebot.adapters.onebot.v11 import Message
from nonebot.params import CommandArg

Bot_NICKNAME = set(nonebot.get_driver().config.nickname)

__plugin_name__ = '回复测试'
__plugin_version__ = '0.1.0'
__plugin_meta__ = PluginMetadata(
    __plugin_name__,
    "测试bot状态",
    (
        "指令表：\n"
        "hmr 在？\n"
    ),
    {
        "License": "MIT",
        "Author": "xmb233",
        "version": __plugin_version__,
    },
)

chat_matcher = on_command("hmr", aliases=Bot_NICKNAME)

@chat_matcher.handle()
async def chat(args: Message = CommandArg()):
    if "在" not in args.extract_plain_text():
        await chat_matcher.finish(f"有什么事啊？")
    else:
        await chat_matcher.finish(f"error!出问题了！")