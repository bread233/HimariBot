#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import logging
import re
import os
from pathlib import Path
from typing import Optional
from datetime import datetime

from nonebot import on_command, require
from nonebot.adapters.onebot.v11 import Bot, MessageEvent, Message, MessageSegment
from nonebot.matcher import Matcher
from nonebot.params import CommandArg

# 导入 htmlrender
require("nonebot_plugin_htmlrender")
from nonebot_plugin_htmlrender import template_to_pic

from .config import get_config
from .real_client import HLTVClient

logger = logging.getLogger(__name__)

# 获取配置并初始化客户端
config = get_config()
hltv_client = HLTVClient(api_url=config.hltv_api_url)


# 命令定义 - priority=1 确保优先于 llmchat (priority=99)
matcher_cs2_matches = on_command("cs2比赛", aliases={"cs2匹配", "查看cs2比赛"}, priority=1, block=True)
matcher_cs2_team = on_command("cs2战队", aliases={"查询战队", "cs2队伍"}, priority=1, block=True)
matcher_cs2_results = on_command("cs2结果", aliases={"查看结果", "cs2结果查询"}, priority=1, block=True)
matcher_cs2_ranking = on_command("cs2排名", aliases={"战队排名", "csgo排名"}, priority=1, block=True)
matcher_cs2_player = on_command("cs2选手", aliases={"查询选手", "cs2选手查询"}, priority=1, block=True)
matcher_cs2_events = on_command("cs2赛事", aliases={"cs2比赛赛程", "重要赛事"}, priority=1, block=True)


@matcher_cs2_matches.handle()
async def handle_cs2_matches(bot: Bot, event: MessageEvent, matcher: Matcher):
    """处理CS2比赛查询"""
    result = await hltv_client.get_cs2_matches()

    if result.get("success"):
        matches = result.get("data", [])
        if matches:
            msg = "【CS2实时比赛】\n"
            limit = config.max_matches_per_query
            for i, match in enumerate(matches[:limit], 1):
                team1 = match.get("team1", "TBD")
                team2 = match.get("team2", "TBD")
                match_event = match.get("event", "Unknown")
                time_text = match.get("time", "TBD")
                bo_type = match.get("bo_type", "bo3")

                msg += f"{i}. {team1} vs {team2}\n"
                msg += f"   时间: {time_text} | {bo_type.upper()}\n"
                msg += f"   赛事: {match_event}\n"
        else:
            msg = "当前没有找到比赛信息。\n"
    else:
        msg = result.get("message", "获取比赛信息失败")

    await matcher.finish(msg)


@matcher_cs2_team.handle()
async def handle_cs2_team(
    bot: Bot, event: MessageEvent, matcher: Matcher, args: Message = CommandArg()
):
    team_name = args.extract_plain_text().strip()

    if not team_name:
        await matcher.finish("请提供战队名称。\n示例: /cs2战队 Vitality")
        return

    result = await hltv_client.get_team_info(team_name)

    if result.get("success"):
        team_data = result.get("data", {})
        msg = f"【{team_data.get('name', team_name)} 战队信息】\n"
        msg += f"排名: {team_data.get('rank', 'N/A')}\n"
        members = team_data.get('members', [])
        if members:
            msg += f"阵容: {', '.join(members)}\n"
        coach = team_data.get('coach')
        if coach and coach != 'Unknown':
            msg += f"教练: {coach}\n"
        msg += f"详情: {team_data.get('url', 'N/A')}\n"
    else:
        msg = result.get("message", f"无法获取 {team_name} 的战队信息")

    await matcher.finish(msg)


@matcher_cs2_results.handle()
async def handle_cs2_results(
    bot: Bot, event: MessageEvent, matcher: Matcher, args: Message = CommandArg()
):
    """处理CS2比赛结果查询
    
    用法:
        /cs2结果      - 查看所有赛事结果
        /cs2结果 S    - 只看S级(5星)赛事
        /cs2结果 A    - 只看A级(4星)及以上
        /cs2结果 B    - 只看B级(3星)及以上
    """
    arg_text = args.extract_plain_text().strip().upper()
    
    # 解析级别参数
    tier_map = {
        "S": 5,  # S级 = 5星
        "A": 4,  # A级 = 4星及以上
        "B": 3,  # B级 = 3星及以上
        "C": 1,  # C级 = 1星及以上
    }
    
    stars = tier_map.get(arg_text, 0)  # 默认0表示全部
    
    filter_text = ""
    if arg_text in tier_map:
        filter_text = f"筛选: {arg_text}级及以上赛事 ({stars}星+)"
    
    days = config.default_query_days
    result = await hltv_client.get_match_results(days=days, stars=stars)

    if result.get("success"):
        matches = result.get("data", [])
        if matches:
            # 使用 HTML 渲染
            template_path = Path(__file__).parent / "templates"
            
            try:
                pic = await template_to_pic(
                    template_path=str(template_path),
                    template_name="results.html",
                    templates={
                        "results": matches[:20],  # 最多显示20条
                        "filter_text": filter_text,
                        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    },
                    pages={
                        "viewport": {"width": 800, "height": 100},
                    },
                )
                await matcher.finish(MessageSegment.image(pic))
            except Exception as e:
                logger.error(f"渲染图片失败: {e}")
                # 降级为文本输出
                msg = f"【最近比赛结果】{' (' + filter_text + ')' if filter_text else ''}\n"
                limit = config.max_results_per_query
                for i, match in enumerate(matches[:limit], 1):
                    team1 = match.get("team1", "TBD")
                    team2 = match.get("team2", "TBD")
                    score1 = match.get("score1", 0)
                    score2 = match.get("score2", 0)
                    evt = match.get("event", "Unknown")
                    star_count = match.get("stars", 0)

                    winner = team1 if int(score1) > int(score2) else team2
                    msg += f"{i}. {team1} {score1}-{score2} {team2} {'★' * star_count}\n"
                    msg += f"   胜者: {winner} | 赛事: {evt}\n"
                await matcher.finish(f"渲染图片可能失败: {e}")
        else:
            await matcher.finish("当前没有找到比赛结果。\n")
    else:
        msg = result.get("message", "获取比赛结果失败")
        await matcher.finish(msg)


@matcher_cs2_ranking.handle()
async def handle_cs2_ranking(bot: Bot, event: MessageEvent, matcher: Matcher):
    limit = config.max_teams_in_ranking
    result = await hltv_client.get_team_rankings(limit=limit)

    if result.get("success"):
        teams = result.get("data", [])
        if teams:
            msg = f"【CS2战队排名 Top {limit}】\n"
            for team in teams[:limit]:
                rank = team.get("rank", "N/A")
                name = team.get("title", "Unknown")
                points = team.get("points", "N/A")
                msg += f"{rank}. {name} ({points}分)\n"
        else:
            msg = "当前没有战队排名数据。\n"
    else:
        msg = result.get("message", "获取战队排名失败")

    await matcher.finish(msg)


@matcher_cs2_player.handle()
async def handle_cs2_player(
    bot: Bot, event: MessageEvent, matcher: Matcher, args: Message = CommandArg()
):
    player_name = args.extract_plain_text().strip()

    if not player_name:
        await matcher.finish("请提供选手名称。\n示例: /cs2选手 ZywOo")
        return

    result = await hltv_client.get_player_info(player_name)

    if result.get("success"):
        player_data = result.get("data", {})
        msg = f"【{player_data.get('full_name', player_name)} 选手信息】\n"
        msg += f"ID: {player_data.get('name', player_name)}\n"
        
        team = player_data.get('team', 'N/A')
        msg += f"战队: {team}\n"
        
        country = player_data.get('country', 'N/A')
        if country and country != 'N/A':
            msg += f"国籍: {country}\n"
        
        # 显示 Rating (3.0)
        rating = player_data.get('rating')
        if rating and rating != 'N/A':
            msg += f"Rating: {rating}\n"
        
        kpr = player_data.get('kpr')
        if kpr and kpr != 'N/A':
            msg += f"KPR: {kpr}\n"
        
        adr = player_data.get('adr')
        if adr and adr != 'N/A':
            msg += f"ADR: {adr}\n"
        
        kast = player_data.get('kast')
        if kast and kast != 'N/A':
            msg += f"KAST: {kast}\n"
        
        headshot = player_data.get('headshot_pct')
        if headshot and headshot != 'N/A':
            msg += f"爆头率: {headshot}\n"
        
        msg += f"详情: {player_data.get('url', 'N/A')}\n"
    else:
        msg = result.get("message", f"无法获取 {player_name} 的选手信息")

    await matcher.finish(msg)


@matcher_cs2_events.handle()
async def handle_cs2_events(bot: Bot, event: MessageEvent, matcher: Matcher):
    """处理CS2赛事查询"""
    result = await hltv_client.get_events()

    if result.get("success"):
        events = result.get("data", [])
        if events:
            msg = "【CS2重要赛事】\n"
            # 只显示前10个赛事
            limit = 10
            for i, evt in enumerate(events[:limit], 1):
                name = evt.get("name", "Unknown")
                tier = evt.get("tier", "?")
                tier_name = evt.get("tier_name", "")
                location = evt.get("location", "TBD")
                start_date = evt.get("start_date", "TBD")
                end_date = evt.get("end_date", "TBD")
                
                msg += f"{i}. [{tier}级] {name}\n"
                msg += f"   📍 {location}\n"
                msg += f"   📅 {start_date} ~ {end_date}\n"
            
            if len(events) > limit:
                msg += f"\n...还有 {len(events) - limit} 场赛事"
        else:
            msg = "当前没有找到重要赛事信息。\n"
    else:
        msg = result.get("message", "获取赛事信息失败")

    await matcher.finish(msg)

