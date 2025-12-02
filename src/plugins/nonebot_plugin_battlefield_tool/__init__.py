# nonebot_plugin_battlefield_tool/__init__.py

from __future__ import annotations

from pathlib import Path
import aiohttp
from types import SimpleNamespace
from typing import Any

from nonebot import get_driver, on_command
from nonebot.log import logger
from nonebot.plugin import PluginMetadata
from nonebot.rule import to_me

# 这里仍然按 OneBot v11 的类型做注解，不过真正用的时候主要靠 event.get_plaintext()
from nonebot.adapters.onebot.v11 import (
    Bot,
    MessageEvent,
    GroupMessageEvent,
    PrivateMessageEvent,
    MessageSegment,
)

from .config import Config, plugin_config
from .database.battlefield_database import BattleFieldDataBase
from .database.battlefield_db_service import BattleFieldDBService
from .core.plugin_logic import BattlefieldPluginLogic
from .core.api_handlers import ApiHandlers
from .core.exceptions import UserNotFoundError

__plugin_meta__ = PluginMetadata(
    name="战地风云战绩查询插件（NoneBot版）",
    description="BF4/BF1/BFV/BF2042/BF6 战绩查询、武器/载具/士兵/服务器、战报等",
    # 新命令名（无下划线）
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

# 保持 Path
db = BattleFieldDataBase(DATA_DIR)
db_service = BattleFieldDBService(db)

_session: aiohttp.ClientSession | None = None
wake_prefix: list[str] = []


async def html_render(*args, **kwargs) -> str:
    """
    兼容原 AstrBot battlefield 插件的 html_render 调用方式。

    当前调用方式大致为：
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

    因此这里简单处理为：
      - 取第一个参数作为 HTML 字符串；
      - 直接原样返回；
      - 如果以后你要接 Playwright / 截图服务，把 HTML 渲成图片，返回图片 URL 或 base64 即可。
    """
    if not args:
        logger.error("html_render 被调用但没有传入参数")
        return ""

    html = args[0]
    if not isinstance(html, str):
        logger.error(f"html_render 第一个参数不是 str，而是 {type(html)}，args={args!r}")
        return ""

    # TODO: 将 html 渲成图片，返回图片 URL 或 base64://...
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


def make_astr_like_event(event: MessageEvent, raw_message: str):
    """把 OneBot 事件简单包装成 AstrBot 风格的 event，供核心逻辑复用"""

    def is_private_chat() -> bool:
        return isinstance(event, PrivateMessageEvent)

    def is_admin() -> bool:
        # TODO: 这里按你自己权限逻辑改
        return True

    def get_sender_id() -> str:
        return str(event.user_id)

    def get_group_id() -> str:
        if isinstance(event, GroupMessageEvent):
            return str(event.group_id)
        return ""

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


def _send_result_as_message_segment(result: Any) -> MessageSegment:
    """
    统一把 core 返回的 result 转成可发送的 MessageSegment。

    - bytes / bytearray: 当作图片二进制发送；
    - str:
        - 以 http/https/base64:// 开头：当作图片（URL 或 base64）；
        - 否则：当作普通文本。
    """
    if isinstance(result, (bytes, bytearray)):
        return MessageSegment.image(result)

    if isinstance(result, str):
        lower = result.lower()
        if lower.startswith("http://") or lower.startswith("https://") or lower.startswith("base64://"):
            return MessageSegment.image(result)
        return MessageSegment.text(result)

    # 兜底：直接转字符串发出去
    return MessageSegment.text(str(result))


def _extract_arg_from_plaintext(plain: str, cmd: str) -> str:
    """
    从纯文本里把命令参数抠出来。

    e.g. plain="/bfstat xiaomianbao,game=bf6", cmd="bfstat"
         -> "xiaomianbao,game=bf6"
    """
    plain = plain.strip()
    # 去掉前导斜杠
    if plain.startswith("/"):
        plain = plain[1:]
    if plain.lower().startswith(cmd):
        return plain[len(cmd):].strip()
    return plain


# ===== bfstat（原 bf_stat） =====
bf_stat_cmd = on_command("bfstat", rule=to_me(), priority=10, block=True)


@bf_stat_cmd.handle()
async def _(bot: Bot, event: MessageEvent):
    plain = event.get_plaintext()
    arg_str = _extract_arg_from_plaintext(plain, "bfstat")
    raw_message = f"stat {arg_str}".strip()

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
                await bf_stat_cmd.send(_send_result_as_message_segment(result))
        else:
            async for result in api_handlers.fetch_gt_data(
                astr_event, request_data, "stat", "all"
            ):
                await bf_stat_cmd.send(_send_result_as_message_segment(result))

    except UserNotFoundError:
        await bf_stat_cmd.finish("API查不到这个ID")


# ===== bfweapons / 武器（原 bf_weapons） =====
bf_weapons_cmd = on_command("bfweapons", aliases={"武器"}, rule=to_me(), priority=10, block=True)


@bf_weapons_cmd.handle()
async def _(bot: Bot, event: MessageEvent):
    plain = event.get_plaintext()
    arg_str = _extract_arg_from_plaintext(plain, "bfweapons")
    raw_message = f"weapons {arg_str}".strip()

    astr_event = make_astr_like_event(event, raw_message)
    request_data = await plugin_logic.handle_player_data_request(astr_event, ["weapons", "武器"])

    if request_data.error_msg:
        await bf_weapons_cmd.finish(request_data.error_msg)

    if request_data.game in ["bf2042", "bf6"]:
        async for result in api_handlers.handle_btr_game(astr_event, request_data, "weapons"):
            await bf_weapons_cmd.send(_send_result_as_message_segment(result))
    else:
        async for result in api_handlers.fetch_gt_data(astr_event, request_data, "weapons", "weapons"):
            await bf_weapons_cmd.send(_send_result_as_message_segment(result))


# ===== bfvehicles / 载具（原 bf_vehicles） =====
bf_vehicles_cmd = on_command("bfvehicles", aliases={"载具"}, rule=to_me(), priority=10, block=True)


@bf_vehicles_cmd.handle()
async def _(bot: Bot, event: MessageEvent):
    plain = event.get_plaintext()
    arg_str = _extract_arg_from_plaintext(plain, "bfvehicles")
    raw_message = f"vehicles {arg_str}".strip()

    astr_event = make_astr_like_event(event, raw_message)
    request_data = await plugin_logic.handle_player_data_request(astr_event, ["vehicles", "载具"])

    if request_data.error_msg:
        await bf_vehicles_cmd.finish(request_data.error_msg)

    if request_data.game in ["bf2042", "bf6"]:
        async for result in api_handlers.handle_btr_game(astr_event, request_data, "vehicles"):
            await bf_vehicles_cmd.send(_send_result_as_message_segment(result))
    else:
        async for result in api_handlers.fetch_gt_data(astr_event, request_data, "vehicles", "vehicles"):
            await bf_vehicles_cmd.send(_send_result_as_message_segment(result))


# ===== bfsoldiers / 士兵（原 bf_soldiers） =====
bf_soldiers_cmd = on_command("bfsoldiers", aliases={"士兵"}, rule=to_me(), priority=10, block=True)


@bf_soldiers_cmd.handle()
async def _(bot: Bot, event: MessageEvent):
    plain = event.get_plaintext()
    arg_str = _extract_arg_from_plaintext(plain, "bfsoldiers")
    raw_message = f"soldiers {arg_str}".strip()

    astr_event = make_astr_like_event(event, raw_message)
    request_data = await plugin_logic.handle_player_data_request(astr_event, ["soldiers", "士兵"])

    if request_data.error_msg:
        await bf_soldiers_cmd.finish(request_data.error_msg)

    if request_data.game not in ["bf2042", "bf6"]:
        await bf_soldiers_cmd.finish("士兵数据查询仅支持 bf2042 / bf6")

    async for result in api_handlers.handle_btr_game(astr_event, request_data, "soldiers"):
        await bf_soldiers_cmd.send(_send_result_as_message_segment(result))


# ===== bfrecent / 最近 / 战报（仅 bf6，原 bf_recent） =====
bf_recent_cmd = on_command("bfrecent", aliases={"最近", "战报"}, rule=to_me(), priority=10, block=True)


@bf_recent_cmd.handle()
async def _(bot: Bot, event: MessageEvent):
    if not plugin_config.battlefield_evaluation_provider:
        await bf_recent_cmd.finish("尚未配置 evaluation_provider，无法生成战报锐评。")

    provider = plugin_config.battlefield_evaluation_provider

    plain = event.get_plaintext()
    arg_str = _extract_arg_from_plaintext(plain, "bfrecent")
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
        await bf_recent_cmd.send(_send_result_as_message_segment(result))
        if next_page:
            await bf_recent_cmd.send(
                f"可以用下面的指令翻页，当前页:{request_data.page}/{total_page}\n"
                f"{next_page}"
            )


# ===== bfservers / 服务器（原 bf_servers） =====
bf_servers_cmd = on_command("bfservers", aliases={"服务器"}, rule=to_me(), priority=10, block=True)


@bf_servers_cmd.handle()
async def _(bot: Bot, event: MessageEvent):
    plain = event.get_plaintext()
    arg_str = _extract_arg_from_plaintext(plain, "bfservers")
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

    async for result in await plugin_logic.process_api_response(
        astr_event, servers_data, "servers", request_data.game, html_render
    ):
        await bf_servers_cmd.send(_send_result_as_message_segment(result))


# ===== bfbind / 绑定（原 bf_bind） =====
bf_bind_cmd = on_command("bfbind", aliases={"绑定"}, rule=to_me(), priority=10, block=True)


@bf_bind_cmd.handle()
async def _(bot: Bot, event: MessageEvent):
    plain = event.get_plaintext()
    arg_str = _extract_arg_from_plaintext(plain, "bfbind")
    raw_message = f"bind {arg_str}".strip()

    astr_event = make_astr_like_event(event, raw_message)
    request_data = await plugin_logic.handle_player_data_request(astr_event, ["bind", "绑定"])

    if request_data.error_msg:
        await bf_bind_cmd.finish(request_data.error_msg)

    msg = await db_service.upsert_user_bind(
        request_data.qq_id, request_data.ea_name, request_data.pider
    )
    await bf_bind_cmd.finish(msg)


# ===== bfinit（原 bf_init） =====
bf_init_cmd = on_command("bfinit", rule=to_me(), priority=10, block=True)


@bf_init_cmd.handle()
async def _(bot: Bot, event: MessageEvent):
    plain = event.get_plaintext()
    arg_str = _extract_arg_from_plaintext(plain, "bfinit")
    raw_message = f"bf_init {arg_str}".strip()  # 内部用字符串，随便

    astr_event = make_astr_like_event(event, raw_message)

    session_channel_id = plugin_logic.get_session_channel_id(astr_event)

    if isinstance(event, GroupMessageEvent):
        # TODO: 这里的管理员逻辑按你情况来实现
        pass

    default_game = arg_str.strip()
    if not default_game:
        await bf_init_cmd.finish("请提供游戏代号，例如：bf4/bf1/bfv/bf2042/bf6")

    msg = await db_service.upsert_session_channel(
        session_channel_id, default_game
    )
    await bf_init_cmd.finish(msg)


# ===== bfhelp（原 bf_help） =====
bf_help_cmd = on_command("bfhelp", rule=to_me(), priority=10, block=True)


@bf_help_cmd.handle()
async def _(bot: Bot, event: MessageEvent):
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

注意：所有命令都需要 @ 机器人 使用。
"""
    await bf_help_cmd.finish(help_msg)
