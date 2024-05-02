import asyncio
import re
import random
from datetime import datetime
from nonebot import on_command, require, get_bots, on_fullmatch
from nonebot.adapters.onebot.v11 import (
    Bot,
    GROUP,
    Message,
    GroupMessageEvent,
    MessageSegment,
    GROUP_ADMIN,
    GROUP_OWNER,
    ActionFailed
)
from ..lay_out import assign_bot, assign_bot_group, Cooldown, CooldownIsolateLevel
from nonebot.log import logger
from nonebot.params import CommandArg
from nonebot.permission import SUPERUSER
from .back_util import (
    get_user_main_back_msg, check_equipment_can_use,
    get_use_equipment_sql, get_shop_data, save_shop,
    get_item_msg, get_item_msg_rank, check_use_elixir,
    get_use_jlq_msg, get_no_use_equipment_sql
)
from .backconfig import get_config, savef
from ..item_json import Items
from ..utils import (
    check_user, send_forward_img,
    get_msg_pic, send_forward_img_list, CommandObjectID,
    Txt2Img
)
from ..xiuxian2_handle import (
    XiuxianDateManage, OtherSet,
    get_weapon_info_msg, get_armor_info_msg,
    get_sec_msg, get_main_info_msg, get_sub_info_msg, UserBuffDate
)
from ..xiuxian_config import XiuConfig, USERRANK

items = Items()
config = get_config()
groups = config['open']  # list，群交流会使用
auction = {}
AUCTIONSLEEPTIME = 120  # 拍卖初始等待时间（秒）
cache_help = {}
auction_offer_flag = False  # 拍卖标志
AUCTIONOFFERSLEEPTIME = 30  # 每次拍卖增加拍卖剩余的时间（秒）
auction_offer_time_count = 0  # 计算剩余时间
auction_offer_all_count = 0  # 控制线程等待时间
auction_time_config = config['拍卖会定时参数']  #
sql_message = XiuxianDateManage()  # sql类
# 定时任务
from src.service.apscheduler import scheduler
set_auction_by_scheduler = scheduler
reset_day_num_scheduler = scheduler

goods_re_root = on_command("炼金", priority=6, permission=GROUP, block=True)
shop = on_command("坊市查看", aliases={'查看坊市'}, priority=8, permission=GROUP, block=True)
shop_added = on_command("坊市上架", priority=10, permission=GROUP, block=True)
shop_added_by_admin = on_command("系统坊市上架", priority=5, permission=SUPERUSER, block=True)
shop_off = on_command("坊市下架", priority=5, permission=GROUP, block=True)
shop_off_all = on_fullmatch("清空坊市", priority=3, permission=SUPERUSER, block=True)
main_back = on_command('我的背包', aliases={'我的物品'}, priority=10, permission=GROUP, block=True)
use = on_command("使用", priority=15, permission=GROUP, block=True)
no_use_zb = on_command("换装", priority=5, permission=GROUP, block=True)
buy = on_command("坊市购买", priority=5, block=True)
set_auction = on_command("群拍卖会", priority=4, permission=GROUP and (SUPERUSER | GROUP_ADMIN | GROUP_OWNER), block=True)
creat_auction = on_fullmatch("举行拍卖会", priority=5, permission=GROUP and SUPERUSER, block=True)
offer_auction = on_command("拍卖", priority=5, permission=GROUP, block=True)
back_help = on_command("背包帮助", aliases={'坊市帮助'}, priority=8, permission=GROUP, block=True)
xiuxian_sone = on_fullmatch("灵石", priority=4, permission=GROUP, block=True)
chakan_wupin = on_command("查看修仙界物品", priority=25, permission=GROUP, block=True)

__back_help__ = f"""
指令：
1、我的背包、我的物品:查看自身背包前196个物品的信息
2、使用+物品名字：使用物品,丹药可批量使用
3、换装+装备名字：卸载目标装备
4、坊市购买+物品编号:购买坊市内的物品
5、坊市查看、查看坊市:查询坊市在售物品
6、坊市上架:坊市上架 物品 金额，上架背包内的物品,最低金额50w
7、系统坊市上架:系统坊市上架 物品 金额，上架任意存在的物品，超管权限
8、坊市下架+物品编号：下架坊市内的物品，管理员和群主可以下架任意编号的物品！
9、群拍卖会开启、关闭:开启拍卖行功能，管理员指令，注意：会在机器人所在的全部已开启此功能的群内通报拍卖消息
10、拍卖+金额：对本次拍卖会的物品进行拍卖
11、炼金+物品名字：将物品炼化为灵石,支持批量炼金和绑定丹药炼金
12、背包帮助:获取背包帮助指令
13、查看修仙界物品:支持类型【功法|神通|丹药|合成丹药|法器|防具】
14、清空坊市:清空本群坊市,管理员权限
非指令：
1、定时生成拍卖会,每天{auction_time_config['hours']}点每整点生成一场拍卖会
""".strip()


# 重置丹药每日使用次数
@reset_day_num_scheduler.scheduled_job("cron", hour=0, minute=0, )
async def reset_day_num_scheduler_():
    sql_message.day_num_reset()
    logger.info("每日丹药使用次数重置成功！")


# 定时任务生成拍卖会
@set_auction_by_scheduler.scheduled_job("cron", hour=auction_time_config['hours'])
async def set_auction_by_scheduler_():
    if groups:
        global auction
        if auction != {}:  # 存在拍卖会
            logger.info("本群已存在一场拍卖会，已清除！")
            auction = {}
        try:
            auction_id_list = get_auction_id_list()
            auction_id = random.choice(auction_id_list)
        except LookupError:
            msg = "获取不到拍卖物品的信息，请检查配置文件！"
            logger.info(msg)
            return
        auction_info = items.get_data_by_item_id(auction_id)
        start_price = get_auction_price_by_id(auction_id)['start_price']
        msg = '本次拍卖的物品为：\n'
        msg += get_auction_msg(auction_id)
        msg += f"\n底价为{start_price}灵石"
        msg += "\n请诸位道友发送 拍卖+金额 来进行拍卖吧！"
        msg += f"\n本次竞拍时间为:{AUCTIONSLEEPTIME}秒！"
        auction['id'] = auction_id
        auction['user_id'] = 0
        auction['now_price'] = start_price
        auction['name'] = auction_info['name']
        auction['type'] = auction_info['type']
        auction['start_time'] = datetime.now()
        auction['group_id'] = 0
        for group_id in groups:
            bot = await assign_bot_group(group_id=group_id)
            try:
                if XiuConfig().img:
                    pic = await get_msg_pic(msg)
                    await bot.send_group_msg(group_id=int(group_id), message=MessageSegment.image(pic))
                else:
                    await bot.send_group_msg(group_id=int(group_id), message=msg)
            except ActionFailed:  # 发送群消息失败
                continue
        await asyncio.sleep(AUCTIONSLEEPTIME)  # 先睡60秒

        global auction_offer_flag, auction_offer_all_count, auction_offer_time_count
        while auction_offer_flag:  # 有人拍卖
            if auction_offer_all_count == 0:
                auction_offer_flag = False
                break
            logger.info(f"有人拍卖，本次等待时间：{auction_offer_all_count * AUCTIONOFFERSLEEPTIME}秒")
            first_time = auction_offer_all_count * AUCTIONOFFERSLEEPTIME
            auction_offer_all_count = 0
            auction_offer_flag = False
            await asyncio.sleep(first_time)
            logger.info(
                f"总计等待时间{auction_offer_time_count * AUCTIONOFFERSLEEPTIME}秒，当前拍卖标志：{auction_offer_flag}，本轮等待时间：{first_time}")

        logger.info(f"等待时间结束，总计等待时间{auction_offer_time_count * AUCTIONOFFERSLEEPTIME}秒")
        if auction['user_id'] == 0:
            msg = "很可惜，本次拍卖会流拍了！"
            auction = {}
            for group_id in groups:
                bot = await assign_bot_group(group_id=group_id)
                try:
                    if XiuConfig().img:
                        pic = await get_msg_pic(msg)
                        await bot.send_group_msg(group_id=int(group_id), message=MessageSegment.image(pic))
                    else:
                        await bot.send_group_msg(group_id=int(group_id), message=msg)
                except ActionFailed:  # 发送群消息失败
                    continue
            return
        now_price = int(auction['now_price'])
        user_info = sql_message.get_user_message(auction['user_id'])
        user_stone = user_info.stone
        punish_stone = now_price * 0.1
        if user_stone < now_price:
            sql_message.update_ls(user_info.user_id, punish_stone, 2)  # 扣除用户灵石
            msg = f"拍卖会结算！竞拍者灵石小于拍卖物品要求之数量，判定为捣乱，捣乱次数+1!\n"
            msg += "扣除道友{}枚灵石作为惩罚，望道友莫要再捣乱！".format(punish_stone)
            for group_id in groups:
                bot = await assign_bot_group(group_id=group_id)
                try:
                    if XiuConfig().img:
                        pic = await get_msg_pic(msg)
                        await bot.send_group_msg(group_id=int(group_id), message=MessageSegment.image(pic))
                    else:
                        await bot.send_group_msg(group_id=int(group_id), message=msg)
                except ActionFailed:  # 发送群消息失败
                    continue
            return
        msg = "本次拍卖会结束！"
        msg += f"恭喜来自群{auction['group_id']}的{user_info.user_name}道友成功拍卖获得：{auction['type']}-{auction['name']}!"
        for group_id in groups:
            bot = await assign_bot_group(group_id=group_id)
            try:
                if XiuConfig().img:
                    pic = await get_msg_pic(msg)
                    await bot.send_group_msg(group_id=int(group_id), message=MessageSegment.image(pic))
                else:
                    await bot.send_group_msg(group_id=int(group_id), message=msg)
            except ActionFailed:  # 发送群消息失败
                continue

        sql_message.send_back(user_info.user_id, auction['id'], auction['name'], auction['type'], 1)
        sql_message.update_ls(user_info.user_id, int(auction['now_price']), 2)
        auction = {}
        auction_offer_time_count = 0
        return


@back_help.handle(parameterless=[Cooldown(at_sender=True)])
async def back_help_(bot: Bot, event: GroupMessageEvent, session_id: int = CommandObjectID()):
    bot, send_group_id = await assign_bot(bot=bot, event=event)
    if session_id in cache_help:
        await bot.send_group_msg(group_id=int(send_group_id), message=MessageSegment.image(cache_help[session_id]))
        await back_help.finish()
    else:
        msg = __back_help__
        title = ''
        font_size = 32
        img = Txt2Img(font_size)
        if XiuConfig().img:
            pic = await img.save(title,msg)
            cache_help[session_id] = pic
            await bot.send_group_msg(group_id=int(send_group_id), message=MessageSegment.image(pic))
        else:
            await bot.send_group_msg(group_id=int(send_group_id), message=msg)
        await back_help.finish()


@xiuxian_sone.handle(parameterless=[Cooldown(at_sender=True)])
async def xiuxian_sone_(bot: Bot, event: GroupMessageEvent):
    """我的灵石信息"""
    bot, send_group_id = await assign_bot(bot=bot, event=event)
    isUser, user_info, msg = check_user(event)
    if not isUser:
        if XiuConfig().img:
            pic = await get_msg_pic(f"@{event.sender.nickname}\n" + msg)
            await bot.send_group_msg(group_id=int(send_group_id), message=MessageSegment.image(pic))
        else:
            await bot.send_group_msg(group_id=int(send_group_id), message=msg)
        await xiuxian_sone.finish()
    msg = f"当前灵石：{user_info.stone}"
    if XiuConfig().img:
        pic = await get_msg_pic(f"@{event.sender.nickname}\n" + msg)
        await bot.send_group_msg(group_id=int(send_group_id), message=MessageSegment.image(pic))
    else:
        await bot.send_group_msg(group_id=int(send_group_id), message=msg)
    await xiuxian_sone.finish()


buy_lock = asyncio.Lock()


@buy.handle(parameterless=[Cooldown(1.4, isolate_level=CooldownIsolateLevel.GROUP)])
async def buy_(bot: Bot, event: GroupMessageEvent, args: Message = CommandArg()):
    """购物"""
    bot, send_group_id = await assign_bot(bot=bot, event=event)
    async with buy_lock:
        isUser, user_info, msg = check_user(event)
        if not isUser:
            if XiuConfig().img:
                pic = await get_msg_pic(f"@{event.sender.nickname}\n" + msg)
                await bot.send_group_msg(group_id=int(send_group_id), message=MessageSegment.image(pic))
            else:
                await bot.send_group_msg(group_id=int(send_group_id), message=msg)
            await buy.finish()
        user_id = user_info.user_id
        group_id = str(event.group_id)
        shop_data = get_shop_data(group_id)
        
        
        if shop_data[group_id] == {}:
            msg = "坊市目前空空如也！"
            if XiuConfig().img:
                pic = await get_msg_pic(f"@{event.sender.nickname}\n" + msg)
                await bot.send_group_msg(group_id=int(send_group_id), message=MessageSegment.image(pic))
            else:
                await bot.send_group_msg(group_id=int(send_group_id), message=msg)
            await buy.finish()
        input_args = args.extract_plain_text().strip().split() # 购买参数
        # 确定物品的价格和数量
        if len(input_args) < 1:
            # 没有输入任何参数或只输入了"坊市购买"而没有后续的物品编号和数量
            msg = "请输入正确指令！例如：坊市购买 物品编号 数量"
            if XiuConfig().img:
                pic = await get_msg_pic(f"@{event.sender.nickname}\n" + msg)
                await bot.send_group_msg(group_id=int(send_group_id), message=MessageSegment.image(pic))
            else:
                await bot.send_group_msg(group_id=int(send_group_id), message=msg)
            await buy.finish()
        else:
            try:
                arg = int(input_args[0]) # 购买编号
                if len(input_args) == 0:
                    # 没有输入任何参数
                    msg = "请输入正确指令！例如：坊市购买 物品 数量"

                # 取出商品信息，检查库存
                goods_info = shop_data[group_id].get(str(arg))
                if not goods_info:
                    raise ValueError("编号对应的商品不存在")

                purchase_quantity = int(input_args[1]) if len(input_args) > 1 else 1  # 购买数量，默认为1
                if purchase_quantity <= 0:
                    raise ValueError("购买数量必须是正数")
    
                if 'stock' in goods_info and purchase_quantity > goods_info['stock']:
                 # 如果商品有库存限制，且购买数量超过库存，则抛出错误
                    raise ValueError("购买数量超过库存限制")
    
            except ValueError as e:
                msg = f"{str(e)}！请输入正确的格式！如：坊市购买 1 5"
                if XiuConfig().img:
                    pic = await get_msg_pic(f"@{event.sender.nickname}\n" + msg)
                    await bot.send_group_msg(group_id=int(send_group_id), message=MessageSegment.image(pic))
                else:
                    await bot.send_group_msg(group_id=int(send_group_id), message=msg)
                await buy.finish()
        shop_user_id = shop_data[group_id][str(arg)]['user_id']
        goods_price = goods_info['price'] * purchase_quantity  # 总价格
        goods_stock = goods_info.get('stock', 1)  # 如果没有指定数量，默认为1
        if user_info.stone < goods_price:
            msg = '没钱还敢来买东西！！'
            if XiuConfig().img:
                pic = await get_msg_pic(f"@{event.sender.nickname}\n" + msg)
                await bot.send_group_msg(group_id=int(send_group_id), message=MessageSegment.image(pic))
            else:
                await bot.send_group_msg(group_id=int(send_group_id), message=msg)
            await buy.finish()
        elif int(user_id) == int(shop_data[group_id][str(arg)]['user_id']):
            msg = "道友自己的东西就不要自己购买啦！"
            if XiuConfig().img:
                pic = await get_msg_pic(f"@{event.sender.nickname}\n" + msg)
                await bot.send_group_msg(group_id=int(send_group_id), message=MessageSegment.image(pic))
            else:
                await bot.send_group_msg(group_id=int(send_group_id), message=msg)
            await buy.finish()
        elif purchase_quantity > goods_stock and shop_user_id != 0:
            msg = "库存不足，无法购买所需数量！"
            if XiuConfig().img:
                pic = await get_msg_pic(f"@{event.sender.nickname}\n" + msg)
                await bot.send_group_msg(group_id=int(send_group_id), message=MessageSegment.image(pic))
            else:
                await bot.send_group_msg(group_id=int(send_group_id), message=msg)
        else:
            shop_goods_name = shop_data[group_id][str(arg)]['goods_name']
            shop_user_name = shop_data[group_id][str(arg)]['user_name']
            shop_goods_id = shop_data[group_id][str(arg)]['goods_id']
            shop_goods_type = shop_data[group_id][str(arg)]['goods_type']
            sql_message.update_ls(user_id, goods_price, 2)
            sql_message.send_back(user_id, shop_goods_id, shop_goods_name, shop_goods_type, purchase_quantity)
            save_shop(shop_data)

            if shop_user_id == 0:  # 0为系统
                msg = f"道友成功购买{purchase_quantity}个{shop_goods_name}，消耗灵石{goods_price}枚！"
            else:
                # 更新坊市物品库存（如果物品是有限的）
                goods_info['stock'] -= purchase_quantity
                if goods_info['stock'] <= 0:
                    del shop_data[group_id][str(arg)]  # 如果库存为0，则从坊市中移除该物品
                else:
                    shop_data[group_id][str(arg)] = goods_info # 更新库存
                service_charge = int(goods_price * 0.1)  # 手续费10%
                give_stone = goods_price - service_charge
                msg = f"道友成功购买{purchase_quantity}个{shop_user_name}道友寄售的{shop_goods_name}，消耗灵石{goods_price}枚,坊市收取手续费：{service_charge}枚灵石！"
                sql_message.update_ls(shop_user_id, give_stone, 1)
            shop_data[group_id] = reset_dict_num(shop_data[group_id])
            save_shop(shop_data)
            if XiuConfig().img:
                pic = await get_msg_pic(f"@{event.sender.nickname}\n" + msg)
                await bot.send_group_msg(group_id=int(send_group_id), message=MessageSegment.image(pic))
            else:
                await bot.send_group_msg(group_id=int(send_group_id), message=msg)
            await buy.finish()


@shop.handle(parameterless=[Cooldown(at_sender=True)])
async def shop_(bot: Bot, event: GroupMessageEvent):
    """坊市查看"""
    bot, send_group_id = await assign_bot(bot=bot, event=event)
    isUser, user_info, msg = check_user(event)
    if not isUser:
        if XiuConfig().img:
            pic = await get_msg_pic(f"@{event.sender.nickname}\n" + msg)
            await bot.send_group_msg(group_id=int(send_group_id), message=MessageSegment.image(pic))
        else:
            await bot.send_group_msg(group_id=int(send_group_id), message=msg)
        await shop.finish()

    group_id = str(event.group_id)
    shop_data = get_shop_data(group_id)
    data_list = []
    if shop_data[group_id] == {}:
        msg = "坊市目前空空如也！"
        if XiuConfig().img:
            pic = await get_msg_pic(f"@{event.sender.nickname}\n" + msg)
            await bot.send_group_msg(group_id=int(send_group_id), message=MessageSegment.image(pic))
        else:
            await bot.send_group_msg(group_id=int(send_group_id), message=msg)
        await shop.finish()

    for k, v in shop_data[group_id].items():
        msg = f"编号：{k}\n"
        msg += f"{v['desc']}"
        msg += f"\n价格：{v['price']}枚灵石\n"
        if v['user_id'] != 0:
            msg += f"拥有人：{v['user_name']}道友\n"
            try:
                msg += f"数量：{v['stock']}\n"
            except:
                msg += "数量：获取失败\n"
        else:
            msg += f"系统出售\n"
            msg += f"数量：无限\n"
        data_list.append(msg)
    await send_forward_img(bot, event, '坊市', bot.self_id, data_list)
    await shop.finish()


@shop_added_by_admin.handle(parameterless=[Cooldown(1.4, isolate_level=CooldownIsolateLevel.GROUP, parallel=1)])
async def shop_added_by_admin_(bot: Bot, event: GroupMessageEvent, args: Message = CommandArg()):
    """系统上架坊市"""
    bot, send_group_id = await assign_bot(bot=bot, event=event)
    args = args.extract_plain_text().split()
    if not args:
        msg = "请输入正确指令！例如：系统坊市上架 物品 金额"
        if XiuConfig().img:
            pic = await get_msg_pic(f"@{event.sender.nickname}\n" + msg)
            await bot.send_group_msg(group_id=int(send_group_id), message=MessageSegment.image(pic))
        else:
            await bot.send_group_msg(group_id=int(send_group_id), message=msg)
        await shop_added_by_admin.finish()
    goods_name = args[0]
    goods_id = -1
    for k, v in items.items.items():
        if goods_name == v['name']:
            goods_id = k
            break
        else:
            continue
    if goods_id == -1:
        msg = f"不存在物品：{goods_name}的信息，请检查名字是否输入正确！"
        if XiuConfig().img:
            pic = await get_msg_pic(f"@{event.sender.nickname}\n" + msg)
            await bot.send_group_msg(group_id=int(send_group_id), message=MessageSegment.image(pic))
        else:
            await bot.send_group_msg(group_id=int(send_group_id), message=msg)
        await shop_added_by_admin.finish()
    price = None
    try:
        price = args[1]
    except LookupError:
        msg = "请输入正确指令！例如：系统坊市上架 物品 金额"
        if XiuConfig().img:
            pic = await get_msg_pic(f"@{event.sender.nickname}\n" + msg)
            await bot.send_group_msg(group_id=int(send_group_id), message=MessageSegment.image(pic))
        else:
            await bot.send_group_msg(group_id=int(send_group_id), message=msg)
        await shop_added_by_admin.finish()
    try:
        price = int(price)
        if price < 0:
            msg = "请不要设置负数！"
            if XiuConfig().img:
                pic = await get_msg_pic(f"@{event.sender.nickname}\n" + msg)
                await bot.send_group_msg(group_id=int(send_group_id), message=MessageSegment.image(pic))
            else:
                await bot.send_group_msg(group_id=int(send_group_id), message=msg)
            await shop_added_by_admin.finish()
    except LookupError:
        msg = "请输入正确的金额！"
        if XiuConfig().img:
            pic = await get_msg_pic(f"@{event.sender.nickname}\n" + msg)
            await bot.send_group_msg(group_id=int(send_group_id), message=MessageSegment.image(pic))
        else:
            await bot.send_group_msg(group_id=int(send_group_id), message=msg)
        await shop_added_by_admin.finish()

    try:
        var = args[2]
        msg = "请输入正确指令！例如：系统坊市上架 物品 金额"
        if XiuConfig().img:
            pic = await get_msg_pic(f"@{event.sender.nickname}\n" + msg)
            await bot.send_group_msg(group_id=int(send_group_id), message=MessageSegment.image(pic))
        else:
            await bot.send_group_msg(group_id=int(send_group_id), message=msg)
        await shop_added_by_admin.finish()
    except LookupError:
        pass

    group_id = str(event.group_id)
    shop_data = get_shop_data(group_id)
    if shop_data == {}:
        shop_data[group_id] = {}
    goods_info = items.get_data_by_item_id(goods_id)

    id_ = len(shop_data[group_id]) + 1
    shop_data[group_id][id_] = {}
    shop_data[group_id][id_]['user_id'] = 0
    shop_data[group_id][id_]['goods_name'] = goods_name
    shop_data[group_id][id_]['goods_id'] = goods_id
    shop_data[group_id][id_]['goods_type'] = goods_info['type']
    shop_data[group_id][id_]['desc'] = get_item_msg(goods_id)
    shop_data[group_id][id_]['price'] = price
    shop_data[group_id][id_]['user_name'] = '系统'
    save_shop(shop_data)
    msg = f"物品：{goods_name}成功上架坊市，金额：{price}枚灵石！"
    if XiuConfig().img:
        pic = await get_msg_pic(f"@{event.sender.nickname}\n" + msg)
        await bot.send_group_msg(group_id=int(send_group_id), message=MessageSegment.image(pic))
    else:
        await bot.send_group_msg(group_id=int(send_group_id), message=msg)
    await shop_added_by_admin.finish()


@shop_added.handle(parameterless=[Cooldown(1.4, isolate_level=CooldownIsolateLevel.GROUP)])
async def shop_added_(bot: Bot, event: GroupMessageEvent, args: Message = CommandArg()):
    """用户上架坊市"""
    bot, send_group_id = await assign_bot(bot=bot, event=event)
    isUser, user_info, msg = check_user(event)
    if not isUser:
        if XiuConfig().img:
            pic = await get_msg_pic(f"@{event.sender.nickname}\n" + msg)
            await bot.send_group_msg(group_id=int(send_group_id), message=MessageSegment.image(pic))
        else:
            await bot.send_group_msg(group_id=int(send_group_id), message=msg)
        await shop_added.finish()
    user_id = user_info.user_id
    args = args.extract_plain_text().split()
    goods_name = args[0] if len(args) > 0 else None
    price_str = args[1] if len(args) > 1 else "500000"  # 如果未提供价格，默认为500000
    quantity_str = args[2] if len(args) > 2 else "1"  # 如果未提供数量，默认为1
    if len(args) == 0:
        # 没有输入任何参数
        msg = "请输入正确指令！例如：坊市上架 物品 金额 数量"
        if XiuConfig().img:
            pic = await get_msg_pic(f"@{event.sender.nickname}\n" + msg)
            await bot.send_group_msg(group_id=int(send_group_id), message=MessageSegment.image(pic))
        else:
            await bot.send_group_msg(group_id=int(send_group_id), message=msg)
        await shop_added.finish()
    elif len(args) == 1:
        # 只提供了物品名称
        msg = "请输入正确指令！例如：坊市上架 物品 金额 数量"
        if XiuConfig().img:
            pic = await get_msg_pic(f"@{event.sender.nickname}\n" + msg)
            await bot.send_group_msg(group_id=int(send_group_id), message=MessageSegment.image(pic))
        else:
            await bot.send_group_msg(group_id=int(send_group_id), message=msg)
        await shop_added_by_admin.finish()
    elif len(args) == 2:
        # 提供了物品名称和价格
        goods_name, price_str = args[0], args[1]
        quantity_str = "1"  # 默认数量
    else:
        # 提供了物品名称、价格和数量
        goods_name, price_str, quantity_str = args[0], args[1], args[2]

    back_msg = sql_message.get_back_msg(user_id)  # 背包sql信息,list(back)
    if back_msg is None:
        msg = "道友的背包空空如也！"
        if XiuConfig().img:
            pic = await get_msg_pic(f"@{event.sender.nickname}\n" + msg)
            await bot.send_group_msg(group_id=int(send_group_id), message=MessageSegment.image(pic))
        else:
            await bot.send_group_msg(group_id=int(send_group_id), message=msg)
        await shop_added.finish()
    in_flag = False  # 判断指令是否正确，道具是否在背包内
    goods_id = None
    goods_type = None
    goods_state = None
    goods_num = None
    goods_bind_num = None
    for back in back_msg:
        if goods_name == back.goods_name:
            in_flag = True
            goods_id = back.goods_id
            goods_type = back.goods_type
            goods_state = back.state
            goods_num = back.goods_num
            goods_bind_num = back.bind_num
            break
    if not in_flag:
        msg = f"请检查该道具 {goods_name} 是否在背包内！"
        if XiuConfig().img:
            pic = await get_msg_pic(f"@{event.sender.nickname}\n" + msg)
            await bot.send_group_msg(group_id=int(send_group_id), message=MessageSegment.image(pic))
        else:
            await bot.send_group_msg(group_id=int(send_group_id), message=msg)
        await shop_added.finish()
    price = None
    
    # 解析价格
    try:
        price = int(price_str)
        if price <= 0:
            raise ValueError("价格必须为正数!")
    except ValueError as e:
        msg = f"请输入正确的金额: {str(e)}"
        if XiuConfig().img:
            pic = await get_msg_pic(f"@{event.sender.nickname}\n" + msg)
            await bot.send_group_msg(group_id=int(send_group_id), message=MessageSegment.image(pic))
        else:
            await bot.send_group_msg(group_id=int(send_group_id), message=msg)
        await shop_added.finish()
    # 解析数量
    try:
        quantity = int(quantity_str)
        if quantity <= 0 or quantity > goods_num:  # 检查指定的数量是否合法
            raise ValueError("数量必须为正数或者小于等于你拥有的物品数!")
    except ValueError as e:
        msg = f"请输入正确的数量: {str(e)}"
        if XiuConfig().img:
            pic = await get_msg_pic(f"@{event.sender.nickname}\n" + msg)
            await bot.send_group_msg(group_id=int(send_group_id), message=MessageSegment.image(pic))
        else:
            await bot.send_group_msg(group_id=int(send_group_id), message=msg)
        await shop_added.finish()
    price = max(price, 500000)  # 最低价格为50w
    if goods_type == "装备" and int(goods_state) == 1 and int(goods_num) == 1:
        msg = f"装备：{goods_name}已经被道友装备在身，无法上架！"
        if XiuConfig().img:
            pic = await get_msg_pic(f"@{event.sender.nickname}\n" + msg)
            await bot.send_group_msg(group_id=int(send_group_id), message=MessageSegment.image(pic))
        else:
            await bot.send_group_msg(group_id=int(send_group_id), message=msg)
        await shop_added.finish()

    if goods_type == "丹药" and int(goods_num) <= int(goods_bind_num):
        msg = f"该物品是绑定物品，无法上架！"
        if XiuConfig().img:
            pic = await get_msg_pic(f"@{event.sender.nickname}\n" + msg)
            await bot.send_group_msg(group_id=int(send_group_id), message=MessageSegment.image(pic))
        else:
            await bot.send_group_msg(group_id=int(send_group_id), message=msg)
        await shop_added.finish()
    if goods_type == "聚灵旗" or goods_type == "炼丹炉":
        if user_info.root == "器师" :
            pass
        else:
            msg = f"道友职业无法上架！"
            if XiuConfig().img:
                pic = await get_msg_pic(f"@{event.sender.nickname}\n" + msg)
                await bot.send_group_msg(group_id=int(send_group_id), message=MessageSegment.image(pic))
            else:
                await bot.send_group_msg(group_id=int(send_group_id), message=msg)
            await shop_added.finish() 

    group_id = str(event.group_id)
    shop_data = get_shop_data(group_id)

    num = 0
    for k, v in shop_data[group_id].items():
        if str(v['user_id']) == str(user_info.user_id):
            num += 1
        else:
            pass
    if num >= 5 :
        msg = f"每人只可上架两个物品！"
        if XiuConfig().img:
            pic = await get_msg_pic(f"@{event.sender.nickname}\n" + msg)
            await bot.send_group_msg(group_id=int(send_group_id), message=MessageSegment.image(pic))
        else:
            await bot.send_group_msg(group_id=int(send_group_id), message=msg)
        await shop_added.finish()

    if shop_data == {}:
        shop_data[group_id] = {}
    id_ = len(shop_data[group_id]) + 1
    shop_data[group_id][id_] = {
        'user_id': user_id,
        'goods_name': goods_name,
        'goods_id': goods_id,
        'goods_type': goods_type,
        'desc': get_item_msg(goods_id),
        'price': price,
        'user_name': user_info.user_name,
        'stock': quantity,  # 物品数量
    }
    sql_message.update_back_j(user_id, goods_id, num = quantity)
    save_shop(shop_data)
    msg = f"物品：{goods_name}成功上架坊市，金额：{price}枚灵石，数量{quantity}！"
    if XiuConfig().img:
        pic = await get_msg_pic(f"@{event.sender.nickname}\n" + msg)
        await bot.send_group_msg(group_id=int(send_group_id), message=MessageSegment.image(pic))
    else:
        await bot.send_group_msg(group_id=int(send_group_id), message=msg)
    await shop_added.finish()


@goods_re_root.handle(parameterless=[Cooldown(at_sender=True)])
async def goods_re_root_(bot: Bot, event: GroupMessageEvent, args: Message = CommandArg()):
    """物品回收"""
    bot, send_group_id = await assign_bot(bot=bot, event=event)
    isUser, user_info, msg = check_user(event)
    if not isUser:
        if XiuConfig().img:
            pic = await get_msg_pic(f"@{event.sender.nickname}\n" + msg)
            await bot.send_group_msg(group_id=int(send_group_id), message=MessageSegment.image(pic))
        else:
            await bot.send_group_msg(group_id=int(send_group_id), message=msg)
        await goods_re_root.finish()
    user_id = user_info.user_id
    args = args.extract_plain_text().split()
    if args is None:
        msg = "请输入要炼化的物品！"
        if XiuConfig().img:
            pic = await get_msg_pic(f"@{event.sender.nickname}\n" + msg)
            await bot.send_group_msg(group_id=int(send_group_id), message=MessageSegment.image(pic))
        else:
            await bot.send_group_msg(group_id=int(send_group_id), message=msg)
        await goods_re_root.finish()
    goods_name = args[0]
    back_msg = sql_message.get_back_msg(user_id)  # 背包sql信息,list(back)
    if back_msg is None:
        msg = "道友的背包空空如也！"
        if XiuConfig().img:
            pic = await get_msg_pic(f"@{event.sender.nickname}\n" + msg)
            await bot.send_group_msg(group_id=int(send_group_id), message=MessageSegment.image(pic))
        else:
            await bot.send_group_msg(group_id=int(send_group_id), message=msg)
        await goods_re_root.finish()
    in_flag = False  # 判断指令是否正确，道具是否在背包内
    goods_id = None
    goods_type = None
    goods_state = None
    goods_num = None
    for back in back_msg:
        if goods_name == back.goods_name:
            in_flag = True
            goods_id = back.goods_id
            goods_type = back.goods_type
            goods_state = back.state
            goods_num = back.goods_num
            break
    if not in_flag:
        msg = f"请检查该道具 {goods_name} 是否在背包内！"
        if XiuConfig().img:
            pic = await get_msg_pic(f"@{event.sender.nickname}\n" + msg)
            await bot.send_group_msg(group_id=int(send_group_id), message=MessageSegment.image(pic))
        else:
            await bot.send_group_msg(group_id=int(send_group_id), message=msg)
        await goods_re_root.finish()

    if goods_type == "装备" and int(goods_state) == 1 and int(goods_num) == 1:
        msg = f"装备：{goods_name}已经被道友装备在身，无法炼金！"
        if XiuConfig().img:
            pic = await get_msg_pic(f"@{event.sender.nickname}\n" + msg)
            await bot.send_group_msg(group_id=int(send_group_id), message=MessageSegment.image(pic))
        else:
            await bot.send_group_msg(group_id=int(send_group_id), message=msg)
        await goods_re_root.finish()

    if get_item_msg_rank(goods_id) == 520:
        msg = "此类物品不支持！"
        if XiuConfig().img:
            pic = await get_msg_pic(f"@{event.sender.nickname}\n" + msg)
            await bot.send_group_msg(group_id=int(send_group_id), message=MessageSegment.image(pic))
        else:
            await bot.send_group_msg(group_id=int(send_group_id), message=msg)
        await goods_re_root.finish()
    try:
        if 1 <= int(args[1]) <= int(goods_num):
            num = int(args[1])
    except:
            num = 1 
    price = int(6000000 - get_item_msg_rank(goods_id) * 100000) * num
    if price <= 0:
        msg = f"物品：{goods_name}炼金失败，凝聚{price}枚灵石，记得通知晓楠！"
        if XiuConfig().img:
            pic = await get_msg_pic(f"@{event.sender.nickname}\n" + msg)
            await bot.send_group_msg(group_id=int(send_group_id), message=MessageSegment.image(pic))
        else:
            await bot.send_group_msg(group_id=int(send_group_id), message=msg)
        await goods_re_root.finish()

    sql_message.update_back_j(user_id, goods_id, num=num)
    sql_message.update_ls(user_id, price, 1)
    msg = f"物品：{goods_name} 数量：{num} 炼金成功，凝聚{price}枚灵石！"
    if XiuConfig().img:
        pic = await get_msg_pic(f"@{event.sender.nickname}\n" + msg)
        await bot.send_group_msg(group_id=int(send_group_id), message=MessageSegment.image(pic))
    else:
        await bot.send_group_msg(group_id=int(send_group_id), message=msg)
    await goods_re_root.finish()


@shop_off.handle(parameterless=[Cooldown(1.4, isolate_level=CooldownIsolateLevel.GROUP, parallel=1)])
async def shop_off_(bot: Bot, event: GroupMessageEvent, args: Message = CommandArg()):
    """下架商品"""
    bot, send_group_id = await assign_bot(bot=bot, event=event)
    isUser, user_info, msg = check_user(event)
    if not isUser:
        if XiuConfig().img:
            pic = await get_msg_pic(f"@{event.sender.nickname}\n" + msg)
            await bot.send_group_msg(group_id=int(send_group_id), message=MessageSegment.image(pic))
        else:
            await bot.send_group_msg(group_id=int(send_group_id), message=msg)
        await shop_off.finish()
    user_id = user_info.user_id
    group_id = str(event.group_id)
    shop_data = get_shop_data(group_id)
    if shop_data[group_id] == {}:
        msg = "坊市目前空空如也！"
        if XiuConfig().img:
            pic = await get_msg_pic(f"@{event.sender.nickname}\n" + msg)
            await bot.send_group_msg(group_id=int(send_group_id), message=MessageSegment.image(pic))
        else:
            await bot.send_group_msg(group_id=int(send_group_id), message=msg)
        await shop_off.finish()

    arg = args.extract_plain_text().strip()
    shop_user_name = shop_data[group_id][str(arg)]['user_name']
    try:
        arg = int(arg)
        if arg <= 0 or arg > len(shop_data[group_id]):
            msg = "请输入正确的编号！"
            if XiuConfig().img:
                pic = await get_msg_pic(f"@{event.sender.nickname}\n" + msg)
                await bot.send_group_msg(group_id=int(send_group_id), message=MessageSegment.image(pic))
            else:
                await bot.send_group_msg(group_id=int(send_group_id), message=msg)
            await shop_off.finish()
    except ValueError:
        msg = "请输入正确的编号！"
        if XiuConfig().img:
            pic = await get_msg_pic(f"@{event.sender.nickname}\n" + msg)
            await bot.send_group_msg(group_id=int(send_group_id), message=MessageSegment.image(pic))
        else:
            await bot.send_group_msg(group_id=int(send_group_id), message=msg)
        await shop_off.finish()

    if shop_data[group_id][str(arg)]['user_id'] == user_id:
        sql_message.send_back(user_id, shop_data[group_id][str(arg)]['goods_id'],
                              shop_data[group_id][str(arg)]['goods_name'], shop_data[group_id][str(arg)]['goods_type'],
                              1)
        msg = f"成功下架物品：{shop_data[group_id][str(arg)]['goods_name']}！"
        del shop_data[group_id][str(arg)]
        shop_data[group_id] = reset_dict_num(shop_data[group_id])
        save_shop(shop_data)
        if XiuConfig().img:
            pic = await get_msg_pic(f"@{event.sender.nickname}\n" + msg)
            await bot.send_group_msg(group_id=int(send_group_id), message=MessageSegment.image(pic))
        else:
            await bot.send_group_msg(group_id=int(send_group_id), message=msg)
        await shop_off.finish()

    elif event.sender.role == "admin" or event.sender.role == "owner" or event.get_user_id() in bot.config.superusers:
        if shop_data[group_id][str(arg)]['user_id'] == 0:  # 这么写为了防止bot.send发送失败，不结算
            msg = f"成功下架物品：{shop_data[group_id][str(arg)]['goods_name']}！"
            del shop_data[group_id][str(arg)]
            shop_data[group_id] = reset_dict_num(shop_data[group_id])
            save_shop(shop_data)
            if XiuConfig().img:
                pic = await get_msg_pic(f"@{event.sender.nickname}\n" + msg)
                await bot.send_group_msg(group_id=int(send_group_id), message=MessageSegment.image(pic))
            else:
                await bot.send_group_msg(group_id=int(send_group_id), message=msg)
            await shop_off.finish()
        else:
            sql_message.send_back(shop_data[group_id][str(arg)]['user_id'], shop_data[group_id][str(arg)]['goods_id'],
                                  shop_data[group_id][str(arg)]['goods_name'],
                                  shop_data[group_id][str(arg)]['goods_type'], 1)
            msg1 = f"道友上架的{shop_data[group_id][str(arg)]['goods_name']}已被管理员{user_info.user_name}下架！"
            del shop_data[group_id][str(arg)]
            shop_data[group_id] = reset_dict_num(shop_data[group_id])
            save_shop(shop_data)
            try:
                if XiuConfig().img:
                    pic = await get_msg_pic(f"@{shop_user_name}\n" + msg1)
                    await bot.send(event=event, message=MessageSegment.image(pic))
                else:
                    await bot.send(event=event, message=Message(msg1))
            except ActionFailed:
                pass

    else:
        msg = "这东西不是你的！"
        if XiuConfig().img:
            pic = await get_msg_pic(f"@{event.sender.nickname}\n" + msg)
            await bot.send_group_msg(group_id=int(send_group_id), message=MessageSegment.image(pic))
        else:
            await bot.send_group_msg(group_id=int(send_group_id), message=msg)
        await shop_off.finish()


@main_back.handle(parameterless=[Cooldown(cd_time=XiuConfig().user_info_cd, at_sender=True)])
async def main_back_(bot: Bot, event: GroupMessageEvent):
    """我的背包
    ["user_id", "goods_id", "goods_name", "goods_type", "goods_num", "create_time", "update_time",
    "remake", "day_num", "all_num", "action_time", "state"]
    """
    bot, send_group_id = await assign_bot(bot=bot, event=event)
    isUser, user_info, msg = check_user(event)
    if not isUser:
        if XiuConfig().img:
            pic = await get_msg_pic(f"@{event.sender.nickname}\n" + msg)
            await bot.send_group_msg(group_id=int(send_group_id), message=MessageSegment.image(pic))
        else:
            await bot.send_group_msg(group_id=int(send_group_id), message=msg)
        await main_back.finish()
    user_id = user_info.user_id
    msg = get_user_main_back_msg(user_id)

    if len(msg) >= 98: #背包更新
        # 将第一条消息和第二条消息合并为一条消息
        msg1 = [f"{user_info.user_name}的背包，持有灵石：{user_info.stone}枚"] + msg[:98]
        msg2 = [f"{user_info.user_name}的背包，持有灵石：{user_info.stone}枚"] + msg[98:]
        try:
            await send_forward_img(bot, event, '背包', bot.self_id, msg1)
            if msg2:
                # 如果有第三条及以后的消息，需要等待一段时间再发送，避免触发限制
                await asyncio.sleep(1)
                await send_forward_img(bot, event, '背包', bot.self_id, msg2)
        except ActionFailed:
            await main_back.finish("查看背包失败!", reply_message=True)
    else:
        msg = [f"{user_info.user_name}的背包，持有灵石：{user_info.stone}枚"] + msg
        try:
            await send_forward_img(bot, event, '背包', bot.self_id, msg)
        except ActionFailed:
            await main_back.finish("查看背包失败!", reply_message=True)

    await main_back.finish()



@no_use_zb.handle(parameterless=[Cooldown(at_sender=True)])
async def no_use_zb_(bot: Bot, event: GroupMessageEvent, args: Message = CommandArg()):
    """卸载物品（只支持装备）
    ["user_id", "goods_id", "goods_name", "goods_type", "goods_num", "create_time", "update_time",
    "remake", "day_num", "all_num", "action_time", "state"]
    """
    bot, send_group_id = await assign_bot(bot=bot, event=event)
    isUser, user_info, msg = check_user(event)
    if not isUser:
        if XiuConfig().img:
            pic = await get_msg_pic(f"@{event.sender.nickname}\n" + msg)
            await bot.send_group_msg(group_id=int(send_group_id), message=MessageSegment.image(pic))
        else:
            await bot.send_group_msg(group_id=int(send_group_id), message=msg)
        await no_use_zb.finish()
    user_id = user_info.user_id
    arg = args.extract_plain_text().strip()

    back_msg = sql_message.get_back_msg(user_id)  # 背包sql信息,list(back)
    if back_msg is None:
        msg = "道友的背包空空如也！"
        if XiuConfig().img:
            pic = await get_msg_pic(f"@{event.sender.nickname}\n" + msg)
            await bot.send_group_msg(group_id=int(send_group_id), message=MessageSegment.image(pic))
        else:
            await bot.send_group_msg(group_id=int(send_group_id), message=msg)
        await no_use_zb.finish()
    in_flag = False  # 判断指令是否正确，道具是否在背包内
    goods_id = None
    goods_type = None
    for back in back_msg:
        if arg == back.goods_name:
            in_flag = True
            goods_id = back.goods_id
            goods_type = back.goods_type
            break
    if not in_flag:
        msg = f"请检查该道具 {arg} 是否在背包内！"
        if XiuConfig().img:
            pic = await get_msg_pic(f"@{event.sender.nickname}\n" + msg)
            await bot.send_group_msg(group_id=int(send_group_id), message=MessageSegment.image(pic))
        else:
            await bot.send_group_msg(group_id=int(send_group_id), message=msg)
        await no_use_zb.finish()

    if goods_type == "装备":
        if not check_equipment_can_use(user_id, goods_id):
            sql_str, item_type = get_no_use_equipment_sql(user_id, goods_id)
            for sql in sql_str:
                sql_message.update_back_equipment(sql)
            if item_type == "法器":
                sql_message.updata_user_faqi_buff(user_id, 0)
            if item_type == "防具":
                sql_message.updata_user_armor_buff(user_id, 0)
            msg = f"成功卸载装备{arg}！"
            if XiuConfig().img:
                pic = await get_msg_pic(f"@{event.sender.nickname}\n" + msg)
                await bot.send_group_msg(group_id=int(send_group_id), message=MessageSegment.image(pic))
            else:
                await bot.send_group_msg(group_id=int(send_group_id), message=msg)
            await no_use_zb.finish()
        else:
            msg = f"装备没有被使用，无法卸载！"
            if XiuConfig().img:
                pic = await get_msg_pic(f"@{event.sender.nickname}\n" + msg)
                await bot.send_group_msg(group_id=int(send_group_id), message=MessageSegment.image(pic))
            else:
                await bot.send_group_msg(group_id=int(send_group_id), message=msg)
            await no_use_zb.finish()
    else:
        msg = f"目前只支持卸载装备！"
        if XiuConfig().img:
            pic = await get_msg_pic(f"@{event.sender.nickname}\n" + msg)
            await bot.send_group_msg(group_id=int(send_group_id), message=MessageSegment.image(pic))
        else:
            await bot.send_group_msg(group_id=int(send_group_id), message=msg)
        await no_use_zb.finish()


@use.handle(parameterless=[Cooldown(at_sender=True)])
async def use_(bot: Bot, event: GroupMessageEvent, args: Message = CommandArg()):
    """使用物品
    ["user_id", "goods_id", "goods_name", "goods_type", "goods_num", "create_time", "update_time",
    "remake", "day_num", "all_num", "action_time", "state"]
    """
    bot, send_group_id = await assign_bot(bot=bot, event=event)
    isUser, user_info, msg = check_user(event)
    if not isUser:
        if XiuConfig().img:
            pic = await get_msg_pic(f"@{event.sender.nickname}\n" + msg)
            await bot.send_group_msg(group_id=int(send_group_id), message=MessageSegment.image(pic))
        else:
            await bot.send_group_msg(group_id=int(send_group_id), message=msg)
        await use.finish()
    user_id = user_info.user_id
    args = args.extract_plain_text().split()
    arg = args[0]  # 
    back_msg = sql_message.get_back_msg(user_id)  # 背包sql信息,list(back)
    if back_msg is None:
        msg = "道友的背包空空如也！"
        if XiuConfig().img:
            pic = await get_msg_pic(f"@{event.sender.nickname}\n" + msg)
            await bot.send_group_msg(group_id=int(send_group_id), message=MessageSegment.image(pic))
        else:
            await bot.send_group_msg(group_id=int(send_group_id), message=msg)
        await use.finish()
    in_flag = False  # 判断指令是否正确，道具是否在背包内
    goods_id = None
    goods_type = None
    goods_num = None
    for back in back_msg:
        if arg == back.goods_name:
            in_flag = True
            goods_id = back.goods_id
            goods_type = back.goods_type
            goods_num = back.goods_num
            break
    if not in_flag:
        msg = f"请检查该道具 {arg} 是否在背包内！"
        if XiuConfig().img:
            pic = await get_msg_pic(f"@{event.sender.nickname}\n" + msg)
            await bot.send_group_msg(group_id=int(send_group_id), message=MessageSegment.image(pic))
        else:
            await bot.send_group_msg(group_id=int(send_group_id), message=msg)
        await use.finish()

    if goods_type == "装备":
        if not check_equipment_can_use(user_id, goods_id):
            msg = f"该装备已被装备，请勿重复装备！"
            if XiuConfig().img:
                pic = await get_msg_pic(f"@{event.sender.nickname}\n" + msg)
                await bot.send_group_msg(group_id=int(send_group_id), message=MessageSegment.image(pic))
            else:
                await bot.send_group_msg(group_id=int(send_group_id), message=msg)
            await use.finish()
        else:  # 可以装备
            sql_str, item_type = get_use_equipment_sql(user_id, goods_id)
            for sql in sql_str:
                sql_message.update_back_equipment(sql)
            if item_type == "法器":
                sql_message.updata_user_faqi_buff(user_id, goods_id)
            if item_type == "防具":
                sql_message.updata_user_armor_buff(user_id, goods_id)
            msg = f"成功装备{arg}！"
            if XiuConfig().img:
                pic = await get_msg_pic(f"@{event.sender.nickname}\n" + msg)
                await bot.send_group_msg(group_id=int(send_group_id), message=MessageSegment.image(pic))
            else:
                await bot.send_group_msg(group_id=int(send_group_id), message=msg)
            await use.finish()
    elif goods_type == "技能":
        user_buff_info = UserBuffDate(user_id).BuffInfo
        skill_info = items.get_data_by_item_id(goods_id)
        skill_type = skill_info['item_type']
        if skill_type == "神通":
            if int(user_buff_info.sec_buff) == int(goods_id):
                msg = f"道友已学会该神通：{skill_info['name']}，请勿重复学习！"
            else:  # 学习sql
                sql_message.update_back_j(user_id, goods_id)
                sql_message.updata_user_sec_buff(user_id, goods_id)
                msg = f"恭喜道友学会神通：{skill_info['name']}！"
        elif skill_type == "功法":
            if int(user_buff_info.main_buff) == int(goods_id):
                msg = f"道友已学会该功法：{skill_info['name']}，请勿重复学习！"
            else:  # 学习sql
                sql_message.update_back_j(user_id, goods_id)
                sql_message.updata_user_main_buff(user_id, goods_id)
                msg = f"恭喜道友学会功法：{skill_info['name']}！"
        elif skill_type == "辅修功法": #辅修功法1
            if int(user_buff_info.sub_buff) == int(goods_id):
                msg = f"道友已学会该辅修功法：{skill_info['name']}，请勿重复学习！"
            else:#学习sql
                sql_message.update_back_j(user_id, goods_id)
                sql_message.updata_user_sub_buff(user_id, goods_id)
                msg = f"恭喜道友学会辅修功法：{skill_info['name']}！"   
        else:
            msg = "发生未知错误！"

        if XiuConfig().img:
            pic = await get_msg_pic(f"@{event.sender.nickname}\n" + msg)
            await bot.send_group_msg(group_id=int(send_group_id), message=MessageSegment.image(pic))
        else:
            await bot.send_group_msg(group_id=int(send_group_id), message=msg)
        await use.finish()
    elif goods_type == "丹药":
        num = None
        try:
            if 1 <= int(args[1]) <= int(goods_num):
                num = int(args[1])
        except:
            num = 1
        msg = check_use_elixir(user_id, goods_id, num)
        if XiuConfig().img:
            pic = await get_msg_pic(f"@{event.sender.nickname}\n" + msg)
            await bot.send_group_msg(group_id=int(send_group_id), message=MessageSegment.image(pic))
        else:
            await bot.send_group_msg(group_id=int(send_group_id), message=msg)
        await use.finish()
    elif goods_type =="神物":
        num = None
        try:
            if 1 <= int(args[1]) <= int(goods_num):
                num = int(args[1])
        except:
            num = 1
        goods_info = items.get_data_by_item_id(goods_id)
        user_info = sql_message.get_user_message(user_id)
        user_rank = USERRANK[user_info.level]
        goods_rank = goods_info['rank']
        goods_name = goods_info['name']
        if goods_rank < user_rank:  # 使用限制
                msg = f"神物：{goods_name}的使用境界为{goods_info['境界']}以上，道友不满足使用条件！"
        else:
                exp = goods_info['buff'] * num
                user_hp = int(user_info.hp + (exp / 2))
                user_mp = int(user_info.mp + exp)
                user_atk = int(user_info.atk + (exp / 10))
                sql_message.update_exp(user_id, exp)
                sql_message.update_power2(user_id)  # 更新战力
                sql_message.update_user_attribute(user_id, user_hp, user_mp, user_atk)  # 这种事情要放在update_exp方法里
                sql_message.update_back_j(user_id, goods_id, num=num, use_key=1)
                msg = f"道友成功使用神物：{goods_name} {num} ,修为增加{exp}点！"
        if XiuConfig().img:
            pic = await get_msg_pic(f"@{event.sender.nickname}\n" + msg)
            await bot.send_group_msg(group_id=int(send_group_id), message=MessageSegment.image(pic))
        else:
            await bot.send_group_msg(group_id=int(send_group_id), message=msg)
        await use.finish()
        
    elif goods_type =="礼包":
        num = None
        try:
            if 1 <= int(args[1]) <= int(goods_num):
                num = int(args[1])
        except:
            num = 1
        goods_info = items.get_data_by_item_id(goods_id)
        user_info = sql_message.get_user_message(user_id)
        user_rank = USERRANK[user_info.level]
        goods_name = goods_info['name']
        goods_id1 = goods_info['buff_1']
        goods_id2 = goods_info['buff_2']
        goods_id3 = goods_info['buff_3']
        goods_name1 = goods_info['name_1']
        goods_name2 = goods_info['name_2']
        goods_name3 = goods_info['name_3']
        goods_type1 = goods_info['type_1']
        goods_type2 = goods_info['type_2']
        goods_type3 = goods_info['type_3']
        
        sql_message.send_back(user_id, goods_id1, goods_name1, goods_type1, 1)# 增加用户道具
        sql_message.send_back(user_id, goods_id2, goods_name2, goods_type2, 2)
        sql_message.send_back(user_id, goods_id3, goods_name3, goods_type3, 2)
        sql_message.update_back_j(user_id, goods_id, num=num, use_key=0)
        msg = "道友打开了{},里面居然是{}、{}、{}".format(goods_name,goods_name1,goods_name2,goods_name3)
        if XiuConfig().img:
            pic = await get_msg_pic(f"@{event.sender.nickname}\n" + msg)
            await bot.send_group_msg(group_id=int(send_group_id), message=MessageSegment.image(pic))
        else:
            await bot.send_group_msg(group_id=int(send_group_id), message=msg)
        await use.finish()   
        
    elif goods_type == "聚灵旗":
        msg = get_use_jlq_msg(user_id, goods_id)
        if XiuConfig().img:
            pic = await get_msg_pic(f"@{event.sender.nickname}\n" + msg)
            await bot.send_group_msg(group_id=int(send_group_id), message=MessageSegment.image(pic))
        else:
            await bot.send_group_msg(group_id=int(send_group_id), message=msg)
        await use.finish()
    else:
        msg = '该类型物品调试中，未开启！'
        if XiuConfig().img:
            pic = await get_msg_pic(f"@{event.sender.nickname}\n" + msg)
            await bot.send_group_msg(group_id=int(send_group_id), message=MessageSegment.image(pic))
        else:
            await bot.send_group_msg(group_id=int(send_group_id), message=msg)
        await use.finish()


@creat_auction.handle(parameterless=[Cooldown(at_sender=True)])
async def creat_auction_(bot: Bot, event: GroupMessageEvent):
    group_id = str(event.group_id)
    bot = await assign_bot_group(group_id=group_id)
    if group_id not in groups:
        msg = '本群尚未开启拍卖会功能，请联系管理员开启！'
        if XiuConfig().img:
            pic = await get_msg_pic(f"@{event.sender.nickname}\n" + msg)
            await bot.send_group_msg(group_id=int(group_id), message=MessageSegment.image(pic))
        else:
            await bot.send_group_msg(group_id=int(group_id), message=msg)
        await creat_auction.finish()

    global auction
    if auction != {}:
        msg = f'本群已存在一场拍卖会，请等待拍卖会结束！'
        if XiuConfig().img:
            pic = await get_msg_pic(f"@{event.sender.nickname}\n" + msg)
            await bot.send_group_msg(group_id=int(group_id), message=MessageSegment.image(pic))
        else:
            await bot.send_group_msg(group_id=int(group_id), message=msg)
        await creat_auction.finish()
    auction_id = None
    try:
        auction_id_list = get_auction_id_list()
        auction_id = random.choice(auction_id_list)
    except LookupError:
        msg = "获取不到拍卖物品的信息，请检查配置文件！"
        if XiuConfig().img:
            pic = await get_msg_pic(f"@{event.sender.nickname}\n" + msg)
            await bot.send_group_msg(group_id=int(group_id), message=MessageSegment.image(pic))
        else:
            await bot.send_group_msg(group_id=int(group_id), message=msg)
        await creat_auction.finish()

    auction_info = items.get_data_by_item_id(auction_id)
    start_price = get_auction_price_by_id(auction_id)['start_price']
    msg = '本次拍卖的物品为：\n'
    msg += get_auction_msg(auction_id)
    msg += f"\n底价为{start_price}灵石"
    msg += "\n请诸位道友发送 拍卖+金额 来进行拍卖吧！"
    msg += f"\n本次竞拍时间为:{AUCTIONSLEEPTIME}秒！"

    auction['id'] = auction_id
    auction['user_id'] = 0
    auction['now_price'] = start_price
    auction['name'] = auction_info['name']
    auction['type'] = auction_info['type']
    auction['start_time'] = datetime.now()
    auction['group_id'] = group_id

    for group_id in groups:
        bot = await assign_bot_group(group_id=group_id)
        try:
            if XiuConfig().img:
                pic = await get_msg_pic(msg)
                await bot.send_group_msg(group_id=int(group_id), message=MessageSegment.image(pic))
            else:
                await bot.send_group_msg(group_id=int(group_id), message=msg)
        except ActionFailed:  # 发送群消息失败
            continue
    await asyncio.sleep(AUCTIONSLEEPTIME)  # 先睡60秒

    global auction_offer_flag, auction_offer_time_count, auction_offer_all_count
    while auction_offer_flag:  # 有人拍卖
        if auction_offer_all_count == 0:
            auction_offer_flag = False
            break
        logger.info(f"有人拍卖，本次等待时间：{auction_offer_all_count * AUCTIONOFFERSLEEPTIME}秒")
        first_time = auction_offer_all_count * AUCTIONOFFERSLEEPTIME
        auction_offer_all_count = 0
        auction_offer_flag = False
        await asyncio.sleep(first_time)

    logger.info(f"等待时间结束，总计等待时间{auction_offer_time_count * AUCTIONOFFERSLEEPTIME}秒")
    if auction['user_id'] == 0:
        msg = "很可惜，本次拍卖会流拍了！"
        auction = {}
        for group_id in groups:
            bot = await assign_bot_group(group_id=group_id)
            try:
                if XiuConfig().img:
                    pic = await get_msg_pic(msg)
                    await bot.send_group_msg(group_id=int(group_id), message=MessageSegment.image(pic))
                else:
                    await bot.send_group_msg(group_id=int(group_id), message=msg)
            except ActionFailed:  # 发送群消息失败
                continue
        await creat_auction.finish()

    user_info = sql_message.get_user_message(auction['user_id'])
    now_price = int(auction['now_price'])
    user_stone = user_info.stone
    if user_stone < now_price:
        msg = f"拍卖会结算！竞拍者灵石小于拍卖，判定为捣乱，捣乱次数+1!"
        if XiuConfig().img:
            pic = await get_msg_pic(msg)
            await bot.send_group_msg(group_id=int(group_id), message=MessageSegment.image(pic))
        else:
            await bot.send_group_msg(group_id=int(group_id), message=msg)
        await creat_auction.finish()

    msg = "本次拍卖会结束！"
    msg += f"恭喜来自群{auction['group_id']}的{user_info.user_name}道友成功拍卖获得：{auction['type']}-{auction['name']}!"
    for group_id in groups:
        bot = await assign_bot_group(group_id=group_id)
        try:
            if XiuConfig().img:
                pic = await get_msg_pic(msg)
                await bot.send_group_msg(group_id=int(group_id), message=MessageSegment.image(pic))
            else:
                await bot.send_group_msg(group_id=int(group_id), message=msg)
        except ActionFailed:  # 发送群消息失败
            continue

    sql_message.send_back(user_info.user_id, auction['id'], auction['name'], auction['type'], 1)
    sql_message.update_ls(user_info.user_id, int(auction['now_price']), 2)
    auction = {}
    auction_offer_time_count = 0
    await creat_auction.finish()


@offer_auction.handle(parameterless=[Cooldown(1.4, isolate_level=CooldownIsolateLevel.GLOBAL)])
async def offer_auction_(bot: Bot, event: GroupMessageEvent, args: Message = CommandArg()):
    group_id = str(event.group_id)
    bot = await assign_bot_group(group_id=group_id)
    if group_id not in groups:
        msg = '本群尚未开启拍卖会功能，请联系管理员开启！'
        if XiuConfig().img:
            pic = await get_msg_pic(f"@{event.sender.nickname}\n" + msg)
            await bot.send_group_msg(group_id=int(group_id), message=MessageSegment.image(pic))
        else:
            await bot.send_group_msg(group_id=int(group_id), message=msg)
        await creat_auction.finish()

    isUser, user_info, msg = check_user(event)
    if not isUser:
        if XiuConfig().img:
            pic = await get_msg_pic(f"@{event.sender.nickname}\n" + msg)
            await bot.send_group_msg(group_id=int(group_id), message=MessageSegment.image(pic))
        else:
            await bot.send_group_msg(group_id=int(group_id), message=msg)
        await creat_auction.finish()

    global auction
    if auction == {}:
        msg = f'本群不存在拍卖会，请等待拍卖会开启！'
        if XiuConfig().img:
            pic = await get_msg_pic(f"@{event.sender.nickname}\n" + msg)
            await bot.send_group_msg(group_id=int(group_id), message=MessageSegment.image(pic))
        else:
            await bot.send_group_msg(group_id=int(group_id), message=msg)
        await creat_auction.finish()

    price = args.extract_plain_text().strip()
    try:
        price = int(price)
    except ValueError:
        msg = f"请发送正确的灵石数量"
        if XiuConfig().img:
            pic = await get_msg_pic(f"@{event.sender.nickname}\n" + msg)
            await bot.send_group_msg(group_id=int(group_id), message=MessageSegment.image(pic))
        else:
            await bot.send_group_msg(group_id=int(group_id), message=msg)
        await creat_auction.finish()

    now_price = auction['now_price']
    min_price = int(now_price * 0.05)  # 最低加价5%
    if price <= 0 or price <= auction['now_price'] or price > user_info.stone:
        msg = f"走开走开，别捣乱！小心清空你灵石捏！"
        if XiuConfig().img:
            pic = await get_msg_pic(f"@{event.sender.nickname}\n" + msg)
            await bot.send_group_msg(group_id=int(group_id), message=MessageSegment.image(pic))
        else:
            await bot.send_group_msg(group_id=int(group_id), message=msg)
        await creat_auction.finish()
    if price - now_price < min_price:
        msg = f"拍卖不得少于当前竞拍价的5%，目前最少加价为：{min_price}灵石，目前竞拍价为：{now_price}!"
        if XiuConfig().img:
            pic = await get_msg_pic(f"@{event.sender.nickname}\n" + msg)
            await bot.send_group_msg(group_id=int(group_id), message=MessageSegment.image(pic))
        else:
            await bot.send_group_msg(group_id=int(group_id), message=msg)
        await creat_auction.finish()

    global auction_offer_flag, auction_offer_time_count, auction_offer_all_count
    auction_offer_flag = True  # 有人拍卖
    auction_offer_time_count += 1
    auction_offer_all_count += 1
    auction['user_id'] = user_info.user_id
    auction['now_price'] = price
    auction['group_id'] = group_id
    now_time = datetime.now()
    dif_time = OtherSet().date_diff(now_time, auction['start_time'])
    msg = (
        f"来自群{group_id}的{user_info.user_name}道友拍卖：{price}枚灵石！"
        f"竞拍时间增加：{AUCTIONOFFERSLEEPTIME}秒，竞拍剩余时间：{int(AUCTIONSLEEPTIME - dif_time + AUCTIONOFFERSLEEPTIME * auction_offer_time_count)}秒"
    )
    error_msg = None
    for group_id in groups:
        bot = await assign_bot_group(group_id=group_id)
        try:
            if XiuConfig().img:
                pic = await get_msg_pic(msg)
                await bot.send_group_msg(group_id=int(group_id), message=MessageSegment.image(pic))
            else:
                await bot.send_group_msg(group_id=int(group_id), message=msg)
        except ActionFailed:
            error_msg = f"消息发送失败，可能被风控，当前拍卖物品金额为：{auction['now_price']}！"
            continue
    logger.info(
        f"有人拍卖，拍卖标志：{auction_offer_flag}，当前等待时间：{auction_offer_all_count * AUCTIONOFFERSLEEPTIME}，总计拍卖次数：{auction_offer_time_count}")
    if error_msg is None:
        await offer_auction.finish()
    else:
        msg = error_msg
        if XiuConfig().img:
            pic = await get_msg_pic(msg)
            await bot.send_group_msg(group_id=int(group_id), message=MessageSegment.image(pic))
        else:
            await bot.send_group_msg(group_id=int(group_id), message=msg)
        await creat_auction.finish()


@set_auction.handle(parameterless=[Cooldown(at_sender=True)])
async def set_auction_(bot: Bot, event: GroupMessageEvent, args: Message = CommandArg()):
    bot, send_group_id = await assign_bot(bot=bot, event=event)
    mode = args.extract_plain_text().strip()
    group_id = str(event.group_id)
    is_in_group = is_in_groups(event)  # True在，False不在

    if mode == '开启':
        if is_in_group:
            msg = f'本群已开启群交流会，请勿重复开启!'
            if XiuConfig().img:
                pic = await get_msg_pic(f"@{event.sender.nickname}\n" + msg)
                await bot.send_group_msg(group_id=int(send_group_id), message=MessageSegment.image(pic))
            else:
                await bot.send_group_msg(group_id=int(send_group_id), message=msg)
            await set_auction.finish()
        else:
            config['open'].append(group_id)
            savef(config)
            msg = "已开启群交流会"
            if XiuConfig().img:
                pic = await get_msg_pic(f"@{event.sender.nickname}\n" + msg)
                await bot.send_group_msg(group_id=int(send_group_id), message=MessageSegment.image(pic))
            else:
                await bot.send_group_msg(group_id=int(send_group_id), message=msg)
            await set_auction.finish()

    elif mode == '关闭':
        if is_in_group:
            config['open'].remove(group_id)
            savef(config)
            msg = f'已关闭本群交流会!'
            if XiuConfig().img:
                pic = await get_msg_pic(f"@{event.sender.nickname}\n" + msg)
                await bot.send_group_msg(group_id=int(send_group_id), message=MessageSegment.image(pic))
            else:
                await bot.send_group_msg(group_id=int(send_group_id), message=msg)
            await set_auction.finish()
        else:
            msg = f'本群未开启群交流会!'
            if XiuConfig().img:
                pic = await get_msg_pic(f"@{event.sender.nickname}\n" + msg)
                await bot.send_group_msg(group_id=int(send_group_id), message=MessageSegment.image(pic))
            else:
                await bot.send_group_msg(group_id=int(send_group_id), message=msg)
            await set_auction.finish()

    else:
        msg = __back_help__
        if XiuConfig().img:
            pic = await get_msg_pic(f"@{event.sender.nickname}\n" + msg)
            await bot.send_group_msg(group_id=int(send_group_id), message=MessageSegment.image(pic))
        else:
            await bot.send_group_msg(group_id=int(send_group_id), message=msg)
        await set_auction.finish()


@chakan_wupin.handle(parameterless=[Cooldown(at_sender=True)])
async def chakan_wupin_(bot: Bot, event: GroupMessageEvent, args: Message = CommandArg()):
    """查看修仙界所有物品列表"""
    bot, send_group_id = await assign_bot(bot=bot, event=event)
    args = args.extract_plain_text().strip()
    list_tp = []
    if args not in ["功法", "辅修功法", "神通", "丹药", "合成丹药", "法器", "防具"]:
        msg = "请输入正确类型【功法|辅修功法|神通|丹药|合成丹药|法器|防具】！！！"
        if XiuConfig().img:
            pic = await get_msg_pic(f"@{event.sender.nickname}\n" + msg)
            await bot.send_group_msg(group_id=int(send_group_id), message=MessageSegment.image(pic))
        else:
            await bot.send_group_msg(group_id=int(send_group_id), message=msg)
        await chakan_wupin.finish()
    else:
        if args == "功法":
            gf_data = items.get_data_by_item_type(['功法'])
            for x in gf_data:
                name = gf_data[x]['name']
                rank = gf_data[x]['level']
                msg = "※{}:{}".format(rank, name)
                list_tp.append(
                    {"type": "node", "data": {"name": f"修仙界物品列表{args}", "uin": bot.self_id,
                                              "content": msg}})
        elif args == "辅修功法":
            gf_data = items.get_data_by_item_type(['辅修功法'])
            for x in gf_data:
                name = gf_data[x]['name']
                rank = gf_data[x]['level']
                msg = "※{}:{}".format(rank, name)
                list_tp.append(
                    {"type": "node", "data": {"name": f"修仙界物品列表{args}", "uin": bot.self_id,
                                              "content": msg}})
        elif args == "神通":
            st_data = items.get_data_by_item_type(['神通'])
            for x in st_data:
                name = st_data[x]['name']
                rank = st_data[x]['level']
                msg = "※{}:{}".format(rank, name)
                list_tp.append(
                    {"type": "node", "data": {"name": f"修仙界物品列表{args}", "uin": bot.self_id,
                                              "content": msg}})
        elif args == "丹药":
            dy_data = items.get_data_by_item_type(['丹药'])
            for x in dy_data:
                name = dy_data[x]['name']
                rank = dy_data[x]['境界']
                desc = dy_data[x]['desc']
                msg = "※{}丹药:{}，效果：{}\n".format(rank, name, desc)
                list_tp.append(
                    {"type": "node", "data": {"name": f"修仙界物品列表{args}", "uin": bot.self_id,
                                              "content": msg}})
        elif args == "合成丹药":
            hcdy_data = items.get_data_by_item_type(['合成丹药'])
            for x in hcdy_data:
                name = hcdy_data[x]['name']
                rank = hcdy_data[x]['境界']
                desc = hcdy_data[x]['desc']
                msg = "※{}丹药:{}，效果：{}\n\n".format(rank, name, desc)
                list_tp.append(
                    {"type": "node", "data": {"name": f"修仙界物品列表{args}", "uin": bot.self_id,
                                              "content": msg}})
        elif args == "法器":
            fq_data = items.get_data_by_item_type(['法器'])
            for x in fq_data:
                name = fq_data[x]['name']
                rank = fq_data[x]['level']
                msg = "※{}:{}".format(rank, name)
                list_tp.append(
                    {"type": "node", "data": {"name": f"修仙界物品列表{args}", "uin": bot.self_id,
                                              "content": msg}})
        elif args == "防具":
            fj_data = items.get_data_by_item_type(['防具'])
            for x in fj_data:
                name = fj_data[x]['name']
                rank = fj_data[x]['level']
                msg = "※{}:{}".format(rank, name)
                list_tp.append(
                    {"type": "node", "data": {"name": f"修仙界物品列表{args}", "uin": bot.self_id,
                                              "content": msg}})
        try:
            await send_forward_img_list(bot, event, list_tp)
        except ActionFailed:
            msg = "未知原因，查看失败!"
            if XiuConfig().img:
                pic = await get_msg_pic(f"@{event.sender.nickname}\n" + msg)
                await bot.send_group_msg(group_id=int(send_group_id), message=MessageSegment.image(pic))
            else:
                await bot.send_group_msg(group_id=int(send_group_id), message=msg)
        await chakan_wupin.finish()


@shop_off_all.handle(parameterless=[Cooldown(60, isolate_level=CooldownIsolateLevel.GROUP, parallel=1)])
async def shop_off_all_(bot: Bot, event: GroupMessageEvent):
    """坊市清空"""
    bot, send_group_id = await assign_bot(bot=bot, event=event)
    isUser, user_info, msg = check_user(event)
    if not isUser:
        if XiuConfig().img:
            pic = await get_msg_pic(f"@{event.sender.nickname}\n" + msg)
            await bot.send_group_msg(group_id=int(send_group_id), message=MessageSegment.image(pic))
        else:
            await bot.send_group_msg(group_id=int(send_group_id), message=msg)
        await shop_off_all.finish()
    group_id = str(event.group_id)
    shop_data = get_shop_data(group_id)
    if shop_data[group_id] == {}:
        msg = "坊市目前空空如也！"
        if XiuConfig().img:
            pic = await get_msg_pic(f"@{event.sender.nickname}\n" + msg)
            await bot.send_group_msg(group_id=int(send_group_id), message=MessageSegment.image(pic))
        else:
            await bot.send_group_msg(group_id=int(send_group_id), message=msg)
        await shop_off_all.finish()

    msg = "正在清空,稍等！"
    if XiuConfig().img:
        pic = await get_msg_pic(f"@{event.sender.nickname}\n" + msg)
        await bot.send_group_msg(group_id=int(send_group_id), message=MessageSegment.image(pic))
    else:
        await bot.send_group_msg(group_id=int(send_group_id), message=msg)

    list_msg = []
    msg = ""
    num = len(shop_data[group_id])
    for x in range(num):
        x = num - x
        if shop_data[group_id][str(x)]['user_id'] == 0:  # 这么写为了防止bot.send发送失败，不结算
            msg += f"成功下架物品：{shop_data[group_id][str(x)]['goods_name']}!\n"
            del shop_data[group_id][str(x)]
            save_shop(shop_data)
        else:
            sql_message.send_back(shop_data[group_id][str(x)]['user_id'], shop_data[group_id][str(x)]['goods_id'],
                                  shop_data[group_id][str(x)]['goods_name'],
                                  shop_data[group_id][str(x)]['goods_type'], 1)
            msg += f"成功下架{shop_data[group_id][str(x)]['user_name']}的物品：{shop_data[group_id][str(x)]['goods_name']}!\n"
            del shop_data[group_id][str(x)]
            save_shop(shop_data)
    shop_data[group_id] = reset_dict_num(shop_data[group_id])
    save_shop(shop_data)
    list_msg.append(
                    {"type": "node", "data": {"name": f"执行清空坊市ing", "uin": bot.self_id,
                                              "content": msg}})
    try:
        await send_forward_img_list(bot, event, list_msg)
    except ActionFailed:
        if XiuConfig().img:
            pic = await get_msg_pic(f"@{event.sender.nickname}\n" + msg)
            await bot.send_group_msg(group_id=int(send_group_id), message=MessageSegment.image(pic))
        else:
            await bot.send_group_msg(group_id=int(send_group_id), message=msg)
    await shop_off_all.finish()


def reset_dict_num(dict_):
    i = 1
    temp_dict = {}
    for k, v in dict_.items():
        temp_dict[i] = v
        temp_dict[i]['编号'] = i
        i += 1
    return temp_dict


def get_auction_id_list():
    auctions = config['auctions']
    auction_id_list = []
    for k, v in auctions.items():
        auction_id_list.append(v['id'])
    return auction_id_list


def get_auction_price_by_id(id):
    auctions = config['auctions']
    auction_info = None
    for k, v in auctions.items():
        if int(v['id']) == int(id):
            auction_info = auctions[k]
            break
    return auction_info


def is_in_groups(event: GroupMessageEvent):
    return str(event.group_id) in groups


def get_auction_msg(auction_id):
    item_info = items.get_data_by_item_id(auction_id)
    _type = item_info['type']
    msg = None
    if _type == "装备":
        if item_info['item_type'] == "防具":
            msg = get_armor_info_msg(auction_id, item_info)
        if item_info['item_type'] == '法器':
            msg = get_weapon_info_msg(auction_id, item_info)

    if _type == "技能":
        if item_info['item_type'] == '神通':
            msg = f"{item_info['level']}神通-{item_info['name']}:"
            msg += get_sec_msg(item_info)
        if item_info['item_type'] == '功法':
            msg = f"{item_info['level']}功法-"
            msg += get_main_info_msg(auction_id)[1]
        if item_info['item_type'] == '辅修功法': #辅修功法10
            msg = f"{item_info['level']}辅修功法-"
            msg += get_sub_info_msg(auction_id)[1]
            
    if _type == "神物":
        msg = f"名字：{item_info['name']}\n"
        msg += f"效果:{item_info['desc']}"

    if _type == "丹药":
        msg = f"名字：{item_info['name']}\n"
        msg += f"效果:{item_info['desc']}"

    return msg
