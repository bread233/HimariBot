"""虚神界 Web 业务辅助模块。

复用 QQ 端既有数据容器与计算（impart_pk / xu_world / XIUXIAN_IMPART_BUFF /
XiuxianDateManage / OtherSet / UserBuffDate / jsondata / XiuConfig），
不在 Web 复制全套 DB 逻辑，也不构造假的 NoneBot event。
"""

import asyncio
import random
from datetime import datetime

from .. import NICKNAME
from ..xiuxian_config import XiuConfig
from ..xiuxian_utils.data_source import jsondata
from ..xiuxian_utils.utils import (
    check_user_type,
    number_to,
    update_statistics_value,
)
from ..xiuxian_utils.xiuxian2_handle import (
    OtherSet,
    UserBuffDate,
    XIUXIAN_IMPART_BUFF,
    XiuxianDateManage,
)
from ..xiuxian_impart_pk.impart_pk import impart_pk
from ..xiuxian_impart_pk.xu_world import xu_world
from ..xiuxian_impart_pk import impart_pk_uitls

game_sql = XiuxianDateManage()
xiuxian_impart = XIUXIAN_IMPART_BUFF()

IMPART_LEVEL_NAME = {
    0: "凡尘迷雾", 1: "灵气初现", 2: "感气之渊",
    3: "练气云海", 4: "筑基灵台", 5: "金丹道场",
    6: "元神幻境", 7: "化神星域", 8: "炼神火宅",
    9: "返虚古路", 10: "大乘天阶", 11: "虚道玄门",
    12: "斩我剑冢", 13: "遁一星河", 14: "至尊王座",
    15: "微光圣境", 16: "星芒神域", 17: "月华仙宫",
    18: "耀日天穹", 19: "祭道荒原", 20: "自在净土",
    21: "破虚之隙", 22: "无界瀚海", 23: "混元道源",
    24: "造化玉池", 25: "永恒神庭", 26: "至高天阙",
    27: "大道尽头", 28: "法则本源", 29: "混沌核心",
    30: "虚神本源",
}

# 探索随机事件权重：stay, fail, down, up, down_rate, up_rate
EXPLORE_RATES = [0.15, 0.15, 0.25, 0.25, 0.10, 0.10]


def _run_async(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _ensure_impart(user_id):
    """确保 xiuxian_impart 用户记录存在并返回，等价 QQ 端 impart_pk_check。"""
    data = xiuxian_impart.get_user_impart_info_with_id(user_id)
    if data is None:
        xiuxian_impart._create_user(user_id)
        data = xiuxian_impart.get_user_impart_info_with_id(user_id)
    return data or {}


def _parse_dt(value):
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    value = str(value)
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


def world_status(user_id):
    """虚神界状态（info/修炼时间/次数/加成/投影/闭关）。"""
    user_data = impart_pk.find_user_data(user_id) or {}
    impart_data = _ensure_impart(user_id)
    impart_lv = int(impart_data.get("impart_lv") or 0)
    exp_day = int(impart_data.get("exp_day") or 0)
    stone_num = int(impart_data.get("stone_num") or 0)
    impart_num = int(user_data.get("impart_num") or 0)
    pk_num = int(user_data.get("pk_num") or 0)

    try:
        blessed_spot = UserBuffDate(user_id).BuffInfo["blessed_spot"] or 0
        user_blessed_spot_data = blessed_spot * 0.5 / 1.5
    except Exception:
        user_blessed_spot_data = 0

    exp_bonus = impart_lv * 0.15
    efficiency = int((exp_bonus + user_blessed_spot_data) * 100)

    is_type, _ = check_user_type(user_id, 4)
    in_retreat = bool(is_type)
    projected = bool(xu_world.check_xu_world_user_id(user_id))

    retreat_started_at = None
    elapsed_minutes = 0
    if in_retreat:
        user_cd = game_sql.get_user_cd(user_id)
        retreat_started_at = user_cd.get("create_time") if user_cd else None
        start = _parse_dt(retreat_started_at)
        if start:
            elapsed_minutes = int((datetime.now() - start).total_seconds() // 60)

    return {
        "impart_lv": impart_lv,
        "level_name": IMPART_LEVEL_NAME.get(impart_lv, "未知秘境"),
        "exp_day": exp_day,
        "impart_num": impart_num,
        "pk_num": pk_num,
        "stone_num": stone_num,
        "exp_bonus_percent": int(exp_bonus * 100),
        "exp_bonus": exp_bonus,
        "blessed_spot_percent": int(user_blessed_spot_data * 100),
        "efficiency_percent": efficiency,
        "in_retreat": in_retreat,
        "retreat_started_at": retreat_started_at,
        "elapsed_minutes": elapsed_minutes,
        "projected": projected,
    }


def project(user_id):
    """投影虚神界。复用 xu_world.add_xu_world，不手写第二份容器。"""
    user_data = impart_pk.find_user_data(user_id) or {}
    if int(user_data.get("pk_num") or 0) <= 0:
        return {"success": False, "message": "道友今日次数已用尽，无法在加入虚神界！"}
    message = xu_world.add_xu_world(user_id)
    return {
        "success": "成功" in message,
        "message": message,
        "projected": bool(xu_world.check_xu_world_user_id(user_id)),
    }


def projections(user_id):
    """虚神界投影列表（来自 xu_world + impart_pk + 道号）。"""
    xu_list = xu_world.all_xu_world_user() or []
    result = []
    for x in range(len(xu_list)):
        uid = xu_list[x]
        user_data = impart_pk.find_user_data(uid)
        if not user_data:
            continue
        info = game_sql.get_user_info_with_id(uid)
        name = info["user_name"] if info else "未知修士"
        result.append({
            "number": user_data.get("number"),
            "index": x,
            "user_id": str(uid),
            "name": name,
            "win_num": int(user_data.get("win_num") or 0),
            "pk_num": int(user_data.get("pk_num") or 0),
            "is_self": str(uid) == str(user_id),
        })
    return result


def rankings():
    """虚神界等级排行榜 TOP50。"""
    rows = xiuxian_impart.get_impart_rank() or []
    result = []
    for i in rows:
        info = game_sql.get_user_info_with_id(i["user_id"])
        result.append({
            "name": info["user_name"] if info else "未知修士",
            "impart_lv": int(i["impart_lv"] or 0),
            "level_name": IMPART_LEVEL_NAME.get(int(i["impart_lv"] or 0), "未知秘境"),
        })
    return result[:50]


def _humanize_battle_msg(msg):
    if isinstance(msg, str):
        return [line.strip() for line in msg.split("\n") if line.strip()]
    return [str(msg)] if msg else []


def _run_bot_duel(player_name):
    """与机器人对决一场，返回 (text_msg, win)。win: 1胜 2负 None异常。"""
    return _run_async(impart_pk_uitls.impart_pk_now_msg_to_bot(player_name, NICKNAME))


def _run_player_duel(player_1, player_1_name, player_2, player_2_name):
    """与其他玩家投影对决一场。"""
    return _run_async(impart_pk_uitls.impart_pk_now_msg(
        player_1, player_1_name, player_2, player_2_name
    ))


def validate_challenge(user_id, target_number=None, max_loss_count=1):
    """仅校验虚神界对决参数与目标，不产生任何胜负/结晶/次数副作用。"""
    user_data = impart_pk.find_user_data(user_id) or {}
    remaining_pk = int(user_data.get("pk_num") or 0)
    if remaining_pk <= 0:
        return {"success": False, "message": "道友今日次数耗尽，明天再来吧！"}
    try:
        max_loss_count = int(max_loss_count)
    except (TypeError, ValueError):
        max_loss_count = 1
    if max_loss_count <= 0:
        return {"success": False, "message": "失败次数必须大于0！"}
    if max_loss_count > remaining_pk:
        return {"success": False, "message": f"道友今日剩余次数只有{remaining_pk}次，无法承受{max_loss_count}次失败！"}
    if target_number not in (None, ""):
        try:
            num = int(target_number) - 1
        except (TypeError, ValueError):
            return {"success": False, "message": "编号解析异常，应全为数字!"}
        xu_world_list = xu_world.all_xu_world_user() or []
        if num < 0 or num >= len(xu_world_list):
            return {"success": False, "message": "编号解析异常，虚神界没有此编号道友!"}
        player_2 = xu_world_list[num]
        if str(user_id) == str(player_2):
            return {"success": False, "message": "道友不能挑战自己的投影!"}
        if not xu_world.check_xu_world_user_id(player_2):
            info = game_sql.get_user_info_with_id(player_2) or {}
            return {"success": False, "message": f"道友{info.get('user_name') or player_2}已离开虚神界！"}
    return {"success": True, "max_loss_count": max_loss_count}


def challenge(user_id, target_number=None, max_loss_count=1):
    """虚神界对决，完整对齐 QQ 端规则。返回结构化 battle 结果。"""
    validation = validate_challenge(user_id, target_number, max_loss_count)
    if not validation.get("success"):
        return validation
    max_loss_count = validation["max_loss_count"]
    user_data = impart_pk.find_user_data(user_id) or {}
    if int(user_data.get("pk_num") or 0) <= 0:
        return {"success": False, "message": "道友今日次数耗尽，明天再来吧！"}

    try:
        max_loss_count = int(max_loss_count)
    except (TypeError, ValueError):
        max_loss_count = 1
    if max_loss_count <= 0:
        return {"success": False, "message": "失败次数必须大于0！"}
    remaining_pk = int(user_data.get("pk_num") or 0)
    if max_loss_count > remaining_pk:
        return {"success": False, "message": f"道友今日剩余次数只有{remaining_pk}次，无法承受{max_loss_count}次失败！"}

    user_info = game_sql.get_user_info_with_id(user_id) or {}
    player_1_name = user_info.get("user_name") or str(user_id)

    player_1_stones = 0
    player_2_stones = 0
    current_loss_count = 0
    total_battles = 0
    total_wins = 0
    total_losses = 0
    battles = []

    if not target_number:
        while current_loss_count < max_loss_count and int(user_data.get("pk_num") or 0) > 0:
            total_battles += 1
            msg, win = _run_bot_duel(player_1_name)
            battle = {
                "round": total_battles,
                "opponent": NICKNAME,
                "logs": _humanize_battle_msg(msg),
                "result": "none",
                "stones_gained": 0,
                "summary": "",
            }
            if win == 1:
                impart_pk.update_user_data(user_id, True)
                xiuxian_impart.update_stone_num(20, user_id, 1)
                player_1_stones += 20
                total_wins += 1
                battle["result"] = "win"
                battle["stones_gained"] = 20
                battle["summary"] = f"道友{player_1_name}获胜，获得思恋结晶20颗"
            elif win == 2:
                impart_pk.update_user_data(user_id, False)
                xiuxian_impart.update_stone_num(10, user_id, 1)
                player_1_stones += 10
                current_loss_count += 1
                total_losses += 1
                battle["result"] = "lose"
                battle["stones_gained"] = 10
                battle["summary"] = f"道友{player_1_name}败了，消耗1次次数，获得思恋结晶10颗"
                user_data = impart_pk.find_user_data(user_id)
            else:
                battle["summary"] = "对决异常，不计结果，本次对决已终止"
                battles.append(battle)
                break
            battles.append(battle)
            if int(user_data.get("pk_num") or 0) <= 0:
                if xu_world.check_xu_world_user_id(user_id):
                    battles.append({"round": None, "opponent": NICKNAME, "logs": [],
                                    "result": "kicked", "stones_gained": 0,
                                    "summary": "道友次数已用尽！已帮助道友退出虚神界！"})
                    xu_world.del_xu_world(user_id)
                else:
                    battles.append({"round": None, "opponent": NICKNAME, "logs": [],
                                    "result": "exhausted", "stones_gained": 0,
                                    "summary": "道友次数已用尽！"})
                break
        return {
            "success": True,
            "battles": battles,
            "total_battles": total_battles,
            "total_wins": total_wins,
            "total_losses": total_losses,
            "current_loss_count": current_loss_count,
            "max_loss_count": max_loss_count,
            "player_stones": player_1_stones,
        }

    try:
        num = int(target_number) - 1
    except (TypeError, ValueError):
        return {"success": False, "message": "编号解析异常，应全为数字!"}

    xu_world_list = xu_world.all_xu_world_user() or []
    if num + 1 > len(xu_world_list) or num < 0:
        return {"success": False, "message": "编号解析异常，虚神界没有此编号道友!"}

    player_2 = xu_world_list[num]
    if str(user_id) == str(player_2):
        return {"success": False, "message": "道友不能挑战自己的投影!"}

    user_info_2 = game_sql.get_user_info_with_id(player_2) or {}
    player_2_name = user_info_2.get("user_name") or str(player_2)
    if not xu_world.check_xu_world_user_id(player_2):
        return {"success": False, "message": f"道友{player_2_name}已离开虚神界！"}

    player_1_wins = 0
    player_2_wins = 0

    while current_loss_count < max_loss_count and int(user_data.get("pk_num") or 0) > 0:
        total_battles += 1
        msg_list, win = _run_player_duel(user_id, player_1_name, player_2, player_2_name)
        battle = {
            "round": total_battles,
            "opponent": player_2_name,
            "logs": _humanize_battle_msg(msg_list) if not isinstance(msg_list, str)
            else _humanize_battle_msg(str(msg_list)),
            "result": "none",
            "stones_gained": 0,
            "summary": "",
        }
        if win is None:
            battle["summary"] = "对决异常，不计结果，本次对决已终止"
            battles.append(battle)
            break

        if win == 1:
            impart_pk.update_user_data(user_id, True)
            impart_pk.update_user_data(player_2, False)
            xiuxian_impart.update_stone_num(20, user_id, 1)
            xiuxian_impart.update_stone_num(10, player_2, 1)
            player_1_stones += 20
            player_2_stones += 10
            player_1_wins += 1
            total_wins += 1
            battle["result"] = "win"
            battle["stones_gained"] = 20
            battle["summary"] = f"道友{player_1_name}获得了胜利，获得思恋结晶20颗！道友{player_2_name}败了，获得思恋结晶10颗！"
            player_2_data = impart_pk.find_user_data(player_2)
            if int(player_2_data.get("pk_num") or 0) <= 0:
                battle["summary"] += f"道友{player_2_name}次数耗尽，离开了虚神界！"
                xu_world.del_xu_world(player_2)
                battles.append(battle)
                break
        elif win == 2:
            impart_pk.update_user_data(player_2, True)
            impart_pk.update_user_data(user_id, False)
            xiuxian_impart.update_stone_num(20, player_2, 1)
            xiuxian_impart.update_stone_num(10, user_id, 1)
            player_2_stones += 20
            player_1_stones += 10
            player_2_wins += 1
            current_loss_count += 1
            total_losses += 1
            battle["result"] = "lose"
            battle["stones_gained"] = 10
            battle["summary"] = f"道友{player_2_name}获得了胜利，获得思恋结晶20颗！道友{player_1_name}败了，获得思恋结晶10颗！"
            user_data = impart_pk.find_user_data(user_id)
            if int(user_data.get("pk_num") or 0) <= 0:
                battle["summary"] += f"道友{player_1_name}次数耗尽！"
                if xu_world.check_xu_world_user_id(user_id):
                    battle["summary"] += "已帮助道友退出虚神界！"
                    xu_world.del_xu_world(user_id)
                battles.append(battle)
                break
        battles.append(battle)

    return {
        "success": True,
        "battles": battles,
        "total_battles": total_battles,
        "player_1_wins": player_1_wins,
        "player_2_wins": player_2_wins,
        "current_loss_count": current_loss_count,
        "max_loss_count": max_loss_count,
        "player_stones": player_1_stones,
        "opponent_stones": player_2_stones,
        "opponent_name": player_2_name,
    }


def train(user_id, minutes):
    """虚神界修炼，对齐 QQ 端计算。minutes 必须为正整数。"""
    user_info = game_sql.get_user_info_with_id(user_id) or {}
    if user_info.get("root_type") == "伪灵根":
        return {"success": False, "message": "凡人无法进行修炼!"}

    try:
        minutes = int(minutes)
    except (TypeError, ValueError):
        minutes = 0
    if minutes <= 0:
        return {"success": False, "message": "修炼分钟数必须为正整数"}

    impart_data = _ensure_impart(user_id)
    exp_day = int(impart_data.get("exp_day") or 0)
    if minutes > exp_day:
        return {"success": False, "message": "累计时间不足，修炼失败!"}

    level = user_info.get("level")
    closing_type = OtherSet().set_closing_type(level)
    max_exp = closing_type * XiuConfig().closing_exp_upper_limit
    current_exp = int(user_info.get("exp") or 0)

    level_rate = game_sql.get_root_rate(user_info.get("root_type"), user_id)
    realm_rate = jsondata.level_data()[level]["spend"]
    user_buff_data = UserBuffDate(user_id)
    mainbuffdata = user_buff_data.get_user_main_buff_data()
    mainbuffratebuff = mainbuffdata["ratebuff"] if mainbuffdata is not None else 0
    mainbuffcloexp = mainbuffdata["clo_exp"] if mainbuffdata is not None else 0

    impart_lv = int(impart_data.get("impart_lv") or 0)
    impart_exp_up = impart_data.get("impart_exp_up") or 0
    impart_exp_up2 = impart_lv * 0.15

    exp_per_minute = int(XiuConfig().closing_exp * (
        level_rate * realm_rate * (1 + mainbuffratebuff) * (1 + mainbuffcloexp)
        * (1 + impart_exp_up) * (1 + impart_exp_up2)
    ))

    remaining_exp = max_exp - current_exp
    max_allowed_time = remaining_exp // exp_per_minute if exp_per_minute > 0 else 0
    if minutes > max_allowed_time:
        if max_allowed_time > 0:
            return {"success": False, "message": f"修炼时长超出上限，最多可修炼{round(max_allowed_time)}分钟"}
        return {"success": False, "message": "修炼时长超出上限，已不可修炼！"}

    exp = exp_per_minute * minutes
    xiuxian_impart.use_impart_exp_day(minutes, user_id)
    game_sql.update_exp(user_id, exp)
    game_sql.update_power2(user_id)

    efficiency_percent = int((
        level_rate + mainbuffratebuff + mainbuffcloexp + impart_exp_up + impart_exp_up2
    ) * 100)
    update_statistics_value(user_id, "虚神界修炼", increment=minutes)

    return {
        "success": True,
        "message": f"虚神界修炼结束，共修炼{round(minutes)}分钟，本次增加修为：{number_to(exp)}（修炼效率：{efficiency_percent}%）",
        "minutes": minutes,
        "exp_gained": exp,
        "efficiency_percent": efficiency_percent,
    }


def explore(user_id):
    """探索虚神界，随机结果在服务器端决定，完整对齐 QQ 端权重与等级变化。"""
    user_data = impart_pk.find_user_data(user_id) or {}
    if int(user_data.get("impart_num") or 0) <= 0:
        return {"success": False, "message": "道友今日探索次数耗尽，需打坐调息，明日方可再探虚神界！"}

    impart_data = _ensure_impart(user_id)
    old_level = int(impart_data.get("impart_lv") or 0)
    impart_name = IMPART_LEVEL_NAME.get(old_level, "未知秘境")

    if old_level == 30:
        impart_exp_up = old_level * 0.15
        return {
            "success": False,
            "message": f"已登临{impart_name}！获得虚神界终极加持：修为增益{int(impart_exp_up * 100)}%",
            "outcome": "top",
        }

    if int(impart_data.get("exp_day") or 0) < 100:
        impart_exp_up = old_level * 0.15
        return {
            "success": False,
            "message": f"道友探索虚神界时间不足，难以突破{impart_name}的禁制！当前区域加持：修为增益{int(impart_exp_up * 100)}%",
            "outcome": "time_insufficient",
        }

    impart_time = random.randint(1, 100)
    impart_rate = random.randint(1, 3)
    all_msgs = {
        "stay": [
            "道友突然心有所感，决定原地静修，参悟{}的玄机".format(impart_name),
            "《{}经》自行运转，道友决定暂缓探索".format(random.choice(["太虚", "九幽", "混元"])),
            "冥冥中似有警示，道友决定今日不宜继续探索虚神界",
            "道友在{}中偶得顿悟，决定就地闭关参悟".format(impart_name),
            "「{}」发出共鸣，道友决定停下脚步".format(random.choice(["青萍剑", "昆仑镜", "造化玉碟"])),
        ],
        "fail": [
            "遭遇{}守护大阵反噬，道友元神受创退回！".format(impart_name),
            "虚空突现《{}禁制》，将道友逼退！".format(random.choice(["太虚", "九幽", "混元"])),
            "心魔劫显化{}虚影，道友不得不暂避锋芒！".format(random.choice(["天魔", "域外邪神", "上古怨灵"])),
            "{}道则显化，阻断道友前进之路！".format(random.choice(["青冥", "玄黄", "混沌"])),
            "道友本命法宝「{}」震颤示警，被迫撤退！".format(random.choice(["青萍剑", "昆仑镜", "造化玉碟"])),
        ],
        "down": [
            "道友误触{}禁制，境界暂时跌落".format(random.choice(["周天", "洪荒", "太古"])),
            "遭遇{}，被迫退守".format(random.choice(["虚空风暴", "法则乱流", "混沌潮汐"])),
            "{}剑气纵横，斩落道友一缕元神".format(random.choice(["诛仙", "戮神", "陷仙"])),
            "神秘存在「{}」虚影显现，威压逼退道友".format(random.choice(["荒天帝", "叶天帝", "楚天尊"])),
            "《{}》显化天碑，道友参悟有误反受其害".format(random.choice(["道藏", "佛经", "魔典"])),
        ],
        "up": [
            "道友顿悟{}真意，境界突破！".format(random.choice(["太初", "鸿蒙", "混沌"])),
            "得「{}」相助，勘破一层玄机".format(random.choice(["菩提树", "悟道石", "混沌青莲"])),
            "以《{}》破开禁制".format(random.choice(["大衍诀", "神象镇狱劲", "他化自在法"])),
            "献祭{}，强行突破桎梏".format(random.choice(["千年修为", "本命精血", "先天灵宝"])),
            "引动{}之力，开辟前路".format(random.choice(["周天星辰", "地脉龙气", "混沌雷劫"])),
        ],
        "down_rate": [
            "遭逢{}天象，道基受损！".format(random.choice(["量劫", "天人五衰", "纪元更迭"])),
            "{}反噬，境界连跌！".format(random.choice(["天道", "大道", "混沌"])),
            "被「{}」冲刷，丢失部分道果".format(random.choice(["时间长河", "命运长河", "因果长河"])),
            "{}传来诡异低语，道友道心几近崩溃".format(random.choice(["上苍之上", "界海彼岸", "黑暗源头"])),
            "《{}》显化，强行削去道友修为".format(random.choice(["葬经", "度人经", "灭世书"])),
        ],
        "up_rate": [
            "触发{}异象，连破数关！".format(random.choice(["混沌青莲", "世界树", "玄黄母气"])),
            "得「{}」道韵洗礼，修为暴涨".format(random.choice(["盘古斧", "造化玉碟", "东皇钟"])),
            "参透《{}》终极奥义，直指大道本源".format(random.choice(["道经", "佛经", "魔典"])),
            "{}老祖显圣点化，醍醐灌顶".format(random.choice(["鸿钧", "陆压", "扬眉"])),
            "吞噬{}，实力飙升".format(random.choice(["先天灵宝", "混沌至宝", "大道碎片"])),
        ],
    }

    msg_type = random.choices(list(all_msgs.keys()), weights=EXPLORE_RATES)[0]
    msg = random.choice(all_msgs[msg_type])
    time_cost = 0
    new_level = old_level

    if msg_type == "stay":
        impart_pk.update_user_impart_lv(user_id)
    elif msg_type == "fail":
        msg += f"\n消耗虚神界时间：{impart_time} 分钟"
        time_cost = impart_time
        xiuxian_impart.use_impart_exp_day(impart_time, user_id)
        impart_pk.update_user_impart_lv(user_id)
    elif msg_type == "down":
        new_level = max(old_level - 1, 0)
    elif msg_type == "up":
        new_level = min(old_level + 1, 30)
    elif msg_type == "down_rate":
        new_level = max(old_level - impart_rate, 0)
    elif msg_type == "up_rate":
        new_level = min(old_level + impart_rate, 30)

    if msg_type not in ("stay", "fail"):
        time_cost = impart_time
        xiuxian_impart.use_impart_exp_day(impart_time, user_id)
        xiuxian_impart.update_impart_lv(user_id, new_level)
        impart_pk.update_user_impart_lv(user_id)

    impart_exp_up = new_level * 0.15
    impart_name_new = IMPART_LEVEL_NAME.get(new_level, "未知秘境")
    msg += f"\n现位于：{impart_name_new}"
    msg += f"\n消耗虚神界时间：{time_cost} 分钟"
    msg += f"\n获得区域道则加持：修为增益{int(impart_exp_up * 100)}%"

    return {
        "success": True,
        "message": msg,
        "outcome": msg_type,
        "old_level": old_level,
        "new_level": new_level,
        "old_level_name": impart_name,
        "new_level_name": impart_name_new,
        "time_cost": time_cost,
        "remaining_explores": int((impart_pk.find_user_data(user_id) or {}).get("impart_num") or 0),
        "exp_bonus_percent": int(impart_exp_up * 100),
    }


def retreat_start(user_id):
    """进入虚神界闭关，复用 check_user_type / in_closing。"""
    user_info = game_sql.get_user_info_with_id(user_id) or {}
    if user_info.get("root_type") == "伪灵根":
        return {"success": False, "message": "凡人无法闭关！"}
    is_type, msg = check_user_type(user_id, 0)
    if not is_type:
        return {"success": False, "message": msg or "当前状态无法闭关"}
    game_sql.in_closing(user_id, 4)
    return {"success": True, "message": "进入虚神界闭关状态，如需出关，请点击出关结算！"}


def retreat_finish(user_id):
    """虚神界出关，完整对齐 QQ 端时间/经验/双倍/上限/HP-MP 结算。"""
    is_type, msg = check_user_type(user_id, 4)
    if not is_type:
        return {"success": False, "message": msg or "当前不在虚神界闭关状态"}

    user_mes = game_sql.get_user_info_with_id(user_id) or {}
    level = user_mes.get("level")
    use_exp = int(user_mes.get("exp") or 0)

    impart_data = _ensure_impart(user_id)
    impart_lv = int(impart_data.get("impart_lv") or 0)
    impart_exp_up = impart_data.get("impart_exp_up") or 0
    impart_exp_up2 = impart_lv * 0.15

    max_exp = int(OtherSet().set_closing_type(level)) * XiuConfig().closing_exp_upper_limit
    user_get_exp_max = max(0, int(max_exp) - use_exp)

    now_time = datetime.now()
    user_cd_message = game_sql.get_user_cd(user_id)
    if not user_cd_message:
        return {"success": False, "message": "闭关数据缺失"}

    impart_pk_in_closing_time = _parse_dt(user_cd_message.get("create_time"))
    if not impart_pk_in_closing_time:
        return {"success": False, "message": "闭关数据异常"}
    exp_time = OtherSet().date_diff(now_time, impart_pk_in_closing_time) // 60

    level_rate = game_sql.get_root_rate(user_mes.get("root_type"), user_id)
    realm_rate = jsondata.level_data()[level]["spend"]
    user_buff_data = UserBuffDate(user_id)
    try:
        user_blessed_spot_data = UserBuffDate(user_id).BuffInfo["blessed_spot"] * 0.5 / 1.5
    except Exception:
        user_blessed_spot_data = 0

    mainbuffdata = user_buff_data.get_user_main_buff_data()
    mainbuffratebuff = mainbuffdata["ratebuff"] if mainbuffdata is not None else 0
    mainbuffcloexp = mainbuffdata["clo_exp"] if mainbuffdata is not None else 0

    base_exp_rate = XiuConfig().closing_exp * (
        level_rate * realm_rate * (1 + mainbuffratebuff) * (1 + mainbuffcloexp)
        * (1 + user_blessed_spot_data) * (1 + impart_exp_up)
    )
    base_exp_rate2 = f"{int((level_rate + mainbuffratebuff + mainbuffcloexp + user_blessed_spot_data + impart_exp_up + impart_exp_up2) * 100)}%"

    available_exp_day = int(impart_data.get("exp_day") or 0)
    double_exp_time = min(exp_time, available_exp_day)
    double_exp = int(double_exp_time * base_exp_rate * (1 + impart_exp_up2))

    single_exp_time = exp_time - double_exp_time
    single_exp = int(single_exp_time * base_exp_rate) if single_exp_time > 0 else 0

    total_exp = double_exp + single_exp
    effective_double_exp_time = double_exp_time
    effective_single_exp_time = single_exp_time
    exp_day_cost = double_exp_time

    if total_exp > user_get_exp_max:
        remaining_exp = user_get_exp_max
        if double_exp >= remaining_exp:
            effective_double_exp_time = remaining_exp / (base_exp_rate * (1 + impart_exp_up2)) if (base_exp_rate * (1 + impart_exp_up2)) else 0
            double_exp = int(effective_double_exp_time * base_exp_rate * (1 + impart_exp_up2))
            effective_single_exp_time = 0
            single_exp = 0
            exp_day_cost = int(effective_double_exp_time)
        else:
            remaining_exp -= double_exp
            effective_single_exp_time = remaining_exp / base_exp_rate if base_exp_rate else 0
            single_exp = int(effective_single_exp_time * base_exp_rate)
        total_exp = double_exp + single_exp

    if exp_day_cost > 0:
        xiuxian_impart.use_impart_exp_day(exp_day_cost, user_id)

    game_sql.in_closing(user_id, 0)
    game_sql.update_exp(user_id, total_exp)
    game_sql.update_power2(user_id)

    result_msg, result_hp_mp = OtherSet().send_hp_mp(
        user_id, int(use_exp / 10 * exp_time), int(use_exp / 20 * exp_time)
    )
    game_sql.update_user_attribute(
        user_id, result_hp_mp[0], result_hp_mp[1], int(result_hp_mp[2] / 10)
    )
    update_statistics_value(user_id, "虚神界闭关时长", increment=exp_time)

    if total_exp >= user_get_exp_max:
        return {
            "success": True,
            "message": f"虚神界闭关结束，本次虚神界闭关到达上限，共增加修为：{number_to(total_exp)}(修炼效率：{base_exp_rate2}){result_msg[0]}{result_msg[1]}",
            "exp_gained": total_exp,
            "elapsed_minutes": exp_time,
        }
    if effective_single_exp_time == 0:
        return {
            "success": True,
            "message": (f"虚神界闭关结束，共闭关{exp_time}分钟，其中{int(effective_double_exp_time)}分钟获得虚神界祝福，"
                        f"本次闭关增加修为：{number_to(total_exp)}(修炼效率：{base_exp_rate2}){result_msg[0]}{result_msg[1]}"),
            "exp_gained": total_exp,
            "elapsed_minutes": exp_time,
        }
    return {
        "success": True,
        "message": (f"虚神界闭关结束，共闭关{exp_time}分钟，其中{int(effective_double_exp_time)}分钟获得虚神界祝福，"
                    f"{int(effective_single_exp_time)}分钟没有获得祝福，"
                    f"本次闭关增加修为：{number_to(total_exp)}(修炼效率：{base_exp_rate2}){result_msg[0]}{result_msg[1]}"),
        "exp_gained": total_exp,
        "elapsed_minutes": exp_time,
    }