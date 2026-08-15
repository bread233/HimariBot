"""轮回 / 转生 Web 业务辅助模块。

严格对齐 QQ 端 xiuxian_lunhui 的规则与数据重置序列：
- 普通轮回按 root_type 决定下一次 root_level（6/7/8/9）与最低境界。
- 无限轮回必须 命运道果 且达到 Infinite_reincarnation_min_level。
- 自废修为仅 感气境 三个境界可用。
所有 DB 更新直接复用 XiuxianDateManage / XIUXIAN_IMPART_BUFF，
不在此复制全套 DB 逻辑。
"""

from ..xiuxian_config import XiuConfig
from ..xiuxian_utils.data_source import jsondata
from ..xiuxian_utils.xiuxian2_handle import XIUXIAN_IMPART_BUFF, XiuxianDateManage

game_sql = XiuxianDateManage()
xiuxian_impart = XIUXIAN_IMPART_BUFF()

# 查询 QQ 帮助中的阶段文案
STAGE_TEXT = {
    "qiushi": "千世轮回",
    "wanshi": "万世轮回",
    "yongheng": "永恒轮回",
    "infinite": "无限轮回",
}

# QQ 端 update_root 的灵根名
ROOT_NAMES = {
    6: "轮回道果",
    7: "真·轮回道果",
    8: "永恒道果",
    9: "命运道果",
}


def _level_index(level):
    levels = list(jsondata.level_data().keys())
    try:
        return levels.index(level)
    except (TypeError, ValueError):
        return 0


def status(user_id):
    """轮回状态：当前根、境界、阶段、下一阶段、门槛、是否符合。"""
    user = game_sql.get_user_info_with_id(user_id) or {}
    root_type = user.get("root_type")
    root_level = user.get("root_level") or 0
    level = user.get("level")
    cfg = XiuConfig()

    # 阶段映射：root_type -> (当前阶段, 下一阶段名, 下一 root level, 最低境界)
    stage_map = [
        ("轮回道果", ("千世轮回", STAGE_TEXT["wanshi"], 7, cfg.twolun_min_level)),
        ("真·轮回道果", ("万世轮回", STAGE_TEXT["yongheng"], 8, cfg.threelun_min_level)),
        ("永恒道果", ("永恒轮回", STAGE_TEXT["infinite"], 9, cfg.Infinite_reincarnation_min_level)),
    ]
    current_stage = "普通"
    next_stage = None
    next_min_level = None
    next_root_level = None
    infinite_ready = False

    if root_type == "命运道果":
        current_stage = "命运道果"
        next_stage = None
        infinite_ready = _level_index(level) >= _level_index(cfg.Infinite_reincarnation_min_level)
    else:
        has_stage = False
        for expect_root, (stage, nxt, next_root, min_level) in stage_map:
            if root_type == expect_root:
                current_stage = stage
                next_stage = nxt
                next_root_level = next_root
                next_min_level = min_level
                has_stage = True
                break
        if not has_stage:
            # 普通 -> 千世轮回
            next_stage = STAGE_TEXT["qiushi"]
            next_root_level = 6
            next_min_level = cfg.lunhui_min_level

    eligible = False
    if next_stage:
        eligible = _level_index(level) >= _level_index(next_min_level)

    return {
        "success": True,
        "root_type": root_type,
        "root_level": root_level,
        # root_level 是无限轮回累计等级/次数，不是 update_root(6..9) 的灵根编号。
        # 当前灵根阶段以 root_type 为准，避免 root_level==6 时误显示成“轮回道果”。
        "root_name": root_type or "未知灵根",
        "level": level,
        "current_stage": current_stage,
        "next_stage": next_stage,
        "next_root_level": next_root_level,
        "next_min_level": next_min_level,
        "eligible": eligible,
        "infinite_ready": infinite_ready,
        "infinite_min_level": cfg.Infinite_reincarnation_min_level,
        "loss_note": ("轮回将清空/重置：修为、功法、神通、灵石、攻修/元血/灵海等级、虚神界修炼时间；"
                      "装备与物品保留，思恋结晶按规则转换。"),
        "infinite_note": ("无限轮回（命运道果专属）也会清空/重置：修为、功法、神通、耐药性、虚神界修炼时间，"
                          "思恋结晶按规则转换；灵石、攻修/元血/灵海等级保持不变。"),
    }


def _do_advance(user_id, user, root_level):
    """执行与 QQ 端普通轮回完全一致的数据重置。"""
    exp = int(user.get("exp") or 0)
    now_exp = exp - 100
    stone = int(user.get("stone") or 0)
    impart_data = xiuxian_impart.get_user_impart_info_with_id(user_id)
    exp_day = int(impart_data["exp_day"]) if impart_data else 0

    game_sql.updata_level(user_id, "江湖好手")
    game_sql.update_levelrate(user_id, 0)
    game_sql.update_j_exp(user_id, now_exp)
    game_sql.update_user_hp(user_id)
    game_sql.updata_user_main_buff(user_id, 0)
    game_sql.updata_user_sub_buff(user_id, 0)
    game_sql.updata_user_sec_buff(user_id, 0)
    game_sql.reset_user_drug_resistance(user_id)
    game_sql.update_user_atkpractice(user_id, 0)
    game_sql.update_user_hppractice(user_id, 0)
    game_sql.update_user_mppractice(user_id, 0)
    if exp_day:
        xiuxian_impart.use_impart_exp_day(exp_day, user_id)
    xiuxian_impart.convert_stone_to_wishing_stone(user_id)
    if stone:
        game_sql.update_ls(user_id, stone, 2)
    game_sql.update_root(user_id, root_level)
    return root_level


def advance(user_id, confirm=False):
    """进入下一阶段轮回（千世/万世/永恒/无限）。高危不可逆，需 confirm。"""
    if confirm is not True:
        return {"success": False, "message": "非预期轮回请求", "need_confirm": True}

    user = game_sql.get_user_info_with_id(user_id) or {}
    user_name = user.get("user_name") or str(user_id)
    root_type = user.get("root_type")
    level = user.get("level")
    cfg = XiuConfig()

    root_level = 6
    min_level = cfg.lunhui_min_level
    stage = STAGE_TEXT["qiushi"]
    msg = f"千世轮回磨不灭，重回绝颠谁能敌，恭喜大能{user_name}轮回成功！"

    if root_type == "轮回道果":
        root_level = 7
        min_level = cfg.twolun_min_level
        stage = STAGE_TEXT["wanshi"]
        msg = f"万世道果集一身，脱出凡道入仙道，恭喜大能{user_name}万世轮回成功！"
    elif root_type == "真·轮回道果":
        root_level = 8
        min_level = cfg.threelun_min_level
        stage = STAGE_TEXT["yongheng"]
        msg = f"穿越千劫万难，证得不朽之身，恭喜大能{user_name}步入永恒之道，成就无上永恒！"
    elif root_type == "永恒道果":
        root_level = 9
        min_level = cfg.Infinite_reincarnation_min_level
        stage = STAGE_TEXT["infinite"]
        msg = f"超越永恒，超脱命运，执掌因果轮回！恭喜大能{user_name}突破命运桎梏，成就无上命运道果！"
    elif root_type == "命运道果":
        return {"success": False, "message": "道友已可无限轮回！"}

    if _level_index(level) < _level_index(min_level):
        return {
            "success": False,
            "message": f"道友境界未达要求\n当前进入：{stage}\n最低境界为：{min_level}",
        }

    try:
        _do_advance(user_id, user, root_level)
    except Exception:
        from nonebot.log import logger
        logger.exception("轮回 advance 部分失败，数据可能处于中间状态")
        return {"success": False, "message": "轮回操作异常，请稍后重试或联系管理员"}

    return {"success": True, "message": msg, "root_level": root_level,
            "root_name": ROOT_NAMES.get(root_level, str(root_level)),
            "profile": _profile_summary(user_id)}


def infinite(user_id, confirm=False):
    """无限轮回，仅 命运道果 可用。严格对齐 QQ 端无限轮回逻辑。"""
    if confirm is not True:
        return {"success": False, "message": "非预期无限轮回请求", "need_confirm": True}

    user = game_sql.get_user_info_with_id(user_id) or {}
    user_name = user.get("user_name") or str(user_id)
    root_type = user.get("root_type")
    level = user.get("level")
    cfg = XiuConfig()

    if root_type != "命运道果":
        return {"success": False, "message": "道友还未完成轮回，请先进入轮回！"}
    if _level_index(level) < _level_index(cfg.Infinite_reincarnation_min_level):
        return {
            "success": False,
            "message": f"道友境界未达要求，无限轮回的最低境界为{cfg.Infinite_reincarnation_min_level}！",
        }

    try:
        exp = int(user.get("exp") or 0)
        now_exp = exp - 100
        impart_data = xiuxian_impart.get_user_impart_info_with_id(user_id)
        exp_day = int(impart_data["exp_day"]) if impart_data else 0

        game_sql.updata_level(user_id, "江湖好手")
        game_sql.update_levelrate(user_id, 0)
        game_sql.update_j_exp(user_id, now_exp)
        game_sql.update_user_hp(user_id)
        game_sql.updata_user_main_buff(user_id, 0)
        game_sql.updata_user_sub_buff(user_id, 0)
        game_sql.updata_user_sec_buff(user_id, 0)
        game_sql.reset_user_drug_resistance(user_id)
        if exp_day:
            xiuxian_impart.use_impart_exp_day(exp_day, user_id)
        xiuxian_impart.convert_stone_to_wishing_stone(user_id)
        game_sql.update_root(user_id, 9)
        game_sql.updata_root_level(user_id, 1)
    except Exception:
        from nonebot.log import logger
        logger.exception("无限轮回执行异常，数据可能处于中间状态")
        return {"success": False, "message": "无限轮回操作异常，请稍后重试或联系管理员"}

    msg = f"超越永恒，超脱命运，执掌因果轮回！恭喜大能{user_name}突破命运桎梏，成就无上命运道果！"
    return {"success": True, "message": msg, "root_level": 9,
            "root_name": ROOT_NAMES[9], "profile": _profile_summary(user_id)}


def reset_cultivation(user_id, confirm=False):
    """自废修为，仅感气境初期/中期/圆满可用。严格对齐 QQ 端。"""
    if confirm is not True:
        return {"success": False, "message": "非预期自废修为请求", "need_confirm": True}

    user = game_sql.get_user_info_with_id(user_id) or {}
    user_name = user.get("user_name") or str(user_id)
    level = user.get("level")

    if level not in ("感气境初期", "感气境中期", "感气境圆满"):
        return {"success": False, "message": "道友境界未达要求，自废修为的最低境界为感气境！"}

    try:
        exp = int(user.get("exp") or 0)
        game_sql.updata_level(user_id, "江湖好手")
        game_sql.update_levelrate(user_id, 0)
        game_sql.update_j_exp(user_id, exp)
        game_sql.update_user_hp(user_id)
    except Exception:
        from nonebot.log import logger
        logger.exception("自废修为执行异常")
        return {"success": False, "message": "自废修为操作异常，请稍后重试或联系管理员"}

    return {"success": True, "message": f"{user_name}现在是一介凡人了！！",
            "profile": _profile_summary(user_id)}


def rankings():
    """轮回排行榜 TOP50。"""
    rows = game_sql.root_top() or []
    result = []
    num = 0
    for r in rows:
        num += 1
        result.append({"name": r[0], "root_level": int(r[1] or 0)})
        if num == 50:
            break
    return result


def _profile_summary(user_id):
    """轻量角色摘要，供轮回成功后的刷新。"""
    user = game_sql.get_user_info_with_id(user_id) or {}
    if not user:
        return {}
    return {
        "user_id": str(user.get("user_id") or user_id),
        "user_name": user.get("user_name") or str(user_id),
        "level": user.get("level"),
        "exp": int(user.get("exp") or 0),
        "root_type": user.get("root_type"),
        "root_level": user.get("root_level") or 0,
        "hp": user.get("hp") or 0,
        "mp": user.get("mp") or 0,
        "atk": user.get("atk") or 0,
    }