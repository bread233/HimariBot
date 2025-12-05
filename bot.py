import os
import sys
import asyncio
from pathlib import Path
from datetime import datetime

import nonebot
from nonebot.adapters.onebot.v11 import Adapter as ONEBOT_V11Adapter
from nonebot.adapters.qq import Adapter as QQAdapter
from nonebot.log import logger, default_format


# =========================
# 运行目录 / data / log 目录
# =========================

def get_runtime_path() -> Path:
    """
    获取程序运行目录：
    - 普通 Python：当前文件所在目录
    - PyInstaller EXE：exe 文件所在目录
    - Docker：/app（根据 Dockerfile/working_dir）
    """
    if getattr(sys, "frozen", False):
        # 打包成 exe 后
        return Path(sys.executable).resolve().parent
    # 普通 Python 运行
    return Path(__file__).resolve().parent


BASE_DIR = get_runtime_path()

# 可选：确保当前工作目录就是程序目录（有利于插件用相对路径）
os.chdir(BASE_DIR)

# 自动创建 data 与 log 目录
DATA_DIR = BASE_DIR / "data"
LOG_DIR = BASE_DIR / "log"
for path in (DATA_DIR, LOG_DIR):
    path.mkdir(parents=True, exist_ok=True)


# =========================
# Windows 下 asyncio 设置
# =========================

if (
    sys.version_info[0] == 3
    and 10 > sys.version_info[1] >= 8
    and sys.platform.startswith("win")
):
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
elif (
    sys.version_info[0] == 3
    and sys.version_info[1] >= 10
    and sys.platform.startswith("win")
):
    asyncio.set_event_loop(asyncio.ProactorEventLoop())


# ==========
# 日志配置
# ==========

# 日志文件路径：log/20251205-120000-INFO.log 之类
log_timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
log_info_path = LOG_DIR / f"{log_timestamp}-INFO.log"
log_error_path = LOG_DIR / f"{log_timestamp}-ERROR.log"

logger.add(
    str(log_info_path),
    rotation="00:00",
    diagnose=False,
    level="INFO",
    format=default_format,
    encoding="utf-8",
)
logger.add(
    str(log_error_path),
    rotation="00:00",
    diagnose=False,
    level="ERROR",
    format=default_format,
    encoding="utf-8",
)

# 如需 DEBUG 日志可取消注释
# log_debug_path = LOG_DIR / f"{log_timestamp}-DEBUG.log"
# logger.add(
#     str(log_debug_path),
#     rotation="00:00",
#     diagnose=False,
#     level="DEBUG",
#     format=default_format,
#     encoding="utf-8",
# )


# ==========
# NoneBot 初始化
# ==========

# 可以在这里传入一些配置：nonebot.init(driver="~fastapi", ...)
nonebot.init()

driver = nonebot.get_driver()
driver.register_adapter(ONEBOT_V11Adapter)
driver.register_adapter(QQAdapter)

# 测试用内置 echo 插件
nonebot.load_builtin_plugins("echo")

# 加载插件
nonebot.load_plugin("nonebot_plugin_alconna")
nonebot.load_plugin("nonebot_plugin_uninfo")
nonebot.load_plugins("src/plugins")
# nonebot.load_from_toml("pyproject.toml")

if __name__ == "__main__":
    nonebot.run()
