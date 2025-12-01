#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from pathlib import Path
from typing import Any, Dict

import nonebot
from fastapi import FastAPI, Request, APIRouter
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from nonebot.log import logger

from . import matcher

# 模板目录
TEMPLATES_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

router = APIRouter()

@router.get("/", response_class=HTMLResponse)
async def hltv_index(request: Request):
    """WebUI 首页"""
    return templates.TemplateResponse("index.html", {"request": request})

@router.get("/api/config")
async def get_config():
    """获取当前配置"""
    return matcher.config.dict()

@router.post("/api/config")
async def update_config(new_config: Dict[str, Any]):
    """更新配置"""
    # 更新 matcher 中的 config 对象
    for key, value in new_config.items():
        if hasattr(matcher.config, key):
            setattr(matcher.config, key, value)
    
    # 特殊处理: 如果更新了 API URL，需要重新初始化 client 或更新其属性
    if "hltv_api_url" in new_config:
        new_url = new_config["hltv_api_url"]
        # 更新 client 的 api_url
        # 注意: HLTVClient 的 api_url 处理逻辑在 __init__ 中，这里我们需要手动模拟
        from .real_client import HLTVClient
        if not new_url:
            matcher.hltv_client.api_url = HLTVClient.DEFAULT_API_URL
        else:
            matcher.hltv_client.api_url = new_url.rstrip("/")
            
    return {"success": True, "message": "配置已更新"}

@router.get("/api/test")
async def test_api(type: str, arg: str = ""):
    """测试 API"""
    client = matcher.hltv_client
    
    if type == "matches":
        return await client.get_cs2_matches()
    elif type == "results":
        return await client.get_match_results()
    elif type == "ranking":
        return await client.get_team_rankings()
    elif type == "team":
        if not arg:
            return {"success": False, "message": "缺少参数: 战队名"}
        return await client.get_team_info(arg)
    elif type == "player":
        if not arg:
            return {"success": False, "message": "缺少参数: 选手名"}
        return await client.get_player_info(arg)
    else:
        return {"success": False, "message": "未知测试类型"}

def init_web_ui():
    """初始化 WebUI"""
    try:
        app = nonebot.get_app()
        # 创建子应用
        sub_app = FastAPI(title="NoneBot HLTV Plugin", description="HLTV Plugin WebUI")
        sub_app.include_router(router)
        
        # 挂载到 /hltv
        app.mount("/hltv", sub_app)
        logger.info("HLTV WebUI 已加载: /hltv")
    except Exception as e:
        logger.warning(f"HLTV WebUI 加载失败: {e}")
