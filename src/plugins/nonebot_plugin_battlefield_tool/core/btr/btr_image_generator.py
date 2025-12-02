# core/btr/btr_image_generator.py

from typing import Callable

from ...constants.battlefield_constants import ImageUrls


class BtrImageGenerator:
    """图片生成工具类，负责将 BTR 数据转换为图片"""

    def __init__(self, img_quality: int = 90):
        """
        初始化图片生成器
        Args:
            img_quality: 图片质量，默认 90
        """
        self.img_quality = img_quality

    async def generate_main_btr_data_pic(
        self,
        game: str,
        html_render_func: Callable,
        html_builder_func: Callable,
        stat_data,
        weapon_data,
        vehicle_data,
        soldier_data,
    ) -> str:
        """将查询的全部数据转为图片"""
        html = await html_builder_func(stat_data, weapon_data, vehicle_data, soldier_data, game)
        url = await html_render_func(
            html,
            {},
            True,
            {
                "timeout": 10000,
                "quality": self.img_quality,
                "clip": {**ImageUrls.COMMON_CLIP_PARAMS, "height": 2353},
            },
        )
        return url

    async def generate_weapons_btr_data_pic(
        self,
        game: str,
        html_render_func: Callable,
        html_builder_func: Callable,
        stat_data,
        weapon_data,
        vehicle_data,
        soldier_data,
    ) -> str:
        """将查询的武器数据转为图片"""
        html = await html_builder_func(stat_data, weapon_data, vehicle_data, soldier_data, game)
        url = await html_render_func(
            html,
            {},
            True,
            {
                "timeout": 10000,
                "quality": self.img_quality,
                "clip": {**ImageUrls.COMMON_CLIP_PARAMS, "height": 20000},
            },
        )
        return url

    async def generate_vehicles_btr_data_pic(
        self,
        game: str,
        html_render_func: Callable,
        html_builder_func: Callable,
        stat_data,
        weapon_data,
        vehicle_data,
        soldier_data,
    ) -> str:
        """将查询的载具数据转为图片"""
        html = await html_builder_func(stat_data, weapon_data, vehicle_data, soldier_data, game)
        url = await html_render_func(
            html,
            {},
            True,
            {
                "timeout": 10000,
                "quality": self.img_quality,
                "clip": {**ImageUrls.COMMON_CLIP_PARAMS, "height": 20000},
            },
        )
        return url

    async def generate_soldiers_btr_data_pic(
        self,
        game: str,
        html_render_func: Callable,
        html_builder_func: Callable,
        stat_data,
        weapon_data,
        vehicle_data,
        soldier_data,
    ) -> str:
        """将查询的士兵数据转为图片"""
        html = await html_builder_func(stat_data, weapon_data, vehicle_data, soldier_data, game)
        url = await html_render_func(
            html,
            {},
            True,
            {
                "timeout": 10000,
                "quality": self.img_quality,
                "clip": {**ImageUrls.COMMON_CLIP_PARAMS, "height": 10000},
            },
        )
        return url

    async def generate_matches_btr_data_pic(
        self,
        game: str,
        ea_name: str,
        html_render_func: Callable,
        html_builder_func: Callable,
        stat_data,
        weapon_data,
        vehicle_data,
        soldier_data,
        mode_data,
        maps_data,
        matches_timestamp,
        provider,
    ) -> str:
        """将战报数据转为图片"""
        html = await html_builder_func(
            ea_name,
            stat_data,
            weapon_data,
            vehicle_data,
            soldier_data,
            mode_data,
            maps_data,
            game,
            matches_timestamp,
            provider,
        )
        url = await html_render_func(
            html,
            {},
            True,
            {
                "timeout": 10000,
                "quality": self.img_quality,
                # "clip": {**ImageUrls.COMMON_CLIP_PARAMS, "height": 2353},
            },
        )
        return url
