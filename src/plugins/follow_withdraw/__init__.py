from typing import Any, List, Optional

from nonebot.typing import T_State
from nonebot.permission import SUPERUSER
from nonebot import on_notice, on_command
from nonebot.plugin import PluginMetadata
from nonebot.internal.matcher import current_event, current_matcher
from nonebot.log import logger
from nonebot.adapters.onebot.v11 import (
    Bot,
    GroupRecallNoticeEvent,
)
from .utils import (
    get_origin_message_fromdb,
    save_message,
    clear_message,
    get_follow_message_fromdb,
    delete_message,
)


__plugin_meta__ = PluginMetadata(
    name="follow_withdraw",
    description="当命令消息被撤回时，Bot跟随撤回命令结果",
    usage="被动跟随消息并撤回",
    type="application",
    homepage="已修改为bread233自用插件",
    supported_adapters={
        "~onebot.v11",
        "~onebot.v12",
        "~qqguild",
        # "~discord",
        "~kaiheila",
    },
)


withdraw_notice = on_notice(priority=5)
clear_cmd = on_command("清除消息记录", priority=5, permission=SUPERUSER)


@withdraw_notice.handle()
async def handle_withdraw(bot: Bot, event: GroupRecallNoticeEvent):
    try:
        if str(event.user_id) != str(bot.self_id):
            o_mid = event.message_id
            o_mids = await get_origin_message_fromdb(o_mid)
            if o_mids is None:
                return
            f_mids = await get_follow_message_fromdb(o_mid)
            if f_mids is None:
                return
            for f_mid in f_mids:
                await bot.delete_msg(message_id=f_mid)
            await delete_message(o_mid, f_mids)
    except:
        import traceback

        logger.error(traceback.print_exc())


@clear_cmd.handle()
async def handle_clear_message():
    await clear_message()
    await clear_cmd.finish("清除完成")


@Bot.on_called_api
async def handle_save_message(
    bot: Bot, exception: Optional[Exception], api: str, data: Any, result: Any
):
    if exception:
        return
    adapter_name = bot.adapter.get_name()
    try:
        event = current_event.get()
    except LookupError:
        return

    if (result) and (event):
        event = str(event.__str__)
        logger.info(event)
        event = event.split("message_id=")
        event = event[1].split(",")
        event = event[0]
        event = dict(message_id=event)
        await save_message(adapter_name, event, result)
