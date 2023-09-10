from src.utils.sql import DBManage
from nonebot.log import logger


follow_withdraw = DBManage("follow_withdraw.db")

OriginMessage = "OriginMessage"

OriginMessage_clm = dict(
    message_id="INTEGER PRIMARY KEY UNIQUE",
    adapter_name="TEXT NOT NULL",
    channel_id="TEXT",
)

FollowMessage = "FollowMessage"

FollowMessage_clm = dict(
    message_id="INTEGER PRIMARY KEY UNIQUE",
    adapter_name="TEXT NOT NULL",
    channel_id="TEXT",
    origin_message_id="INTEGER NOT NULL",
)

follow_withdraw.create(OriginMessage, OriginMessage_clm)

follow_withdraw.create(FollowMessage, FollowMessage_clm)


async def get_follow_message_fromdb(mid):
    try:
        colum = ["message_id"]
        where = dict(origin_message_id=int(mid))
        req = follow_withdraw.select(FollowMessage, colum, where)
        return req
    except Exception as e:
        logger.error(e)
        return None


async def get_origin_message_fromdb(mid):
    try:
        where = dict(message_id=int(mid))
        req = follow_withdraw.select(OriginMessage, None, where)
        return req
    except Exception as e:
        logger.error(e)
        return None


async def save_message(adapter_name, origin_message, message):
    try:
        OriginMessage_clm_ = dict(
            message_id=int(origin_message.get("message_id")),
            adapter_name=f"'{str(adapter_name)}'",
            channel_id=origin_message.get("channel_id"),
        )
        follow_withdraw.insert(OriginMessage, OriginMessage_clm_)
        FollowMessage_clm_ = dict(
            message_id=int(message.get("message_id")),
            adapter_name=f"'{str(adapter_name)}'",
            channel_id=message.get("channel_id"),
            origin_message_id=int(origin_message.get("message_id")),
        )
        follow_withdraw.insert(FollowMessage, FollowMessage_clm_)
    except Exception as e:
        logger.error(e)
        return


async def clear_message():
    try:
        follow_withdraw.delete(OriginMessage)
        follow_withdraw.delete(FollowMessage)
    except Exception as e:
        logger.error(e)
        return


async def delete_message(OriginMessage_id, FollowMessage_ids):
    try:
        OriginMessage_clm_ = dict(
            message_id=int(OriginMessage_id),
        )
        follow_withdraw.delete(OriginMessage, OriginMessage_clm_)
        for a in FollowMessage_ids:
            a = list(a)
            a = a[0]
            FollowMessage_clm_ = dict(
                message_id=int(a),
            )
            follow_withdraw.delete(FollowMessage, FollowMessage_clm_)
    except Exception as e:
        logger.error(e)
        return
