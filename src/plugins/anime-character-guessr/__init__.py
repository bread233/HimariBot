import nonebot
import re
import requests
from nonebot.log import logger
from nonebot.adapters import Bot
from nonebot import on_command
from nonebot.plugin import PluginMetadata
from nonebot.params import CommandArg, RawCommand
from nonebot.adapters.onebot.v11 import Message, MessageSegment, Event
from nonebot.rule import to_me
from .character import decrypt_character_js_style
from typing import Optional

Bot_NICKNAME = set(nonebot.get_driver().config.nickname)
apikey = 'xmb1236987'
api_url = "https://anime-character-guessr.superbread.uk/api/answer"

__plugin_name__ = 'anime-character-guessr'
__plugin_version__ = '0.1.0'
__plugin_meta__ = PluginMetadata(
    name=__plugin_name__,
    description="anime-character-guessr获取答案",
    usage="指令表：\n/acg 房间链接",
    extra={
        "License": "MIT",
        "Author": "xmb233",
        "version": __plugin_version__,
    },
)

def extract_room_id(link: str) -> Optional[str]:
    match = re.search(r'/multiplayer/([a-f0-9\-]+)', link)
    return match.group(1) if match else None

acg_matcher = on_command("anime-character-guessr", aliases={"/acg"}, priority=5)

@acg_matcher.handle()
async def acg_(bot: Bot, event: Event, args: Message = CommandArg(), cmd: Message = RawCommand()):
    if event.message_type != 'group':
        return

    try:
        user_input = args.extract_plain_text().strip()
        links = user_input.split()
        if len(links) != 1:
            return await acg_matcher.send("参数给多(少)了或者多打空格了\n具体使用方法:/acg 房间链接", at_sender=True)

        roomid = extract_room_id(links[0])
        if not roomid:
            return await acg_matcher.send("无法解析房间号，请检查链接是否正确", at_sender=True)

        payload = {
            "key": apikey,
            "roomId": roomid
        }

        response = requests.post(api_url, json=payload, timeout=5)
        response.raise_for_status()  # 自动抛出错误请求异常

        data = response.json()
        encrypted_character = data.get("character")
        if not encrypted_character:
            return await acg_matcher.send("没有获取到加密角色数据", at_sender=True)

        character = decrypt_character_js_style(encrypted_character)
        if not character:
            return await acg_matcher.send("解密失败，可能是密钥或格式问题", at_sender=True)

        name = character.get("name", "未知角色")
        img_url = character.get("images", {}).get("medium", "")

        msg = f"答案角色：{name}"
        if img_url:
            msg += MessageSegment.image(img_url)

        await acg_matcher.send(msg, at_sender=True)

    except requests.Timeout:
        return await acg_matcher.send("请求超时，请稍后再试", at_sender=True)
    except Exception as e:
        logger.exception(f"获取答案出错: {e}")
        return await acg_matcher.send("出错啦！请稍后重试", at_sender=True)
