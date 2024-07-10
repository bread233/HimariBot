from nonebot import on_message
from nonebot.adapters.onebot.v11 import Message, MessageEvent, Bot, Event
from nonebot.log import logger
from nonebot.rule import to_me
from ollama import Client

client = Client(host='http://192.168.0.125:11434')

ai = on_message(rule=to_me())
@ai.handle()
async def _(bot: Bot, event: Event):

    if not (event.message_type == 'group') :
        return

    template = '''
    我希望你扮演一个名叫上原绯玛丽的女子乐队贝斯手，别称为绯玛丽或者肥玛丽，她来自日本公司Bushiroad的企划BanG Dream! 
    上原绯玛丽是乐队Afterglow的一员，尽管她身材有点小胖，但她充满元气和热情。她以细腻的贝斯演奏和与乐队成员的默契配合而闻名。
    作为乐队中的贝斯手，她负责稳定的节奏和与其他乐器的和谐协调，确保每场演出都充满动感和活力。
    在舞台上，上原绯玛丽展现出她独特的魅力和对音乐的深厚理解，无论是与主唱美竹兰的合声，还是与键盘手羽泽鸫的华丽对位，都能给观众留下深刻印象。
    她的目标是通过音乐传递快乐和正能量，成为乐迷心中永不磨灭的存在。
    在你不知道答案的情况下只需要回答不知道。
    而我只是你的一个朋友。
    '''

    response = client.chat(model='qwen:0.5b', messages=[
        {
            'role': 'system',
            'content': str(template),
        },
        {
            'role': 'user',
            'content': str(event.get_message()),
        },
    ])

    msg = str(response['message']['content'])
    if msg == "" or msg is None:
        logger(msg)
        await ai.finish(message=Message("回复失败"), at_sender=True)
    else:
        await ai.finish(message=Message(msg), at_sender=True)