#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import logging
from typing import Any, Dict, Optional
from datetime import datetime
import aiohttp

logger = logging.getLogger(__name__)


class HLTVClient:
    """HLTV数据客户端 - 纯 API 模式"""

    BASE_URL = "https://www.hltv.org"
    # 默认 API 地址
    DEFAULT_API_URL = "https://hltv-api-proxy.shirasuazusa.workers.dev"
    
    def __init__(self, api_url: str = "") -> None:
        self.logger = logging.getLogger(__name__)
        # 如果没有配置，使用默认 API
        self.api_url = (api_url.rstrip("/") if api_url else self.DEFAULT_API_URL)
        self.logger.info(f"HLTV客户端初始化完成 (API: {self.api_url})")

    async def _api_request(self, endpoint: str, params: Optional[Dict] = None) -> Dict[str, Any]:
        """通过 API Server 获取数据"""
        try:
            url = f"{self.api_url}{endpoint}"
            self.logger.info(f"API请求: {url}")
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        self.logger.info(f"API请求成功: {endpoint}")
                        return data
                    else:
                        self.logger.error(f"API请求失败 {endpoint}: HTTP {resp.status}")
                        return {
                            "success": False,
                            "message": f"API请求失败: HTTP {resp.status}",
                            "data": []
                        }
        except Exception as e:
            self.logger.error(f"API请求失败 {endpoint}: {e}")
            return {
                "success": False,
                "message": f"API请求失败: {str(e)}",
                "data": []
            }

    async def get_cs2_matches(self) -> Dict[str, Any]:
        """获取CS2比赛数据"""
        return await self._api_request("/api/matches")

    async def get_team_rankings(self, limit: int = 30) -> Dict[str, Any]:
        """获取战队排名数据"""
        return await self._api_request("/api/rankings", {"limit": limit})

    async def get_match_results(self, days: int = 7, stars: int = 0) -> Dict[str, Any]:
        """获取比赛结果数据
        
        Args:
            days: 天数（暂未使用）
            stars: 最低星级 (0=全部, 3=B级及以上, 4=A级及以上, 5=S级)
        """
        params = {"days": days}
        if stars > 0:
            params["stars"] = stars
        return await self._api_request("/api/results", params)

    async def get_player_info(self, player_name: str) -> Dict[str, Any]:
        """获取选手信息"""
        return await self._api_request("/api/player", {"name": player_name})

    async def get_team_info(self, team_name: str) -> Dict[str, Any]:
        """获取战队详细信息"""
        return await self._api_request("/api/team", {"name": team_name})

    async def get_events(self) -> Dict[str, Any]:
        """获取重要赛事 (S级 Major + A级 国际LAN)"""
        return await self._api_request("/api/events")
