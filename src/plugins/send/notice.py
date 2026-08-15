from nonebot import on_command
from nonebot.permission import SUPERUSER
from nonebot.adapters.onebot.v11 import Bot, PrivateMessageEvent
import asyncio

notice = on_command('.notice', priority=5, permission=SUPERUSER)


@notice.handle()
async def notice_receive(bot: Bot, event: PrivateMessageEvent):
    message = event.raw_message.replace('.notice', '', 1).strip().strip('\n')
    grouplist = await bot.call_api('get_group_list')
    await notice.send('通知正在传达喵！')
    for group in grouplist:
        await bot.call_api('send_group_msg', **{
            'message': message,
            'group_id': group['group_id'],
        })
        await asyncio.sleep(5)
    await notice.finish('通知已经传达完毕了喵！')
