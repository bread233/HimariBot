import traceback

from nonebot import on_command
from nonebot.adapters import Bot, Event
from nonebot.adapters.onebot.v11 import GroupMessageEvent, MessageSegment
from nonebot.log import logger
from nonebot.typing import T_State

from .ascii2d import Ascii2D
from .config import saucenao_api_key, search_proxy
from .saucenao import SauceNao
from .utils import get_message_image


logger.warning(f"PROXY: {search_proxy}")
logger.warning(f"S_API configured: {bool(saucenao_api_key)}")

Search = on_command("search", aliases={"搜图"})


def have_image(images: list) -> bool:
    return len(images) > 0


def _format_dict(data: dict) -> str:
    return "\n".join(f"{k}: {v}" for k, v in data.items())


def _make_reply(event: Event, text: str):
    return MessageSegment.reply(event.message_id) + MessageSegment.text(text)


def _make_ascii2d_content(item: dict, thumbnail=None):
    content = MessageSegment.text(_format_dict(item))
    if thumbnail:
        content += MessageSegment.image(thumbnail)
    return content


saucenao = SauceNao(saucenao_api_key, search_proxy)
ascii2d = Ascii2D(search_proxy)


@Search.handle()
async def search(bot: Bot, event: Event, state: T_State):
    try:
        images = get_message_image(event.json())

        if not have_image(images):
            await bot.send(event, "现在的搜图功能为 搜图直接跟图片 不需要at")
            return

        for image in images:
            logger.info(f'imgsearch: search -> "{image}"')

            logger.info("SauceNAO: searching...")
            await bot.send(event, "SauceNAO: searching...")

            res_sauce = await saucenao.search(image)
            sauce_status_group = res_sauce.status_code // 100

            if sauce_status_group == 2:
                logger.info(f"SauceNAO: hit on {res_sauce.content['rate']}")

                res_text = (
                    f"[ {res_sauce.content['index']} / {res_sauce.content['rate']} ]\n"
                    + _format_dict(res_sauce.content["data"])
                )
                await bot.send(event, _make_reply(event, res_text))
                continue

            if sauce_status_group == 4:
                logger.error(f"SauceNAO: {res_sauce.message}")
                await bot.send(
                    event,
                    _make_reply(event, res_sauce.message or "SauceNAO搜索失败"),
                )
                continue

            if sauce_status_group != 3:
                logger.warning(
                    f"SauceNAO: unexpected status={res_sauce.status_code} message={res_sauce.message}"
                )
                await bot.send(
                    event,
                    _make_reply(event, res_sauce.message or "SauceNAO返回了未知状态"),
                )
                continue

            logger.info("SauceNAO: not found")
            logger.info("Ascii2D: searching...")
            await bot.send(event, "SauceNAO: not found\nAscii2D: searching...")

            res_ascii = await ascii2d.search(image)
            ascii_status_group = res_ascii.status_code // 100

            if ascii_status_group == 2:
                if isinstance(res_ascii.content, dict):
                    message = _make_reply(event, _format_dict(res_ascii.content))
                else:
                    message = _make_reply(
                        event,
                        res_ascii.message or "Ascii2D找到了结果，但返回内容格式异常",
                    )
                await bot.send(event, message)
                continue

            if ascii_status_group == 3:
                # Ascii2D 可能返回 ACTION_WARNING 但 content=None，
                # 比如 HTTP 403、无可用结果等。这里必须先判断 content。
                if not isinstance(res_ascii.content, list) or len(res_ascii.content) < 2:
                    logger.info(f"Ascii2D: {res_ascii.message}")
                    await bot.send(
                        event,
                        _make_reply(
                            event,
                            res_ascii.message or "Ascii2D没有找到可用结果",
                        ),
                    )
                    continue

                logger.info("Ascii2D: sending possible results...")

                nodes = []

                if len(res_ascii.content) >= 2 and isinstance(res_ascii.content[0], dict):
                    content_1 = _make_ascii2d_content(
                        res_ascii.content[0],
                        res_ascii.content[1],
                    )
                    nodes.append(
                        {
                            "type": "node",
                            "data": {
                                "name": "搜图",
                                "uin": event.self_id,
                                "content": content_1,
                            },
                        }
                    )

                if len(res_ascii.content) >= 4 and isinstance(res_ascii.content[2], dict):
                    content_2 = _make_ascii2d_content(
                        res_ascii.content[2],
                        res_ascii.content[3],
                    )
                    nodes.append(
                        {
                            "type": "node",
                            "data": {
                                "name": "搜图",
                                "uin": event.self_id,
                                "content": content_2,
                            },
                        }
                    )

                if not nodes:
                    await bot.send(
                        event,
                        _make_reply(
                            event,
                            res_ascii.message or "Ascii2D没有找到可用结果",
                        ),
                    )
                    continue

                if isinstance(event, GroupMessageEvent):
                    await bot.send_group_forward_msg(
                        group_id=event.group_id,
                        messages=nodes,
                    )
                else:
                    for node in nodes:
                        await bot.send(event, node["data"]["content"])

                continue

            if ascii_status_group == 4:
                logger.info(f"Ascii2D: {res_ascii.message}")
                await bot.send(
                    event,
                    _make_reply(event, res_ascii.message or "Ascii2D搜索失败"),
                )
                continue

            logger.warning(
                f"Ascii2D: unexpected status={res_ascii.status_code} message={res_ascii.message}"
            )
            await bot.send(
                event,
                _make_reply(event, res_ascii.message or "Ascii2D返回了未知状态"),
            )

    except Exception as e:
        logger.error(f"Error: {traceback.format_exc()}")
        message = _make_reply(event, f"你说得对，但是出错了。({e})")
        await bot.send(event, message)