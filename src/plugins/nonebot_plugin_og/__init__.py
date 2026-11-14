from nonebot import logger, on_message
from nonebot.plugin import PluginMetadata
from nonebot.adapters.onebot.v11 import Bot, MessageEvent, MessageSegment
from nonebot_plugin_alconna import uniseg

from .utils import extract_og_url, fetch_og_image, get_og_info


__plugin_meta__ = PluginMetadata(
    name="og",
    description="仅解析白名单网页链接并发送简介及预览图",
    usage="无",
    extra={
        "Author": "mute. <mute231010@gmail.com>",
        "version": "v0.3.0",
    },
)


async def _react(event: MessageEvent, status: str) -> None:
    emoji = {"resolving": "424", "done": "144", "fail": "10060"}[status]
    try:
        await uniseg.message_reaction(emoji, message_id=uniseg.get_message_id(event))
    except Exception:
        logger.opt(exception=True).warning("OG 消息表情回应失败: {}", status)


get_og = on_message(priority=99)


@get_og.handle()
async def get_og(bot: Bot, event: MessageEvent):
    target_url = extract_og_url(event.message)
    if not target_url:
        return

    await _react(event, "resolving")
    try:
        og_info = await get_og_info(event.message)
        if not og_info or not any(og_info.get(key) for key in ("title", "description", "image")):
            raise ValueError("网页未提供可用的 OG 信息")
        title = og_info.get("title") or "未知标题"
        desc = og_info.get("description") or "未提供描述信息"
        img = og_info.get("image")
        text = f"{title}\n{desc}"
        if img:
            try:
                image_bytes = await fetch_og_image(img)
                await bot.send(event, message=MessageSegment.image(image_bytes) + f"\n{text}")
            except Exception:
                logger.opt(exception=True).warning("OG 图片下载或发送失败，尝试纯文字: {}", target_url)
                await bot.send(event, message=text)
        else:
            await bot.send(event, message=text)
    except Exception:
        logger.opt(exception=True).warning("OG 解析或发送失败: {}", target_url)
        await _react(event, "fail")
        return
    await _react(event, "done")
