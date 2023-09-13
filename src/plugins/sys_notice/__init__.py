import clr

from nonebot.plugin import PluginMetadata, on_command
from nonebot.permission import SUPERUSER
from nonebot.log import logger
from nonebot import get_driver
import nonebot
from nonebot.adapters.onebot.v11 import (
    Bot,
    PrivateMessageEvent,
)
import os

path = os.path.dirname(__file__)
file = os.path.join(path, "OpenHardwareMonitorLib.dll")

clr.AddReference(file)

from OpenHardwareMonitor.Hardware import Computer

spec = Computer()
spec.GPUEnabled = True
spec.CPUEnabled = True
spec.Open()


# Get CPU Temp
def Cpu_Temp():
    cpu_list = []
    try:
        for cpu in range(0, len(spec.Hardware[0].Sensors)):
            if "/temperature" in str(spec.Hardware[0].Sensors[cpu].Identifier):
                cpu_list.append(str(spec.Hardware[0].Sensors[cpu].Value))
    except Exception as e:
        logger.error(e)
        logger.error("获取cpu温度出错!")
        cpu_list.append("获取cpu温度出错!")
    return cpu_list


# Get GPU Temp
def Gpu_Temp():
    gpu_list = []
    try:
        for gpu in range(0, len(spec.Hardware[0].Sensors)):
            if "/temperature" in str(spec.Hardware[0].Sensors[gpu].Identifier):
                gpu_list.append(str(spec.Hardware[0].Sensors[gpu].Value))
    except Exception as e:
        logger.error(e)
        logger.error("获取gpu温度出错!")
        gpu_list.append("获取gpu温度出错!")
    return gpu_list


__plugin_meta__ = PluginMetadata(
    name="温度查看器",
    description="winserver温度查看插件",
    usage="""服务器温度  查看服务器cpu gpu温度
    温度超过80度会私聊报告超管""",
    type="application",
    homepage="https://github.com/bread233/HimariBot/tree/main/src/plugins/sys_notice",
    supported_adapters={"~onebot.v11"},
)

temp_ask = on_command("服务器温度", permission=SUPERUSER)

# 获取超级用户的id
super_id = get_driver().config.superusers


@temp_ask.handle()
async def _(bot: Bot, event: PrivateMessageEvent):
    cpu_list = Cpu_Temp()
    gpu_list = Gpu_Temp()
    msg = []
    user_id = int(event.get_user_id())
    if "获取cpu温度出错!" not in cpu_list:
        if "获取gpu温度出错!" not in gpu_list:
            msg.append("服务器温度信息如下:")
            msg.append("cpu:" + str(cpu_list))
            msg.append("gpu:" + str(gpu_list))
            msg = "\n".join(msg)
            await bot.send_private_msg(user_id=user_id, message=msg)
            return
        else:
            await bot.send_private_msg(user_id=user_id, message="获取cpu温度出错!获取gpu温度出错!")
    else:
        await bot.send_private_msg(user_id=user_id, message="获取cpu温度出错!")


from src.service.apscheduler import scheduler


async def check_temp():
    cpu_list = Cpu_Temp()
    gpu_list = Gpu_Temp()
    msg = []
    schedBot = nonebot.get_bot()
    if "获取cpu温度出错!" not in cpu_list:
        if "获取gpu温度出错!" not in gpu_list:
            n = 0
            for cpu in cpu_list:
                if int(cpu) > 80:
                    n = 1
            for gpu in gpu_list:
                if int(gpu) > 80:
                    n = 1
            if n == 1:
                msg.append("有核心温度超过警戒值,请尽快降温处理")
                msg.append("cpu:" + str(cpu_list))
                msg.append("gpu:" + str(gpu_list))
                msg = "\n".join(msg)
                for su_qq in super_id:
                    await schedBot.send_msg(message=msg, user_id=int(su_qq))


scheduler.add_job(
    check_temp, "interval", minutes=10, id="check_temp", misfire_grace_time=90
)
