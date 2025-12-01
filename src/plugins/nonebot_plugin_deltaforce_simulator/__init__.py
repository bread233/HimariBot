# coding=utf-8
from pathlib import Path
import random

from .gen_result import generate_result
from nonebot.adapters.onebot.v11 import MessageEvent
from nonebot import require, on_command, logger
from .config import Config
from nonebot.plugin import PluginMetadata
import base64

#require("nonebot_plugin_saa")
from src.service.nonebot_plugin_saa import Text, Image, MessageFactory

#require("nonebot_plugin_userinfo")
from src.service.nonebot_plugin_userinfo import EventUserInfo,UserInfo


from nonebot.params import ArgPlainText

# from nonebot.plugin import PluginMetadata
from nonebot.typing import T_State

__plugin_meta__ = PluginMetadata(
    name="三角洲鼠鼠偷吃模拟器",
    description="适用于nonebot的三角洲鼠鼠偷吃模拟器（开容器模拟器）机器人插件",
    usage="""
    发送“开始跑刀”开始，如有命令前缀需要添加
    跑刀结果出来后，发送“还要吃”继续开容器，不需要添加命令前缀
    跑刀结果出来后，发送其他任意信息撤离
    """,
    config=Config,
    extra={},
    type="application",
    homepage="https://github.com/Alpaca4610/nonebot_plugin_deltaforce_simulator",
    supported_adapters={"~onebot.v11"},
)

start = on_command("开始跑刀", block=True, priority=1)

@start.handle()
async def handle_function(
     state: T_State, user_info: UserInfo = EventUserInfo()
):
    # state["count"] = 1
    # player_id = user_info.user_id
    # container_type = random.choice(list(CONTAINER_CONFIGS.keys()))

    img = await generate_result("random", user_name="你")
    mf = MessageFactory([Text("继续请发送\"还要吃\"（不需要带命令前缀），撤离则发送其他任意内容"), Image(img)])
    await mf.send(reply=True)

@start.got("code_")
async def got_name_(event: MessageEvent, state: T_State, code_: str = ArgPlainText(), user_info: UserInfo = EventUserInfo()):
    if code_ != "还要吃":
        # await Image(Path(__file__).parent / "resource\\success.png").finish(reply=True, at_sender=True)
        img_path = Path(__file__).parent / "resource/success.png"
        with open(img_path, "rb") as f:
            img_data = f.read()
        img_base64 = base64.b64encode(img_data).decode()
        if not img_path.exists():
            logger.error(f"图片文件不存在: {img_path}")
            await (Text("  撤离成功")).send(reply=True, at_sender=True)
        else:
            await (Text("  撤离成功") + Image(image=f"base64://{img_base64}")).send(reply=True, at_sender=True)
    else:
        if random.random() < 0.3:
            # await Image(Path(__file__).parent / "resource\\fail.jpg").finish(reply=True, at_sender=True)
            img_path = Path(__file__).parent / "resource/fail.jpg"
            with open(img_path, "rb") as f:
                img_data = f.read()
            img_base64 = base64.b64encode(img_data).decode()
            if not img_path.exists():
                logger.error(f"图片文件不存在: {img_path}")
                await (Text("  你被一脚踢死了")).send(reply=True, at_sender=True)
            else:
                await (Text("  你被一脚踢死了") + Image(image=f"base64://{img_base64}")).send(reply=True, at_sender=True)
        else:
            img = await generate_result("random", user_name="你")
            mf = MessageFactory([Text(" 继续请发送\"还要吃\"（不需要带命令前缀），撤离则发送其他任意内容"), Image(img)])
            await mf.send(reply=True)
            await start.reject()
