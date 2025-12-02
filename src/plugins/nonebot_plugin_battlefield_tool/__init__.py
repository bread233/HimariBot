# nonebot_plugin_battlefield_tool/__init__.py

from __future__ import annotations

from pathlib import Path
import aiohttp
import base64
from types import SimpleNamespace
from typing import Any

from nonebot import get_driver, on_command
from nonebot.adapters.onebot.v11 import (
    Message,
    MessageSegment,
)
from nonebot.params import CommandArg
from nonebot.plugin import PluginMetadata
from nonebot.rule import to_me
from nonebot.log import logger

from .config import Config, plugin_config
from .database.battlefield_database import BattleFieldDataBase
from .database.battlefield_db_service import BattleFieldDBService
from .core.plugin_logic import BattlefieldPluginLogic
from .core.api_handlers import ApiHandlers
from .core.exceptions import UserNotFoundError

__plugin_meta__ = PluginMetadata(
    name="战地风云战绩查询插件（NoneBot版）",
    description="BF4/BF1/BFV/BF2042/BF6 战绩查询、武器/载具/士兵/服务器、战报等",
    # 不带下划线的新命令名
    usage="使用 /bfstat /bfweapons /bfvehicles /bfsoldiers /bfrecent /bfservers /bfbind /bfinit /bfhelp 等命令",
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

_session: aiohttp.ClientSession | None = None
wake_prefix: list[str] = []


async def html_render(*args, **kwargs) -> str:
    """
    兼容原 AstrBot 插件调用方式的 html_render 适配层。
    当前实现：直接返回 HTML 字符串，不做截图。
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
    img_quality=plugin_config.battlefield_img_quality,
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


def make_astr_like_event(event, raw_message: str):
    """把 NoneBot 事件简单包装成 AstrBot 风格的 event，供核心逻辑复用"""

    # 对于 qq 官方 / go-cqhttp，我们这里都做一个最小适配：
    def is_private_chat() -> bool:
        # 不区分，统一按群聊处理即可
        try:
            # onebot v11 私聊通常有 user_id 没有 group_id，这里简单判断
            return getattr(event, "message_type", "") == "private"
        except Exception:
            return False

    def is_admin() -> bool:
        # TODO: 这里按你自己权限逻辑改
        return True

    def get_sender_id() -> str:
        return str(getattr(event, "user_id", "") or getattr(event, "sender_id", ""))

    def get_group_id() -> str:
        # OB11: group_id；qq 官方：guild_id / channel_id 等，这里尽量兜底
        for attr in ("group_id", "group_openid", "guild_id", "channel_id"):
            val = getattr(event, attr, None)
            if val:
                return str(val)
        return ""

    def plain_result(text: str):
        return text

    def image_result(data: Any):
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


async def _send_result_as_message_segment(result: Any) -> MessageSegment:
    """
    统一转换所有 API 返回结果为 base64 图片或文本再发送。

    规则：
    - bytes / bytearray: 当作图片二进制 → base64://...
    - str:
        - 以 base64:// 开头：直接作为图片发送
        - 以 http/https 开头：使用 _session 下载 → base64://...
        - 含 HTML：提示“未启用截图服务”
        - 其他：当作普通文本
    """
    if isinstance(result, (bytes, bytearray)):
        b64 = base64.b64encode(result).decode()
        return MessageSegment.image(f"base64://{b64}")

    if isinstance(result, str):
        lower = result.lower().strip()

        if lower.startswith("base64://"):
            return MessageSegment.image(result)

        if lower.startswith("http://") or lower.startswith("https://"):
            if not _session:
                logger.error("HTTP Session 未初始化，无法下载图片，退回 URL 文本发送。")
                return MessageSegment.text(f"[图片 URL]\n{result}")
            try:
                async with _session.get(result) as resp:
                    data = await resp.read()
                b64 = base64.b64encode(data).decode()
                logger.debug(f"图片 URL -> base64 已完成: {result}")
                return MessageSegment.image(f"base64://{b64}")
            except Exception as e:
                logger.error(f"下载 URL 图片失败: {e} → 作为文本发送")
                return MessageSegment.text(f"[图片加载失败]\n{result}")

        if lower.startswith("<html") or "</html>" in lower:
            return MessageSegment.text("⚠ 当前未启用 HTML 截图服务，无法渲染战绩图片。")

        return MessageSegment.text(result)

    logger.warning(f"未知 result 类型：{type(result)}，将以文本形式发送")
    return MessageSegment.text(str(result))


# ===== bfstat（原 bf_stat） =====
bf_stat_cmd = on_command("bfstat", rule=to_me(), priority=10, block=True)


@bf_stat_cmd.handle()
async def _(args: Message = CommandArg()):
    arg_str = args.extract_plain_text().strip()
    raw_message = f"stat {arg_str}".strip()

    # 从当前会话上下文里拿 event
    from nonebot.internal.matcher import current_event
    event = current_event.get()

    astr_event = make_astr_like_event(event, raw_message)

    request_data = await plugin_logic.handle_player_data_request(
        astr_event, ["stat"]
    )

    if request_data.error_msg:
        await bf_stat_cmd.finish(request_data.error_msg)

    try:
        if request_data.game in ["bf2042", "bf6"]:
            async for result in api_handlers.handle_btr_game(
                astr_event, request_data, "stat"
            ):
                await bf_stat_cmd.send(await _send_result_as_message_segment(result))
        else:
            async for result in api_handlers.fetch_gt_data(
                astr_event, request_data, "stat", "all"
            ):
                await bf_stat_cmd.send(await _send_result_as_message_segment(result))

    except UserNotFoundError:
        await bf_stat_cmd.finish("API查不到这个ID")


# ===== bfweapons / 武器 =====
bf_weapons_cmd = on_command("bfweapons", aliases={"武器"}, rule=to_me(), priority=10, block=True)


@bf_weapons_cmd.handle()
async def _(args: Message = CommandArg()):
    from nonebot.internal.matcher import current_event
    event = current_event.get()

    arg_str = args.extract_plain_text().strip()
    raw_message = f"weapons {arg_str}".strip()

    astr_event = make_astr_like_event(event, raw_message)
    request_data = await plugin_logic.handle_player_data_request(astr_event, ["weapons", "武器"])

    if request_data.error_msg:
        await bf_weapons_cmd.finish(request_data.error_msg)

    if request_data.game in ["bf2042", "bf6"]:
        async for result in api_handlers.handle_btr_game(astr_event, request_data, "weapons"):
            await bf_weapons_cmd.send(await _send_result_as_message_segment(result))
    else:
        async for result in api_handlers.fetch_gt_data(astr_event, request_data, "weapons", "weapons"):
            await bf_weapons_cmd.send(await _send_result_as_message_segment(result))


# ===== bfvehicles / 载具 =====
bf_vehicles_cmd = on_command("bfvehicles", aliases={"载具"}, rule=to_me(), priority=10, block=True)


@bf_vehicles_cmd.handle()
async def _(args: Message = CommandArg()):
    from nonebot.internal.matcher import current_event
    event = current_event.get()

    arg_str = args.extract_plain_text().strip()
    raw_message = f"vehicles {arg_str}".strip()

    astr_event = make_astr_like_event(event, raw_message)
    request_data = await plugin_logic.handle_player_data_request(astr_event, ["vehicles", "载具"])

    if request_data.error_msg:
        await bf_vehicles_cmd.finish(request_data.error_msg)

    if request_data.game in ["bf2042", "bf6"]:
        async for result in api_handlers.handle_btr_game(astr_event, request_data, "vehicles"):
            await bf_vehicles_cmd.send(await _send_result_as_message_segment(result))
    else:
        async for result in api_handlers.fetch_gt_data(astr_event, request_data, "vehicles", "vehicles"):
            await bf_vehicles_cmd.send(await _send_result_as_message_segment(result))


# ===== bfsoldiers / 士兵 =====
bf_soldiers_cmd = on_command("bfsoldiers", aliases={"士兵"}, rule=to_me(), priority=10, block=True)


@bf_soldiers_cmd.handle()
async def _(args: Message = CommandArg()):
    from nonebot.internal.matcher import current_event
    event = current_event.get()

    arg_str = args.extract_plain_text().strip()
    raw_message = f"soldiers {arg_str}".strip()

    astr_event = make_astr_like_event(event, raw_message)
    request_data = await plugin_logic.handle_player_data_request(astr_event, ["soldiers", "士兵"])

    if request_data.error_msg:
        await bf_soldiers_cmd.finish(request_data.error_msg)

    if request_data.game not in ["bf2042", "bf6"]:
        await bf_soldiers_cmd.finish("士兵数据查询仅支持 bf2042 / bf6")

    async for result in api_handlers.handle_btr_game(astr_event, request_data, "soldiers"):
        await bf_soldiers_cmd.send(await _send_result_as_message_segment(result))


# ===== bfrecent / 最近 / 战报 =====
bf_recent_cmd = on_command("bfrecent", aliases={"最近", "战报"}, rule=to_me(), priority=10, block=True)


@bf_recent_cmd.handle()
async def _(args: Message = CommandArg()):
    if not plugin_config.battlefield_evaluation_provider:
        await bf_recent_cmd.finish("尚未配置 evaluation_provider，无法生成战报锐评。")

    provider = plugin_config.battlefield_evaluation_provider

    from nonebot.internal.matcher import current_event
    event = current_event.get()

    arg_str = args.extract_plain_text().strip()
    raw_message = f"recent {arg_str}".strip()
    astr_event = make_astr_like_event(event, raw_message)
    request_data = await plugin_logic.handle_player_data_request(astr_event, ["recent", "最近", "战报"])

    if request_data.error_msg:
        await bf_recent_cmd.finish(request_data.error_msg)

    if request_data.game != "bf6":
        await bf_recent_cmd.finish("最近战局查询仅支持 bf6")

    async for result, next_page, total_page in api_handlers.handle_btr_matches(
        astr_event, request_data, provider
    ):
        await bf_recent_cmd.send(await _send_result_as_message_segment(result))
        if next_page:
            await bf_recent_cmd.send(
                f"可以用下面的指令翻页，当前页:{request_data.page}/{total_page}\n"
                f"{next_page}"
            )


# ===== bfservers / 服务器 =====
bf_servers_cmd = on_command("bfservers", aliases={"服务器"}, rule=to_me(), priority=10, block=True)


@bf_servers_cmd.handle()
async def _(args: Message = CommandArg()):
    from nonebot.internal.matcher import current_event
    event = current_event.get()

    arg_str = args.extract_plain_text().strip()
    raw_message = f"servers {arg_str}".strip()

    astr_event = make_astr_like_event(event, raw_message)
    request_data = await plugin_logic.handle_player_data_request(astr_event, ["servers", "服务器"])

    if request_data.error_msg:
        await bf_servers_cmd.finish(request_data.error_msg)

    if request_data.game in ["bf2042", "bf6"]:
        await bf_servers_cmd.finish("服务器查询仅支持 bf4/bf1/bfv")

    if request_data.server_name is None:
        await bf_servers_cmd.finish("服务器名称不能为空。")

    servers_data = await api_handlers.fetch_gt_servers_data(
        request_data, plugin_config.battlefield_timeout_config, _session
    )

    async for result in plugin_logic.process_api_response(
        astr_event, servers_data, "servers", request_data.game, html_render
    ):
        await bf_servers_cmd.send(await _send_result_as_message_segment(result))


# ===== bfbind / 绑定 =====
bf_bind_cmd = on_command("bfbind", aliases={"绑定"}, rule=to_me(), priority=10, block=True)


@bf_bind_cmd.handle()
async def _(args: Message = CommandArg()):
    from nonebot.internal.matcher import current_event
    event = current_event.get()

    arg_str = args.extract_plain_text().strip()
    raw_message = f"bind {arg_str}".strip()

    astr_event = make_astr_like_event(event, raw_message)
    request_data = await plugin_logic.handle_player_data_request(astr_event, ["bind", "绑定"])

    if request_data.error_msg:
        await bf_bind_cmd.finish(request_data.error_msg)

    msg = await db_service.upsert_user_bind(
        request_data.qq_id, request_data.ea_name, request_data.pider
    )
    await bf_bind_cmd.finish(msg)


# ===== bfinit =====
bf_init_cmd = on_command("bfinit", rule=to_me(), priority=10, block=True)


@bf_init_cmd.handle()
async def _(args: Message = CommandArg()):
    from nonebot.internal.matcher import current_event
    event = current_event.get()

    arg_str = args.extract_plain_text().strip()
    raw_message = f"bf_init {arg_str}".strip()

    astr_event = make_astr_like_event(event, raw_message)

    session_channel_id = plugin_logic.get_session_channel_id(astr_event)

    # 这里如果要做权限判断，可以通过 event 自己判断

    default_game = arg_str.strip()
    if not default_game:
        await bf_init_cmd.finish("请提供游戏代号，例如：bf4/bf1/bfv/bf2042/bf6")

    msg = await db_service.upsert_session_channel(
        session_channel_id, default_game
    )
    await bf_init_cmd.finish(msg)


# ===== bfhelp =====
bf_help_cmd = on_command("bfhelp", rule=to_me(), priority=10, block=True)


@bf_help_cmd.handle()
async def _():
    help_msg = f"""战地风云插件使用帮助（NoneBot 版）：
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

注: 所有命令都需要 @机器人 使用（因为 rule=to_me()）。
"""
    await bf_help_cmd.finish(help_msg)
