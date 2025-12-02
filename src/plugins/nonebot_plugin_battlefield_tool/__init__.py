from __future__ import annotations

import base64
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Optional

import aiohttp
from nonebot import get_driver, on_command
from nonebot.params import CommandArg
from nonebot.plugin import PluginMetadata
from nonebot.rule import to_me
from nonebot.log import logger

# 适配多协议：只在需要的地方做 isinstance 判断
from nonebot.adapters.onebot.v11 import Bot as OB11Bot, MessageSegment as OB11MS

# QQ 官方适配器：可选导入
try:
    from nonebot.adapters.qq import (
        Bot as QQBot,
        Message as QQMessage,
        MessageSegment as QQMS,
    )
except Exception:
    QQBot = None      # type: ignore
    QQMessage = None  # type: ignore
    QQMS = None       # type: ignore

from .config import Config, plugin_config
from .database.battlefield_database import BattleFieldDataBase
from .database.battlefield_db_service import BattleFieldDBService
from .core.plugin_logic import BattlefieldPluginLogic
from .core.api_handlers import ApiHandlers
from .core.exceptions import UserNotFoundError

__plugin_meta__ = PluginMetadata(
    name="战地风云战绩查询插件（NoneBot版）",
    description="BF4/BF1/BFV/BF2042/BF6 战绩查询、武器/载具/士兵/服务器、战报等",
    usage="使用 /bfstat /bfweapons /bfvehicles /bfsoldiers /bfrecent /bfservers /bfbind /bfinit /bfhelp 等命令（需 @ 机器人）",
    config=Config,
    extra={
        "author": "SHOOTING_STAR_C (NoneBot 适配 by bread233)",
        "version": "v2.1.3-nb",
        "homepage": "https://github.com/SHOOTING-STAR-C/astrbot_plugin_battlefield_tool",
    },
)

driver = get_driver()

DATA_DIR = Path() / "data" / "nonebot_plugin_battlefield_tool"
DATA_DIR.mkdir(parents=True, exist_ok=True)

db = BattleFieldDataBase(DATA_DIR)
db_service = BattleFieldDBService(db)

_session: Optional[aiohttp.ClientSession] = None
wake_prefix: list[str] = []


async def html_render(*args, **kwargs) -> str:
    """
    兼容原 AstrBot 插件调用方式的 html_render 适配层。

    当前各处调用大致为：
        html = await html_builder_func(...)
        url  = await html_render_func(
            html,
            {},
            True,
            {
                "timeout": 10000,
                "quality": self.img_quality,
                "clip": {...},
            },
        )

    这里暂时直接返回第一个参数的 HTML 字符串。
    如后续需要接入截图服务，在这里把 HTML 渲成图片并返回 URL 即可。
    """
    if not args:
        logger.error("html_render 被调用但没有传入参数")
        return ""

    html = args[0]
    if not isinstance(html, str):
        logger.error(f"html_render 第一个参数不是 str，而是 {type(html)}，args={args!r}")
        return ""

    return html


plugin_logic = BattlefieldPluginLogic(
    db_service=db_service,
    default_game=plugin_config.battlefield_default_game,
    timeout_config=plugin_config.battlefield_timeout_config,
    img_quality=plugin_config.battlefield_img_quality or 70,
    session=None,
    bf_prompt=plugin_config.battlefield_bf_prompt,
    default_platform="pc",
)

api_handlers = ApiHandlers(
    plugin_logic=plugin_logic,
    html_render=html_render,
    timeout_config=plugin_config.battlefield_timeout_config,
    ssc_token=plugin_config.battlefield_ssc_token,
    session=None,
    wake_prefix=wake_prefix,
)


@driver.on_startup
async def _startup():
    global _session
    _session = aiohttp.ClientSession()
    await db.initialize()
    plugin_logic._session = _session
    api_handlers._session = _session
    logger.info("nonebot_plugin_battlefield_tool 启动完成，数据库和 HTTP Session 已初始化")


@driver.on_shutdown
async def _shutdown():
    global _session
    if _session:
        await _session.close()
        _session = None
        logger.info("nonebot_plugin_battlefield_tool 已关闭 HTTP Session")


def _get_sender_id_generic(event: Any) -> str:
    """
    同时兼容 OneBot v11 + QQ 官方事件的发送者 ID 获取。
    只是当作数据库 key 用，不要求绝对准确。
    """
    # OneBot v11
    uid = getattr(event, "user_id", None)
    if uid is not None:
        return str(uid)

    # QQ 官方适配器：author.id / author.user_openid 等
    author = getattr(event, "author", None)
    if author is not None:
        for attr in ("user_openid", "id"):
            v = getattr(author, attr, None)
            if v is not None:
                return str(v)

    return ""


def _get_group_id_generic(event: Any) -> str:
    # OneBot v11
    gid = getattr(event, "group_id", None)
    if gid is not None:
        return str(gid)

    # QQ 官方适配器：group_openid
    gid = getattr(event, "group_openid", None)
    if gid is not None:
        return str(gid)

    return ""


def make_astr_like_event(event: Any, raw_message: str):
    """把任意适配器的事件简单包装成 AstrBot 风格 event，供核心逻辑复用"""

    def is_private_chat() -> bool:
        # 我们只真正支持群，用不到私聊，这里一律 False
        return False

    def is_admin() -> bool:
        # TODO: 这里按你自己权限逻辑改
        return True

    def get_sender_id() -> str:
        return _get_sender_id_generic(event)

    def get_group_id() -> str:
        return _get_group_id_generic(event)

    def plain_result(text: str):
        return text

    def image_result(data: Any):
        # 原 AstrBot 里这里一般是返回图片 URL，这里先原样透传
        return data

    return SimpleNamespace(
        message_str=raw_message,
        is_private_chat=is_private_chat,
        is_admin=is_admin,
        get_sender_id=get_sender_id,
        get_group_id=get_group_id,
        plain_result=plain_result,
        image_result=image_result,
    )


async def _fetch_bytes(url: str) -> Optional[bytes]:
    """从 URL 下载图片字节，用于把 URL 转换为 base64."""
    global _session
    sess = _session or aiohttp.ClientSession()
    try:
        async with sess.get(url, timeout=15) as resp:
            if resp.status == 200:
                return await resp.read()
            logger.error(f"下载图片失败: {url}, status={resp.status}")
    except Exception as e:
        logger.error(f"下载图片异常: {url}, err={e}")
    return None


async def _result_to_image_bytes(result: Any) -> Optional[bytes]:
    """
    把 core 返回的各种结果统一转换成图片字节：
    - bytes / bytearray: 直接用
    - str:
        - base64://xxxx  => decode
        - http(s)://...  => 下载
        - 其它            => 非图片，返回 None
    """
    if isinstance(result, (bytes, bytearray)):
        return bytes(result)

    if isinstance(result, str):
        lower = result.lower()
        if lower.startswith("base64://"):
            try:
                return base64.b64decode(result[9:])
            except Exception as e:
                logger.error(f"base64 解码失败: {e}")
                return None
        if lower.startswith("http://") or lower.startswith("https://"):
            return await _fetch_bytes(result)

    return None


async def _send_result(bot: Any, event: Any, result: Any):
    try:
        # ===== QQ 适配器：优先直接用 URL 发送 =====
        if QQBot is not None and QQMS is not None and isinstance(bot, QQBot):
            if isinstance(result, str) and result.lower().startswith(("http://", "https://")):
                seg = QQMS.image(result)
                await bot.send(event, seg)
                return

        img_bytes = await _result_to_image_bytes(result)

        if img_bytes is not None:
            b64 = base64.b64encode(img_bytes).decode("ascii")

            if isinstance(bot, OB11Bot):
                seg = OB11MS.image(f"base64://{b64}")
                await bot.send(event, seg)
                return

            if QQBot is not None and QQMS is not None and isinstance(bot, QQBot):
                seg = QQMS.file_image(img_bytes)
                await bot.send(event, seg)
                return

            await bot.send(event, "[图片消息，当前适配器未专门适配，已丢弃]")
            return

        # 文本消息（→ 原来的 283 行）
        await bot.send(event, str(result))

    except Exception as e:
        # 额外打印调试信息
        logger.error(
            f"发送战地结果失败: bot={type(bot)}, "
            f"event={type(event)}, "
            f"result_type={type(result)}, "
            f"preview={str(result)[:200]!r}"
        )


# ===================== 命令实现 =====================
# 说明：为兼容两个适配器，这里不对 bot/event 做类型注解；
# CommandArg 默认是适配器 Message，这里做一层兼容转 str。


def _normalize_args(args: Any) -> str:
    """把 CommandArg 注入的各种类型统一转成字符串"""
    if args is None:
        return ""
    if isinstance(args, str):
        return args
    # 适配器 Message，一般有 extract_plain_text
    extract = getattr(args, "extract_plain_text", None)
    if callable(extract):
        try:
            return extract()
        except Exception:
            pass
    # 兜底：直接 str
    return str(args)


# ===== bfstat（原 bf_stat） =====
bf_stat_cmd = on_command("bfstat", rule=to_me(), priority=10, block=True)


@bf_stat_cmd.handle()
async def _(bot, event, args: Any = CommandArg()):
    arg_str = _normalize_args(args).strip()
    raw_message = f"stat {arg_str}".strip()

    astr_event = make_astr_like_event(event, raw_message)
    request_data = await plugin_logic.handle_player_data_request(astr_event, ["stat"])

    if request_data.error_msg:
        await bf_stat_cmd.finish(request_data.error_msg)

    try:
        if request_data.game in ["bf2042", "bf6"]:
            async for result in api_handlers.handle_btr_game(
                astr_event, request_data, "stat"
            ):
                await _send_result(bot, event, result)
        else:
            async for result in api_handlers.fetch_gt_data(
                astr_event, request_data, "stat", "all"
            ):
                await _send_result(bot, event, result)

    except UserNotFoundError:
        await bf_stat_cmd.finish("API查不到这个ID")


# ===== bfweapons / 武器 =====
bf_weapons_cmd = on_command("bfweapons", aliases={"武器"}, rule=to_me(), priority=10, block=True)


@bf_weapons_cmd.handle()
async def _(bot, event, args: Any = CommandArg()):
    arg_str = _normalize_args(args).strip()
    raw_message = f"weapons {arg_str}".strip()

    astr_event = make_astr_like_event(event, raw_message)
    request_data = await plugin_logic.handle_player_data_request(
        astr_event, ["weapons", "武器"]
    )

    if request_data.error_msg:
        await bf_weapons_cmd.finish(request_data.error_msg)

    if request_data.game in ["bf2042", "bf6"]:
        async for result in api_handlers.handle_btr_game(
            astr_event, request_data, "weapons"
        ):
            await _send_result(bot, event, result)
    else:
        async for result in api_handlers.fetch_gt_data(
            astr_event, request_data, "weapons", "weapons"
        ):
            await _send_result(bot, event, result)


# ===== bfvehicles / 载具 =====
bf_vehicles_cmd = on_command("bfvehicles", aliases={"载具"}, rule=to_me(), priority=10, block=True)


@bf_vehicles_cmd.handle()
async def _(bot, event, args: Any = CommandArg()):
    arg_str = _normalize_args(args).strip()
    raw_message = f"vehicles {arg_str}".strip()

    astr_event = make_astr_like_event(event, raw_message)
    request_data = await plugin_logic.handle_player_data_request(
        astr_event, ["vehicles", "载具"]
    )

    if request_data.error_msg:
        await bf_vehicles_cmd.finish(request_data.error_msg)

    if request_data.game in ["bf2042", "bf6"]:
        async for result in api_handlers.handle_btr_game(
            astr_event, request_data, "vehicles"
        ):
            await _send_result(bot, event, result)
    else:
        async for result in api_handlers.fetch_gt_data(
            astr_event, request_data, "vehicles", "vehicles"
        ):
            await _send_result(bot, event, result)


# ===== bfsoldiers / 士兵（仅 2042 / 6） =====
bf_soldiers_cmd = on_command("bfsoldiers", aliases={"士兵"}, rule=to_me(), priority=10, block=True)


@bf_soldiers_cmd.handle()
async def _(bot, event, args: Any = CommandArg()):
    arg_str = _normalize_args(args).strip()
    raw_message = f"soldiers {arg_str}".strip()

    astr_event = make_astr_like_event(event, raw_message)
    request_data = await plugin_logic.handle_player_data_request(
        astr_event, ["soldiers", "士兵"]
    )

    if request_data.error_msg:
        await bf_soldiers_cmd.finish(request_data.error_msg)

    if request_data.game not in ["bf2042", "bf6"]:
        await bf_soldiers_cmd.finish("士兵数据查询仅支持 bf2042 / bf6")

    async for result in api_handlers.handle_btr_game(
        astr_event, request_data, "soldiers"
    ):
        await _send_result(bot, event, result)


# ===== bfrecent / 战报（仅 bf6） =====
bf_recent_cmd = on_command("bfrecent", aliases={"最近", "战报"}, rule=to_me(), priority=10, block=True)


@bf_recent_cmd.handle()
async def _(bot, event, args: Any = CommandArg()):
    if not plugin_config.battlefield_evaluation_provider:
        await bf_recent_cmd.finish("尚未配置 evaluation_provider，无法生成战报锐评。")

    provider = plugin_config.battlefield_evaluation_provider

    arg_str = _normalize_args(args).strip()
    raw_message = f"recent {arg_str}".strip()

    astr_event = make_astr_like_event(event, raw_message)
    request_data = await plugin_logic.handle_player_data_request(
        astr_event, ["recent", "最近", "战报"]
    )

    if request_data.error_msg:
        await bf_recent_cmd.finish(request_data.error_msg)

    if request_data.game != "bf6":
        await bf_recent_cmd.finish("最近战局查询仅支持 bf6")

    async for result, next_page, total_page in api_handlers.handle_btr_matches(
        astr_event, request_data, provider
    ):
        await _send_result(bot, event, result)
        if next_page:
            await bf_recent_cmd.send(
                f"可以用下面的指令翻页，当前页:{request_data.page}/{total_page}\n{next_page}"
            )


# ===== bfservers / 服务器 =====
bf_servers_cmd = on_command("bfservers", aliases={"服务器"}, rule=to_me(), priority=10, block=True)


@bf_servers_cmd.handle()
async def _(bot, event, args: Any = CommandArg()):
    arg_str = _normalize_args(args).strip()
    raw_message = f"servers {arg_str}".strip()

    astr_event = make_astr_like_event(event, raw_message)
    request_data = await plugin_logic.handle_player_data_request(
        astr_event, ["servers", "服务器"]
    )

    if request_data.error_msg:
        await bf_servers_cmd.finish(request_data.error_msg)

    if request_data.game in ["bf2042", "bf6"]:
        await bf_servers_cmd.finish("服务器查询仅支持 bf4/bf1/bfv")

    if request_data.server_name is None:
        await bf_servers_cmd.finish("服务器名称不能为空。")

    servers_data = await api_handlers.fetch_gt_servers_data(
        request_data, plugin_config.battlefield_timeout_config, _session
    )

    async for result in await plugin_logic.process_api_response(
        astr_event, servers_data, "servers", request_data.game, html_render
    ):
        await _send_result(bot, event, result)


# ===== bfbind / 绑定 =====
bf_bind_cmd = on_command("bfbind", aliases={"绑定"}, rule=to_me(), priority=10, block=True)


@bf_bind_cmd.handle()
async def _(bot, event, args: Any = CommandArg()):
    arg_str = _normalize_args(args).strip()
    raw_message = f"bind {arg_str}".strip()

    astr_event = make_astr_like_event(event, raw_message)
    request_data = await plugin_logic.handle_player_data_request(
        astr_event, ["bind", "绑定"]
    )

    if request_data.error_msg:
        await bf_bind_cmd.finish(request_data.error_msg)

    msg = await db_service.upsert_user_bind(
        request_data.qq_id, request_data.ea_name, request_data.pider
    )
    await bf_bind_cmd.finish(msg)


# ===== bfinit / 设置默认游戏 =====
bf_init_cmd = on_command("bfinit", rule=to_me(), priority=10, block=True)


@bf_init_cmd.handle()
async def _(bot, event, args: Any = CommandArg()):
    arg_str = _normalize_args(args).strip()
    raw_message = f"bf_init {arg_str}".strip()

    astr_event = make_astr_like_event(event, raw_message)
    session_channel_id = plugin_logic.get_session_channel_id(astr_event)

    default_game = arg_str.strip()
    if not default_game:
        await bf_init_cmd.finish("请提供游戏代号，例如：bf4/bf1/bfv/bf2042/bf6")

    msg = await db_service.upsert_session_channel(session_channel_id, default_game)
    await bf_init_cmd.finish(msg)


# ===== bfhelp / 帮助 =====
bf_help_cmd = on_command("bfhelp", rule=to_me(), priority=10, block=True)


@bf_help_cmd.handle()
async def _(bot, event):
    help_msg = f"""战地风云插件使用帮助：
1. 账号绑定
命令: /bfbind [name] 或 /绑定 [name]

2. 默认查询设置
命令: /bfinit [游戏代号]
参数: 游戏代号 {", ".join(plugin_logic.SUPPORTED_GAMES)}

3. 战绩查询
命令: /bfstat [name],game=[游戏代号]

4. 武器统计
命令: /bfweapons [name],game=[游戏代号] 或 /武器 [name],game=[游戏代号]

5. 载具统计
命令: /bfvehicles [name],game=[游戏代号] 或 /载具 [name],game=[游戏代号]

6. 士兵查询
命令: /bfsoldiers [name],game=bf2042 或 /士兵 [name],game=bf2042

7. 战报查询
命令: /bfrecent [name],game=bf6 或 /战报 [name],game=bf6

8. 服务器查询
命令: /bfservers [server_name],game=[游戏代号] 或 /服务器 [server_name],game=[游戏代号]

※ 所有命令都需要 @机器人 使用
"""
    await bf_help_cmd.finish(help_msg)
