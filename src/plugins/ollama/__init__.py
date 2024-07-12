import base64
import httpx
import json
from io import BytesIO
from typing import Union

from PIL import Image
from nonebot import on_message
from nonebot.adapters.onebot.v11 import Message, Bot, Event
from nonebot.log import logger
from nonebot.rule import to_me
from ollama import AsyncClient

client = AsyncClient(host='http://192.168.0.125:11434')

ai = on_message(rule=to_me())


@ai.handle()
async def _(bot: Bot, event: Event):
    if not (event.message_type == 'group'):
        return

    images = get_message_image(event.json())
    image_base64 = []
    if have_image(images):
        for image_url in images:
            image_base64.append(await pic2b64(image_url))

    template = '''
    我希望你扮演一个名叫上原绯玛丽的女子乐队贝斯手，别称为绯玛丽或者肥玛丽，她来自日本公司Bushiroad的企划BanG Dream! 
    上原绯玛丽是乐队Afterglow的一员，尽管她身材有点小胖，但她充满元气和热情。她以细腻的贝斯演奏和与乐队成员的默契配合而闻名。
    作为乐队中的贝斯手，她负责稳定的节奏和与其他乐器的和谐协调，确保每场演出都充满动感和活力。
    在舞台上，上原绯玛丽展现出她独特的魅力和对音乐的深厚理解，无论是与主唱美竹兰的合声，还是与键盘手羽泽鸫的华丽对位，都能给观众留下深刻印象。
    她的目标是通过音乐传递快乐和正能量，成为乐迷心中永不磨灭的存在。
    在你不知道答案的情况下只需要回答不知道。
    而我只是你的一个朋友。
    '''
    if len(image_base64) > 0:
        response = await client.generate(model='qwen2:1.5b',
                                         prompt=str(event.get_message()),
                                         images=image_base64
                                         )
        msg = str(response['response'])
    else:
        response = await client.chat(model='qwen2:1.5b', messages=[
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
        logger.error(msg)
        await ai.finish(message=Message("回复失败"), at_sender=True)
    else:
        await ai.finish(message=Message(msg), at_sender=True)


def get_message_image(data: Union[str, dict]) -> "list":
    """
    返回一个包含消息中所有图片文件路径的list,

    Args :
          * ``data: str`` : 消息内容, 来自event.json()
          * ``type: Literal['file','url']``: 当``type``为``'file'``时, 返回的是文件路径, 当``type``为``'url'``时, 返回的是url

    Return :
          * ``img_list: list`` : 包含图片绝对路径或url的list
    """
    if isinstance(data, str):
        data = json.loads(data)
    return [message['data']['url'] for message in data['message'] if message['type'] == 'image']


def have_image(images: list) -> bool:
    return len(images) > 0


async def pic2b64(pic_url) -> str:
    pic = Image.open(BytesIO(await download_url(pic_url)))
    buf = BytesIO()
    pic.save(buf, format='PNG')
    base64_str = base64.b64encode(buf.getvalue()).decode()
    return base64_str


async def download_url(url: str) -> bytes:
    async with httpx.AsyncClient() as client_:
        for i in range(3):
            try:
                resp = await client_.get(url)
                if resp.status_code != 200:
                    continue
                return resp.content
            except Exception as e:
                print(f"Error downloading {url}, retry {i}/3: {str(e)}")
