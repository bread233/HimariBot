import time
from typing import Dict, Any, Optional
from nonebot import on_request, on_message, get_driver
from nonebot.permission import SUPERUSER
from nonebot.log import logger
from nonebot.adapters.onebot.v11 import Bot, FriendRequestEvent, GroupRequestEvent, PrivateMessageEvent

async def get_user_nickname(bot: Bot, user_id: int) -> str:
    """获取用户昵称，失败则返回 '未知昵称'"""
    try:
        resp = await bot.call_api("get_stranger_info", user_id=user_id, no_cache=True)
        return resp.get("nickname", "未知昵称")
    except Exception as e:
        logger.error(f"获取用户昵称失败 (user_id={user_id}): {e}")
        return "未知昵称"

# 存储待处理请求的字典
# { notify_message_id: { "type": ..., "flag": ..., ... } }
pending_requests: Dict[int, Dict[str, Any]] = {}

def get_superuser_ids() -> list[int]:
    """从配置中读取 superusers 并转换为 int 列表"""
    try:
        superusers = get_driver().config.superusers
        ids = []
        for s in superusers:
            try:
                # 处理可能为 str 的情况
                ids.append(int(str(s)))
            except (ValueError, TypeError):
                continue
        logger.info(f"get_superuser_ids: superusers={superusers}, ids={ids}")
        return ids
    except Exception as e:
        logger.error(f"获取 superuser_ids 失败: {e}")
        return []

def extract_sent_message_id(resp: Any) -> Optional[int]:
    """从发送结果中提取 message_id"""
    if not resp:
        return None
    # 如果 resp 是 dict，取 resp["message_id"]
    if isinstance(resp, dict):
        if "message_id" in resp:
            return int(resp["message_id"])
    # 如果 resp 有 message_id 属性，取 resp.message_id
    try:
        if hasattr(resp, "message_id"):
            return int(resp.message_id)
    except Exception:
        pass
    return None

def extract_reply_message_id(event: PrivateMessageEvent) -> Optional[int]:
    """提取被回复消息的 id"""
    # 优先 event.reply.message_id
    try:
        if hasattr(event, "reply") and event.reply is not None:
            if hasattr(event.reply, "message_id"):
                return int(event.reply.message_id)
            if isinstance(event.reply, dict):
                return int(event.reply.get("message_id", 0))
    except Exception:
        pass

    # 遍历 event.message，找 type == "reply"
    for msg in event.message:
        try:
            if msg.type == "reply":
                # 取 data["id"] 或 data["message_id"]
                return int(msg.data.get("id") or msg.data.get("message_id"))
        except Exception:
            continue
    return None

def cleanup_expired_requests():
    """删除 created_at 超过 86400 秒的记录"""
    now = time.time()
    expired_keys = [
        k for k, v in pending_requests.items()
        if now - v.get("created_at", now) > 86400
    ]
    for k in expired_keys:
        del pending_requests[k]

request_guard = on_request(priority=5, block=False)
approval_reply = on_message(permission=SUPERUSER, priority=5, block=False)

@request_guard.handle()
async def request_guard_handle(bot: Bot, event):
    cleanup_expired_requests()
    
    request_info = {}
    notify_msg = ""

    if isinstance(event, FriendRequestEvent):
        flag = event.flag
        user_id = event.user_id
        comment = event.comment
        nickname = await get_user_nickname(bot, user_id)
        notify_msg = (
            f"【好友申请】\n"
            f"申请人：{nickname}（QQ：{user_id}）\n"
            f"验证信息：{comment}\n"
            "操作：请回复本条消息“同意”或“拒绝”"
        )
        request_info = {
            "type": "friend",
            "flag": flag,
            "user_id": user_id,
            "comment": comment,
            "created_at": time.time()
        }
    elif isinstance(event, GroupRequestEvent):
        if event.sub_type == "invite":
            flag = event.flag
            sub_type = event.sub_type
            group_id = event.group_id
            user_id = event.user_id
            nickname = await get_user_nickname(bot, user_id)
            notify_msg = (
                f"【群聊邀请】\n"
                f"群号：{group_id}\n"
                f"邀请人：{nickname}（QQ：{user_id}）\n"
                "操作：请回复本条消息“同意”或“拒绝”"
            )
            request_info = {
                "type": "group_invite",
                "flag": flag,
                "sub_type": sub_type,
                "group_id": group_id,
                "user_id": user_id,
                "created_at": time.time()
            }
        else:
            return

    if not request_info or not notify_msg:
        return

    # 给所有 superuser 私聊发送通知
    superuser_ids = get_superuser_ids()
    logger.info(f"request_guard superuser_ids={superuser_ids}")
    if not superuser_ids:
        logger.warning("request_guard 未读取到 SUPERUSERS，无法发送审批通知")

    for su_id in superuser_ids:
        try:
            resp = await bot.send_private_msg(user_id=su_id, message=notify_msg)
            notify_id = extract_sent_message_id(resp)
            if notify_id is not None:
                pending_requests[int(notify_id)] = request_info
        except Exception as e:
            logger.error(f"发送通知失败 (su_id={su_id}): {e}")

@approval_reply.handle()
async def approval_reply_handle(bot: Bot, event: PrivateMessageEvent):
    cleanup_expired_requests()

    if not isinstance(event, PrivateMessageEvent):
        return

    # 只处理私聊，因为事件类型已经是 PrivateMessageEvent
    reply_id = extract_reply_message_id(event)
    if reply_id is None:
        return

    request = pending_requests.get(reply_id)
    if request is None:
        await approval_reply.finish("没有找到对应的申请，可能已处理或已过期。")
        return

    text = event.get_plaintext().strip()
    if text not in ["同意", "拒绝"]:
        await approval_reply.finish("请回复“同意”或“拒绝”。")
        return

    is_approve = (text == "同意")
    try:
        if request["type"] == "friend":
            await bot.call_api("set_friend_add_request", flag=request["flag"], approve=is_approve)
            res_msg = f"已{'同意' if is_approve else '拒绝'}好友申请"
        elif request["type"] == "group_invite":
            await bot.call_api("set_group_add_request", flag=request["flag"], sub_type=request["sub_type"], approve=is_approve)
            res_msg = f"已{'同意' if is_approve else '拒绝'}群聊邀请"
        else:
            await approval_reply.finish("未知请求类型")
            return

        del pending_requests[reply_id]
    except Exception as e:
        logger.error(f"审批执行失败: {e}")
        await approval_reply.finish(f"处理失败: {str(e)}")
        return

    await approval_reply.finish(res_msg)
