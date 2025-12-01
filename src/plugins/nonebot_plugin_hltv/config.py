#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from nonebot import get_plugin_config
from pydantic import BaseModel


class ConfigModel(BaseModel):
    """插件配置"""

    # API Server 配置
    hltv_api_url: str = ""  # API Server URL (如: https://your-app.vercel.app)

    # 缓存配置
    cache_duration_matches: int = 60  # 比赛数据缓存时间(秒)
    cache_duration_teams: int = 3600  # 战队排名缓存时间(秒)
    cache_duration_results: int = 300  # 比赛结果缓存时间(秒)

    # 查询配置
    max_matches_per_query: int = 10  # 每次查询最大比赛数量
    max_teams_in_ranking: int = 30  # 战队排名最大数量
    max_results_per_query: int = 20  # 每次查询最大结果数量
    default_query_days: int = 1  # 默认查询天数

    # 功能开关
    enable_caching: bool = True  # 启用缓存机制
    enable_detailed_logging: bool = True  # 启用详细日志
    enable_topic_detection: bool = True  # 启用话题检测

    # 工具响应配置
    context_depth_default: str = "basic"  # 默认上下文深度
    include_match_ratings: bool = True  # 包含比赛重要程度
    show_live_scores: bool = True  # 显示实时比分
    show_ranking_changes: bool = True  # 显示排名变化

    class Config:
        extra = "ignore"


def get_config() -> ConfigModel:
    """获取插件配置"""
    return get_plugin_config(ConfigModel)
