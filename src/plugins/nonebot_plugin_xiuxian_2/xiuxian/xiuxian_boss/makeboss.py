import random
import json
from pathlib import Path
from ..xiuxian_utils.xiuxian2_handle import XiuxianDateManage
from ..xiuxian_utils.data_source import jsondata
from .bossconfig import get_boss_config

config = get_boss_config()
jinjie_list = [
    "感气境",
    "练气境",
    "筑基境",
    "结丹境",
    "金丹境",
    "元神境",
    "化神境",
    "炼神境",
    "返虚境",
    "大乘境",
    "虚道境",
    "斩我境",
    "遁一境",
    "至尊境",
    "微光境",
    "星芒境",
    "月华境",
    "耀日境",
    "祭道境",
    "自在境",
    "破虚境",
    "无界境",
    "混元境",
    "造化境",
    "永恒境"
]

sql_message = XiuxianDateManage()  # sql类

def get_boss_jinjie_dict():
    CONFIGJSONPATH = Path() / "data" / "xiuxian" / "境界.json"
    with open(CONFIGJSONPATH, "r", encoding="UTF-8") as f:
        data = f.read()
    temp_dict = {}
    data = json.loads(data)
    for k, v in data.items():
        temp_dict[k] = v['exp']
    return temp_dict


def get_boss_exp(boss_jj):
    if boss_jj in jinjie_list:
        stages = random.choice(["初期", "中期", "圆满"])
        level = f"{boss_jj}{stages}"
        exp_rate = random.randint(8, 12)
        exp = int(jsondata.level_data()[level]["power"])
        bossexp = int(exp * (0.1 * exp_rate))
        bossinfo = {
            '气血': bossexp * config["Boss倍率"]["气血"],
            '总血量': bossexp * config["Boss倍率"]["气血"],
            '真元': bossexp * config["Boss倍率"]["真元"],
            '攻击': int(bossexp * config["Boss倍率"]["攻击"])
        }
        return bossinfo
    else:
        return None

def createboss():
    top_user_info = sql_message.get_realm_top1_user() # 改成了境界第一
    top_user_level = top_user_info['level']
    if len(top_user_level) == 5:
        level = top_user_level[:3] 
    elif len(top_user_level) == 4: # 对江湖好手判断
        level = "感气境"
    elif len(top_user_level) == 2: # 对至高判断
        level = "永恒境"

    boss_jj = random.choice(jinjie_list[:jinjie_list.index(level) + 1])
    return boss_jj


def createboss_jj(boss_jj, boss_name=None):
    bossinfo = get_boss_exp(boss_jj)
    if bossinfo:
        bossinfo['name'] = boss_name if boss_name else random.choice(config["Boss名字"])
        bossinfo['jj'] = boss_jj
        bossinfo['max_stone'] = random.choice(config["Boss灵石"][boss_jj])
        bossinfo['stone'] = bossinfo['max_stone']
        return bossinfo
    else:
        return None

def create_all_bosses(max_jj: str = None) -> list:
    """
    生成所有可生成境界的 BOSS（每个境界一个）
    """
    
    # 如果没有指定最高境界，则根据当前最高玩家境界计算
    if max_jj is None:
        try:
            top_user_info = sql_message.get_realm_top1_user()
            if top_user_info:
                top_user_level = top_user_info.get('level', "感气境")
                if len(top_user_level) == 5:
                    max_jj = top_user_level[:3] 
                elif len(top_user_level) == 4:
                    max_jj = "感气境"
                elif len(top_user_level) == 2:
                    max_jj = "永恒境"
                else:
                    max_jj = top_user_level
            else:
                max_jj = "筑基境" # 默认保底
        except Exception:
            max_jj = "筑基境"
    
    # 获取所有不超过 max_jj 的境界
    try:
        max_idx = jinjie_list.index(max_jj)
    except ValueError:
        max_idx = 0
        for i, jj in enumerate(jinjie_list):
            if jj in max_jj or max_jj in jj:
                max_idx = i
                break
                
    all_jj = jinjie_list[:max_idx + 1]
    
    # 生成每个境界的 BOSS
    bosses = []
    # 限制返回境界数量，返回最高境界及以下 5 个境界
    display_jj = all_jj[-5:] if len(all_jj) > 5 else all_jj
    
    for jj in display_jj:
        # 每个境界生成 2 个不同的 Boss 名字
        names = random.sample(config["Boss名字"], 2)
        for name in names:
            boss = createboss_jj(jj, boss_name=name)
            if boss:
                bosses.append(boss)
    
    return bosses[::-1] # 降序排列，强的在前
