import nonebot
from nonebot.adapters import Bot
from nonebot import on_command
from nonebot.plugin import PluginMetadata
from nonebot.adapters.onebot.v11 import Message, MessageEvent 
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

#@chat_matcher.handle()
async def chat(args: Message = CommandArg()):
    await chat_matcher.finish(f"error!出问题了！")

chat_matcher1 = on_command("hmr", aliases=Bot_NICKNAME)

#@chat_matcher1.handle()
async def chat1(args: Message = CommandArg()):
    if next(x for x in {'在?','zai?','在吗?','在吗？','在？','zaima?'} if x in args.extract_plain_text()):
        await chat_matcher1.finish(f"error!出问题了！")

async def chain_reply(bot, ev, chain, msg):
    uid=ev.user_id
    try:
        info = await bot.get_stranger_info(self_id=ev.self_id, user_id=ev.user_id)
        name = info['nickname']
        data ={
                "type": "node",
                "data": {
                    "name": name,#str(NICKNAME[0])
                    "uin": uid,#str(ev.self_id)
                    "content": str(msg)
                        }
            }
        chain.append(data)
    except:
        data ={
                "type": "node",
                "data": {
                    "name": '小冰',#str(NICKNAME[0])
                    "uin": '2854196306',#str(ev.self_id)
                    "content": str(msg)
                        }
            }
        chain.append(data)
    return chain

mc_matcher = on_command("mc帮助", aliases={"mc连接","mc登录"})

<<<<<<< HEAD
msgs = ["客户端连接方法：\n1，先下载hmcl客户端，直接创建离线账号并且安装1.20.1的客户端（不用安装forge）\n2，多人游戏中填写下记服务器 xmb-home-pc.softether.net:25565",
        "客户端直接百度hmcl或者下载群里的",
        "只玩就不用往下看了，下面是服务端配置mod文件位置",
        "mod安装位置：\n1，登录管理网页： xmb-home-pc.softether.net:23333\n2，用户名：user 密码：User12345\n3，第一个实例点击管理\n4，在实例功能组中点击 文件管理\n5，在mods文件夹中上传mod\n6，回到控制台重启实例"
=======
msgs = ["客户端连接方法：\n https://www.superbread.uk/2024/04/23/minecraft%e5%ae%a2%e6%88%b7%e7%ab%af%e4%bd%bf%e7%94%a8%e4%b8%8emod%e5%ae%89%e8%a3%85/",
        "下载包:\n https://www.superbread.uk/nas/sharing/KSBjRGyg2",
        "宝可梦服:\n pkm.superbread.uk",
        "工业2服:\n fcy.superbread.uk"
>>>>>>> 5016642 (更新插件追加回复变更mc)
        ]

@mc_matcher.handle()
async def mc_(bot: Bot, event: MessageEvent):
    chain = []
    for x in msgs:
        chain = await chain_reply(bot,event,chain,x)
    await bot.send_group_forward_msg(group_id=event.group_id, messages=chain)