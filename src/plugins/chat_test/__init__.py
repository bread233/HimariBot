import nonebot
from nonebot.adapters import Bot
from nonebot import on_command
from nonebot.plugin import PluginMetadata
from nonebot.adapters.onebot.v11 import Message
from nonebot.params import CommandArg
from nonebot.rule import to_me

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

chat_matcher = on_command("在?", aliases={'zai?','在吗?','在吗？','在？','zaima?'}, rule=to_me())

@chat_matcher.handle()
async def chat(args: Message = CommandArg()):
    await chat_matcher.finish(f"error!出问题了！")

chat_matcher1 = on_command("hmr", aliases=Bot_NICKNAME)

@chat_matcher1.handle()
async def chat1(args: Message = CommandArg()):
    if next(x for x in {'在?','zai?','在吗?','在吗？','在？','zaima?'} if x in args.extract_plain_text()):
        await chat_matcher1.finish(f"error!出问题了！")