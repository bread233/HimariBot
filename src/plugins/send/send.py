import time
from nonebot import on_command
from nonebot.adapters.onebot.v11 import Bot, Message, GroupMessageEvent
from nonebot.params import CommandArg
from .utils import sendtosuperuser

send = on_command('.send', priority=5)


@send.handle()
async def send_receive(bot: Bot, event: GroupMessageEvent, args: Message = CommandArg()):
    args_in = args.extract_plain_text()
    name = event.sender.nickname
    group = await bot.call_api('get_group_info', **{
        'group_id': event.group_id,
    })
    group_name = group['group_name']
    timenow = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())
    sendmsg = timenow+'\n群聊：'+group_name+'\n发送者：'+name+'\n'+args_in
    await sendtosuperuser(sendmsg)
    await send.finish('已经把意见传达给Master了喵！')
