from nonebot.log import logger
from ...models.gt_entities import PlayerStats, Weapon, Vehicle

from typing import List, Dict, Any


def sort_list_of_dicts(list_of_dicts, key):
    """降序排序"""
    return sorted(list_of_dicts, key=lambda k: k[key], reverse=True)


def prepare_weapons_data(d: dict, lens: int) -> List[Weapon]:
    """提取武器数据，格式化使用时间，并返回 Weapon 对象列表"""
    weapons_list_raw = d.get("weapons", [])
    weapons_list_raw = sort_list_of_dicts(weapons_list_raw, "kills")

    weapons_objects = []
    for w_data in weapons_list_raw[:lens]:
        if w_data.get("kills", 0) > 0:
            # 创建 Weapon 对象
            weapon = Weapon.from_dict(w_data)
            weapons_objects.append(weapon)

    return weapons_objects


def prepare_vehicles_data(d: dict, lens: int) -> List[Vehicle]:
    """提取载具数据，格式化使用时间，并返回 Vehicle 对象列表"""
    vehicles_list_raw = d.get("vehicles", [])
    vehicles_list_raw = sort_list_of_dicts(vehicles_list_raw, "kills")

    vehicles_objects = []
    for v_data in vehicles_list_raw[:lens]:
        if v_data.get("kills", 0) > 0:
            vehicle = Vehicle.from_dict(v_data)
            vehicles_objects.append(vehicle)

    return vehicles_objects


def gt_main_llm_builder(raw_data: dict, game: str, bf_prompt: str) -> str:
    """
    构建LLM能够理解的Prompt
    Args:
        raw_data: 查询到的原始数据字典
        game: 所查询的游戏
        bf_prompt: llm prompt
    Returns:
        构建的Html
    """

    # 预处理原始数据，使其符合 PlayerStats.from_gt_dict 的期望
    processed_data = raw_data.copy()

    processed_data["__hours_played"] = str(round(processed_data.get("secondsPlayed", 0) / 3600, 1))
    processed_data["revives"] = int(processed_data.get("revives", 0))
    processed_data["longest_head_shot"] = int(processed_data.get("longest_head_shot", 0))

    # 创建 PlayerStats 对象
    player_stats = PlayerStats.from_gt_dict(processed_data)

    # 整理武器和载具数据，返回实体对象列表
    weapons_objects = prepare_weapons_data(processed_data, 2)
    vehicles_objects = prepare_vehicles_data(processed_data, 2)

    llm_text = f"""{bf_prompt}，{game}中{player_stats.to_llm_text()}"""

    if weapons_objects:
        for weapon in weapons_objects:
            llm_text += weapon.to_llm_text(game)
    if vehicles_objects:
        for vehicle in vehicles_objects:
            llm_text += vehicle.to_llm_text(game)

    return llm_text
