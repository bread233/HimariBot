# nonebot_plugin_battlefield_tool/__init__.py

from __future__ import annotations

from pathlib import Path
import aiohttp
from types import SimpleNamespace

from nonebot import get_driver, on_command
from nonebot.adapters.onebot.v11 import (
    Bot,
    MessageEvent,
    GroupMessageEvent,
    PrivateMessageEvent,
    Message,
    MessageSegment,
)
from nonebot.params import CommandArg
from nonebot.plugin import PluginMetadata
from nonebot.rule import to_me

from .config import Config, plugin_config
from .database.battlefield_database import BattleFieldDataBase
from .database.battlefield_db_service import BattleFieldDBService
from .core.plugin_logic import BattlefieldPluginLogic
from .core.api_handlers import ApiHandlers

__plugin_meta__ = PluginMetadata(
    name="战地风云战绩查询插件（NoneBot版）",
    description="BF4/BF1/BFV/BF2042/BF6 战绩查询、武器/载具/士兵/服务器、战报等",
    usage="使用 /bf_stat /bf_weapons /bf_vehicles /bf_soldiers /bf_recent /bf_servers /bf_bind /bf_init /bf_help 等命令",
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

# 保持 Path，不要转 str
db = BattleFieldDataBase(DATA_DIR)
db_service = BattleFieldDBService(db)

_session: aiohttp.ClientSession | None = None
wake_prefix: list[str] = []


async def html_render(html: str, **kwargs) -> bytes:
    # TODO: 实现 html -> 图片。这里先抛异常提醒你实现。
    raise NotImplementedError("请在 html_render 中实现 html->image 的逻辑")


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


@driver.on_shutdown
async def _shutdown():
    global _session
    if _session:
        await _session.close()
        _session = None


def make_astr_like_event(event: MessageEvent, raw_message: str):
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

    def image_result(data):
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


# ===== bf_stat =====
bf_stat_cmd = on_command("bf_stat", rule=to_me(), priority=10, block=True)


@bf_stat_cmd.handle()
async def _(bot: Bot, event: MessageEvent, args: Message = CommandArg()):
    arg_str = args.extract_plain_text().strip()
    # 注意：给 core 的 message_str 仍然用 "stat"，兼容原逻辑
    raw_message = f"stat {arg_str}".strip()

    astr_event = make_astr_like_event(event, raw_message)
    request_data = await plugin_logic.handle_player_data_request(astr_event, ["stat"])

    if request_data.error_msg:
        await bf_stat_cmd.finish(request_data.error_msg)

    if request_data.game in ["bf2042", "bf6"]:
        async for result in api_handlers.handle_btr_game(astr_event, request_data, "stat"):
            await bf_stat_cmd.send(MessageSegment.image(result))
    else:
        async for result in api_handlers.fetch_gt_data(astr_event, request_data, "stat", "all"):
            await bf_stat_cmd.send(MessageSegment.image(result))


# ===== bf_weapons / 武器 =====
bf_weapons_cmd = on_command("bf_weapons", aliases={"武器"}, rule=to_me(), priority=10, block=True)


@bf_weapons_cmd.handle()
async def _(bot: Bot, event: MessageEvent, args: Message = CommandArg()):
    arg_str = args.extract_plain_text().strip()
    raw_message = f"weapons {arg_str}".strip()

    astr_event = make_astr_like_event(event, raw_message)
    request_data = await plugin_logic.handle_player_data_request(astr_event, ["weapons", "武器"])

    if request_data.error_msg:
        await bf_weapons_cmd.finish(request_data.error_msg)

    if request_data.game in ["bf2042", "bf6"]:
        async for result in api_handlers.handle_btr_game(astr_event, request_data, "weapons"):
            await bf_weapons_cmd.send(MessageSegment.image(result))
    else:
        async for result in api_handlers.fetch_gt_data(astr_event, request_data, "weapons", "weapons"):
            await bf_weapons_cmd.send(MessageSegment.image(result))


# ===== bf_vehicles / 载具 =====
bf_vehicles_cmd = on_command("bf_vehicles", aliases={"载具"}, rule=to_me(), priority=10, block=True)


@bf_vehicles_cmd.handle()
async def _(bot: Bot, event: MessageEvent, args: Message = CommandArg()):
    arg_str = args.extract_plain_text().strip()
    raw_message = f"vehicles {arg_str}".strip()

    astr_event = make_astr_like_event(event, raw_message)
    request_data = await plugin_logic.handle_player_data_request(astr_event, ["vehicles", "载具"])

    if request_data.error_msg:
        await bf_vehicles_cmd.finish(request_data.error_msg)

    if request_data.game in ["bf2042", "bf6"]:
        async for result in api_handlers.handle_btr_game(astr_event, request_data, "vehicles"):
            await bf_vehicles_cmd.send(MessageSegment.image(result))
    else:
        async for result in api_handlers.fetch_gt_data(astr_event, request_data, "vehicles", "vehicles"):
            await bf_vehicles_cmd.send(MessageSegment.image(result))


# ===== bf_soldiers / 士兵 =====
bf_soldiers_cmd = on_command("bf_soldiers", aliases={"士兵"}, rule=to_me(), priority=10, block=True)


@bf_soldiers_cmd.handle()
async def _(bot: Bot, event: MessageEvent, args: Message = CommandArg()):
    arg_str = args.extract_plain_text().strip()
    raw_message = f"soldiers {arg_str}".strip()

    astr_event = make_astr_like_event(event, raw_message)
    request_data = await plugin_logic.handle_player_data_request(astr_event, ["soldiers", "士兵"])

    if request_data.error_msg:
        await bf_soldiers_cmd.finish(request_data.error_msg)

    if request_data.game not in ["bf2042", "bf6"]:
        await bf_soldiers_cmd.finish("士兵数据查询仅支持 bf2042 / bf6")

    async for result in api_handlers.handle_btr_game(astr_event, request_data, "soldiers"):
        await bf_soldiers_cmd.send(MessageSegment.image(result))


# ===== bf_recent / 最近 / 战报（仅 bf6） =====
bf_recent_cmd = on_command("bf_recent", aliases={"最近", "战报"}, rule=to_me(), priority=10, block=True)


@bf_recent_cmd.handle()
async def _(bot: Bot, event: MessageEvent, args: Message = CommandArg()):
    if not plugin_config.battlefield_evaluation_provider:
        await bf_recent_cmd.finish("尚未配置 evaluation_provider，无法生成战报锐评。")

    provider = plugin_config.battlefield_evaluation_provider

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
        await bf_recent_cmd.send(MessageSegment.image(result))
        if next_page:
            await bf_recent_cmd.send(
                f"可以用下面的指令翻页，当前页:{request_data.page}/{total_page}\n"
                f"{next_page}"
            )


# ===== bf_servers / 服务器 =====
bf_servers_cmd = on_command("bf_servers", aliases={"服务器"}, rule=to_me(), priority=10, block=True)


@bf_servers_cmd.handle()
async def _(bot: Bot, event: MessageEvent, args: Message = CommandArg()):
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

    async for result in await plugin_logic.process_api_response(
        astr_event, servers_data, "servers", request_data.game, html_render
    ):
        await bf_servers_cmd.send(MessageSegment.image(result))


# ===== bf_bind / 绑定 =====
bf_bind_cmd = on_command("bf_bind", aliases={"绑定"}, rule=to_me(), priority=10, block=True)


@bf_bind_cmd.handle()
async def _(bot: Bot, event: MessageEvent, args: Message = CommandArg()):
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


# ===== bf_init（本来就带 bf_，保持不变） =====
bf_init_cmd = on_command("bf_init", rule=to_me(), priority=10, block=True)


@bf_init_cmd.handle()
async def _(bot: Bot, event: MessageEvent, args: Message = CommandArg()):
    arg_str = args.extract_plain_text().strip()
    raw_message = f"bf_init {arg_str}".strip()

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


# ===== bf_help（本来就带 bf_） =====
bf_help_cmd = on_command("bf_help", rule=to_me(), priority=10, block=True)


@bf_help_cmd.handle()
async def _(bot: Bot, event: MessageEvent):
    help_msg = f"""战地风云插件使用帮助（NoneBot 版）：
1. 账号绑定
命令: /bf_bind [name] 或 /绑定 [name]

2. 默认查询设置
命令: /bf_init [游戏代号]
参数: 游戏代号 {", ".join(plugin_logic.SUPPORTED_GAMES)}

3. 战绩查询
命令: /bf_stat [name],game=[游戏代号]

4. 武器统计
命令: /bf_weapons [name],game=[游戏代号] 或 /武器 [name],game=[游戏代号]

5. 载具统计
命令: /bf_vehicles [name],game=[游戏代号] 或 /载具 [name],game=[游戏代号]

6. 士兵查询
命令: /bf_soldiers [name],game=bf2042 或 /士兵 [name],game=bf2042

7. 战报查询
命令: /bf_recent [name],game=bf6 或 /战报 [name],game=bf6

8. 服务器查询
命令: /bf_servers [server_name],game=[游戏代号] 或 /服务器 [server_name],game=[游戏代号]

注: 实际使用时不需要输入[]。
"""
    await bf_help_cmd.finish(help_msg)
