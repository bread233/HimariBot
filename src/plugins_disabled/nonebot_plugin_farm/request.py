import json
import os
import random

import httpx
from nonebot import logger
from rich.progress import (
    BarColumn,
    DownloadColumn,
    Progress,
    TextColumn,
    TimeRemainingColumn,
    TransferSpeedColumn,
)

from .config import g_pConfigManager, g_sPlantPath, g_sSignInPath
from .dbService import g_pDBService
from .tool import g_pToolManager


class CRequestManager:
    m_sTokens = "xZ%?z5LtWV7H:0-Xnwp+bNRNQ-jbfrxG"

    @classmethod
    async def download(
        cls,
        url: str,
        savePath: str,
        fileName: str,
        params: dict | None = None,
        jsonData: dict | None = None,
    ) -> bool:
        """下载文件到指定路径并覆盖已存在的文件

        Args:
            url (str): 文件的下载链接
            savePath (str): 保存文件夹路径
            fileName (str): 保存后的文件名
            params (dict | None): 可选的 URL 查询参数
            jsonData (dict | None): 可选的 JSON 请求体

        Returns:
            bool: 是否下载成功
        """
        headers = {"token": cls.m_sTokens}

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                requestArgs: dict = {"headers": headers}
                if params:
                    requestArgs["params"] = params
                if jsonData:
                    requestArgs["json"] = jsonData

                response = await client.request(
                    "GET", url, **requestArgs, follow_redirects=True
                )

                if response.status_code != 200:
                    logger.warning(
                        f"文件下载失败: HTTP {response.status_code} {response.text}"
                    )
                    return False

                totalLength = int(response.headers.get("Content-Length", 0))
                fullPath = os.path.join(savePath, fileName)
                os.makedirs(os.path.dirname(fullPath), exist_ok=True)

                with Progress(
                    TextColumn("[progress.description]{task.description}"),
                    BarColumn(),
                    DownloadColumn(),
                    TransferSpeedColumn(),
                    TimeRemainingColumn(),
                    transient=True,
                ) as progress:
                    task = progress.add_task(
                        f"[green]【真寻农场】正在下载 {fileName}", total=totalLength
                    )

                    with open(fullPath, "wb") as f:
                        async for chunk in response.aiter_bytes(chunk_size=1024):
                            f.write(chunk)
                            progress.advance(task, len(chunk))

                return True

        except Exception as e:
            logger.warning(f"下载文件异常: {e}")
            return False

    @classmethod
    async def post(cls, endpoint: str, name: str = "", jsonData: dict = {}) -> dict:
        """发送POST请求到指定接口，统一调用，仅支持JSON格式数据

        Args:
            endpoint (str): 请求的接口路径
            name (str, optional): 操作名称用于日志记录
            jsonData (dict): 以JSON格式发送的数据

        Raises:
            ValueError: 当jsonData未提供时抛出

        Returns:
            dict: 返回请求结果的JSON数据
        """
        baseUrl = g_pConfigManager.farm_server_url
        url = f"{baseUrl.rstrip('/')}:8998/{endpoint.lstrip('/')}"
        headers = {"token": cls.m_sTokens}

        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.post(url, json=jsonData, headers=headers)

                if response.status_code == 200:
                    return response.json()
                else:
                    logger.warning(
                        f"{name}请求失败: HTTP {response.status_code} {response.text}"
                    )
                    return {}
        except httpx.RequestError as e:
            logger.warning(f"{name}请求异常", e=e)
            return {}
        except Exception as e:
            logger.warning(f"{name}处理异常", e=e)
            return {}

    @classmethod
    async def get(cls, endpoint: str, name: str = "") -> dict:
        """发送GET请求到指定接口，统一调用，仅支持无体的查询

        Args:
            endpoint (str): 请求的接口路径
            name (str, optional): 操作名称用于日志记录

        Returns:
            dict: 返回请求结果的JSON数据
        """
        baseUrl = g_pConfigManager.farm_server_url
        url = f"{baseUrl.rstrip('/')}:8998/{endpoint.lstrip('/')}"
        headers = {"token": cls.m_sTokens}

        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(url, headers=headers)

                if response.status_code == 200:
                    return response.json()
                else:
                    logger.warning(
                        f"{name}请求失败: HTTP {response.status_code} {response.text}"
                    )
                    return {}
        except httpx.RequestError as e:
            logger.warning(f"{name}请求异常", e=e)
            return {}
        except Exception as e:
            logger.warning(f"{name}处理异常", e=e)
            return {}

    # ===== 工具1：从 plant 表里拿所有作物名称 =====
    @classmethod
    async def _get_all_plant_names(cls) -> list[str]:
        try:
            plants = await g_pDBService.plant.listPlants()
            return [p["name"] for p in plants if p.get("name")]
        except Exception as e:
            logger.warning("获取作物列表失败", e=e)
            # 兜底：至少保留一组可用的
            return ["胡萝卜", "土豆", "玉米", "草莓"]

    # ===== 工具2：生成当月随机 continuou 奖励 =====
    @classmethod
    async def _generate_random_continuou(cls) -> dict:
        """
        每个月随机挑 4 种植物，但保留你原来的奖励数值
        """
        plants = await cls._get_all_plant_names()
        if not plants:
            plants = ["胡萝卜", "土豆", "玉米", "草莓"]

        # 和你原来的奖励结构一致：天数, 积分, 经验, vipPoint, 种子数量
        config_list = [
            ("7",  100,  50, 0, 2),
            ("14", 150,  80, 1, 2),
            ("21", 200, 120, 1, 3),
            ("30", 500, 200, 2, 3),
        ]

        random.shuffle(plants)
        continuou: dict[str, dict] = {}
        idx = 0

        for day, point, exp, vip, count in config_list:
            plant_name = plants[idx % len(plants)]
            idx += 1
            continuou[day] = {
                "point": point,
                "exp": exp,
                "plant": {plant_name: count},
                "vipPoint": vip,
            }

        return continuou

    # ===== 工具3：按模板创建/更新 sign_in.json（当前月份 + 随机 continuou） =====
    @classmethod
    async def _create_or_update_default_sign_file(cls) -> bool:
        year_month = g_pToolManager.dateTime().now().strftime("%Y%m")

        default_sign_data = {
            "date": year_month,
            "daily": {
                "1": {"exp": 10, "point": 30},
                "2": {"exp": 10, "point": 30},
                "3": {"exp": 12, "point": 35},
                "4": {"exp": 12, "point": 35},
                "5": {"exp": 15, "point": 40},
                "6": {"exp": 15, "point": 40},
                "7": {"exp": 20, "point": 50},
                "8": {"exp": 10, "point": 30},
                "9": {"exp": 10, "point": 30},
                "10": {"exp": 12, "point": 35},
                "11": {"exp": 12, "point": 35},
                "12": {"exp": 15, "point": 40},
                "13": {"exp": 15, "point": 40},
                "14": {"exp": 20, "point": 50},
                "15": {"exp": 12, "point": 36},
                "16": {"exp": 12, "point": 36},
                "17": {"exp": 14, "point": 42},
                "18": {"exp": 14, "point": 42},
                "19": {"exp": 16, "point": 48},
                "20": {"exp": 16, "point": 48},
                "21": {"exp": 20, "point": 55},
                "22": {"exp": 12, "point": 36},
                "23": {"exp": 12, "point": 36},
                "24": {"exp": 14, "point": 42},
                "25": {"exp": 14, "point": 42},
                "26": {"exp": 16, "point": 48},
                "27": {"exp": 16, "point": 48},
                "28": {"exp": 22, "point": 60},
                "29": {"exp": 15, "point": 40},
                "30": {"exp": 30, "point": 88},
            },
            "continuou": await cls._generate_random_continuou(),
        }

        try:
            os.makedirs(os.path.dirname(g_sSignInPath), exist_ok=True)
            with open(g_sSignInPath, "w", encoding="utf-8") as f:
                json.dump(default_sign_data, f, ensure_ascii=False, indent=2)

            logger.success(f"默认签到配置创建/更新成功: {g_sSignInPath}")
            return True
        except Exception as e:
            logger.error("创建/更新默认签到配置失败", e=e)
            return False

    @classmethod
    async def initSignInFile(cls) -> bool:
        if os.path.exists(g_sSignInPath):
            # 已存在：检查 JSON 和月份
            try:
                with open(g_sSignInPath, encoding="utf-8") as f:
                    sign = json.load(f)
            except json.JSONDecodeError:
                logger.warning("签到文件 JSON 格式错误，将重建默认配置")
                return await cls._create_or_update_default_sign_file()

            year_month = g_pToolManager.dateTime().now().strftime("%Y%m")
            date = sign.get("date", "")

            if date == year_month:
                logger.debug("本地签到文件存在且为当月，跳过更新")
                return True

            logger.info(
                f"签到文件为旧月份(date={date}, now={year_month})，将刷新为本月默认配置并随机连续奖励"
            )
            return await cls._create_or_update_default_sign_file()
        else:
            # 不存在：直接创建
            logger.warning(f"签到文件不存在 -> 自动创建默认配置: {g_sSignInPath}")
            return await cls._create_or_update_default_sign_file()

    @classmethod
    async def downloadSignInFile(cls) -> bool:
        """下载签到文件，并重命名为 sign_in.json

        Returns:
            bool: 是否下载成功
        """
        try:
            baseUrl = g_pConfigManager.farm_server_url

            url = f"{baseUrl.rstrip('/')}:8998/sign_in"
            path = str(g_sSignInPath.parent.resolve(strict=False))
            yearMonth = g_pToolManager.dateTime().now().strftime("%Y%m")

            # 下载为 signTemp.json
            success = await cls.download(
                url=url,
                savePath=path,
                fileName="signTemp.json",
                jsonData={"date": yearMonth},
            )

            if not success:
                return False

            # 重命名为 sign_in.json
            g_pToolManager.renameFile(f"{path}/signTemp.json", "sign_in.json")
            return True
        except Exception as e:
            logger.error("下载签到文件失败", e=e)
            return False

    @classmethod
    async def initPlantDBFile(cls) -> bool:
        """检查本地 plant.db 版本，如远程版本更新则重新下载

        Returns:
            bool: 是否为最新版或成功更新
        """
        versionPath = os.path.join(os.path.dirname(g_sPlantPath), "version.json")

        try:
            with open(versionPath, encoding="utf-8") as f:
                localVersion = json.load(f).get("version", 0)
        except Exception as e:
            logger.warning(f"读取本地版本失败，默认版本为0: {e}")
            localVersion = 0

        remoteInfo = await cls.get("plant_version", name="版本检查")
        remoteVersion = remoteInfo.get("version")

        if remoteVersion is None:
            logger.warning("获取远程版本失败")
            return False

        if float(remoteVersion) <= float(localVersion):
            logger.debug("plant.db 已为最新版本")
            return True

        logger.warning(
            f"发现新版本 plant.db（远程: {remoteVersion} / 本地: {localVersion}），开始更新..."
        )

        # 先断开数据库连接
        await g_pDBService.cleanup()

        return await cls.downloadPlantDBFile(remoteVersion)

    @classmethod
    async def downloadPlantDBFile(cls, remoteVersion: float) -> bool:
        """下载最新版 plant.db 并更新本地 version.json

        Args:
            remoteVersion (float): 远程版本号

        Returns:
            bool: 是否下载并更新成功
        """
        baseUrl = g_pConfigManager.farm_server_url

        savePath = os.path.dirname(g_sPlantPath)
        success = await cls.download(
            url=f"{baseUrl.rstrip('/')}:8998/file/plant.db",
            savePath=savePath,
            fileName="plantTemp.db",
        )

        if not success:
            return False

        # 重命名为 sign_in.json
        g_pToolManager.renameFile(f"{savePath}/plantTemp.db", "plant.db")

        versionPath = os.path.join(savePath, "version.json")
        try:
            with open(versionPath, "w", encoding="utf-8") as f:
                json.dump({"version": remoteVersion}, f)
            logger.debug("版本文件已更新")
        except Exception as e:
            logger.warning(f"写入版本文件失败: {e}")
            return False

        await g_pDBService.plant.init()
        await g_pDBService.plant.downloadPlant()

        return True


g_pRequestManager = CRequestManager()
