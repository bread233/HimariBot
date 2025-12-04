from nonebot import get_driver, logger, require
from nonebot.plugin import PluginMetadata, inherit_supported_adapters
from nonebot.adapters.onebot.v11 import Adapter as OneBotV11Adapter  # ✅ 新增

from .config import Config

# 这些依赖的 NoneBot 插件还是照常 require
require("nonebot_plugin_alconna")
require("nonebot_plugin_uninfo")
require("nonebot_plugin_waiter")
# require("nonebot_plugin_apscheduler")  # ⬅️ 等会儿我们换成自己的，不再 require 官方

# ✅ 改成你自己的 apscheduler 封装
from src.service.apscheduler import scheduler

from .command import diuse_farm, diuse_register, reclamation
from .config import g_pConfigManager
from .database.database import g_pSqlManager
from .dbService import g_pDBService
from .farm.farm import g_pFarmManager
from .farm.shop import g_pShopManager
from .json import g_pJsonManager
from .request import g_pRequestManager

__plugin_meta__ = PluginMetadata(
    name="真寻农场",
    description="快乐的农场时光",
    usage=""" ... """.strip(),
    type="application",
    homepage="https://github.com/Shu-Ying/nonebot_plugin_farm",
    config=Config,
    # ❌ 不再用 inherit_supported_adapters(...)
    # ✅ 只支持 OneBot V11
    supported_adapters={OneBotV11Adapter},
)

driver = get_driver()


# 构造函数
@driver.on_startup
async def start():
    # 初始化数据库
    await g_pSqlManager.init()

    # 初始化读取Json
    await g_pJsonManager.init()

    await g_pDBService.init()

    # 检查作物文件是否缺失 or 更新
    await g_pRequestManager.initPlantDBFile()


# 析构函数
@driver.on_shutdown
async def shutdown():
    await g_pSqlManager.cleanup()

    await g_pDBService.cleanup()


@scheduler.scheduled_job(trigger="cron", hour=4, minute=30, id="signInFile")
async def signInFile():
    try:
        await g_pJsonManager.initSignInFile()
        await g_pRequestManager.initPlantDBFile()
    except Exception as e:
        logger.error("农场定时检查出错", e=e)
