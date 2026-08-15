import sqlite3
import os
import json
import re
import platform
import psutil
import time
import asyncio
import secrets
import random
from pathlib import Path
from functools import wraps
from nonebot.log import logger
from datetime import datetime
from nonebot import get_driver, get_bots
from nonebot import on_command
from nonebot.params import CommandArg
from nonebot.adapters.onebot.v11 import Bot, Message, GroupMessageEvent, PrivateMessageEvent
from flask import Flask, render_template, request, redirect, url_for, session, jsonify, send_file, Blueprint
from ..xiuxian_utils.item_json import Items
from ..xiuxian_config import XiuConfig, Xiu_Plugin, convert_rank
from ..xiuxian_utils.data_source import jsondata
from ..xiuxian_utils.download_xiuxian_data import UpdateManager
from ..xiuxian_utils.xiuxian2_handle import config_impart, XiuxianDateManage, UserBuffDate, OtherSet, convert_rank, XIUXIAN_IMPART_BUFF
from ..xiuxian_utils.utils import number_to, check_user_type, update_statistics_value, log_message
from ..xiuxian_buff.two_exp_cd import two_exp_cd
from ..xiuxian_work.work_handle import workhandle
from ..xiuxian_work.reward_data_source import (
    savef as save_work_file,
    delete_work_file,
    has_unaccepted_work,
)
from ..xiuxian_utils.player_fight import Player_fight, Boss_fight
from ..xiuxian_utils.utils import handle_send
from ..xiuxian_rift.old_rift_info import old_rift_info
from ..xiuxian_rift.jsondata import save_rift_data, read_rift_data
from ..xiuxian_rift.riftmake import (
    Rift, get_rift_type, get_story_type, NONEMSG, get_battle_type,
    get_dxsj_info, get_boss_battle_info, get_treasure_info
)
from ..xiuxian_mixelixir.mixelixirutil import get_mix_elixir_msg, tiaohe, check_mix, make_dict
from ..xiuxian_boss.makeboss import create_all_bosses, createboss_jj
from ..xiuxian_boss.bossconfig import get_boss_config
from ..xiuxian_boss.boss_limit import boss_limit
from ..xiuxian_impart.impart_uitls import get_impart_card_display_info
from ..xiuxian_impart.impart_data import impart_data_json
from ..xiuxian_impart_pk.impart_pk import impart_pk
from ..xiuxian_impart_pk import impart_pk_uitls
from ..xiuxian_impart_pk.xu_world import xu_world
from .gameplay_impart import (
    world_status as _ws_world_status,
    project as _ws_project,
    projections as _ws_projections,
    rankings as _ws_rankings,
    validate_challenge as _ws_validate_challenge,
    challenge as _ws_challenge,
    train as _ws_train,
    explore as _ws_explore,
    retreat_start as _ws_retreat_start,
    retreat_finish as _ws_retreat_finish,
)
from .gameplay_reincarnation import (
    status as _lh_status,
    advance as _lh_advance,
    infinite as _lh_infinite,
    reset_cultivation as _lh_reset_cultivation,
    rankings as _lh_rankings,
)
from .. import NICKNAME
from .auth_password import (
    is_valid_user_id as _auth_is_valid_user_id,
    validate_password as _auth_validate_password,
    has_password as _auth_has_password,
    verify_password as _auth_verify_password,
    set_password as _auth_set_password,
    mark_password_login as _auth_mark_password_login,
    check_rate_limit as _auth_check_rate_limit,
    record_failure as _auth_record_failure,
    clear_failures as _auth_clear_failures,
)
from ..xiuxian_back.back_util import (
    check_equipment_can_use,
    get_use_equipment_sql,
    get_no_use_equipment_sql,
)

items = Items()
game_sql = XiuxianDateManage()
update_manager = UpdateManager()
xiuxian_impart = XIUXIAN_IMPART_BUFF()
app = Flask(__name__)
app.config["SESSION_PERMANENT"] = False

# 配置
DATA_PATH = Path.cwd() / "data" / "xiuxian"
DATABASE = DATA_PATH / "xiuxian.db"
IMPART_DB = DATA_PATH / "xiuxian_impart.db"
ASSETS_PATH = DATA_PATH
PLAYERSDATA = DATA_PATH / "players"
ADMIN_IDS = get_driver().config.superusers
PORT = XiuConfig().web_port
HOST = XiuConfig().web_host

# 配置秘钥，确保重启后 Session 依然有效，如果需要强制所有用户重新登录，可以修改此处
SECRET_KEY_FILE = DATA_PATH / "web_secret.key"
if not SECRET_KEY_FILE.exists():
    if not DATA_PATH.exists():
        DATA_PATH.mkdir(parents=True, exist_ok=True)
    with open(SECRET_KEY_FILE, "w") as f:
        f.write(secrets.token_hex(32))

with open(SECRET_KEY_FILE, "r") as f:
    app.secret_key = f.read().strip()

# =========================
# 资源服务
# =========================

@app.route('/assets/card/<name>')
def serve_card_img(name):
    """服务角色卡图，支持 .webp 和 .png"""
    if not name or name == 'undefined' or name == 'default' or name == 'null':
        # 随机返回一个卡图作为默认值
        cards = list((ASSETS_PATH / "卡图").glob("*.webp"))
        if not cards: cards = list((ASSETS_PATH / "卡图").glob("*.png"))
        if cards: 
            target = cards[secrets.randbelow(len(cards))]
            return send_file(str(target.absolute()))
        return "Not Found", 404
        
    for ext in ['.webp', '.png']:
        path = ASSETS_PATH / "卡图" / f"{name}{ext}"
        if path.exists():
            return send_file(str(path.absolute()))
    
    # 模糊匹配
    cards = list((ASSETS_PATH / "卡图").glob(f"*{name}*"))
    if cards: return send_file(str(cards[0].absolute()))
    
    # 回退到随机卡图
    cards = list((ASSETS_PATH / "卡图").glob("*.webp"))
    if not cards: cards = list((ASSETS_PATH / "卡图").glob("*.png"))
    if cards:
        return send_file(str(cards[secrets.randbelow(len(cards))].absolute()))
    
    return "Not Found", 404

@app.route('/assets/boss/<name>')
def serve_boss_img(name):
    """服务 Boss 图片"""
    if not name or name == 'undefined' or name == 'null':
        bosses = list((ASSETS_PATH / "boss_img").glob("*.png"))
        if bosses:
            return send_file(str(bosses[secrets.randbelow(len(bosses))].absolute()))
        return "Not Found", 404

    path = ASSETS_PATH / "boss_img" / f"{name}.png"
    if path.exists():
        return send_file(str(path.absolute()))
    path_c = ASSETS_PATH / "boss_img" / f"{name}_c.png"
    if path_c.exists():
        return send_file(str(path_c.absolute()))
        
    # 模糊匹配
    bosses = list((ASSETS_PATH / "boss_img").glob(f"*{name}*"))
    if bosses:
        return send_file(str(bosses[0].absolute()))
        
    # 回退到随机 Boss 图
    bosses = list((ASSETS_PATH / "boss_img").glob("*.png"))
    if bosses:
        return send_file(str(bosses[secrets.randbelow(len(bosses))].absolute()))
        
    return "Not Found", 404

@app.route('/assets/bg')
def serve_bg():
    """服务背景图"""
    # 优先尝试 data/xiuxian/image/background.png
    path = ASSETS_PATH / "image" / "background.png"
    if path.exists():
        return send_file(str(path.absolute()))
    
    # 备选路径：如果没有背景图，尝试从卡图中随便找一张，或者返回 404
    return "Not Found", 404

# 境界和灵根预设
LEVELS = convert_rank('江湖好手')[1]

ROOTS = {
    "1": "混沌灵根",
    "2": "融合灵根",
    "3": "超灵根",
    "4": "龙灵根",
    "5": "天灵根",
    "6": "轮回道果",
    "7": "真·轮回道果",
    "8": "永恒道果",
    "9": "命运道果"
}

# 管理员指令
ADMIN_COMMANDS = {
    "gm_command": {
        "name": "神秘力量",
        "description": "修改灵石数量",
        "params": [
            {"name": "目标", "type": "select", "options": ["指定用户", "全服"], "key": "target"},
            {"name": "道号", "type": "text", "required": False, "key": "username", "show_if": {"target": "指定用户"}},
            {"name": "数量", "type": "number", "required": True, "key": "amount"}
        ]
    },
    "adjust_exp_command": {
        "name": "修为调整",
        "description": "修改修为数量",
        "params": [
            {"name": "目标", "type": "select", "options": ["指定用户", "全服"], "key": "target"},
            {"name": "道号", "type": "text", "required": False, "key": "username", "show_if": {"target": "指定用户"}},
            {"name": "数量", "type": "number", "required": True, "key": "amount"}
        ]
    },
    "gmm_command": {
        "name": "轮回力量",
        "description": "修改灵根",
        "params": [
            {"name": "道号", "type": "text", "required": True, "key": "username"},
            {"name": "灵根类型", "type": "select", "options": ROOTS, "key": "root_type"}
        ]
    },
    "zaohua_xiuxian": {
        "name": "造化力量",
        "description": "修改境界",
        "params": [
            {"name": "道号", "type": "text", "required": True, "key": "username"},
            {"name": "境界", "type": "select", "options": LEVELS, "key": "level"}
        ]
    },
    "cz": {
        "name": "创造力量",
        "description": "发放物品",
        "params": [
            {"name": "目标", "type": "select", "options": ["指定用户", "全服"], "key": "target"},
            {"name": "道号", "type": "text", "required": False, "key": "username", "show_if": {"target": "指定用户"}},
            {"name": "物品", "type": "text", "required": True, "key": "item", "placeholder": "物品名称或ID"},
            {"name": "数量", "type": "number", "required": True, "key": "amount"}
        ]
    },
    "hmll": {
        "name": "毁灭力量",
        "description": "扣除物品",
        "params": [
            {"name": "目标", "type": "select", "options": ["指定用户", "全服"], "key": "target"},
            {"name": "道号", "type": "text", "required": False, "key": "username", "show_if": {"target": "指定用户"}},
            {"name": "物品", "type": "text", "required": True, "key": "item", "placeholder": "物品名称或ID"},
            {"name": "数量", "type": "number", "required": True, "key": "amount"}
        ]
    },
    "ccll_command": {
        "name": "传承力量",
        "description": "修改思恋结晶数量",
        "params": [
            {"name": "目标", "type": "select", "options": ["指定用户", "全服"], "key": "target"},
            {"name": "道号", "type": "text", "required": False, "key": "username", "show_if": {"target": "指定用户"}},
            {"name": "数量", "type": "number", "required": True, "key": "amount"}
        ]
    }
}

# 从配置类获取表结构信息
def get_config_tables():
    """从预设配置类获取表结构信息"""
    tables = {
        "主数据库": {
            "path": DATABASE,
            "tables": get_config_table_structure(XiuConfig())
        },
        "虚神界数据库": {
            "path": IMPART_DB,
            "tables": get_impart_table_structure(config_impart)
        }
    }
    return tables

def get_config_table_structure(config):
    """从XiuConfig获取表结构"""
    tables = {}
    
    # 主用户表
    tables["user_xiuxian"] = {
        "name": "用户修仙信息",
        "fields": config.sql_user_xiuxian,
        "primary_key": "id"
    }
    
    # CD表
    tables["user_cd"] = {
        "name": "用户CD信息",
        "fields": config.sql_user_cd,
        "primary_key": "user_id"
    }
    
    # 宗门表
    tables["sects"] = {
        "name": "宗门信息",
        "fields": config.sql_sects,
        "primary_key": "sect_id"
    }
    
    # 背包表 - 特殊处理复合主键
    tables["back"] = {
        "name": "用户背包",
        "fields": config.sql_back,
        "primary_key": ["user_id", "goods_id"],  # 改为复合主键
        "composite_key": True  # 添加标识
    }
    
    # Buff信息表
    tables["BuffInfo"] = {
        "name": "Buff信息",
        "fields": config.sql_buff,
        "primary_key": "id"
    }
    
    return tables

def get_impart_table_structure(config):
    """从IMPART_BUFF_CONFIG获取表结构"""
    tables = {}
    
    # 虚神界表
    tables["xiuxian_impart"] = {
        "name": "虚神界信息",
        "fields": config.sql_table_impart_buff,
        "primary_key": "id"
    }

    # 传承信息表
    tables["impart_cards"] = {
        "name": "传承信息",
        "fields": ["user_id", "card_name", "quantity"],
        "primary_key": ["user_id", "card_name"],  # 复合主键
        "composite_key": True  # 添加复合主键标识
    }
    
    return tables

def get_tables():
    """获取所有数据库的表结构，按数据库分组（使用预设配置）"""
    return get_config_tables()

def get_database_tables(db_path):
    """动态获取数据库中的所有表及其字段信息，包括主键（备用函数）"""
    tables = {}
    conn = sqlite3.connect(db_path, check_same_thread=False)
    cursor = conn.cursor()
    
    # 获取所有用户表
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
    table_names = [row[0] for row in cursor.fetchall()]
    
    for table_name in table_names:
        # 获取表的字段信息
        cursor.execute(f"PRAGMA table_info({table_name})")
        fields_info = cursor.fetchall()
        fields = [row[1] for row in fields_info]
        
        # 查找主键字段
        primary_key = None
        for row in fields_info:
            if row[5] == 1:
                primary_key = row[1]
                break
        
        tables[table_name] = {
            "name": table_name,
            "fields": fields,
            "primary_key": primary_key
        }
    
    conn.close()
    return tables

def get_db_connection(db_path):
    """获取数据库连接"""
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def execute_sql(db_path, sql, params=None):
    """执行SQL语句"""
    conn = get_db_connection(db_path)
    cursor = conn.cursor()
    
    try:
        if params:
            cursor.execute(sql, params)
        else:
            cursor.execute(sql)
        
        # 判断是否是查询语句
        if sql.strip().lower().startswith('select'):
            result = cursor.fetchall()
            return [dict(row) for row in result]
        else:
            conn.commit()
            return {"affected_rows": cursor.rowcount}
    except Exception as e:
        return {"error": str(e)}
    finally:
        conn.close()

def get_table_data(db_path, table_name, page=1, per_page=10, search_field=None, search_value=None):
    """获取表数据（分页和搜索）"""
    offset = (page - 1) * per_page
    
    # 获取表信息以确定主键
    tables = get_database_tables(db_path)
    table_info = tables.get(table_name, {})
    primary_key = table_info.get('primary_key', 'id')
    
    # 基础查询
    sql = f"SELECT * FROM {table_name}"
    params = []
    
    # 添加搜索条件 - 支持多值搜索
    if search_field and search_value:
        # 单字段搜索逻辑（保持不变）
        values = search_value.split()
        if len(values) > 1:
            placeholders = " OR ".join([f"{search_field} LIKE ?" for _ in values])
            sql += f" WHERE ({placeholders})"
            params.extend([f"%{value}%" for value in values])
        else:
            sql += f" WHERE {search_field} LIKE ?"
            params.append(f"%{search_value}%")
    
    elif search_value:  # 全字段搜索
        # 获取所有字段
        tables = get_database_tables(db_path)
        table_fields = tables.get(table_name, {}).get('fields', [])
        
        if table_fields:
            conditions = []
            search_params = []
            
            # 对每个字段添加LIKE条件
            for field in table_fields:
                # 排除主键字段（可选）
                if field != tables[table_name].get('primary_key'):
                    conditions.append(f"{field} LIKE ?")
                    search_params.append(f"%{search_value}%")
            
            # 只有当有搜索条件时才添加WHERE子句
            if conditions:
                sql += f" WHERE ({' OR '.join(conditions)})"
                params.extend(search_params)
            else:
                # 如果没有可搜索的字段，返回空结果
                sql += " WHERE 1=0"  # 确保不返回任何结果
    
    # 添加分页
    sql += f" LIMIT ? OFFSET ?"
    params.extend([per_page, offset])
    
    # 执行查询
    data = execute_sql(db_path, sql, params)
    
    # 获取总数（需要相应修改）
    count_sql = f"SELECT COUNT(*) FROM {table_name}"
    count_params = []
    
    if search_field and search_value:
        # 单字段搜索的计数逻辑
        values = search_value.split()
        if len(values) > 1:
            placeholders = " OR ".join([f"{search_field} LIKE ?" for _ in values])
            count_sql += f" WHERE ({placeholders})"
            count_params = [f"%{value}%" for value in values]
        else:
            count_sql += f" WHERE {search_field} LIKE ?"
            count_params = [f"%{search_value}%"]
    
    elif search_value:
        # 全字段搜索的计数逻辑
        tables = get_database_tables(db_path)
        table_fields = tables.get(table_name, {}).get('fields', [])
        
        if table_fields:
            conditions = []
            for field in table_fields:
                if field != tables[table_name].get('primary_key'):
                    conditions.append(f"{field} LIKE ?")
                    count_params.append(f"%{search_value}%")
            
            if conditions:
                count_sql += f" WHERE ({' OR '.join(conditions)})"
            else:
                count_sql += " WHERE 1=0"
    
    total_result = execute_sql(db_path, count_sql, count_params)
    total = total_result[0]['COUNT(*)'] if total_result else 0

    return {
        "data": data,
        "total": total,
        "page": page,
        "per_page": per_page,
        "total_pages": (total + per_page - 1) // per_page
    }

def get_user_by_name(username):
    """根据道号获取用户信息（使用execute_sql）"""
    sql = "SELECT * FROM user_xiuxian WHERE user_name = ?"
    result = execute_sql(DATABASE, sql, (username,))
    if result and len(result) > 0:
        return result[0]
    return None

def get_user_by_id(user_id):
    """根据ID获取用户信息（使用execute_sql）"""
    sql = "SELECT * FROM user_xiuxian WHERE user_id = ?"
    result = execute_sql(DATABASE, sql, (user_id,))
    if result and len(result) > 0:
        return result[0]
    return None


# =========================
# 玩家网页端（MVP）
# =========================
# 说明：这里先在现有 Flask 管理面板中挂载一个玩家端原型，避免额外引入前端构建链。
# 后续如果要做正式 DMM 风格 SPA，可以把这些 /game/api/* 接口迁移/扩展到独立 service。

WORK_EXPIRE_MINUTES = 30
TOKEN_EXPIRE_SECONDS = 300
LOGIN_TOKEN_CACHE = {}  # token -> {user_id, expire_at, used}
ADMIN_TOKEN_CACHE = {}  # token -> {admin_id, expire_at, used}
WORLD_BOSS_INTEGRAL_BASE = 15000
WORLD_BOSS_DAILY_INTEGRAL_LIMIT = 30000
WORLD_BOSS_DAILY_STONE_LIMIT = 300000000

# QQ 群内发送「/修仙登录」后，机器人会将一次性网页登录链接私聊给发起人。
web_login_token_cmd = on_command("修仙登录", priority=5, block=True)
# 管理员发送「/修仙后台登录」，生成后台登录链接
admin_login_token_cmd = on_command("修仙后台登录", priority=5, block=True)


def _clean_expired_tokens():
    now_ts = datetime.now().timestamp()
    # 清理玩家 token
    expired = [tk for tk, info in LOGIN_TOKEN_CACHE.items() if info.get("expire_at", 0) < now_ts or info.get("used")]
    for tk in expired:
        LOGIN_TOKEN_CACHE.pop(tk, None)
    # 清理管理员 token
    expired_admin = [tk for tk, info in ADMIN_TOKEN_CACHE.items() if info.get("expire_at", 0) < now_ts or info.get("used")]
    for tk in expired_admin:
        ADMIN_TOKEN_CACHE.pop(tk, None)


def _issue_login_token(user_id: int) -> str:
    _clean_expired_tokens()
    token = secrets.token_urlsafe(18)
    LOGIN_TOKEN_CACHE[token] = {
        "user_id": int(user_id),
        "expire_at": datetime.now().timestamp() + TOKEN_EXPIRE_SECONDS,
        "used": False,
    }
    return token


def _issue_admin_token(admin_id: str) -> str:
    _clean_expired_tokens()
    token = "adm_" + secrets.token_urlsafe(24)
    ADMIN_TOKEN_CACHE[token] = {
        "admin_id": str(admin_id),
        "expire_at": datetime.now().timestamp() + TOKEN_EXPIRE_SECONDS,
        "used": False,
    }
    return token


def _consume_login_token(token: str):
    _clean_expired_tokens()
    info = LOGIN_TOKEN_CACHE.get(token)
    if not info:
        return None, "登录令无效或已过期"
    if info.get("used"):
        return None, "登录令已使用"
    info["used"] = True
    return int(info["user_id"]), ""


def _consume_admin_token(token: str):
    _clean_expired_tokens()
    info = ADMIN_TOKEN_CACHE.get(token)
    if not info:
        return None, "管理员登录令无效或已过期"
    if info.get("used"):
        return None, "管理员登录令已使用"
    info["used"] = True
    return str(info["admin_id"]), ""


def get_local_ip():
    """获取本机 IP，用于生成登录链接"""
    try:
        import socket
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"

@web_login_token_cmd.handle()
async def _(bot: Bot, event: GroupMessageEvent | PrivateMessageEvent, args: Message = CommandArg()):
    user_id = int(event.get_user_id())
    user = game_sql.get_user_info_with_id(user_id)
    if not user:
        await handle_send(bot, event, "尚未创建修仙角色，请先发送【我要修仙】")
        await web_login_token_cmd.finish()
    
    token = _issue_login_token(user_id)
    
    # 自动识别外部访问地址
    display_host = "xiuxian.superbread.uk"
    
    login_url = f"https://{display_host}/game?token={token}"
    
    msg = (
        "【网页一次性登录令】\n"
        f"道号：{user.get('user_name', user_id)}\n"
        f"登录令：{token}\n"
        f"有效期：{TOKEN_EXPIRE_SECONDS // 60} 分钟，仅可使用一次\n\n"
        f"快捷登录链接：\n{login_url}\n\n"
        "温馨提示：如果点击链接无法打开，请尝试在网页登录页面手动输入登录令。请勿将此链接泄露给他人。"
    )
    
    try:
        # 尝试私聊发送
        await bot.send_private_msg(user_id=user_id, message=msg)
        if isinstance(event, GroupMessageEvent):
            await handle_send(bot, event, "【仙途绘卷】网页登录令已通过私聊发送给您，请注意查收。")
    except Exception as e:
        logger.error(f"发送网页登录令私聊失败: {e}")
        if isinstance(event, GroupMessageEvent):
            await handle_send(bot, event, "私聊发送失败，请先添加机器人好友或允许临时会话后再发送 /修仙登录。")
        else:
            # 如果本身就是私聊但发送失败（罕见），则尝试在当前会话回复（虽然通常也是私聊）
            await handle_send(bot, event, msg)
    await web_login_token_cmd.finish()


@admin_login_token_cmd.handle()
async def _(bot: Bot, event: GroupMessageEvent | PrivateMessageEvent):
    user_id = str(event.get_user_id())
    if user_id not in ADMIN_IDS:
        await handle_send(bot, event, "权限不足，只有超级管理员可以使用此指令。")
        await admin_login_token_cmd.finish()
    
    token = _issue_admin_token(user_id)
    
    display_host = "xiuxian.superbread.uk"
    login_url = f"https://{display_host}/login?token={token}"
    
    msg = (
        "【管理员后台快捷登录】\n"
        f"有效期：{TOKEN_EXPIRE_SECONDS // 60} 分钟，仅可使用一次\n\n"
        f"点击链接直接进入后台：\n{login_url}"
    )
    
    try:
        await bot.send_private_msg(user_id=int(user_id), message=msg)
        if isinstance(event, GroupMessageEvent):
            await handle_send(bot, event, "管理员登录链接已通过私聊发送。")
    except Exception as e:
        logger.error(f"发送管理员登录令失败: {e}")
        await handle_send(bot, event, "私聊发送失败，请确保已添加机器人为好友。")
    await admin_login_token_cmd.finish()


def game_login_required(view_func):
    """玩家端接口登录保护。"""
    @wraps(view_func)
    def wrapper(*args, **kwargs):
        if 'player_id' not in session:
            return jsonify({"success": False, "error": "未登录", "login_required": True}), 401
        return view_func(*args, **kwargs)
    return wrapper


def _current_player_id():
    player_id = session.get('player_id')
    try:
        return int(player_id) if player_id is not None else None
    except (TypeError, ValueError):
        return None


# Token 登录后免旧密码重置的临时权限时长（秒）
TOKEN_AUTH_TTL_SECONDS = 600


def _has_fresh_token_auth():
    """判断当前会话是否有效且仍处于 Token 登录后的短期高权限窗口内。"""
    if session.get('player_auth_via') != 'token':
        return False
    until = session.get('player_token_auth_until')
    try:
        until = int(until)
    except (TypeError, ValueError):
        return False
    if until <= 0:
        return False
    return time.time() <= until


def _grant_token_auth(user_id):
    """Token 登录成功后标记短期免旧密码重置权限。"""
    session['player_auth_via'] = 'token'
    session['player_token_auth_until'] = int(time.time()) + TOKEN_AUTH_TTL_SECONDS


def _consume_token_auth():
    """消费/清除 token 高权限标记，回到常规密码登录语义。"""
    session['player_auth_via'] = 'password'
    session.pop('player_token_auth_until', None)


def _ok(**kwargs):
    data = {"success": True}
    data.update(kwargs)
    return jsonify(data)


def _err(message, status_code=400, **kwargs):
    data = {"success": False, "error": message}
    data.update(kwargs)
    return jsonify(data), status_code


def _display_number(value):
    try:
        return number_to(int(value))
    except Exception:
        return str(value if value is not None else 0)


def _parse_datetime(value):
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


def _calculate_work_remaining(create_time, work_name=None, user_id=None):
    """计算悬赏剩余时间，返回 remaining/elapsed/total（分钟）。"""
    start = _parse_datetime(create_time)
    if not start:
        return 0, 0, None
    elapsed = int((datetime.now() - start).total_seconds() // 60)
    if work_name and user_id:
        try:
            total = int(workhandle().do_work(key=1, name=work_name, user_id=user_id) or 0)
        except Exception:
            total = 0
        return max(total - elapsed, 0), elapsed, total
    return max(WORK_EXPIRE_MINUTES - elapsed, 0), elapsed, WORK_EXPIRE_MINUTES


def _get_player_work_status(user_id):
    """网页端复用悬赏令状态机。

    返回：
    0 无悬赏 / 1 进行中 / 2 可结算 / 3 未接取可选 / 4 已过期
    """
    user_cd = game_sql.get_user_cd(user_id)
    if user_cd and user_cd.get('type') == 2:
        remaining, _, _ = _calculate_work_remaining(user_cd.get('create_time'), user_cd.get('scheduled_time'), user_id)
        return (1 if remaining > 0 else 2), user_cd

    has_work, work_data = has_unaccepted_work(user_id, expire_minutes=WORK_EXPIRE_MINUTES)
    if has_work:
        return 3, work_data
    if work_data:
        return 4, work_data
    return 0, None


def _serialize_item(goods_id, fallback=None):
    try:
        item = items.get_data_by_item_id(goods_id) if goods_id else None
    except (KeyError, Exception):
        item = None
    fallback = fallback or {}
    res = {
        "id": goods_id,
        "name": (item or {}).get('name') or fallback.get('goods_name') or "未知物品",
        "type": (item or {}).get('type') or fallback.get('goods_type') or "未知",
        "item_type": (item or {}).get('item_type') or fallback.get('goods_type') or "未知",
        "level": (item or {}).get('level') or "凡品",
        "desc": (item or {}).get('desc') or fallback.get('remake') or "暂无描述",
    }
    if item:
        res["buff_type"] = item.get("buff_type")
        res["buff"] = item.get("buff")
    return res


def _serialize_work(status, work_data, user_id):
    user = game_sql.get_user_info_with_id(user_id) or {}
    payload = {
        "status_code": status,
        "status": "idle",
        "label": "暂无悬赏",
        "message": "没有查到悬赏令，请刷新获取新的悬赏。",
        "refresh_left": user.get('work_num', 0),
        "tasks": [],
    }

    if status == 1 and work_data:
        remaining, elapsed, total = _calculate_work_remaining(work_data.get('create_time'), work_data.get('scheduled_time'), user_id)
        payload.update({
            "status": "running",
            "label": "悬赏执行中",
            "message": f"悬赏令【{work_data.get('scheduled_time')}】执行中，剩余 {remaining} 分钟。",
            "current_task": work_data.get('scheduled_time'),
            "remaining_minutes": remaining,
            "elapsed_minutes": elapsed,
            "total_minutes": total,
        })
    elif status == 2 and work_data:
        payload.update({
            "status": "settle",
            "label": "悬赏可结算",
            "message": f"悬赏令【{work_data.get('scheduled_time')}】已完成，可以领取奖励。",
            "current_task": work_data.get('scheduled_time'),
            "remaining_minutes": 0,
        })
    elif status == 3 and work_data:
        remaining, elapsed, total = _calculate_work_remaining(work_data.get('refresh_time'))
        task_items = []
        for index, (task_name, task_data) in enumerate((work_data.get('tasks') or {}).items(), 1):
            item_id = task_data.get('item_id', 0)
            task_items.append({
                "index": index,
                "name": task_name,
                "rate": task_data.get('rate', 0),
                "award": task_data.get('award', 0),
                "award_display": _display_number(task_data.get('award', 0)),
                "time": task_data.get('time', 0),
                "item": _serialize_item(item_id) if item_id else None,
            })
        payload.update({
            "status": "available",
            "label": "待接取悬赏",
            "message": f"请选择一个悬赏接取，悬赏令剩余 {remaining} 分钟。",
            "remaining_minutes": remaining,
            "elapsed_minutes": elapsed,
            "total_minutes": total,
            "tasks": task_items,
        })
    elif status == 4:
        payload.update({
            "status": "expired",
            "label": "悬赏已过期",
            "message": "悬赏令已过期，请刷新获取新的悬赏。",
        })
    return payload


def _build_player_profile(user_id):
    user = game_sql.get_user_real_info(user_id) or game_sql.get_user_info_with_id(user_id)
    if not user:
        return None

    try:
        rank = game_sql.get_exp_rank(user_id)
        exp_rank = int(rank[0]) if rank else 0
    except Exception:
        exp_rank = 0
    try:
        stone_rank = int((game_sql.get_stone_rank(user_id) or [0])[0])
    except Exception:
        stone_rank = 0

    try:
        level_rate = game_sql.get_root_rate(user.get('root_type'), user_id)
        realm_rate = jsondata.level_data()[user.get('level')]["spend"]
        power = int(user.get('power') or user.get('exp', 0) * level_rate * realm_rate)
    except Exception:
        level_rate = 0
        power = int(user.get('power') or 0)

    sect_name = "无宗门"
    sect_position = "无"
    if user.get('sect_id'):
        try:
            sect = game_sql.get_sect_info(user.get('sect_id'))
            sect_name = sect.get('sect_name', sect_name) if sect else sect_name
            sect_position = jsondata.sect_config_data().get(str(user.get('sect_position')), {}).get('title', sect_position)
        except Exception:
            pass

    try:
        level_list = OtherSet().level
        now_index = level_list.index(user.get('level'))
        if now_index >= len(level_list) - 1:
            next_level = None
            need_exp = 0
            breakthrough = "位面至高"
        else:
            next_level = level_list[now_index + 1]
            need_exp = max(int(game_sql.get_level_power(next_level)) - int(user.get('exp', 0)), 0)
            breakthrough = "可突破" if need_exp == 0 else f"还需 {_display_number(need_exp)} 修为"
    except Exception:
        next_level = None
        need_exp = 0
        breakthrough = "未知"

    buff = UserBuffDate(user_id)
    def buff_name(getter):
        try:
            data = getter()
            if data:
                return f"{data.get('name', '未知')}({data.get('level', '未知')})"
        except Exception:
            pass
        return "无"

    max_stamina = XiuConfig().max_stamina
    hp = int(user.get('hp') or 0)
    mp = int(user.get('mp') or 0)
    exp = int(user.get('exp') or 0)
    
    # 确定卡图名称
    cards = [c.stem for c in (ASSETS_PATH / "卡图").glob("*.webp")]
    if not cards: cards = [c.stem for c in (ASSETS_PATH / "卡图").glob("*.png")]
    card_name = cards[int(user_id) % len(cards)] if cards else "default"

    equipment = {
        "main": buff_name(buff.get_user_main_buff_data),
        "sub": buff_name(buff.get_user_sub_buff_data),
        "skill": buff_name(buff.get_user_sec_buff_data),
        "movement": buff_name(buff.get_user_effect1_buff_data),
        "eyes": buff_name(buff.get_user_effect2_buff_data),
        "weapon": buff_name(buff.get_user_weapon_data),
        "armor": buff_name(buff.get_user_armor_buff_data),
    }

    try:
        equip_rows = execute_sql(
            DATABASE,
            "SELECT goods_id, goods_name, goods_type, state FROM back WHERE user_id = ? AND state = 1",
            (user_id,),
        ) or []
        for row in equip_rows:
            goods_type = str(row.get("goods_type") or "")
            if goods_type not in ("法器", "防具"):
                continue
            goods_id = row.get("goods_id")
            item = _serialize_item(goods_id, fallback=row)
            item_obj = {
                "name": item.get("name"),
                "type": item.get("type"),
                "level": item.get("level"),
                "buff_type": item.get("buff_type"),
                "buff": item.get("buff"),
            }
            if goods_type == "法器":
                equipment["weapon"] = item_obj
            elif goods_type == "防具":
                equipment["armor"] = item_obj
    except Exception:
        pass

    impart_crystal = 0
    impart_wish = 0
    impart_daily_draws = 0
    try:
        impart_info = xiuxian_impart.get_user_impart_info_with_id(user_id) or {}
        impart_crystal = int(impart_info.get("stone_num") or 0)
        impart_wish = int(impart_info.get("wish") or 0)
        impart_daily_draws = int(impart_info.get("impart_num") or 0)
    except Exception:
        pass

    return {
        "id": int(user.get('user_id')),
        "name": user.get('user_name') or f"无名氏({user_id})",
        "card_img": f"/assets/card/{card_name}",
        "level": user.get('level') or "未知",
        "next_level": next_level,
        "breakthrough": breakthrough,
        "need_exp": need_exp,
        "root": user.get('root') or "未知",
        "root_type": user.get('root_type') or "未知",
        "root_rate": int(level_rate * 100) if isinstance(level_rate, (int, float)) else 0,
        "sect": sect_name,
        "sect_position": sect_position,
        "exp": exp,
        "exp_display": _display_number(exp),
        "stone": int(user.get('stone') or 0),
        "stone_display": _display_number(user.get('stone') or 0),
        "impart_crystal": impart_crystal,
        "impart_crystal_display": _display_number(impart_crystal),
        "impart_wish": impart_wish,
        "impart_daily_draws": impart_daily_draws,
        "power": power,
        "power_display": _display_number(power),
        "hp": hp,
        "hp_display": _display_number(hp),
        "mp": mp,
        "mp_display": _display_number(mp),
        "atk": int(user.get('atk') or 0),
        "atk_display": _display_number(user.get('atk') or 0),
        "stamina": int(user.get('user_stamina') or 0),
        "max_stamina": int(max_stamina),
        "work_num": int(user.get('work_num') or 0),
        "exp_rank": exp_rank,
        "stone_rank": stone_rank,
        "cultivation": {
            "atk": int(user.get('atkpractice') or 0),
            "hp": int(user.get('hppractice') or 0),
            "mp": int(user.get('mppractice') or 0),
        },
        "equipment": equipment
    }


def _build_backpack(user_id, limit=120):
    rows = game_sql.get_back_msg(user_id) or []
    result = []
    for row in rows[:limit]:
        goods_id = row.get('goods_id')
        item = _serialize_item(goods_id, row)
        result.append({
            "id": goods_id,
            "name": row.get('goods_name') or item['name'],
            "type": row.get('goods_type') or item['type'],
            "item_type": item['item_type'],
            "level": item['level'],
            "desc": item['desc'],
            "count": int(row.get('goods_num') or 0),
            "bind_count": int(row.get('bind_num') or 0) if row.get('bind_num') is not None else 0,
            "state": int(row.get('state') or 0),
            "equipped": int(row.get('state') or 0) == 1,
            "buff_type": item.get("buff_type"),
            "buff": item.get("buff"),
        })
    result.sort(key=lambda x: (not x['equipped'], x['type'], x['id'] or 0))
    return result


def _is_equipment_item(item: dict) -> bool:
    item_type = str(item.get("item_type") or "")
    goods_type = str(item.get("type") or "")
    return item_type in ("法器", "防具") or goods_type in ("装备", "法器", "防具")


def _build_rankings(limit=20):
    exp_rows = execute_sql(DATABASE, "SELECT user_id,user_name,level,exp FROM user_xiuxian ORDER BY exp DESC LIMIT ?", (limit,)) or []
    stone_rows = execute_sql(DATABASE, "SELECT user_id,user_name,level,stone FROM user_xiuxian ORDER BY stone DESC LIMIT ?", (limit,)) or []
    power_rows = execute_sql(DATABASE, "SELECT user_id,user_name,level,power FROM user_xiuxian ORDER BY power DESC LIMIT ?", (limit,)) or []
    def _fmt(rows, key):
        return [{
            "rank": idx,
            "user_id": int(r.get("user_id") or 0),
            "name": r.get("user_name") or f"道友{idx}",
            "level": r.get("level") or "未知",
            "value": int(r.get(key) or 0),
            "value_display": _display_number(r.get(key) or 0),
        } for idx, r in enumerate(rows, 1)]
    return {
        "exp": _fmt(exp_rows, "exp"),
        "stone": _fmt(stone_rows, "stone"),
        "power": _fmt(power_rows, "power"),
    }


def _build_sect_info(user_id):
    user = game_sql.get_user_info_with_id(user_id) or {}
    sect_id = user.get("sect_id")
    if not sect_id:
        return {"joined": False, "message": "尚未加入宗门"}
    sect = game_sql.get_sect_info(sect_id) or {}
    members = execute_sql(DATABASE, "SELECT COUNT(*) as c FROM user_xiuxian WHERE sect_id = ?", (sect_id,)) or [{"c": 0}]
    try:
        pragma_rows = execute_sql(DATABASE, "PRAGMA table_info(user_xiuxian)") or []
        columns = {str((r or {}).get("name") or "") for r in pragma_rows if isinstance(r, dict)}
        columns.discard("")
    except Exception:
        columns = set()
    try:
        sect_pragma_rows = execute_sql(DATABASE, "PRAGMA table_info(sects)") or []
        sect_columns = {str((r or {}).get("name") or "") for r in sect_pragma_rows if isinstance(r, dict)}
        sect_columns.discard("")
    except Exception:
        sect_columns = set()

    def _safe_get(obj, key, default=None):
        if isinstance(obj, dict):
            return obj.get(key, default)
        try:
            if hasattr(obj, "keys") and key in obj.keys():
                return obj[key]
        except Exception:
            pass
        return getattr(obj, key, default)

    def _safe_bool(value):
        if value is None:
            return None
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return value != 0
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"1", "true", "yes", "on", "开放"}:
                return True
            if normalized in {"0", "false", "no", "off", "关闭"}:
                return False
            return None
        return None

    def _safe_int(value):
        if value is None or value == "":
            return None
        try:
            return int(value)
        except Exception:
            return None

    def _safe_text(value):
        if value is None:
            return ""
        try:
            return str(value)
        except Exception:
            return ""

    def _compact_text(value):
        text = _safe_text(value).strip()
        return text

    def _join_non_empty(parts, sep="，"):
        valid = [p for p in parts if isinstance(p, str) and p.strip()]
        return sep.join(valid)

    def _safe_first(data, keys):
        if not isinstance(data, dict):
            return None
        for key in keys:
            if key in data and data.get(key) not in (None, ""):
                return data.get(key)
        return None

    def _format_cost_text(cfg):
        if not isinstance(cfg, dict):
            return ""
        cost = _safe_first(cfg, ["cost", "price", "contribution", "integral", "stone", "materials"])
        if cost not in (None, ""):
            if "contribution" in cfg:
                return f"贡献 {_safe_text(cfg.get('contribution'))}"
            if "integral" in cfg:
                return f"贡献 {_safe_text(cfg.get('integral'))}"
            if "stone" in cfg:
                return f"灵石 {_safe_text(cfg.get('stone'))}"
            if "materials" in cfg:
                return f"资材 {_safe_text(cfg.get('materials'))}"
            return _safe_text(cost)
        parts = []
        need_item = cfg.get("need_item")
        if isinstance(need_item, dict):
            for item_id, num in list(need_item.items())[:5]:
                parts.append(f"物品{_safe_text(item_id)}x{_safe_text(num)}")
        return _join_non_empty(parts)

    def _format_requirement_text(cfg):
        if not isinstance(cfg, dict):
            return ""
        req_parts = []
        level_req = _safe_first(cfg, ["sect_level", "need_sect_level", "required_sect_level"])
        if level_req not in (None, ""):
            req_parts.append(f"宗门等级≥{_safe_text(level_req)}")
        room_req = _safe_first(cfg, ["elixir_room_level", "need_elixir_room_level", "required_elixir_room_level"])
        if room_req not in (None, ""):
            req_parts.append(f"丹房等级≥{_safe_text(room_req)}")
        pos_req = _safe_first(cfg, ["position", "sect_position", "required_position", "title"])
        if pos_req not in (None, ""):
            req_parts.append(f"职位要求：{_safe_text(pos_req)}")
        contribution_req = _safe_first(cfg, ["need_contribution", "required_contribution", "min_contribution"])
        if contribution_req not in (None, ""):
            req_parts.append(f"贡献≥{_safe_text(contribution_req)}")
        return _join_non_empty(req_parts)

    def _build_shop_items_preview():
        try:
            from ..xiuxian_sect.sectconfig import get_config as get_sect_config  # 局部导入，避免影响启动
            cfg = get_sect_config() or {}
            shop_cfg = cfg.get("商店商品") if isinstance(cfg, dict) else {}
            if not isinstance(shop_cfg, dict):
                return []
            items_preview = []
            for item_id, item_cfg in list(shop_cfg.items())[:100]:
                if not isinstance(item_cfg, dict):
                    continue
                name = _compact_text(_safe_first(item_cfg, ["name", "title"])) or f"商品{_safe_text(item_id)}"
                desc = _compact_text(_safe_first(item_cfg, ["description", "desc", "remark"]))
                cost = _compact_text(_format_cost_text(item_cfg)) or "未记录"
                weekly_limit = _safe_first(item_cfg, ["weekly_limit", "daily_limit", "limit", "stock"])
                limit = f"限制：{_safe_text(weekly_limit)}" if weekly_limit not in (None, "") else "未记录"
                requirement = _compact_text(_format_requirement_text(item_cfg)) or "条件未知"
                items_preview.append({
                    "name": name,
                    "description": desc,
                    "cost": cost,
                    "limit": limit,
                    "requirement": requirement,
                    "status": "可查看",
                })
            return items_preview
        except Exception:
            return []

    join_open = _safe_get(sect, "join_open")
    if join_open is None:
        join_open = _safe_get(sect, "is_join_open")

    closed = _safe_get(sect, "closed")
    if closed is None:
        closed = _safe_get(sect, "is_closed")

    combat_power = _safe_get(sect, "combat_power")
    if combat_power is None:
        combat_power = _safe_get(sect, "power")

    members_list = []
    try:
        if columns:
            name_col = next((c for c in ("user_name", "username", "name") if c in columns), None)
            level_col = next((c for c in ("level", "realm", "jingjie", "境界") if c in columns), None)
            contribution_col = next((c for c in ("sect_contribution", "contribution") if c in columns), None)
            position_col = "sect_position" if "sect_position" in columns else None

            select_fields = ["user_id"]
            if name_col:
                select_fields.append(name_col)
            if level_col:
                select_fields.append(level_col)
            if position_col:
                select_fields.append(position_col)
            if contribution_col:
                select_fields.append(contribution_col)

            order_parts = []
            if position_col:
                order_parts.append("sect_position ASC")
            if contribution_col:
                order_parts.append(f"{contribution_col} DESC")

            sql = f"SELECT {', '.join(select_fields)} FROM user_xiuxian WHERE sect_id = ?"
            if order_parts:
                sql += " ORDER BY " + ", ".join(order_parts)
            sql += " LIMIT 100"

            member_rows = execute_sql(DATABASE, sql, (sect_id,)) or []
            for row in member_rows:
                if not isinstance(row, dict):
                    continue
                raw_position = row.get(position_col) if position_col else None
                try:
                    pos_num = int(raw_position) if raw_position is not None and raw_position != "" else 4
                except Exception:
                    pos_num = 4
                members_list.append({
                    "user_id": int(row.get("user_id") or 0),
                    "user_name": (row.get(name_col) if name_col else None) or "",
                    "level": (row.get(level_col) if level_col else None) or None,
                    "sect_position": pos_num,
                    "position_title": jsondata.sect_config_data().get(str(pos_num), {}).get("title", "弟子"),
                "contribution": _safe_int(row.get(contribution_col)) if contribution_col else None,
                })
    except Exception:
        members_list = []

    position_stats = {"has_data": False, "items": [], "total": 0}
    try:
        if "sect_position" in columns:
            stats_rows = execute_sql(
                DATABASE,
                """
                SELECT sect_position, COUNT(*) as c
                FROM user_xiuxian
                WHERE sect_id = ?
                GROUP BY sect_position
                ORDER BY sect_position ASC
                LIMIT 20
                """,
                (sect_id,)
            ) or []

            sect_position_cfg = jsondata.sect_config_data() or {}
            items = []
            total = 0
            for row in stats_rows:
                if not isinstance(row, dict):
                    continue
                raw_position = row.get("sect_position")
                try:
                    position_val = int(raw_position)
                except Exception:
                    position_val = raw_position
                try:
                    count_val = int(row.get("c") or 0)
                except Exception:
                    count_val = 0
                total += count_val
                items.append({
                    "position": position_val,
                    "title": sect_position_cfg.get(str(position_val), {}).get("title", "未知职位"),
                    "count": count_val,
                })

            position_stats = {
                "has_data": len(items) > 0,
                "items": items,
                "total": total,
            }
    except Exception:
        position_stats = {"has_data": False, "items": [], "total": 0}

    task_info = {
        "has_task": False,
        "name": "",
        "type": "",
        "description": "",
        "progress": "",
        "status": "",
        "times": "",
        "cd": "",
        "raw": "",
    }
    try:
        task_columns = [
            "sect_task",
            "sect_task_status",
            "sect_task_progress",
            "sect_task_count",
            "sect_task_cd",
            "sect_task_refresh_cd",
            "sect_task_complete_num",
            "sect_task_times",
        ]
        exist_task_columns = [c for c in task_columns if c in columns]
        if exist_task_columns:
            sql = f"SELECT {', '.join(exist_task_columns)} FROM user_xiuxian WHERE user_id = ? LIMIT 1"
            task_rows = execute_sql(DATABASE, sql, (user_id,)) or []
            task_row = task_rows[0] if task_rows and isinstance(task_rows[0], dict) else {}

            raw_task = task_row.get("sect_task") if "sect_task" in task_row else None
            raw_text = "" if raw_task in (None, "") else str(raw_task)
            if len(raw_text) > 300:
                raw_text = raw_text[:300] + "..."
            parsed_task = raw_task
            if isinstance(raw_task, str):
                raw_parse_text = raw_task.strip()
                if raw_parse_text:
                    try:
                        parsed_task = json.loads(raw_parse_text)
                    except Exception:
                        parsed_task = raw_task
                else:
                    parsed_task = ""

            name = ""
            task_type = ""
            description = ""
            progress = task_row.get("sect_task_progress") if "sect_task_progress" in task_row else ""
            status = task_row.get("sect_task_status") if "sect_task_status" in task_row else ""

            if isinstance(parsed_task, dict):
                name = parsed_task.get("name") or parsed_task.get("task_name") or parsed_task.get("title") or ""
                task_type = parsed_task.get("type") or parsed_task.get("task_type") or ""
                description = parsed_task.get("description") or parsed_task.get("desc") or parsed_task.get("target") or ""
                if not progress:
                    progress = parsed_task.get("progress") or parsed_task.get("current_progress") or ""
                if not status:
                    status = parsed_task.get("status") or ""
            elif parsed_task not in (None, ""):
                description = str(parsed_task)

            times_parts = []
            count_val = task_row.get("sect_task_count") if "sect_task_count" in task_row else None
            complete_num_val = task_row.get("sect_task_complete_num") if "sect_task_complete_num" in task_row else None
            times_val = task_row.get("sect_task_times") if "sect_task_times" in task_row else None
            if count_val not in (None, ""):
                times_parts.append(f"今日次数：{count_val}")
            if complete_num_val not in (None, ""):
                times_parts.append(f"剩余次数：{complete_num_val}")
            if times_val not in (None, ""):
                times_parts.append(f"次数：{times_val}")
            times_text = " / ".join(times_parts)

            cd_parts = []
            cd_val = task_row.get("sect_task_cd") if "sect_task_cd" in task_row else None
            refresh_cd_val = task_row.get("sect_task_refresh_cd") if "sect_task_refresh_cd" in task_row else None
            if cd_val not in (None, ""):
                cd_parts.append(f"CD：{cd_val}")
            if refresh_cd_val not in (None, ""):
                cd_parts.append(f"刷新CD：{refresh_cd_val}")
            cd_text = " / ".join(cd_parts)

            has_task = any(v not in (None, "") for v in [raw_task, name, task_type, description, progress, status])
            task_info = {
                "has_task": bool(has_task),
                "name": str(name or ""),
                "type": str(task_type or ""),
                "description": str(description or ""),
                "progress": str(progress or ""),
                "status": str(status or ""),
                "times": str(times_text or ""),
                "raw": raw_text,
            }
    except Exception:
        task_info = {
            "has_task": False,
            "name": "",
            "type": "",
            "description": "",
            "progress": "",
            "status": "",
            "times": "",
            "cd": "",
            "raw": "",
        }

    # --- QQ 侧内存任务 userstask 覆盖 + can_accept/can_complete/cost/give/sect ---
    try:
        from ..xiuxian_sect import isUserTask, userstask
        from ..xiuxian_sect.sectconfig import get_config as _get_sect_config
        _sect_cfg = _get_sect_config() or {}
        daily_limit = int(_sect_cfg.get("每日宗门任务次上限", 3))
        today_count = int(user.get("sect_task") or user.get("sect_task_count") or user.get("sect_task_complete_num") or 0)
        has_sect = bool(sect_id)

        if isUserTask(user_id):
            mt = userstask.get(user_id, {})
            task_content = mt.get("任务内容", {}) or {}
            desc_val = task_content.get("desc") or task_content.get("description") or ""
            task_info.update({
                "has_task": True,
                "name": str(mt.get("任务名称") or ""),
                "type": str(task_content.get("type") or ""),
                "description": str(desc_val),
                "cost": str(task_content.get("cost") or ""),
                "give": str(task_content.get("give") or ""),
                "sect": str(task_content.get("sect") or ""),
                "can_accept": False,
                "can_complete": True,
            })
        else:
            task_info.update({
                "has_task": task_info.get("has_task", False),
                "cost": "",
                "give": "",
                "sect": "",
                "can_accept": bool(has_sect and today_count < daily_limit and not task_info.get("has_task")),
                "can_complete": False,
            })
    except Exception:
        task_info.setdefault("cost", "")
        task_info.setdefault("give", "")
        task_info.setdefault("sect", "")
        task_info.setdefault("can_accept", False)
        task_info.setdefault("can_complete", False)

    elixir_room_info = {
        "has_data": False,
        "level": "",
        "get_num": "",
        "cd": "",
        "status": "暂无丹房数据",
        "message": "暂无丹房数据",
    }
    try:
        sect_level_candidates = ["elixir_room_level", "sect_elixir_room_level", "elixir_level", "elixir_room"]
        user_get_num_candidates = ["sect_elixir_get", "sect_elixir_get_num", "elixir_get_num"]
        user_cd_candidates = ["sect_elixir_cd", "sect_elixir_time"]

        level_val = None
        for field in sect_level_candidates:
            if field == "elixir_room_level":
                v = _safe_get(sect, field)
                if v not in (None, ""):
                    level_val = v
                    break
            elif field in sect_columns:
                rows = execute_sql(DATABASE, f"SELECT {field} FROM sects WHERE sect_id = ? LIMIT 1", (sect_id,)) or []
                row = rows[0] if rows and isinstance(rows[0], dict) else {}
                v = row.get(field)
                if v not in (None, ""):
                    level_val = v
                    break

        user_extra_fields = [c for c in (user_get_num_candidates + user_cd_candidates) if c in columns]
        user_extra_row = {}
        if user_extra_fields:
            sql = f"SELECT {', '.join(user_extra_fields)} FROM user_xiuxian WHERE user_id = ? LIMIT 1"
            user_rows = execute_sql(DATABASE, sql, (user_id,)) or []
            user_extra_row = user_rows[0] if user_rows and isinstance(user_rows[0], dict) else {}

        get_num_val = None
        get_num_field = None
        for field in user_get_num_candidates:
            if field in user_extra_row and user_extra_row.get(field) not in (None, ""):
                get_num_field = field
                get_num_val = user_extra_row.get(field)
                break

        cd_val = None
        cd_field = None
        for field in user_cd_candidates:
            if field in user_extra_row and user_extra_row.get(field) not in (None, ""):
                cd_field = field
                cd_val = user_extra_row.get(field)
                break

        level_text = ""
        if level_val not in (None, ""):
            level_num = _safe_int(level_val)
            level_text = str(level_num) if level_num is not None else _safe_text(level_val)

        get_num_text = ""
        if get_num_val not in (None, ""):
            if get_num_field == "sect_elixir_get":
                bool_val = _safe_bool(get_num_val)
                if bool_val is True:
                    get_num_text = "今日已领取"
                elif bool_val is False:
                    get_num_text = "今日未领取"
                else:
                    get_num_text = _safe_text(get_num_val)
            else:
                get_num_text = _safe_text(get_num_val)

        cd_text = _safe_text(cd_val) if cd_val not in (None, "") else ""

        has_data = any(v not in (None, "") for v in [level_text, get_num_text, cd_text])
        status_text = "可查看" if has_data else "暂无丹房数据"
        message_text = "丹房信息仅供查看" if has_data else "暂无丹房数据"

        elixir_room_info = {
            "has_data": bool(has_data),
            "level": level_text,
            "get_num": get_num_text,
            "cd": cd_text,
            "status": status_text,
            "message": message_text,
        }
    except Exception:
        elixir_room_info = {
            "has_data": False,
            "level": "",
            "get_num": "",
            "cd": "",
            "status": "暂无丹房数据",
            "message": "暂无丹房数据",
        }

    owner_value = sect.get("sect_owner") or sect.get("owner") or sect.get("sect_owner_id") or sect.get("owner_id") or "未知"
    owner_display = owner_value
    try:
        owner_text = str(owner_value).strip()
        owner_id = ""
        if owner_text.isdigit():
            owner_id = owner_text
        else:
            match = re.search(r"(\d+)", owner_text)
            if match:
                owner_id = match.group(1)

        if owner_id:
            owner_name_rows = execute_sql(
                DATABASE,
                "SELECT user_name AS owner_name FROM user_xiuxian WHERE user_id = ? LIMIT 1",
                (owner_id,)
            )
            owner_name = ((owner_name_rows or [{}])[0]).get("owner_name")
            if owner_name not in (None, ""):
                owner_display = f"{owner_name}（{owner_id}）"
    except Exception:
        owner_display = owner_value

    return {
        "joined": True,
        "sect_id": sect_id,
        "sect_name": sect.get("sect_name") or "未知宗门",
        "owner": owner_value,
        "owner_display": owner_display,
        "level": sect.get("sect_level") or 0,
        "materials": int(sect.get("sect_materials") or 0),
        "scale": int(sect.get("sect_scale") or 0),
        "elixir_room_level": int(sect.get("elixir_room_level") or 0),
        "members": int((members[0] or {}).get("c") or 0),
        "position": jsondata.sect_config_data().get(str(user.get("sect_position")), {}).get("title", "弟子"),
        "join_open": _safe_bool(join_open),
        "closed": _safe_bool(closed),
        "combat_power": _safe_int(combat_power),
        "members_list": members_list,
        "position_stats": position_stats,
        "task_info": task_info,
        "elixir_room_info": elixir_room_info,
        "shop_items": _build_shop_items_preview(),
    }


def _consume_stamina(user_id, cost=1):
    user = game_sql.get_user_info_with_id(user_id) or {}
    stamina = int(user.get('user_stamina') or 0)
    if stamina < cost:
        return False, f"体力不足，本次操作需要 {cost} 点体力。"
    game_sql.update_user_stamina(user_id, cost, 2)
    return True, ""


def _restore_stamina(user_id, amount=1):
    """回补体力，不超出上限。用于预验证后仍失败的保守回滚。"""
    try:
        game_sql.update_user_stamina(user_id, -abs(amount), 2)
    except Exception:
        pass


def _run_async(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _load_player_user_data(user_id: int):
    user_dir = PLAYERSDATA / str(user_id)
    user_file = user_dir / "user_data.json"
    if not user_file.exists():
        return {}
    try:
        content = user_file.read_text(encoding="utf-8").strip()
        if not content:
            return {}
        return json.loads(content)
    except Exception:
        return {}


def _save_player_user_data(user_id: int, data: dict):
    user_dir = PLAYERSDATA / str(user_id)
    user_dir.mkdir(parents=True, exist_ok=True)
    user_file = user_dir / "user_data.json"
    user_file.write_text(json.dumps(data, ensure_ascii=False, indent=4), encoding="utf-8")


def _get_user_boss_fight_info(user_id: int):
    """读取世界 BOSS 永久积分信息，兼容 QQ 端 boss_fight_info.json。"""
    user_dir = PLAYERSDATA / str(user_id)
    user_dir.mkdir(parents=True, exist_ok=True)
    info_file = user_dir / "boss_fight_info.json"
    data = {"boss_integral": 0}

    if info_file.exists():
        try:
            raw = info_file.read_text(encoding="utf-8").strip()
            if raw:
                loaded = json.loads(raw)
                if isinstance(loaded, dict):
                    data.update(loaded)
        except Exception as e:
            logger.warning(f"Read boss_fight_info failed: user_id={user_id}, error={e}")

    try:
        data["boss_integral"] = max(int(data.get("boss_integral") or 0), 0)
    except Exception:
        data["boss_integral"] = 0
    return data


def _save_user_boss_fight_info(user_id: int, data: dict):
    """保存世界 BOSS 永久积分信息。"""
    user_dir = PLAYERSDATA / str(user_id)
    user_dir.mkdir(parents=True, exist_ok=True)
    info_file = user_dir / "boss_fight_info.json"
    info_file.write_text(json.dumps(data, ensure_ascii=False, indent=4), encoding="utf-8")


def _calc_world_boss_rank_penalty(user_rank: int, boss_rank: int) -> tuple[float, str]:
    """复用 QQ 端世界 BOSS 的境界收益衰减/加成。"""
    rank_penalty = 1.0
    bonus_msg = ""

    if user_rank < boss_rank:
        rank_diff = boss_rank - user_rank
        if rank_diff == 1:
            rank_penalty = 0.95
        elif rank_diff == 2:
            rank_penalty = 0.9
        elif rank_diff == 3:
            rank_penalty = 0.8
        else:
            rank_penalty = 0.5
    elif user_rank > boss_rank:
        points_bonus = int(30 * (user_rank - boss_rank))
        bonus_msg = f"境界加成：+{points_bonus}%积分"

    return rank_penalty, bonus_msg


def _calc_world_boss_web_reward(user_id: int, user_info: dict, boss: dict, winner: str, events: list[dict]):
    """计算并写入网页端世界 BOSS 奖励。

    当前 Web 世界 BOSS 是一次性挑战，沿用既有网页逻辑：只有胜利才结算奖励；
    在原有灵石奖励基础上补齐 QQ 端世界积分的持久化与每日限制。
    """
    reward = {
        "stone": 0,
        "stone_display": _display_number(0),
        "boss_integral": 0,
        "daily_integral": 0,
        "daily_integral_limit": WORLD_BOSS_DAILY_INTEGRAL_LIMIT,
        "total_boss_integral": 0,
        "rank_bonus_message": "",
        "limit_messages": [],
    }

    boss_info = _get_user_boss_fight_info(user_id)
    reward["total_boss_integral"] = int(boss_info.get("boss_integral") or 0)

    if winner != "群友赢了":
        return reward

    boss_all_hp = int(boss.get("总血量") or boss.get("气血") or 0)
    if boss_all_hp <= 0 and events:
        boss_all_hp = max(int(e.get("enemy_max_hp") or 0) for e in events)

    final_enemy_hp = 0
    if events:
        final_enemy_hp = int(events[-1].get("enemy_hp") or 0)
    total_damage = max(boss_all_hp - final_enemy_hp, 0) if boss_all_hp > 0 else 0
    damage_ratio = min(total_damage / boss_all_hp, 0.20) if boss_all_hp > 0 else 0

    try:
        boss_rank = convert_rank(boss.get("jj") if boss.get("jj") == "零" else f"{boss.get('jj')}中期")[0]
    except Exception:
        boss_rank = 0
    try:
        user_rank = convert_rank(user_info.get("level"))[0]
    except Exception:
        user_rank = 0

    rank_penalty, rank_bonus_message = _calc_world_boss_rank_penalty(user_rank, boss_rank)
    reward["rank_bonus_message"] = rank_bonus_message

    today_integral = boss_limit.get_integral(user_id)
    today_stone = boss_limit.get_stone(user_id)

    stone = int(boss.get("max_stone") or 0)
    stone = max(stone, 0)
    if stone > 0 and today_stone < WORLD_BOSS_DAILY_STONE_LIMIT:
        stone = min(stone, WORLD_BOSS_DAILY_STONE_LIMIT - today_stone)
    elif stone > 0:
        stone = 0
        reward["limit_messages"].append("今日灵石已达上限")

    boss_integral = 0
    if today_integral >= WORLD_BOSS_DAILY_INTEGRAL_LIMIT:
        reward["limit_messages"].append("今日世界积分已达上限")
    else:
        boss_integral = max(int(damage_ratio * WORLD_BOSS_INTEGRAL_BASE), 1) if damage_ratio > 0 else 0
        boss_integral = int(boss_integral * rank_penalty)
        if rank_penalty == 1.0 and user_rank > boss_rank:
            boss_integral = int(boss_integral * (1 + (0.3 * (user_rank - boss_rank))))

        try:
            sub_buff = UserBuffDate(user_id).get_user_sub_buff_data()
            integral_buff = sub_buff.get("integral", 0) if sub_buff else 0
            boss_integral = int(boss_integral * (1 + integral_buff))
        except Exception:
            pass

        boss_integral = max(boss_integral, 0)
        boss_integral = min(boss_integral, WORLD_BOSS_DAILY_INTEGRAL_LIMIT - today_integral)

    if stone > 0:
        game_sql.update_ls(user_id, stone, 1)
        boss_limit.update_stone(user_id, stone)

    if boss_integral > 0:
        boss_info["boss_integral"] = int(boss_info.get("boss_integral") or 0) + boss_integral
        _save_user_boss_fight_info(user_id, boss_info)
        boss_limit.update_integral(user_id, boss_integral)

    reward.update({
        "stone": stone,
        "stone_display": _display_number(stone),
        "boss_integral": boss_integral,
        "daily_integral": boss_limit.get_integral(user_id),
        "total_boss_integral": int(boss_info.get("boss_integral") or 0),
    })
    return reward


def _format_world_boss_reward_message(reward: dict) -> str:
    parts = []
    if int(reward.get("stone") or 0) > 0:
        parts.append(f"获得灵石：{reward.get('stone_display') or _display_number(reward.get('stone') or 0)}")
    if int(reward.get("boss_integral") or 0) > 0:
        parts.append(f"获得世界积分：{int(reward.get('boss_integral') or 0)}点")
    if reward.get("rank_bonus_message"):
        parts.append(str(reward.get("rank_bonus_message")))
    parts.extend(reward.get("limit_messages") or [])
    return "，".join(parts) if parts else "未获得奖励"


def _get_world_boss_shop_config() -> dict:
    """读取世界 BOSS 积分商店配置，复用 QQ 端 config['世界积分商品']。"""
    try:
        shop = (get_boss_config() or {}).get("世界积分商品") or {}
        return shop if isinstance(shop, dict) else {}
    except Exception as e:
        logger.warning(f"Read world boss shop config failed: {e}")
        return {}


def _find_world_boss_shop_item(shop_id):
    shop = _get_world_boss_shop_config()
    shop_id_str = str(shop_id)
    if shop_id_str in shop:
        return shop_id_str, shop[shop_id_str]

    for key, value in shop.items():
        if str(key) == shop_id_str:
            return str(key), value
    return None, None


def _build_world_boss_shop_goods(user_id: int):
    boss_info = _get_user_boss_fight_info(user_id)
    total_integral = int(boss_info.get("boss_integral") or 0)
    shop = _get_world_boss_shop_config()
    goods = []

    def _shop_sort_key(pair):
        key, _ = pair
        try:
            return int(key)
        except Exception:
            return str(key)

    for raw_shop_id, cfg in sorted(shop.items(), key=_shop_sort_key):
        if not isinstance(cfg, dict):
            continue

        try:
            shop_id = int(raw_shop_id)
        except Exception:
            continue

        try:
            item_id = int(cfg.get("item_id") or cfg.get("id") or shop_id)
        except Exception:
            item_id = shop_id

        try:
            cost = max(int(cfg.get("cost") or 0), 0)
        except Exception:
            cost = 0

        try:
            weekly_limit = max(int(cfg.get("weekly_limit", 1) or 1), 0)
        except Exception:
            weekly_limit = 1

        weekly_purchased = int(boss_limit.get_weekly_purchases(user_id, shop_id) or 0)
        weekly_left = max(weekly_limit - weekly_purchased, 0)

        item = _serialize_item(item_id)
        goods.append({
            "shop_id": shop_id,
            "item_id": item_id,
            "name": item.get("name") or f"物品{item_id}",
            "type": item.get("type") or "未知",
            "item_type": item.get("item_type") or item.get("type") or "未知",
            "level": item.get("level") or "凡品",
            "desc": item.get("desc") or "暂无描述",
            "cost": cost,
            "cost_display": f"{cost}点",
            "weekly_limit": weekly_limit,
            "weekly_purchased": weekly_purchased,
            "weekly_left": weekly_left,
            "can_exchange": cost > 0 and total_integral >= cost and weekly_left > 0,
        })

    return goods


def _build_world_boss_shop_payload(user_id: int):
    boss_info = _get_user_boss_fight_info(user_id)
    return {
        "boss_integral": int(boss_info.get("boss_integral") or 0),
        "today_integral": int(boss_limit.get_integral(user_id) or 0),
        "today_integral_limit": WORLD_BOSS_DAILY_INTEGRAL_LIMIT,
        "today_stone": int(boss_limit.get_stone(user_id) or 0),
        "today_stone_limit": WORLD_BOSS_DAILY_STONE_LIMIT,
        "today_battle_count": int(boss_limit.get_battle_count(user_id) or 0),
        "goods": _build_world_boss_shop_goods(user_id),
    }


def _exchange_world_boss_shop_item(user_id: int, shop_id: int, quantity: int):
    shop_key, cfg = _find_world_boss_shop_item(shop_id)
    if not shop_key or not isinstance(cfg, dict):
        return None, "该编号不在世界积分商店内，请检查后再兑换"

    quantity = int(quantity or 1)
    if quantity < 1:
        return None, "兑换数量必须大于 0"
    if quantity > 99:
        return None, "单次兑换数量不能超过 99"

    shop_id = int(shop_key)
    try:
        item_id = int(cfg.get("item_id") or cfg.get("id") or shop_id)
    except Exception:
        item_id = shop_id

    try:
        cost = max(int(cfg.get("cost") or 0), 0)
    except Exception:
        cost = 0
    if cost <= 0:
        return None, "该商品积分价格配置异常，无法兑换"

    try:
        weekly_limit = max(int(cfg.get("weekly_limit", 1) or 1), 0)
    except Exception:
        weekly_limit = 1

    already_purchased = int(boss_limit.get_weekly_purchases(user_id, shop_id) or 0)
    if weekly_limit > 0 and already_purchased + quantity > weekly_limit:
        return None, f"该商品每周限购{weekly_limit}个，您本周已购买{already_purchased}个，无法再购买{quantity}个"

    try:
        item_info = items.get_data_by_item_id(item_id)
    except Exception:
        item_info = None
    if not item_info:
        return None, "商品对应物品不存在，无法兑换"

    boss_info = _get_user_boss_fight_info(user_id)
    current_integral = int(boss_info.get("boss_integral") or 0)
    total_cost = cost * quantity
    if current_integral < total_cost:
        return None, f"世界积分不足，需要{total_cost}点，当前仅有{current_integral}点"

    boss_info["boss_integral"] = current_integral - total_cost
    _save_user_boss_fight_info(user_id, boss_info)
    boss_limit.update_weekly_purchase(user_id, shop_id, quantity)
    game_sql.send_back(user_id, item_id, item_info["name"], item_info["type"], quantity, 1)

    try:
        log_message(user_id, f"Web 世界BOSS商店兑换：{item_info['name']}x{quantity}，消耗世界积分{total_cost}")
    except Exception:
        pass

    return {
        "shop_id": shop_id,
        "item_id": item_id,
        "name": item_info.get("name") or f"物品{item_id}",
        "type": item_info.get("type") or "未知",
        "quantity": quantity,
        "cost": cost,
        "total_cost": total_cost,
        "boss_integral": int(boss_info.get("boss_integral") or 0),
        "weekly_limit": weekly_limit,
        "weekly_purchased": int(boss_limit.get_weekly_purchases(user_id, shop_id) or 0),
    }, ""



def _get_dual_protect_status(user_id: int):
    user_data = _load_player_user_data(user_id)
    status = user_data.get("two_exp_protect", False)
    if status in (False, True, "refusal", "friends_only"):
        return status
    return False


def _get_friend_policy(user_id: int):
    user_data = _load_player_user_data(user_id)
    policy = user_data.get("friend_request_policy", "all")
    return policy if policy in ("all", "refuse") else "all"


def _get_relation(viewer_id: int, other_id: int):
    if int(viewer_id) == int(other_id):
        return "self"
    viewer_data = _load_player_user_data(viewer_id)
    friends = set(int(x) for x in (viewer_data.get("friends") or []) if str(x).isdigit())
    if int(other_id) in friends:
        return "friend"
    incoming = viewer_data.get("friend_requests_in") or {}
    outgoing = viewer_data.get("friend_requests_out") or {}
    if str(other_id) in incoming:
        return "incoming"
    if str(other_id) in outgoing:
        return "outgoing"
    return "none"


def _get_any_bot():
    bots = list(get_bots().values())
    return bots[0] if bots else None


async def _send_private_msg(target_user_id: int, message: str):
    bot = _get_any_bot()
    if not bot:
        return False
    try:
        await bot.send_private_msg(user_id=int(target_user_id), message=message)
        return True
    except Exception as e:
        logger.error(f"发送私聊失败: {e}")
        return False


WEB_DUAL_INVITES = {}
WEB_DUAL_EXPIRE_SECONDS = 600
TWO_EXP_LIMIT = 3


def _issue_web_dual_invite(inviter_id: int, target_id: int, count: int):
    token = "dual_" + secrets.token_urlsafe(18)
    WEB_DUAL_INVITES[token] = {
        "inviter_id": int(inviter_id),
        "target_id": int(target_id),
        "count": int(count),
        "expire_at": datetime.now().timestamp() + WEB_DUAL_EXPIRE_SECONDS,
        "used": False,
    }
    return token


def _consume_web_dual_invite(token: str):
    info = WEB_DUAL_INVITES.get(token)
    if not info:
        return None, "邀请无效或已过期"
    if info.get("used"):
        return None, "邀请已处理"
    if info.get("expire_at", 0) < datetime.now().timestamp():
        return None, "邀请无效或已过期"
    info["used"] = True
    return info, ""


def _ensure_social_fields(data: dict):
    data = dict(data or {})
    if not isinstance(data.get("friends"), list):
        data["friends"] = []
    if not isinstance(data.get("friend_requests_in"), dict):
        data["friend_requests_in"] = {}
    if not isinstance(data.get("friend_requests_out"), dict):
        data["friend_requests_out"] = {}
    policy = data.get("friend_request_policy", "all")
    data["friend_request_policy"] = policy if policy in ("all", "refuse") else "all"
    status = data.get("two_exp_protect", False)
    data["two_exp_protect"] = status if status in (False, True, "refusal", "friends_only") else False
    return data


def _add_friend_pair(user_a: int, user_b: int):
    a = _ensure_social_fields(_load_player_user_data(user_a))
    b = _ensure_social_fields(_load_player_user_data(user_b))
    a_friends = set(int(x) for x in a["friends"] if str(x).isdigit())
    b_friends = set(int(x) for x in b["friends"] if str(x).isdigit())
    a_friends.add(int(user_b))
    b_friends.add(int(user_a))
    a["friends"] = sorted(a_friends)
    b["friends"] = sorted(b_friends)
    a["friend_requests_in"].pop(str(user_b), None)
    a["friend_requests_out"].pop(str(user_b), None)
    b["friend_requests_in"].pop(str(user_a), None)
    b["friend_requests_out"].pop(str(user_a), None)
    _save_player_user_data(user_a, a)
    _save_player_user_data(user_b, b)


def _remove_friend_request(user_a: int, user_b: int):
    a = _ensure_social_fields(_load_player_user_data(user_a))
    b = _ensure_social_fields(_load_player_user_data(user_b))
    a["friend_requests_in"].pop(str(user_b), None)
    a["friend_requests_out"].pop(str(user_b), None)
    b["friend_requests_in"].pop(str(user_a), None)
    b["friend_requests_out"].pop(str(user_a), None)
    _save_player_user_data(user_a, a)
    _save_player_user_data(user_b, b)


def _get_two_exp_remaining(user_id: int):
    used = two_exp_cd.find_user(user_id)
    impart_data = xiuxian_impart.get_user_impart_info_with_id(user_id)
    impart_two_exp = impart_data.get("impart_two_exp", 0) if impart_data else 0
    main_two_data = UserBuffDate(user_id).get_user_main_buff_data()
    main_two = main_two_data.get("two_buff", 0) if main_two_data else 0
    return max(0, TWO_EXP_LIMIT + int(impart_two_exp or 0) + int(main_two or 0) - int(used or 0))


def _process_two_exp(user_id_1: int, user_id_2: int, is_partner: bool = False):
    user_1 = game_sql.get_user_real_info(user_id_1)
    user_2 = game_sql.get_user_real_info(user_id_2)
    if not user_1 or not user_2:
        return 0, 0, "无法获取玩家信息，无法进行双修。"

    user_mes_1 = game_sql.get_user_info_with_id(user_id_1)
    user_mes_2 = game_sql.get_user_info_with_id(user_id_2)
    level_1 = user_mes_1["level"]
    level_2 = user_mes_2["level"]

    max_exp_1_limit = int(OtherSet().set_closing_type(level_1)) * XiuConfig().closing_exp_upper_limit
    max_exp_2_limit = int(OtherSet().set_closing_type(level_2)) * XiuConfig().closing_exp_upper_limit

    remaining_exp_1 = max_exp_1_limit - int(user_mes_1["exp"])
    remaining_exp_2 = max_exp_2_limit - int(user_mes_2["exp"])

    user_buff_data_1 = UserBuffDate(user_id_1)
    user_buff_data_2 = UserBuffDate(user_id_2)
    mainbuffdata_1 = user_buff_data_1.get_user_main_buff_data()
    mainbuffdata_2 = user_buff_data_2.get_user_main_buff_data()

    mainbuffratebuff_1 = mainbuffdata_1["ratebuff"] if mainbuffdata_1 else 0
    mainbuffcloexp_1 = mainbuffdata_1["clo_exp"] if mainbuffdata_1 else 0
    mainbuffratebuff_2 = mainbuffdata_2["ratebuff"] if mainbuffdata_2 else 0
    mainbuffcloexp_2 = mainbuffdata_2["clo_exp"] if mainbuffdata_2 else 0

    user_blessed_spot_data_1 = user_buff_data_1.BuffInfo["blessed_spot"] * 0.5 if user_buff_data_1.BuffInfo else 0
    user_blessed_spot_data_2 = user_buff_data_2.BuffInfo["blessed_spot"] * 0.5 if user_buff_data_2.BuffInfo else 0

    exp_base = int((int(user_mes_1["exp"]) + int(user_mes_2["exp"])) * 0.005)

    exp_limit_1 = int(exp_base * (1 + mainbuffratebuff_1) * (1 + mainbuffcloexp_1) * (1 + user_blessed_spot_data_1))
    exp_limit_2 = int(exp_base * (1 + mainbuffratebuff_2) * (1 + mainbuffcloexp_2) * (1 + user_blessed_spot_data_2))

    user1_rank = convert_rank(user_mes_1["level"])[0]
    user2_rank = convert_rank(user_mes_2["level"])[0]
    max_exp_1 = int((int(user_mes_1["exp"]) * 0.001) * min(0.1 * user1_rank, 1))
    max_exp_2 = int((int(user_mes_2["exp"]) * 0.001) * min(0.1 * user2_rank, 1))

    max_two_exp = 100000000
    exp_limit_1 = min(exp_limit_1, max_exp_1, remaining_exp_1) if max_exp_1 >= max_two_exp else min(exp_limit_1, remaining_exp_1, max_exp_1_limit * 0.1)
    exp_limit_2 = min(exp_limit_2, max_exp_2, remaining_exp_2) if max_exp_2 >= max_two_exp else min(exp_limit_2, min(remaining_exp_2, max_exp_2_limit * 0.1))

    if is_partner:
        if remaining_exp_1 <= 0:
            exp_limit_1 = 1
        if remaining_exp_2 <= 0:
            exp_limit_2 = 1
        exp_limit_1 = int(exp_limit_1 * 1.2)
        exp_limit_2 = int(exp_limit_2 * 1.2)
    else:
        if remaining_exp_1 <= 0 or remaining_exp_2 <= 0:
            return 0, 0, "修为已达上限，无法继续双修。"

    is_special = random.randint(1, 100) <= 6
    if is_special:
        special_events = [
            "突然天降异象，七彩祥云笼罩两人，修为大增！",
            "意外发现一处灵脉，两人共同吸收，修为精进！",
            "功法意外产生共鸣，引发天地灵气倒灌！",
            "两人心意相通，功法运转达到完美契合！",
            "顿悟时刻来临，两人同时进入玄妙境界！",
        ]
        event_desc = random.choice(special_events) + "\n💫天降异象，双方各增加突破概率2%。"
        exp_limit_1 = int(exp_limit_1 * 1.5)
        exp_limit_2 = int(exp_limit_2 * 1.5)
        game_sql.update_levelrate(user_id_1, int(user_mes_1["level_up_rate"]) + 2)
        game_sql.update_levelrate(user_id_2, int(user_mes_2["level_up_rate"]) + 2)
    else:
        event_descriptions = [
            f"月明星稀之夜，{user_1['user_name']}与{user_2['user_name']}在灵山之巅相对而坐，双手相抵，周身灵气环绕如雾。",
            f"洞府之中，{user_1['user_name']}与{user_2['user_name']}盘膝对坐，真元交融，形成阴阳鱼图案在两人之间流转。",
            f"瀑布之下，{user_1['user_name']}与{user_2['user_name']}沐浴灵泉，水汽蒸腾间功法共鸣，修为精进。",
            f"竹林小筑内，{user_1['user_name']}与{user_2['user_name']}共饮灵茶，茶香氤氲中功法相互印证。",
            f"云端之上，{user_1['user_name']}与{user_2['user_name']}脚踏飞剑，剑气交织间功法互补，修为大涨。",
        ]
        event_desc = random.choice(event_descriptions)

    return int(exp_limit_1), int(exp_limit_2), event_desc


def _perform_two_exp(user_id_1: int, user_id_2: int, exp_count: int = 1, is_partner: bool = False):
    user_1 = game_sql.get_user_info_with_id(user_id_1)
    user_2 = game_sql.get_user_info_with_id(user_id_2)
    if not user_1 or not user_2:
        return {"ok": False, "message": "无法获取玩家信息，无法进行双修。"}

    rem_1 = _get_two_exp_remaining(user_id_1)
    rem_2 = _get_two_exp_remaining(user_id_2)
    if rem_1 <= 0:
        return {"ok": False, "message": "你的双修次数不足，无法进行双修！"}
    if rem_2 <= 0:
        return {"ok": False, "message": "对方的双修次数不足，无法进行双修！"}

    exp_count = max(int(exp_count or 1), 1)
    actual_count = min(exp_count, rem_1, rem_2)
    total_exp_1 = 0
    total_exp_2 = 0
    event_descriptions = []
    used_count = 0

    for _ in range(actual_count):
        exp_1, exp_2, event_desc = _process_two_exp(user_id_1, user_id_2, is_partner=is_partner)
        if exp_1 == 0 and exp_2 == 0:
            break
        total_exp_1 += exp_1
        total_exp_2 += exp_2
        event_descriptions.append(event_desc)
        used_count += 1
        two_exp_cd.add_user(user_id_1)
        two_exp_cd.add_user(user_id_2)

    user_1_info = game_sql.get_user_real_info(user_id_1)
    user_2_info = game_sql.get_user_real_info(user_id_2)

    if used_count == 0:
        return {"ok": False, "message": "双修过程中修为已达上限，无法进行双修！"}

    game_sql.update_exp(user_id_1, total_exp_1)
    game_sql.update_power2(user_id_1)
    _, result_hp_mp_1 = OtherSet().send_hp_mp(user_id_1, int(user_1_info["exp"] / 10), int(user_1_info["exp"] / 20))
    game_sql.update_user_attribute(user_id_1, result_hp_mp_1[0], result_hp_mp_1[1], int(result_hp_mp_1[2] / 10))

    game_sql.update_exp(user_id_2, total_exp_2)
    game_sql.update_power2(user_id_2)
    _, result_hp_mp_2 = OtherSet().send_hp_mp(user_id_2, int(user_2_info["exp"] / 10), int(user_2_info["exp"] / 20))
    game_sql.update_user_attribute(user_id_2, result_hp_mp_2[0], result_hp_mp_2[1], int(result_hp_mp_2[2] / 10))

    update_statistics_value(user_id_1, "双修次数", increment=used_count)
    update_statistics_value(user_id_2, "双修次数", increment=used_count)
    log_message(user_id_1, f"与{user_2_info['user_name']}进行双修，获得修为{number_to(total_exp_1)}，共{used_count}次")
    log_message(user_id_2, f"与{user_1_info['user_name']}进行双修，获得修为{number_to(total_exp_2)}，共{used_count}次")

    msg = f"{random.choice(event_descriptions)}\n\n"
    msg += f"{user_1_info['user_name']}获得修为：{number_to(total_exp_1)}\n"
    msg += f"{user_2_info['user_name']}获得修为：{number_to(total_exp_2)}"
    return {"ok": True, "message": msg, "used_count": used_count, "exp_1": total_exp_1, "exp_2": total_exp_2}


def _normalize_battle_nodes(nodes, player_id, enemy_name=None, is_boss=False):
    events = []
    player_card = None  # 延迟获取
    player_info = game_sql.get_user_info_with_id(player_id) or {}
    player_name = str(player_info.get("user_name") or "")

    # 先给一个数据库兜底值；战斗内真实 HP 以战报 speaker/content 解析结果为准。
    player_hp = int(player_info.get("hp") or 0)
    player_max_hp = int((player_info.get("exp") or 0) / 2) if player_info.get("exp") else max(player_hp, 0)
    enemy_hp = 0
    enemy_max_hp = 0

    def _parse_cn_number(value):
        raw = str(value or "").strip().replace(" ", "")
        if not raw:
            return 0
        m = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)([万亿]?)", raw)
        if not m:
            return 0
        base = float(m.group(1))
        unit = m.group(2)
        if unit == "万":
            base *= 10000
        elif unit == "亿":
            base *= 100000000
        return int(base)

    def _clean_hp_owner(owner: str):
        owner = str(owner or "").strip()
        owner = re.sub(r"[\s☆★—\-]+", "", owner)
        owner = owner.replace("当前", "").replace("剩余", "")
        # 避免把整句战报都当成名字，只保留冒号/逗号后最靠近“血量”的短名称。
        for sep in ("：", ":", "，", ",", "！", "!", "。"):
            if sep in owner:
                owner = owner.split(sep)[-1]
        return owner.strip()

    def _detect_side_by_identity(owner: str, speaker: str = "", side: str = "system", text: str = ""):
        owner = _clean_hp_owner(owner)
        speaker = str(speaker or "")
        text = str(text or "")
        player_keys = [str(player_id), player_name, "群友", "玩家"]
        enemy_keys = [str(enemy_name or "")]

        # owner 是最靠近“当前血量/剩余血量”的名称，优先级最高。
        if any(k and k in owner for k in player_keys):
            return "player"
        if any(k and k in owner for k in enemy_keys):
            return "enemy"

        # 其次看血量文本本身；不要让 speaker 覆盖 content 里的“敌人剩余血量”。
        if any(k and k in text for k in player_keys) and not any(k and k in text for k in enemy_keys):
            return "player"
        if any(k and k in text for k in enemy_keys) and not any(k and k in text for k in player_keys):
            return "enemy"

        # 最后才用 speaker/uin 兜底，主要用于 owner 为空的“当前血量 x/y”。
        if any(k and k in speaker for k in player_keys):
            return "player"
        if any(k and k in speaker for k in enemy_keys):
            return "enemy"

        if side in ("player", "enemy"):
            return side
        return None

    def _node_side_and_text(node):
        data = node.get('data', {}) if isinstance(node, dict) else {}
        speaker = str(data.get('name', '战报'))
        content = str(data.get('content', ''))
        uin = data.get('uin')
        side = "system"
        try:
            if int(uin) == int(player_id):
                side = "player"
            elif speaker != "Bot":
                side = "enemy"
        except Exception:
            if speaker != "Bot":
                side = "enemy"
        return data, speaker, content, side

    def _extract_hp_pairs(text: str, speaker: str = "", side: str = "system"):
        """解析“当前血量/气血/HP：cur / max”，返回 side/hp/max 快照。"""
        s = str(text or "")
        num_pat = r"([0-9]+(?:\.[0-9]+)?\s*[万亿]?)"
        # owner 允许为空；用非贪婪捕获，避免把“当前”吞进名字。
        pattern = re.compile(
            rf"([^\n：:/]{{0,40}}?)\s*[，,]?\s*(?:当前\s*)?(?:气血|血量|HP|hp)\s*[：: ]\s*{num_pat}\s*/\s*{num_pat}"
        )
        result = []
        for owner, cur, max_v in pattern.findall(s):
            cur_v = _parse_cn_number(cur)
            max_hp_v = _parse_cn_number(max_v)
            if cur_v <= 0 or max_hp_v <= 0:
                continue
            detected_side = _detect_side_by_identity(owner, speaker=speaker, side=side, text=s)
            result.append({
                "side": detected_side,
                "hp": cur_v,
                "max_hp": max_hp_v,
                "owner": _clean_hp_owner(owner),
            })
        return result

    def _extract_remaining_hp(text: str, speaker: str = "", side: str = "system"):
        """解析“xxx剩余血量cur / xxx当前血量cur”这种没有 max 的状态行。"""
        s = str(text or "")
        num_pat = r"([0-9]+(?:\.[0-9]+)?\s*[万亿]?)"
        pattern = re.compile(
            rf"([^\n：:/]{{0,40}}?)\s*(?:剩余|当前)\s*(?:气血|血量|HP|hp)\s*[：: ]*\s*{num_pat}"
        )
        result = []
        for owner, cur in pattern.findall(s):
            cur_v = _parse_cn_number(cur)
            if cur_v <= 0:
                continue
            detected_side = _detect_side_by_identity(owner, speaker=speaker, side=side, text=s)
            result.append({
                "side": detected_side,
                "hp": cur_v,
                "owner": _clean_hp_owner(owner),
            })
        return result

    def _apply_hp_pair_snapshot(snapshot):
        nonlocal player_hp, player_max_hp, enemy_hp, enemy_max_hp
        side = snapshot.get("side")
        hp = int(snapshot.get("hp") or 0)
        max_hp = int(snapshot.get("max_hp") or 0)
        if side == "player":
            if max_hp > 0:
                player_max_hp = max_hp
            if hp > 0:
                player_hp = hp
        elif side == "enemy":
            if max_hp > 0:
                enemy_max_hp = max_hp
            if hp > 0:
                enemy_hp = hp

    def _apply_remaining_hp_snapshot(snapshot, fallback_side=None):
        nonlocal player_hp, enemy_hp
        side = snapshot.get("side") or fallback_side
        hp = int(snapshot.get("hp") or 0)
        if hp <= 0:
            return
        if side == "player":
            player_hp = hp
        elif side == "enemy":
            enemy_hp = hp

    # 预扫描：只补齐最大血量。
    # 注意：不要用后续战报里的“当前血量/剩余血量”初始化当前 HP，
    # 否则第一刀会在已经扣过血的数值上再次扣血，造成血条先掉过头再回弹。
    for node in nodes or []:
        _, speaker, content, side = _node_side_and_text(node)
        for text in (speaker, content):
            for hp_info in _extract_hp_pairs(text, speaker=speaker, side=side):
                detected_side = hp_info.get("side")
                max_hp_v = int(hp_info.get("max_hp") or 0)
                if detected_side == "player" and max_hp_v > 0:
                    player_max_hp = max(player_max_hp, max_hp_v)
                elif detected_side == "enemy" and max_hp_v > 0:
                    enemy_max_hp = max(enemy_max_hp, max_hp_v)

    if player_max_hp > 0 and player_hp <= 0:
        player_hp = player_max_hp
    if enemy_max_hp > 0 and enemy_hp <= 0:
        enemy_hp = enemy_max_hp

    for idx, node in enumerate(nodes or [], 1):
        data, speaker, content, side = _node_side_and_text(node)
        speaker_img = None

        if side == "player":
            if not player_card:
                p = _build_player_profile(player_id)
                player_card = p['card_img'] if p else None
            speaker_img = player_card
        elif side == "enemy" and is_boss and enemy_name:
            speaker_img = f"/assets/boss/{enemy_name}"

        event_type = "info"
        legacy_type = "log"
        if "回合" in content:
            event_type = "round"
            legacy_type = "turn"
        elif "闪避" in content or "未命中" in content:
            event_type = "miss"
            legacy_type = "miss"
        elif "回复" in content or "恢复" in content or "治疗" in content or "吸取" in content:
            event_type = "heal"
            legacy_type = "heal"
        elif "造成" in content or "伤害" in content:
            event_type = "attack"
            legacy_type = "attack"
        elif "胜利" in content or "赢了" in content or "战斗结束" in content:
            event_type = "end"
            legacy_type = "result"
        elif "提升" in content or "获得" in content or "降低" in content:
            event_type = "info"
            legacy_type = "buff"

        num_pat = r"([0-9]+(?:\.[0-9]+)?\s*[万亿]?)"
        damage = 0
        heal = 0

        damage_matchers = [
            rf"造成了\s*{num_pat}\s*伤害",
            rf"造成\s*{num_pat}\s*伤害",
            rf"受到\s*{num_pat}\s*伤害",
        ]
        for pat in damage_matchers:
            m = re.search(pat, content)
            if m:
                damage = _parse_cn_number(m.group(1))
                break

        heal_matchers = [
            rf"回复\s*{num_pat}",
            rf"恢复\s*{num_pat}",
            rf"治疗\s*{num_pat}",
            rf"吸取\s*{num_pat}",
        ]
        for pat in heal_matchers:
            m = re.search(pat, content)
            if m:
                heal = _parse_cn_number(m.group(1))
                break

        if event_type == "attack":
            amount = damage
        elif event_type == "heal":
            amount = heal
        else:
            amount = 0

        effect = {
            "attack": "slash",
            "miss": "wind",
            "heal": "heal",
            "buff": "aura",
            "turn": "turn",
            "result": "result",
        }.get(legacy_type, "log")

        actor_side = side if side in ("player", "enemy") else None
        target_side = side if side in ("player", "enemy") else None
        if side == "player" and event_type in ("attack", "miss"):
            target_side = "enemy"
        elif side == "enemy" and event_type in ("attack", "miss"):
            target_side = "player"

        # speaker 通常保存“xxx当前血量：cur / max”，必须优先解析。
        for hp_info in _extract_hp_pairs(speaker, speaker=speaker, side=side):
            _apply_hp_pair_snapshot(hp_info)
        for hp_info in _extract_hp_pairs(content, speaker=speaker, side=side):
            _apply_hp_pair_snapshot(hp_info)

        # content 常保存“xxx剩余血量cur”。这种行没有 max，只更新当前 hp。
        for hp_info in _extract_remaining_hp(content, speaker=speaker, side=side):
            _apply_remaining_hp_snapshot(hp_info, fallback_side=target_side)

        if event_type == "attack":
            if actor_side == "player" and target_side == "enemy":
                enemy_hp = max(0, int(enemy_hp) - int(damage)) if enemy_hp > 0 else 0
            elif actor_side == "enemy" and target_side == "player":
                player_hp = max(0, int(player_hp) - int(damage)) if player_hp > 0 else 0
        elif event_type == "heal":
            if actor_side == "player":
                player_hp = min(int(player_max_hp), int(player_hp) + int(heal)) if player_max_hp > 0 else int(player_hp) + int(heal)
            elif actor_side == "enemy":
                enemy_hp = min(int(enemy_max_hp), int(enemy_hp) + int(heal)) if enemy_max_hp > 0 else int(enemy_hp) + int(heal)

        miss = event_type == "miss"

        events.append({
            "seq": idx,
            "side": side,
            "target_side": target_side,
            "type": legacy_type,
            "effect": effect,
            "speaker": speaker,
            "speaker_img": speaker_img,
            "content": content,
            "amount": amount,
            "duration": 1050 if legacy_type in ("attack", "heal", "buff") else 760,
            "event_type": event_type,
            "actor_side": actor_side,
            "damage": damage,
            "heal": heal,
            "miss": miss,
            "player_hp": int(player_hp),
            "player_max_hp": int(player_max_hp),
            "enemy_hp": int(enemy_hp),
            "enemy_max_hp": int(enemy_max_hp),
        })
    return events
def _build_battle_payload(title, winner, events, player_id, enemy_name=None, is_boss=False):
    event_count = len(events or [])
    return {
        "title": title,
        "winner": winner,
        "events": events,
        "enemy": {
            "name": enemy_name,
            "is_boss": is_boss,
            "img": f"/assets/boss/{enemy_name}" if is_boss and enemy_name else None
        },
        "meta": {
            "event_count": event_count,
            "player_id": int(player_id),
            "estimated_seconds": round(event_count * 0.85, 1),
            "schema_version": 2,
        }
    }


def _settle_work_for_web(user_id, work_data):
    user_info = game_sql.get_user_info_with_id(user_id)
    if not user_info:
        return None, "用户不存在"

    msg, give_exp, success, item_id, big_success = workhandle().do_work(
        2,
        work_list=work_data.get('scheduled_time'),
        level=user_info.get('level'),
        exp=user_info.get('exp'),
        user_id=user_id,
    )
    delete_work_file(user_id)

    current_exp = int(user_info.get('exp') or 0)
    max_exp = int(OtherSet().set_closing_type(user_info.get('level'))) * XiuConfig().closing_exp_upper_limit
    if big_success:
        gain_exp = int(give_exp * random.uniform(1.5, 2.5))
        result_label = "悬赏大成功"
    elif success:
        gain_exp = int(give_exp)
        result_label = "悬赏完成"
    else:
        gain_exp = int(give_exp // 2)
        result_label = "悬赏勉强完成"
    gain_exp = max(min(gain_exp, int(max_exp - current_exp)), 0)

    if gain_exp:
        game_sql.update_exp(user_id, gain_exp)
    game_sql.do_work(user_id, 0)

    reward_item = None
    if (big_success or success) and item_id:
        item_info = items.get_data_by_item_id(item_id)
        if item_info:
            game_sql.send_back(user_id, item_id, item_info['name'], item_info['type'], 1)
            reward_item = _serialize_item(item_id)

    return {
        "title": result_label,
        "task": work_data.get('scheduled_time'),
        "message": msg,
        "gain_exp": gain_exp,
        "gain_exp_display": _display_number(gain_exp),
        "success": bool(success),
        "big_success": bool(big_success),
        "item": reward_item,
    }, None


@app.route('/game')
def game_home():
    # 支持 ?token=xxx 一次性登录
    token = (request.args.get('token') or '').strip()
    if token:
        user_id, err = _consume_login_token(token)
        if user_id:
            session.clear()
            session.permanent = False
            session['player_id'] = str(user_id)
            _grant_token_auth(user_id)
            return redirect(url_for('game_home'))

    player = None
    token_error = None
    if token:
        token_error = "登录令无效、已过期或已使用"
    player_id = _current_player_id()
    password_configured = False
    auth_via = None
    fresh_token_auth = False
    if player_id:
        player = game_sql.get_user_info_with_id(player_id)
        password_configured = _auth_has_password(player_id)
        auth_via = session.get('player_auth_via')
        fresh_token_auth = _has_fresh_token_auth()
    return render_template('game.html', player=player, token_error=token_error,
                           password_configured=password_configured, auth_via=auth_via,
                           fresh_token_auth=fresh_token_auth,
                           login_tab='token')


@app.route('/game/login', methods=['POST'])
def game_login():
    token = request.form.get('token', '').strip()
    if token:
        # 一次性 Token 登录
        user_id, err = _consume_login_token(token)
        if not user_id:
            return render_template('game.html', player=None, error=err or "登录令无效或已过期", login_tab='token')
        session.clear()
        session.permanent = False
        session['player_id'] = str(user_id)
        _grant_token_auth(user_id)
        return redirect(url_for('game_home'))

    # QQ号 + Web 密码登录
    user_id_raw = (request.form.get('user_id', '') or '').strip()
    password = request.form.get('password', '') or ''
    if not user_id_raw or not password:
        return render_template('game.html', player=None, error="请输入 QQ 号与密码", login_tab='password')

    if not _auth_is_valid_user_id(user_id_raw):
        return render_template('game.html', player=None, error="账号或密码错误", login_tab='password')

    user_id = int(user_id_raw)
    client_key = request.remote_addr or 'unknown'
    if not _auth_check_rate_limit(user_id, client_key):
        return render_template('game.html', player=None, error="尝试过于频繁，请稍后再试", login_tab='password'), 429

    # 先执行 credential verify（无凭证会走 dummy scrypt），再确认玩家真实存在；
    # 避免通过“玩家是否存在”与“是否配置密码”的响应差异枚举账号
    if not _auth_verify_password(user_id, password):
        _auth_record_failure(user_id, client_key)
        return render_template('game.html', player=None, error="账号或密码错误", login_tab='password')

    player_info = game_sql.get_user_info_with_id(user_id)
    if not player_info:
        _auth_record_failure(user_id, client_key)
        return render_template('game.html', player=None, error="账号或密码错误", login_tab='password')

    _auth_clear_failures(user_id, client_key)
    _auth_mark_password_login(user_id)
    session.clear()
    session.permanent = False
    session['player_id'] = str(user_id)
    session['player_auth_via'] = 'password'
    session.pop('player_token_auth_until', None)
    return redirect(url_for('game_home'))


@app.route('/game/logout')
def game_logout():
    session.pop('player_id', None)
    session.pop('player_auth_via', None)
    session.pop('player_token_auth_until', None)
    return redirect(url_for('game_home'))


@app.route('/game/api/profile')
@game_login_required
def game_api_profile():
    player_id = _current_player_id()
    profile = _build_player_profile(player_id)
    if not profile:
        return _err("角色不存在", 404)
    return _ok(profile=profile)


@app.route('/game/api/backpack')
@game_login_required
def game_api_backpack():
    player_id = _current_player_id()
    return _ok(items=_build_backpack(player_id))


@app.route('/game/api/rankings')
@game_login_required
def game_api_rankings():
    return _ok(rankings=_build_rankings())


@app.route('/game/api/settings')
@game_login_required
def game_api_settings():
    user_id = _current_player_id()
    user = game_sql.get_user_info_with_id(user_id) or {}
    user_data = _ensure_social_fields(_load_player_user_data(user_id))
    return _ok(settings={
        "user_id": int(user_id),
        "user_name": user.get("user_name") or "",
        "two_exp_protect": user_data.get("two_exp_protect", False),
        "friend_request_policy": user_data.get("friend_request_policy", "all"),
        "friends_count": len(user_data.get("friends") or []),
        "requests_in_count": len((user_data.get("friend_requests_in") or {}).keys()),
    })


@app.route('/game/api/settings', methods=['POST'])
@game_login_required
def game_api_settings_update():
    user_id = _current_player_id()
    payload = request.get_json(silent=True) or {}

    new_name = (payload.get("user_name") or "").strip()
    two_exp_protect = payload.get("two_exp_protect", None)
    friend_policy = payload.get("friend_request_policy", None)

    if new_name:
        if len(new_name) > 12:
            return _err("道号长度不能超过 12 个字符")
        if re.search(r"[\s]", new_name):
            return _err("道号不能包含空格")
        msg = game_sql.update_user_name(user_id, new_name)
        if msg and "已存在" in msg:
            return _err(msg)

    user_data = _ensure_social_fields(_load_player_user_data(user_id))
    if two_exp_protect in (False, True, "refusal", "friends_only"):
        user_data["two_exp_protect"] = two_exp_protect
    if friend_policy in ("all", "refuse"):
        user_data["friend_request_policy"] = friend_policy
    _save_player_user_data(user_id, user_data)

    return _ok(message="设置已保存", settings={
        "user_name": (game_sql.get_user_info_with_id(user_id) or {}).get("user_name") or "",
        "two_exp_protect": user_data.get("two_exp_protect", False),
        "friend_request_policy": user_data.get("friend_request_policy", "all"),
    })



@app.route('/game/api/players')
@game_login_required
def game_api_players():
    """获取玩家列表"""
    viewer_id = _current_player_id()
    page = int(request.args.get('page', 1))
    limit = int(request.args.get('limit', 12))
    search = (request.args.get('search', '')).strip()
    
    offset = (page - 1) * limit
    
    # 获取总数
    count_sql = "SELECT COUNT(*) as total FROM user_xiuxian WHERE user_name IS NOT NULL"
    params = []
    if search:
        count_sql += " AND user_name LIKE ?"
        params.append(f"%{search}%")
    
    count_res = execute_sql(DATABASE, count_sql, tuple(params))
    total = count_res[0]['total'] if count_res else 0
    
    # 获取玩家列表
    sql = "SELECT user_id, user_name, level, stone, power, sect_id FROM user_xiuxian WHERE user_name IS NOT NULL"
    if search:
        sql += " AND user_name LIKE ?"
    sql += f" ORDER BY power DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])
    
    rows = execute_sql(DATABASE, sql, tuple(params))
    
    players = []
    for row in rows:
        relation = _get_relation(viewer_id, int(row["user_id"]))
        dual_protect = _get_dual_protect_status(int(row["user_id"]))
        sect_name = "无"
        if row.get('sect_id'):
            sect_info = game_sql.get_sect_info(row['sect_id'])
            if sect_info:
                sect_name = sect_info['sect_name']
        
        # 确定卡图名称
        cards = [c.stem for c in (ASSETS_PATH / "卡图").glob("*.webp")]
        if not cards: cards = [c.stem for c in (ASSETS_PATH / "卡图").glob("*.png")]
        card_name = cards[int(row['user_id']) % len(cards)] if cards else "default"

        players.append({
            "user_id": int(row['user_id']),
            "name": row['user_name'],
            "card_img": f"/assets/card/{card_name}",
            "level": row['level'],
            "stone": int(row['stone'] or 0),
            "stone_display": _display_number(row['stone'] or 0),
            "power": int(row['power'] or 0),
            "power_display": _display_number(row['power'] or 0),
            "sect_name": sect_name,
            "relation": relation,
            "dual_protect": dual_protect,
        })
    
    return _ok(
        players=players,
        total=total,
        page=page,
        limit=limit
    )


@app.route('/game/api/social/friend/request', methods=['POST'])
@game_login_required
def game_api_friend_request():
    user_id = _current_player_id()
    payload = request.get_json(silent=True) or {}
    target_id = payload.get("target_id")
    if not target_id:
        return _err("未指定目标道友")
    target_id = int(target_id)
    if target_id == int(user_id):
        return _err("无法对自己操作")

    target_user = game_sql.get_user_info_with_id(target_id)
    if not target_user:
        return _err("目标道友不存在")

    policy = _get_friend_policy(target_id)
    if policy == "refuse":
        return _err("对方已关闭结识申请")

    relation = _get_relation(user_id, target_id)
    if relation == "friend":
        return _err("你们已经是好友了")
    if relation in ("outgoing", "incoming"):
        return _err("已有待处理的结识申请")

    user_data = _ensure_social_fields(_load_player_user_data(user_id))
    target_data = _ensure_social_fields(_load_player_user_data(target_id))

    ts = str(datetime.now().timestamp())
    user_data["friend_requests_out"][str(target_id)] = ts
    target_data["friend_requests_in"][str(user_id)] = ts
    _save_player_user_data(user_id, user_data)
    _save_player_user_data(target_id, target_data)

    inviter_name = (game_sql.get_user_info_with_id(user_id) or {}).get("user_name") or str(user_id)
    display_host = "xiuxian.superbread.uk"
    login_token = _issue_login_token(target_id)
    msg = (
        "【结识申请】\n"
        f"道友：{inviter_name} 想与你结识。\n\n"
        "请打开网页进入【社交】页面处理该申请：\n"
        f"https://{display_host}/game?token={login_token}\n"
    )
    _run_async(_send_private_msg(target_id, msg))
    return _ok(message="已发送结识申请")


@app.route('/game/api/social/friend/respond', methods=['POST'])
@game_login_required
def game_api_friend_respond():
    user_id = _current_player_id()
    payload = request.get_json(silent=True) or {}
    from_id = payload.get("from_id")
    accept = bool(payload.get("accept", False))
    if not from_id:
        return _err("未指定申请来源")
    from_id = int(from_id)
    if from_id == int(user_id):
        return _err("参数错误")

    user_data = _ensure_social_fields(_load_player_user_data(user_id))
    if str(from_id) not in (user_data.get("friend_requests_in") or {}):
        return _err("没有找到待处理的结识申请")

    if accept:
        _add_friend_pair(int(user_id), int(from_id))
        accepter_name = (game_sql.get_user_info_with_id(user_id) or {}).get("user_name") or str(user_id)
        display_host = "xiuxian.superbread.uk"
        login_token = _issue_login_token(from_id)
        msg = (
            "【结识成功】\n"
            f"道友：{accepter_name} 已同意与你结识。\n\n"
            "打开网页即可在【社交】看到好友：\n"
            f"https://{display_host}/game?token={login_token}\n"
        )
        _run_async(_send_private_msg(from_id, msg))
        return _ok(message="已同意结识")

    _remove_friend_request(int(user_id), int(from_id))
    return _ok(message="已拒绝结识")


@app.route('/game/api/social/friend/requests')
@game_login_required
def game_api_friend_requests():
    user_id = _current_player_id()
    user_data = _ensure_social_fields(_load_player_user_data(user_id))
    incoming_ids = [int(k) for k in (user_data.get("friend_requests_in") or {}).keys() if str(k).isdigit()]
    outgoing_ids = [int(k) for k in (user_data.get("friend_requests_out") or {}).keys() if str(k).isdigit()]

    def pack(ids):
        items = []
        for uid in ids[:200]:
            u = game_sql.get_user_info_with_id(uid)
            if not u:
                continue
            items.append({
                "user_id": int(uid),
                "name": u.get("user_name") or str(uid),
                "level": u.get("level") or "未知",
            })
        return items

    return _ok(incoming=pack(incoming_ids), outgoing=pack(outgoing_ids))


@app.route('/game/api/social/requests/status')
@game_login_required
def game_api_social_requests_status():
    user_id = _current_player_id()
    try:
        user_data = _ensure_social_fields(_load_player_user_data(user_id))
        incoming_ids = [
            int(k)
            for k in (user_data.get("friend_requests_in") or {}).keys()
            if str(k).isdigit()
        ]
        pending_count = len(incoming_ids)
        items = []
        for uid in incoming_ids[:3]:
            info = game_sql.get_user_info_with_id(uid) or {}
            items.append({
                "user_id": str(uid),
                "name": info.get("user_name") or f"道友{uid}",
            })
        return _ok(requests={
            "pending_count": pending_count,
            "has_pending": pending_count > 0,
            "items": items,
        })
    except Exception as e:
        return _ok(
            requests={"pending_count": 0, "has_pending": False, "items": []},
            message=f"结识申请状态读取失败：{e}",
        )


@app.route('/game/api/social/friends')
@game_login_required
def game_api_friends():
    user_id = _current_player_id()
    user_data = _ensure_social_fields(_load_player_user_data(user_id))
    friends = [int(x) for x in (user_data.get("friends") or []) if str(x).isdigit()]
    results = []
    for fid in friends[:200]:
        u = game_sql.get_user_info_with_id(fid)
        if not u:
            continue
        results.append({
            "user_id": int(fid),
            "name": u.get("user_name") or str(fid),
            "level": u.get("level") or "未知",
            "power": int(u.get("power") or 0),
            "power_display": _display_number(u.get("power") or 0),
        })
    return _ok(friends=results)


@app.route('/game/api/social/dual/request', methods=['POST'])
@game_login_required
def game_api_dual_request():
    user_id = _current_player_id()
    payload = request.get_json(silent=True) or {}
    target_id = payload.get("target_id")
    exp_count = int(payload.get("count", 1) or 1)
    if not target_id:
        return _err("未指定目标道友")
    target_id = int(target_id)
    if target_id == int(user_id):
        return _err("无法对自己操作")

    target_user = game_sql.get_user_info_with_id(target_id)
    if not target_user:
        return _err("目标道友不存在")

    protect = _get_dual_protect_status(target_id)
    relation = _get_relation(user_id, target_id)
    if protect == "refusal":
        return _err("对方已设置拒绝所有双修")
    if protect == "friends_only" and relation != "friend":
        return _err("对方只接受好友双修邀请")

    ok, msg = _consume_stamina(user_id, 10)
    if not ok:
        return _err(msg)

    exp_count = max(1, min(exp_count, 5))

    if protect is False:
        result = _perform_two_exp(int(user_id), int(target_id), exp_count, is_partner=False)
        if not result.get("ok"):
            return _err(result.get("message") or "双修失败")
        return _ok(message=result["message"], mode="direct")

    token = _issue_web_dual_invite(int(user_id), int(target_id), exp_count)
    inviter_name = (game_sql.get_user_info_with_id(user_id) or {}).get("user_name") or str(user_id)
    display_host = "xiuxian.superbread.uk"
    login_token = _issue_login_token(target_id)
    link = f"https://{display_host}/game?token={login_token}&dual={token}"
    msg = (
        "【双修邀请】\n"
        f"道友：{inviter_name} 邀请你双修 {exp_count} 次。\n"
        f"邀请有效期：{WEB_DUAL_EXPIRE_SECONDS // 60} 分钟\n\n"
        f"点击链接处理：\n{link}\n"
    )
    _run_async(_send_private_msg(target_id, msg))
    return _ok(message="已发送双修邀请，等待对方回应", mode="invite")


@app.route('/game/api/social/dual/respond', methods=['POST'])
@game_login_required
def game_api_dual_respond():
    user_id = _current_player_id()
    payload = request.get_json(silent=True) or {}
    token = (payload.get("token") or "").strip()
    accept = bool(payload.get("accept", False))
    if not token:
        return _err("缺少邀请令")

    info, err = _consume_web_dual_invite(token)
    if not info:
        return _err(err)
    if int(info.get("target_id")) != int(user_id):
        return _err("该邀请不属于你")

    inviter_id = int(info.get("inviter_id"))
    exp_count = int(info.get("count") or 1)
    inviter = game_sql.get_user_info_with_id(inviter_id)
    if not inviter:
        return _err("发起者不存在")

    if not accept:
        inviter_name = (game_sql.get_user_info_with_id(user_id) or {}).get("user_name") or str(user_id)
        _run_async(_send_private_msg(inviter_id, f"【双修邀请】\n道友：{inviter_name} 拒绝了你的双修邀请。"))
        return _ok(message="已拒绝双修")

    result = _perform_two_exp(inviter_id, int(user_id), exp_count, is_partner=False)
    if not result.get("ok"):
        return _err(result.get("message") or "双修失败")

    accepter_name = (game_sql.get_user_info_with_id(user_id) or {}).get("user_name") or str(user_id)
    _run_async(_send_private_msg(inviter_id, f"【双修完成】\n道友：{accepter_name} 已同意双修。\n\n{result['message']}"))
    return _ok(message=result["message"])


@app.route('/game/api/social/action', methods=['POST'])
@game_login_required
def game_api_social_action():
    """社交动作：切磋、双修、赠送"""
    user_id = _current_player_id()
    data = request.json
    target_id = data.get('target_id')
    action_type = data.get('action_type') # 'duel', 'gift_stone'
    amount = int(data.get('amount', 0))
    
    if not target_id:
        return _err("未指定目标道友")
    
    if int(user_id) == int(target_id):
        return _err("道友无法对自己进行此操作")

    user_info = game_sql.get_user_info_with_id(user_id)
    target_info = game_sql.get_user_info_with_id(target_id)
    
    if not target_info:
        return _err("目标道友不存在")

    if action_type == 'duel':
        # 切磋逻辑
        ok, msg = _consume_stamina(user_id, 1)
        if not ok:
            return _err(msg)
            
        # 注意：Player_fight 是异步函数，需要通过 _run_async 执行
        result, victor = _run_async(Player_fight(user_id, target_id, 1, "WebUI"))
        
        # 记录战绩
        if victor == user_info['user_name']:
            update_statistics_value(user_id, "切磋胜利")
            update_statistics_value(target_id, "切磋失败")
        elif victor == target_info['user_name']:
            update_statistics_value(target_id, "切磋胜利")
            update_statistics_value(user_id, "切磋失败")
            
        events = _normalize_battle_nodes(result, user_id, target_info['user_name'], is_boss=False)
        battle_payload = _build_battle_payload(f"与 {target_info['user_name']} 的切磋", victor, events, user_id, target_info['user_name'], is_boss=False)
        
        return _ok(message=f"切磋结束！获胜者：{victor}", battle=battle_payload)
        
    elif action_type == 'gift_stone':
        if amount <= 0:
            return _err("赠送数量必须大于0")
        if user_info['stone'] < amount:
            return _err("灵石不足")
            
        game_sql.update_ls(user_id, amount, 2) # 扣除
        game_sql.update_ls(target_id, amount, 1) # 增加
        
        return _ok(message=f"成功赠送 {amount} 灵石给 {target_info['user_name']}")

    return _err("未知的社交动作")


@app.route('/game/api/sect')
@game_login_required
def game_api_sect():
    player_id = _current_player_id()
    return _ok(sect=_build_sect_info(player_id))


@app.route('/game/api/sect/task/accept', methods=['POST'])
@game_login_required
def game_api_sect_task_accept():
    player_id = _current_player_id()
    user = game_sql.get_user_info_with_id(player_id)
    if not user:
        return _err("当前用户不存在", 404)

    sect_id = user.get("sect_id")
    if not sect_id:
        return _err("当前未加入宗门")

    sect = game_sql.get_sect_info(sect_id)
    if not sect:
        return _err("当前宗门不存在", 404)

    try:
        from ..xiuxian_sect import create_user_sect_task, isUserTask, userstask
        from ..xiuxian_sect.sectconfig import get_config as _get_sect_config
    except Exception:
        return _err("宗门任务模块加载失败", 500)

    try:
        daily_limit = int((_get_sect_config() or {}).get("每日宗门任务次上限", 3))
    except Exception:
        daily_limit = 3
    try:
        today_count = int(user.get("sect_task") or user.get("sect_task_count") or user.get("sect_task_complete_num") or 0)
    except Exception:
        today_count = 0

    if today_count >= daily_limit:
        return _err(f"今日宗门任务次数已达上限（{today_count}/{daily_limit}）")

    if isUserTask(player_id):
        return _ok(message="已有进行中的宗门任务", sect=_build_sect_info(player_id))

    userstask.setdefault(player_id, {})
    create_user_sect_task(player_id)
    if not isUserTask(player_id):
        return _err("宗门任务接取失败", 500)

    return _ok(message="宗门任务接取成功", sect=_build_sect_info(player_id))


@app.route('/game/api/sect/task/complete', methods=['POST'])
@game_login_required
def game_api_sect_task_complete():
    player_id = _current_player_id()
    user = game_sql.get_user_info_with_id(player_id)
    if not user:
        return _err("当前用户不存在", 404)

    sect_id = user.get("sect_id")
    if not sect_id:
        return _err("当前未加入宗门")

    sect = game_sql.get_sect_info(sect_id)
    if not sect:
        return _err("当前宗门不存在", 404)

    try:
        from ..xiuxian_sect import isUserTask, userstask, _clear_user_sect_task_state
    except Exception:
        return _err("宗门任务模块加载失败", 500)

    if not isUserTask(player_id):
        return _err("当前没有进行中的宗门任务")

    task_content = userstask[player_id]["任务内容"]
    try:
        task_type = int(task_content["type"])
        cost = task_content["cost"]
        give = task_content["give"]
        sect_stone = int(task_content["sect"])
    except Exception:
        return _err("宗门任务数据有误", 500)

    user_exp = int(user.get("exp") or 0)
    user_hp = int(user.get("hp") or 0)
    user_mp = int(user.get("mp") or 0)
    user_stone = int(user.get("stone") or 0)
    sect_position = user.get("sect_position")
    if sect_position is None:
        max_exp_limit = 4
    else:
        max_exp_limit = sect_position
    speeds = float(jsondata.sect_config_data()[str(max_exp_limit)]["speeds"])

    get_exp = int(user_exp * float(give))
    max_exp = int(sect.get("sect_scale") or 0) * 100000
    if max_exp >= 100000000000000:
        max_exp = 100000000000000
    max_exp = int(max_exp * speeds)
    if get_exp >= max_exp:
        get_exp = max_exp

    max_exp_next = int(int(OtherSet().set_closing_type(user["level"])) * XiuConfig().closing_exp_upper_limit)
    msg = ""
    if int(get_exp + user_exp) > max_exp_next:
        get_exp = 1
        msg = "检测到修为将要到达上限，"

    conn = None
    try:
        conn = sqlite3.connect(DATABASE, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        conn.execute("BEGIN")

        if task_type == 1:
            costhp = int((user_exp / 2) * float(cost))
            if user_hp < user_exp / 10 or costhp >= user_hp:
                conn.rollback()
                return _err("当前气血不足，宗门任务完成失败")

            cur.execute(
                "UPDATE user_xiuxian SET hp=?, mp=? WHERE user_id=?",
                (user_hp - costhp, user_mp, player_id),
            )
            if cur.rowcount <= 0:
                conn.rollback()
                return _err("气血更新失败", 500)

            cur.execute(
                "UPDATE user_xiuxian SET exp = exp + ? WHERE user_id = ?",
                (get_exp, player_id),
            )
            if cur.rowcount <= 0:
                conn.rollback()
                return _err("修为更新失败", 500)

            cur.execute(
                "UPDATE sects SET sect_used_stone = COALESCE(sect_used_stone,0) + ?, sect_scale = COALESCE(sect_scale,0) + ? WHERE sect_id = ?",
                (sect_stone, sect_stone, sect_id),
            )
            if cur.rowcount <= 0:
                conn.rollback()
                return _err("宗门建设更新失败", 500)

            cur.execute(
                "UPDATE sects SET sect_materials = COALESCE(sect_materials,0) + ? WHERE sect_id = ?",
                (sect_stone * 10, sect_id),
            )
            if cur.rowcount <= 0:
                conn.rollback()
                return _err("宗门资材更新失败", 500)

            cur.execute(
                "UPDATE user_xiuxian SET sect_task = COALESCE(sect_task,0) + 1 WHERE user_id = ?",
                (player_id,),
            )
            if cur.rowcount <= 0:
                conn.rollback()
                return _err("宗门任务次数更新失败", 500)

            cur.execute(
                "UPDATE user_xiuxian SET sect_contribution = COALESCE(sect_contribution,0) + ? WHERE user_id = ?",
                (sect_stone, player_id),
            )
            if cur.rowcount <= 0:
                conn.rollback()
                return _err("宗门贡献更新失败", 500)

            message = (
                f"气血减少 {number_to(costhp)}，获得修为 {number_to(get_exp)}，"
                f"宗门建设度增加 {number_to(sect_stone)}，资材增加 {number_to(sect_stone * 10)}，"
                f"宗门贡献增加 {number_to(int(sect_stone))}"
            )
            if msg:
                message = msg + message
        elif task_type == 2:
            costls = int(cost)
            if costls > user_stone:
                conn.rollback()
                return _err("灵石不足，宗门任务完成失败")

            cur.execute(
                "UPDATE user_xiuxian SET stone = stone - ? WHERE user_id = ? AND stone >= ?",
                (costls, player_id, costls),
            )
            if cur.rowcount <= 0:
                conn.rollback()
                return _err("灵石扣除失败", 500)

            cur.execute(
                "UPDATE user_xiuxian SET exp = exp + ? WHERE user_id = ?",
                (get_exp, player_id),
            )
            if cur.rowcount <= 0:
                conn.rollback()
                return _err("修为更新失败", 500)

            cur.execute(
                "UPDATE sects SET sect_used_stone = COALESCE(sect_used_stone,0) + ?, sect_scale = COALESCE(sect_scale,0) + ? WHERE sect_id = ?",
                (sect_stone, sect_stone, sect_id),
            )
            if cur.rowcount <= 0:
                conn.rollback()
                return _err("宗门建设更新失败", 500)

            cur.execute(
                "UPDATE sects SET sect_materials = COALESCE(sect_materials,0) + ? WHERE sect_id = ?",
                (sect_stone * 10, sect_id),
            )
            if cur.rowcount <= 0:
                conn.rollback()
                return _err("宗门资材更新失败", 500)

            cur.execute(
                "UPDATE user_xiuxian SET sect_task = COALESCE(sect_task,0) + 1 WHERE user_id = ?",
                (player_id,),
            )
            if cur.rowcount <= 0:
                conn.rollback()
                return _err("宗门任务次数更新失败", 500)

            cur.execute(
                "UPDATE user_xiuxian SET sect_contribution = COALESCE(sect_contribution,0) + ? WHERE user_id = ?",
                (sect_stone, player_id),
            )
            if cur.rowcount <= 0:
                conn.rollback()
                return _err("宗门贡献更新失败", 500)

            message = (
                f"灵石消耗 {number_to(costls)}，获得修为 {number_to(get_exp)}，"
                f"宗门建设度增加 {number_to(sect_stone)}，资材增加 {number_to(sect_stone * 10)}，"
                f"宗门贡献增加 {number_to(int(sect_stone))}"
            )
            if msg:
                message = msg + message
        else:
            conn.rollback()
            return _err("宗门任务类型有误", 500)

        conn.commit()
        _clear_user_sect_task_state(player_id)
        try:
            update_statistics_value(player_id, "宗门任务")
        except Exception:
            pass
        return _ok(message=message, sect=_build_sect_info(player_id))
    except Exception as e:
        if conn:
            try:
                conn.rollback()
            except Exception:
                pass
        logger.exception(f"sect task complete failed: player_id={player_id}, error={e}")
        return _err("宗门任务完成失败")
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


@app.route('/game/api/sect/donate', methods=['POST'])
@game_login_required
def game_api_sect_donate():
    player_id = _current_player_id()
    payload = request.get_json(silent=True) or {}
    amount_raw = payload.get("amount")
    if isinstance(amount_raw, bool):
        return _err("amount 必须是整数")
    try:
        amount = int(amount_raw)
    except (TypeError, ValueError):
        return _err("amount 必须是整数")

    if amount <= 0:
        return _err("amount 必须大于 0")
    if amount > 2147483647:
        return _err("amount 超出允许范围")

    user = game_sql.get_user_info_with_id(player_id)
    if not user:
        return _err("当前用户不存在", 404)

    sect_id = user.get("sect_id")
    if not sect_id:
        return _err("当前未加入宗门")

    sect = game_sql.get_sect_info(sect_id)
    if not sect:
        return _err("当前宗门不存在", 404)

    conn = None
    try:
        conn = sqlite3.connect(DATABASE, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        user_cols = {str(r["name"]) for r in cur.execute("PRAGMA table_info(user_xiuxian)").fetchall() if r and r["name"]}
        sect_cols = {str(r["name"]) for r in cur.execute("PRAGMA table_info(sects)").fetchall() if r and r["name"]}
        if "sect_contribution" not in user_cols:
            return _err("数据库缺少列：user_xiuxian.sect_contribution")
        if "sect_used_stone" not in sect_cols:
            return _err("数据库缺少列：sects.sect_used_stone")
        if "sect_scale" not in sect_cols:
            return _err("数据库缺少列：sects.sect_scale")

        conn.execute("BEGIN")
        cur.execute(
            "UPDATE user_xiuxian SET stone = stone - ? WHERE user_id = ? AND stone >= ?",
            (amount, player_id, amount),
        )
        if cur.rowcount <= 0:
            conn.rollback()
            return _err("灵石不足")

        cur.execute(
            "UPDATE sects SET sect_used_stone = COALESCE(sect_used_stone,0) + ?, sect_scale = COALESCE(sect_scale,0) + ? WHERE sect_id = ?",
            (amount, amount, sect_id),
        )
        if cur.rowcount <= 0:
            conn.rollback()
            return _err("宗门不存在或更新失败")

        cur.execute(
            "UPDATE user_xiuxian SET sect_contribution = COALESCE(sect_contribution,0) + ? WHERE user_id = ?",
            (amount, player_id),
        )
        if cur.rowcount <= 0:
            conn.rollback()
            return _err("个人贡献更新失败")

        row = cur.execute(
            """
            SELECT u.stone AS stone_left,
                   COALESCE(u.sect_contribution,0) AS sect_contribution,
                   COALESCE(s.sect_scale,0) AS sect_scale,
                   COALESCE(s.sect_used_stone,0) AS sect_used_stone
              FROM user_xiuxian u
              LEFT JOIN sects s ON s.sect_id = ?
             WHERE u.user_id = ?
             LIMIT 1
            """,
            (sect_id, player_id),
        ).fetchone()
        if not row:
            conn.rollback()
            return _err("捐献成功但读取结果失败")

        conn.commit()
        return _ok(
            message="捐献成功",
            amount=amount,
            stone_left=int(row["stone_left"] or 0),
            sect_contribution=int(row["sect_contribution"] or 0),
            sect_scale=int(row["sect_scale"] or 0),
            sect_used_stone=int(row["sect_used_stone"] or 0),
        )
    except Exception as e:
        if conn:
            try:
                conn.rollback()
            except Exception:
                pass
        logger.exception(f"sect donate failed: user_id={player_id}, error={e}")
        return _err("宗门捐献失败，请稍后重试")
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


@app.route('/game/api/rift/explore', methods=['POST'])
@game_login_required
def game_api_rift_explore():
    player_id = _current_player_id()
    is_type, msg = check_user_type(player_id, 0)
    if not is_type:
        return _err(msg or "当前状态无法开始秘境探索")
        
    group_rift = old_rift_info.read_rift_info()
    group_id = "000000"
    if group_id not in group_rift:
        # 如果没有秘境，尝试生成一个
        from ..xiuxian_rift.riftconfig import get_rift_config
        config = get_rift_config()
        rift = Rift()
        rift.name = get_rift_type()
        rift.rank = config['rift'][rift.name]['rank']
        rift.time = config['rift'][rift.name]['time']
        group_rift[group_id] = rift
        old_rift_info.save_rift(group_rift)
        
    rift = group_rift[group_id]
    user = game_sql.get_user_info_with_id(player_id)
    
    # 境界检查
    user_rank = convert_rank(user["level"])[0]
    required_rank = convert_rank("感气境中期")[0] - rift.rank
    if user_rank > required_rank:
        rank_name_list = convert_rank(user["level"])[1]
        required_rank_name = rank_name_list[len(rank_name_list) - required_rank - 1]
        return _err(f"境界不足，无法进入秘境：{rift.name}，需要{required_rank_name}以上。")

    if str(player_id) in [str(x) for x in rift.l_user_id]:
        return _err("道友已经参加过本次秘境啦。")

    ok, msg = _consume_stamina(player_id, 6)
    if not ok: return _err(msg)

    rift.l_user_id.append(player_id)
    rift_data = {"name": rift.name, "time": rift.time, "rank": rift.rank}
    save_rift_data(player_id, rift_data)
    game_sql.do_work(player_id, 3, rift_data["time"])
    old_rift_info.save_rift(group_rift)
    
    return _ok(message=f"进入秘境：{rift.name}，预计耗时 {rift.time} 分钟。", rift={
        "in_rift": True,
        "name": rift.name,
        "remaining_minutes": rift.time
    })


@app.route('/game/api/rift/settle', methods=['POST'])
@game_login_required
def game_api_rift_settle():
    player_id = _current_player_id()
    is_type, msg = check_user_type(player_id, 3)
    if not is_type:
        logger.warning(f"Rift settle failed: user_id={player_id}, reason={msg or 'not in rift'}")
        return _err(msg or "当前不在秘境探索状态")
        
    user_cd = game_sql.get_user_cd(player_id)
    if not user_cd: 
        logger.warning(f"Rift settle failed: user_id={player_id}, reason=no cd info")
        return _err("数据异常，未找到 CD 信息")
    
    rift_info = read_rift_data(player_id)
    create_time = _parse_datetime(user_cd['create_time'])
    elapsed = (datetime.now() - create_time).total_seconds() // 60
    
    if elapsed < rift_info.get("time", 0) - 1:
        msg = f"正在探索中，还需 {int(rift_info['time'] - elapsed)} 分钟。"
        logger.warning(f"Rift settle failed: user_id={player_id}, reason={msg}")
        return _err(msg)
        
    # 结算逻辑
    game_sql.do_work(player_id, 0)
    rift_rank = rift_info["rank"]
    user_info = game_sql.get_user_info_with_id(player_id)
    
    story_type = get_story_type()
    result_msg = "秘境探索结束。"
    battle = None
    
    if story_type == "无事":
        result_msg = random.choice(NONEMSG)
    elif story_type == "战斗":
        battle_type = get_battle_type()
        if battle_type == "掉血事件":
            result_msg = get_dxsj_info("掉血事件", user_info)
        elif battle_type == "Boss战斗":
            # 模拟 Boss 战
            scarecrow = {
                "name": f"秘境守卫({rift_info['name']})",
                "气血": max(int(user_info.get('exp') or 100) * 1.5, 500),
                "攻击": int(user_info.get('atk') or 100) * 0.8,
                "真元": 0,
                "会心": 10,
                "jj": user_info.get('level'),
            }
            play_list, winner, _ = _run_async(Boss_fight(player_id, scarecrow, type_in=1, bot_id=0))
            events = _normalize_battle_nodes(play_list, player_id, enemy_name=scarecrow['name'], is_boss=True)
            battle = _build_battle_payload(f"秘境战斗：{scarecrow['name']}", winner, events, player_id, enemy_name=scarecrow['name'], is_boss=True)
            result_msg = f"在秘境中遭遇了 {scarecrow['name']}！"
    elif story_type == "宝物":
        result_msg = get_treasure_info(user_info, rift_rank)
        
    return _ok(message=result_msg, battle=battle)


@app.route('/game/api/rift')
@game_login_required
def game_api_rift():
    player_id = _current_player_id()
    user_cd = game_sql.get_user_cd(player_id)
    in_rift = bool(user_cd and user_cd.get('type') == 3)
    
    name = "未知秘境"
    remaining = 0
    if in_rift:
        try:
            rift_info = read_rift_data(player_id)
            name = rift_info.get('name', name)
            create_time = _parse_datetime(user_cd['create_time'])
            if create_time:
                elapsed = (datetime.now() - create_time).total_seconds() // 60
                remaining = max(int(rift_info.get('time', 0) - elapsed), 0)
        except Exception:
            pass
            
    return _ok(rift={
        "in_rift": in_rift,
        "name": name,
        "remaining_minutes": remaining,
        "message": "检测到秘境探索中，可以结算或在QQ侧使用【秘境结算】。" if in_rift else "当前不在秘境中，点击按钮开始探索。",
    })


@app.route('/game/api/alchemy')
@game_login_required
def game_api_alchemy():
    player_id = _current_player_id()
    # 先提供可视化所需基础信息，后续再接入完整炼丹流程
    backpack = _build_backpack(player_id, limit=300)
    yaocai = [x for x in backpack if x.get('type') in ('药材', '丹药', '炼丹炉', '合成丹药')][:50]
    return _ok(alchemy={
        "message": "炼丹网页流程开发中，当前可查看相关材料库存。",
        "materials": yaocai,
    })


@app.route('/game/api/item/use_pill', methods=['POST'])
@game_login_required
def game_api_use_pill():
    player_id = _current_player_id()
    payload = request.get_json(silent=True) or {}

    try:
        item_id = int(payload.get("item_id"))
    except (TypeError, ValueError):
        return _err("参数错误：item_id 无效")

    try:
        quantity = int(payload.get("quantity", 1))
    except (TypeError, ValueError):
        return _err("参数错误：quantity 无效")

    if quantity != 1:
        return _err("第一版丹药使用只支持数量为 1")

    try:
        item_data = items.get_data_by_item_id(item_id)
    except Exception:
        item_data = None

    if not item_data:
        return _err("物品不存在", 404)

    item_name = item_data.get("name") or f"物品{item_id}"
    buff_type = item_data.get("buff_type")

    if buff_type != "hp":
        return _err("当前只支持气血恢复类丹药")

    try:
        buff = float(item_data.get("buff") or 0)
    except (TypeError, ValueError):
        return _err("丹药恢复效果异常")

    if buff <= 0:
        return _err("丹药恢复效果异常")

    # 检查背包数量
    owned_count = 0
    try:
        back_item = game_sql.get_item_by_good_id_and_user_id(player_id, item_id)
        if back_item:
            owned_count = int(back_item.get("goods_num") or 0)
    except Exception:
        back_item = None

    if owned_count <= 0:
        try:
            for row in game_sql.get_back_msg(player_id) or []:
                if int(row.get("goods_id") or 0) == item_id:
                    owned_count = int(row.get("goods_num") or 0)
                    break
        except Exception:
            owned_count = 0

    if owned_count < 1:
        return _err(f"背包中没有可使用的【{item_name}】")

    user = game_sql.get_user_real_info(player_id) or game_sql.get_user_info_with_id(player_id)
    if not user:
        return _err("角色不存在", 404)

    current_hp = int(user.get("hp") or 0)
    current_mp = int(user.get("mp") or 0)
    exp = int(user.get("exp") or 0)
    max_hp = int(exp / 2)

    if max_hp <= 0:
        return _err("角色气血上限异常")

    if current_hp >= max_hp:
        return _err("当前气血已满")

    recover_hp = int(max_hp * buff)
    if recover_hp <= 0:
        return _err("丹药恢复效果异常")

    new_hp = min(current_hp + recover_hp, max_hp)
    actual_recover_hp = new_hp - current_hp

    if actual_recover_hp <= 0:
        return _err("当前气血已满")

    game_sql.update_user_hp_mp(player_id, new_hp, current_mp)
    game_sql.update_back_j(player_id, item_id, num=1, use_key=1)

    return _ok(
        message=f"已使用{item_name}，恢复气血{actual_recover_hp}点",
        data={
            "item_id": item_id,
            "item_name": item_name,
            "quantity": 1,
            "buff_type": buff_type,
            "buff": buff,
            "recover_hp": actual_recover_hp,
            "current_hp": current_hp,
            "new_hp": new_hp,
            "max_hp": max_hp,
        }
    )


@app.route('/game/api/item/equip', methods=['POST'])
@game_login_required
def game_api_item_equip():
    user_id = _current_player_id()
    payload = request.get_json(silent=True) or {}

    try:
        goods_id = int(payload.get("goods_id"))
    except (TypeError, ValueError):
        return _err("参数错误：goods_id 必须为整数")

    backpack_items = _build_backpack(user_id, limit=500)
    item = next((x for x in backpack_items if int(x.get("id") or 0) == goods_id), None)
    if not item:
        return _err("背包中不存在该物品", 404)
    if not _is_equipment_item(item):
        return _err("该物品不是可穿戴装备")

    if int(item.get("state") or 0) != 0:
        return _err("该装备已被装备，请勿重复装备！")

    if not check_equipment_can_use(user_id, goods_id):
        return _err("该装备已被装备，请勿重复装备！")

    sql_result = get_use_equipment_sql(user_id, goods_id)
    sql_list, item_type = sql_result if isinstance(sql_result, tuple) else (sql_result, "")
    if not isinstance(sql_list, list) or not sql_list:
        return _err("穿戴失败：未生成有效装备SQL")

    for sql in sql_list:
        res = execute_sql(DATABASE, sql)
        if isinstance(res, dict) and res.get("error"):
            return _err(f"穿戴失败：{res['error']}")

    if item_type == "法器":
        game_sql.updata_user_faqi_buff(user_id, goods_id)
    if item_type == "防具":
        game_sql.updata_user_armor_buff(user_id, goods_id)

    return _ok(message="穿戴成功", goods_id=goods_id)


@app.route('/game/api/item/unequip', methods=['POST'])
@game_login_required
def game_api_item_unequip():
    user_id = _current_player_id()
    payload = request.get_json(silent=True) or {}

    try:
        goods_id = int(payload.get("goods_id"))
    except (TypeError, ValueError):
        return _err("参数错误：goods_id 必须为整数")

    backpack_items = _build_backpack(user_id, limit=500)
    item = next((x for x in backpack_items if int(x.get("id") or 0) == goods_id), None)
    if not item:
        return _err("背包中不存在该物品", 404)
    if not _is_equipment_item(item):
        return _err("该物品不是可卸下装备")

    if int(item.get("state") or 0) != 1:
        return _err("装备没有被使用，无法卸载！")

    sql_result = get_no_use_equipment_sql(user_id, goods_id)
    sql_list, item_type = sql_result if isinstance(sql_result, tuple) else (sql_result, "")
    if not isinstance(sql_list, list) or not sql_list:
        return _err("卸下失败：未生成有效装备SQL")

    for sql in sql_list:
        res = execute_sql(DATABASE, sql)
        if isinstance(res, dict) and res.get("error"):
            return _err(f"卸下失败：{res['error']}")

    if item_type == "法器":
        game_sql.updata_user_faqi_buff(user_id, 0)
    if item_type == "防具":
        game_sql.updata_user_armor_buff(user_id, 0)

    return _ok(message="卸下成功", goods_id=goods_id)

@app.route('/game/api/impart/wish', methods=['POST'])
@game_login_required
def game_api_impart_wish():
    player_id = _current_player_id()
    payload = request.get_json(silent=True)
    if not payload:
        return jsonify({
            "success": False,
            "ok": False,
            "error": "\u8bf7\u6c42\u53c2\u6570\u4e0d\u80fd\u4e3a\u7a7a",
            "message": "\u8bf7\u6c42\u53c2\u6570\u4e0d\u80fd\u4e3a\u7a7a"
        })

    wish_times_raw = payload.get("wish_times")
    if wish_times_raw is None:
        return jsonify({
            "success": False,
            "ok": False,
            "error": "wish_times \u4e0d\u80fd\u4e3a\u7a7a",
            "message": "wish_times \u4e0d\u80fd\u4e3a\u7a7a"
        })

    try:
        wish_times = int(wish_times_raw)
    except (TypeError, ValueError):
        return jsonify({
            "success": False,
            "ok": False,
            "error": "wish_times \u5fc5\u987b\u662f\u6574\u6570",
            "message": "wish_times \u5fc5\u987b\u662f\u6574\u6570"
        })

    if wish_times not in (1, 10):
        return jsonify({
            "success": False,
            "ok": False,
            "error": "wish_times \u53ea\u5141\u8bb8 1 \u6216 10",
            "message": "wish_times \u53ea\u5141\u8bb8 1 \u6216 10"
        })

    try:
        from ..xiuxian_impart import perform_impart_crystal_wish
        result = _run_async(perform_impart_crystal_wish(player_id, wish_times))
    except Exception as e:
        logger.exception(f"Impart crystal wish failed: user_id={player_id}, error={e}")
        return jsonify({
            "success": False,
            "ok": False,
            "error": "\u4f20\u627f\u7948\u613f\u5931\u8d25",
            "message": "\u4f20\u627f\u7948\u613f\u5931\u8d25"
        })

    if isinstance(result, dict):
        result.setdefault("success", bool(result.get("ok", True)))
        if not result.get("success"):
            result.setdefault("error", result.get("message") or "\u4f20\u627f\u7948\u613f\u5931\u8d25")
        elif result.get("success"):
            card_counts = result.get("card_counts") or {}
            new_cards = result.get("new_cards") or []
            draw_slots = result.get("draw_slots") or []

            if draw_slots:
                result["draw_results"] = []
                for slot in draw_slots:
                    if not slot.get("hit"):
                        result["draw_results"].append(
                            {
                                "empty": True,
                                "name": "未获得",
                                "rarity": "blue",
                                "is_new": False,
                                "effect": "",
                                "current_count": 0,
                                "stars": "",
                                "guaranteed": False,
                            }
                        )
                        continue

                    card_name = slot.get("name")
                    count = int(card_counts.get(card_name, 0) or 0)
                    detail = get_impart_card_display_info(card_name, count)
                    result["draw_results"].append(
                        {
                            "empty": False,
                            "name": card_name,
                            "rarity": detail["rarity"],
                            "is_new": card_name in new_cards,
                            "effect": detail["effect"],
                            "current_count": detail["current_count"],
                            "stars": detail["stars"],
                            "guaranteed": bool(slot.get("guaranteed")),
                        }
                    )
            else:
                drawn_cards = result.get("drawn_cards", [])
                result["draw_results"] = [
                    {
                        "name": card_name,
                        "rarity": detail["rarity"],
                        "is_new": card_name in new_cards,
                        "effect": detail["effect"],
                        "current_count": detail["current_count"],
                        "stars": detail["stars"],
                    }
                    for card_name in drawn_cards
                    for count in [int(card_counts.get(card_name, 0) or 0)]
                    for detail in [get_impart_card_display_info(card_name, count)]
                ]
    else:
        result = {
            "success": False,
            "ok": False,
            "error": "\u4f20\u627f\u7948\u613f\u5931\u8d25",
            "message": "\u4f20\u627f\u7948\u613f\u5931\u8d25"
        }

    return jsonify(result)


@app.route('/game/api/impart/cards', methods=['GET'])
@game_login_required
def game_api_impart_cards():
    player_id = _current_player_id()
    card_dict = impart_data_json.data_person_list(player_id) or {}
    cards = []

    for card_name, count in sorted(card_dict.items(), key=lambda x: (-int(x[1] or 0), x[0])):
        card_count = int(count or 0)
        detail = get_impart_card_display_info(card_name, card_count)
        cards.append({
            "name": card_name,
            "rarity": detail.get("rarity", "blue"),
            "effect": detail.get("effect", "效果未知"),
            "current_count": int(detail.get("current_count", card_count) or 0),
            "stars": detail.get("stars", ""),
        })

    return _ok(cards=cards)

@app.route('/game/api/shop')
@game_login_required
def game_api_shop():
    # 商城一期：先展示部分可售道具（只读）
    sample_ids = [1999, 2500, 4001, 4002, 6001]
    goods = []
    for gid in sample_ids:
        try:
            item = items.get_data_by_item_id(gid)
            if item:
                goods.append({
                    "id": gid,
                    "name": item.get("name", f"物品{gid}"),
                    "type": item.get("type", "未知"),
                    "level": item.get("level", "凡品"),
                    "desc": item.get("desc", "暂无描述"),
                    "price": 1000,
                })
        except Exception:
            continue
    return _ok(shop={
        "message": "商城购买流程开发中，当前展示商品清单。",
        "goods": goods,
    })


@app.route('/game/api/shop/buy', methods=['POST'])
@game_login_required
def game_api_shop_buy():
    player_id = _current_player_id()
    if not player_id:
        return _err("未登录", status_code=401, login_required=True)

    payload = request.get_json(silent=True) or {}
    item_id_raw = payload.get('item_id')
    quantity_raw = payload.get('quantity', 1)

    if not isinstance(item_id_raw, int):
        return _err("item_id 必须是整数")
    if not isinstance(quantity_raw, int):
        return _err("quantity 必须是整数")
    if quantity_raw < 1 or quantity_raw > 99:
        return _err("quantity 需在 1~99 之间")

    sample_ids = [1999, 2500, 4001, 4002, 6001]
    if item_id_raw not in sample_ids:
        return _err("该物品不在当前商城可购买范围")

    item_info = _serialize_item(item_id_raw)
    goods_name = item_info.get('name') or f"物品{item_id_raw}"
    goods_type = item_info.get('type') or "未知"

    price = 1000
    total_cost = price * quantity_raw

    user_rows = execute_sql(DATABASE, "SELECT stone FROM user_xiuxian WHERE user_id = ?", (player_id,))
    if isinstance(user_rows, dict) and user_rows.get("error"):
        return _err("购买失败，无法读取用户信息")
    if not user_rows:
        return _err("未找到角色信息")
    current_stone = int((user_rows[0] or {}).get("stone") or 0)
    if current_stone < total_cost:
        max_qty = current_stone // price
        return _err(f"灵石不足！需要 {total_cost} 灵石，当前持有 {current_stone} 灵石，最多可购买 {max_qty} 个")

    deduct_res = execute_sql(
        DATABASE,
        "UPDATE user_xiuxian SET stone = stone - ? WHERE user_id = ? AND stone >= ?",
        (total_cost, player_id, total_cost)
    )
    if isinstance(deduct_res, dict) and deduct_res.get("error"):
        return _err("灵石不足或购买失败")
    if not isinstance(deduct_res, dict) or int(deduct_res.get("affected_rows") or 0) <= 0:
        return _err("灵石不足或购买失败")

    try:
        game_sql.send_back(player_id, item_id_raw, goods_name, goods_type, quantity_raw)
    except Exception:
        # 回滚灵石，避免出现扣费成功但发货失败
        execute_sql(
            DATABASE,
            "UPDATE user_xiuxian SET stone = stone + ? WHERE user_id = ?",
            (total_cost, player_id)
        )
        return _err("购买失败，物品发放异常")

    left_rows = execute_sql(DATABASE, "SELECT stone FROM user_xiuxian WHERE user_id = ?", (player_id,))
    stone_left = int((left_rows[0] or {}).get("stone") or 0) if isinstance(left_rows, list) and left_rows else max(current_stone - total_cost, 0)

    return _ok(
        message=f"购买成功：{goods_name} x{quantity_raw}",
        cost=total_cost,
        stone_left=stone_left,
        item=_serialize_item(item_id_raw)
    )


@app.route('/game/api/work/status')
@game_login_required
def game_api_work_status():
    player_id = _current_player_id()
    status, work_data = _get_player_work_status(player_id)
    return _ok(work=_serialize_work(status, work_data, player_id))


@app.route('/game/api/daily/status')
@game_login_required
def game_api_daily_status():
    daily_limit = 7
    reward_win = 20
    reward_lose = 10
    try:
        player_id = _current_player_id()
        user_data = impart_pk.find_user_data(player_id) or {}
        remaining = int(user_data.get("pk_num") or 0)
        used = max(daily_limit - remaining, 0)
        completed = remaining <= 0
        return _ok(impart_pk={
            "enabled": True,
            "daily_limit": daily_limit,
            "used": used,
            "remaining": remaining,
            "completed": completed,
            "reward_win": reward_win,
            "reward_lose": reward_lose,
            "message": "今日虚神界对决已完成" if completed else "今日虚神界对决还未完成"
        })
    except Exception:
        return _ok(impart_pk={
            "enabled": False,
            "daily_limit": daily_limit,
            "used": 0,
            "remaining": 0,
            "completed": True,
            "reward_win": reward_win,
            "reward_lose": reward_lose,
            "message": "暂时无法读取虚神界对决状态"
        })


@app.route('/game/api/impart/pk/challenge', methods=['POST'])
@game_login_required
def game_api_impart_pk_challenge():
    player_id = _current_player_id()
    if not player_id:
        return _err("未登录", status_code=401, login_required=True)

    daily_limit = 7

    # 统一走新虚神界对决的体力规则：校验 -> 扣 3 体力 -> 实际对决（单机器人/1 次失败）
    validation = _ws_validate_challenge(player_id, None, 1)
    if not validation.get('success'):
        pk_num_left = int((impart_pk.find_user_data(player_id) or {}).get("pk_num") or 0)
        if pk_num_left <= 0:
            return _ok(
                message="今日虚神界对决次数已用尽",
                result="none",
                logs=[],
                stones_gained=0,
                remaining=0,
                daily_limit=daily_limit,
            )
        return _ok(
            message=validation.get('message') or "暂时无法进行虚神界对决",
            result="none",
            logs=[],
            stones_gained=0,
            remaining=pk_num_left,
            daily_limit=daily_limit,
        )

    ok, msg = _consume_stamina(player_id, 3)
    if not ok:
        return _ok(
            message=msg,
            result="none",
            logs=[],
            stones_gained=0,
            remaining=int((impart_pk.find_user_data(player_id) or {}).get("pk_num") or 0),
            daily_limit=daily_limit,
        )

    try:
        result = _ws_challenge(player_id, None, 1)
    except Exception as e:
        logger.exception(f"虚神界对决执行异常: {e}")
        return _err("虚神界对决失败，请稍后重试")

    if not result.get('success'):
        return _ok(
            message=result.get('message') or "暂时无法进行虚神界对决",
            result="none",
            logs=[],
            stones_gained=0,
            remaining=int((impart_pk.find_user_data(player_id) or {}).get("pk_num") or 0),
            daily_limit=daily_limit,
        )

    battles = result.get('battles') or []
    last = battles[-1] if battles else {}
    result_str = "none"
    stones = 0
    logs = []
    for b in battles:
        stones += int(b.get('stones_gained') or 0)
        for line in (b.get('logs') or []):
            logs.append(line)
    first_res = battles[0].get('result') if battles else None
    if first_res in ("win", "lose"):
        result_str = first_res
    message = result.get('message') or (last.get('summary') or "对决结束")
    return _ok(
        message=message,
        result=result_str,
        logs=logs,
        stones_gained=stones,
        remaining=int((impart_pk.find_user_data(player_id) or {}).get("pk_num") or 0),
        daily_limit=daily_limit,
    )


# =========================
# 虚神界 Web API（对齐 QQ 端 xiuxian_impart_pk，全部复用其数据/计算）
# =========================

@app.route('/game/api/impart/world/status')
@game_login_required
def game_api_impart_world_status():
    player_id = _current_player_id()
    try:
        return _ok(world=_ws_world_status(player_id))
    except Exception as e:
        logger.error(f"虚神界状态读取失败: {e}")
        return _err("虚神界状态读取失败，请稍后重试")


@app.route('/game/api/impart/world/project', methods=['POST'])
@game_login_required
def game_api_impart_world_project():
    player_id = _current_player_id()
    try:
        result = _ws_project(player_id)
    except Exception as e:
        logger.error(f"虚神界投影失败: {e}")
        return _err("虚神界投影失败，请稍后重试")

    # QQ matcher Cooldown(stamina_cost=1)：仅在实际投影成功后扣除 1 体力，
    # 失败场景（已投影/次数用尽等）不误扣体力。
    if result.get('success'):
        ok, msg = _consume_stamina(player_id, 1)
        if not ok:
            _safe_undo_project(player_id)
            return _err(msg)
    return _ok(result=result, message=result.get('message') or '')


@app.route('/game/api/impart/world/projections')
@game_login_required
def game_api_impart_world_projections():
    player_id = _current_player_id()
    try:
        return _ok(projections=_ws_projections(player_id))
    except Exception as e:
        logger.error(f"虚神界投影列表读取失败: {e}")
        return _err("虚神界投影列表读取失败，请稍后重试")


@app.route('/game/api/impart/world/rankings')
@game_login_required
def game_api_impart_world_rankings():
    try:
        return _ok(rankings=_ws_rankings())
    except Exception as e:
        logger.error(f"虚神界排行榜读取失败: {e}")
        return _err("虚神界排行榜读取失败，请稍后重试")


@app.route('/game/api/impart/world/challenge', methods=['POST'])
@game_login_required
def game_api_impart_world_challenge():
    player_id = _current_player_id()
    payload = request.get_json(silent=True) or {}
    target_number = payload.get('target_number')
    max_losses = payload.get('max_losses', 1)
    if target_number in (None, ''):
        target_number = None

    # 1) 无副作用的规则校验；失败直接返回，不扣体力
    validation = _ws_validate_challenge(player_id, target_number=target_number,
                                        max_loss_count=max_losses)
    if not validation.get('success'):
        return _err(validation.get('message') or '虚神界对决条件不满足')

    max_losses = validation.get('max_loss_count', max_losses)

    # 2) 先扣体力，体力不足直接失败，绝不调用 _ws_challenge
    ok, ok_msg = _consume_stamina(player_id, 3)
    if not ok:
        return _err(ok_msg)

    # 3) 体力已扣，执行实际对决；异常时若无法确认是否已产生副作用，
    #    不回滚体力，记录并返回通用错误，避免被利用造成账目不一致。
    try:
        result = _ws_challenge(player_id, target_number=target_number,
                               max_loss_count=max_losses)
    except Exception as e:
        logger.exception(f"虚神界对决执行异常: {e}")
        return _err("虚神界对决失败，请稍后重试")

    if not result.get('success'):
        # 已预验证，正常不应走到这里；若确为校验类失败则退还体力，其余保守处理
        if result.get('message') and _ws_validate_challenge(
                player_id, target_number=target_number,
                max_loss_count=max_losses).get('success') is False:
            _restore_stamina(player_id, 3)
        return _err(result.get('message') or '虚神界对决失败')
    return _ok(message=result.get('message') or '', result=result,
               profile=_build_player_profile(player_id))


@app.route('/game/api/impart/world/train', methods=['POST'])
@game_login_required
def game_api_impart_world_train():
    player_id = _current_player_id()
    payload = request.get_json(silent=True) or {}
    try:
        minutes = int(payload.get('minutes') or 0)
    except (TypeError, ValueError):
        minutes = 0
    if minutes <= 0:
        return _err("请输入正整数修炼分钟数")
    try:
        result = _ws_train(player_id, minutes)
    except Exception as e:
        logger.error(f"虚神界修炼失败: {e}")
        return _err("虚神界修炼失败，请稍后重试")
    if not result.get('success'):
        return _err(result.get('message') or '虚神界修炼失败')
    return _ok(message=result.get('message') or '', result=result,
               profile=_build_player_profile(player_id))


@app.route('/game/api/impart/world/explore', methods=['POST'])
@game_login_required
def game_api_impart_world_explore():
    player_id = _current_player_id()
    try:
        result = _ws_explore(player_id)
    except Exception as e:
        logger.error(f"虚神界探索失败: {e}")
        return _err("虚神界探索失败，请稍后重试")
    if not result.get('success'):
        return _ok(result=result, message=result.get('message') or '')
    return _ok(result=result, message=result.get('message') or '',
               profile=_build_player_profile(player_id))


@app.route('/game/api/impart/world/retreat/start', methods=['POST'])
@game_login_required
def game_api_impart_world_retreat_start():
    player_id = _current_player_id()
    try:
        result = _ws_retreat_start(player_id)
    except Exception as e:
        logger.error(f"虚神界闭关失败: {e}")
        return _err("虚神界闭关失败，请稍后重试")
    if not result.get('success'):
        return _err(result.get('message') or '虚神界闭关失败')
    return _ok(message=result.get('message') or '')


@app.route('/game/api/impart/world/retreat/finish', methods=['POST'])
@game_login_required
def game_api_impart_world_retreat_finish():
    player_id = _current_player_id()
    try:
        result = _ws_retreat_finish(player_id)
    except Exception as e:
        logger.error(f"虚神界出关失败: {e}")
        return _err("虚神界出关失败，请稍后重试")
    if not result.get('success'):
        return _err(result.get('message') or '虚神界出关失败')
    return _ok(message=result.get('message') or '',
               profile=_build_player_profile(player_id))


def _safe_undo_project(user_id):
    """投影成功后体力扣减失败时回滚投影，避免用户被计入自界却未扣体力。"""
    try:
        if xu_world.check_xu_world_user_id(user_id):
            xu_world.del_xu_world(user_id)
    except Exception:
        pass


# =========================
# 轮回 / 转生 Web API（对齐 QQ 端 xiuxian_lunhui）
# =========================

@app.route('/game/api/reincarnation/status')
@game_login_required
def game_api_reincarnation_status():
    player_id = _current_player_id()
    try:
        return _ok(reincarnation=_lh_status(player_id))
    except Exception as e:
        logger.error(f"轮回状态读取失败: {e}")
        return _err("轮回状态读取失败，请稍后重试")


@app.route('/game/api/reincarnation/advance', methods=['POST'])
@game_login_required
def game_api_reincarnation_advance():
    player_id = _current_player_id()
    payload = request.get_json(silent=True) or {}
    confirm = payload.get('confirm')
    if confirm != '确认轮回':
        return _err("请在二次确认后再次提交，确认文本为【确认轮回】", need_confirm=True)
    try:
        result = _lh_advance(player_id, confirm=True)
    except Exception as e:
        logger.error(f"进入轮回失败: {e}")
        return _err("进入轮回失败，请稍后重试")
    if not result.get('success'):
        return _err(result.get('message') or '无法进入轮回')
    return _ok(message=result.get('message') or '', result=result,
               profile=_build_player_profile(player_id))


@app.route('/game/api/reincarnation/infinite', methods=['POST'])
@game_login_required
def game_api_reincarnation_infinite():
    player_id = _current_player_id()
    payload = request.get_json(silent=True) or {}
    confirm = payload.get('confirm')
    if confirm != '确认无限轮回':
        return _err("请在二次确认后再次提交，确认文本为【确认无限轮回】", need_confirm=True)
    try:
        result = _lh_infinite(player_id, confirm=True)
    except Exception as e:
        logger.error(f"无限轮回失败: {e}")
        return _err("无限轮回失败，请稍后重试")
    if not result.get('success'):
        return _err(result.get('message') or '无法进入无限轮回')
    return _ok(message=result.get('message') or '', result=result,
               profile=_build_player_profile(player_id))


@app.route('/game/api/reincarnation/reset-cultivation', methods=['POST'])
@game_login_required
def game_api_reincarnation_reset_cultivation():
    player_id = _current_player_id()
    payload = request.get_json(silent=True) or {}
    confirm = payload.get('confirm')
    if confirm != '确认自废修为':
        return _err("请在二次确认后再次提交，确认文本为【确认自废修为】", need_confirm=True)
    try:
        result = _lh_reset_cultivation(player_id, confirm=True)
    except Exception as e:
        logger.error(f"自废修为失败: {e}")
        return _err("自废修为失败，请稍后重试")
    if not result.get('success'):
        return _err(result.get('message') or '无法自废修为')
    return _ok(message=result.get('message') or '', result=result,
               profile=_build_player_profile(player_id))


@app.route('/game/api/reincarnation/rankings')
@game_login_required
def game_api_reincarnation_rankings():
    try:
        return _ok(rankings=_lh_rankings())
    except Exception as e:
        logger.error(f"轮回排行榜读取失败: {e}")
        return _err("轮回排行榜读取失败，请稍后重试")


@app.route('/game/api/work/refresh', methods=['POST'])
@game_login_required
def game_api_work_refresh():
    player_id = _current_player_id()
    force = bool((request.get_json(silent=True) or {}).get('force'))
    is_type, msg = check_user_type(player_id, 0)
    if not is_type:
        return _err(msg or "当前状态无法刷新悬赏")

    status, work_data = _get_player_work_status(player_id)
    if status in (1, 2):
        return _ok(work=_serialize_work(status, work_data, player_id), message="已有进行中或可结算的悬赏")
    if status == 3 and not force:
        return _ok(work=_serialize_work(status, work_data, player_id), need_confirm=True, message="已有未接取悬赏，确认后会覆盖当前悬赏令")

    user = game_sql.get_user_info_with_id(player_id)
    refresh_left = game_sql.get_work_num(player_id)
    if refresh_left <= 0:
        return _err("今日悬赏令刷新次数已用尽")
    ok, msg = _consume_stamina(player_id, 1)
    if not ok:
        return _err(msg)
    if force:
        delete_work_file(player_id)
    workhandle().do_work(0, level=user.get('level'), exp=user.get('exp'), user_id=player_id)
    game_sql.update_work_num(player_id, refresh_left - 1)
    status, work_data = _get_player_work_status(player_id)
    return _ok(work=_serialize_work(status, work_data, player_id), message="悬赏令已刷新")


@app.route('/game/api/work/accept', methods=['POST'])
@game_login_required
def game_api_work_accept():
    player_id = _current_player_id()
    payload = request.get_json(silent=True) or {}
    try:
        index = int(payload.get('index'))
    except Exception:
        return _err("请选择正确的悬赏编号")

    is_type, msg = check_user_type(player_id, 0)
    if not is_type:
        return _err(msg or "当前状态无法接取悬赏")

    status, work_data = _get_player_work_status(player_id)
    if status != 3 or not work_data:
        return _err("没有可接取的悬赏令")
    tasks = list((work_data.get('tasks') or {}).items())
    if index < 1 or index > len(tasks):
        return _err("悬赏编号不存在")
    ok, msg = _consume_stamina(player_id, 1)
    if not ok:
        return _err(msg)
    task_name, _ = tasks[index - 1]
    game_sql.do_work(player_id, 2, task_name)
    work_data['status'] = 2
    save_work_file(player_id, work_data)
    status, work_data = _get_player_work_status(player_id)
    return _ok(work=_serialize_work(status, work_data, player_id), message=f"已接取悬赏【{task_name}】")


@app.route('/game/api/work/settle', methods=['POST'])
@game_login_required
def game_api_work_settle():
    player_id = _current_player_id()
    is_type, msg = check_user_type(player_id, 2)
    if not is_type:
        return _err(msg or "当前没有可结算悬赏")
    status, work_data = _get_player_work_status(player_id)
    if status == 1:
        return _ok(work=_serialize_work(status, work_data, player_id), message="悬赏仍在进行中")
    if status != 2 or not work_data:
        return _err("没有可结算的悬赏令")
    ok, msg = _consume_stamina(player_id, 1)
    if not ok:
        return _err(msg)
    reward, error = _settle_work_for_web(player_id, work_data)
    if error:
        return _err(error)
    status, work_data = _get_player_work_status(player_id)
    return _ok(reward=reward, work=_serialize_work(status, work_data, player_id), profile=_build_player_profile(player_id))


@app.route('/game/api/work/reset', methods=['POST'])
@game_login_required
def game_api_work_reset():
    player_id = _current_player_id()
    delete_work_file(player_id)
    user_cd = game_sql.get_user_cd(player_id)
    if user_cd and user_cd.get('type') == 2:
        game_sql.do_work(player_id, 0)
    status, work_data = _get_player_work_status(player_id)
    return _ok(work=_serialize_work(status, work_data, player_id), message="悬赏令已重置")


# =========================
# 闭关系统 API
# =========================

@app.route('/game/api/retreat/status')
@game_login_required
def game_api_retreat_status():
    player_id = _current_player_id()
    user_cd = game_sql.get_user_cd(player_id)
    in_retreat = bool(user_cd and user_cd.get('type') == 1)
    
    if not in_retreat:
        return _ok(retreat={"in_retreat": False})
    
    user_info = game_sql.get_user_info_with_id(player_id)
    level = user_info['level']
    
    # 计算当前收益
    now_time = datetime.now()
    in_closing_time = _parse_datetime(user_cd['create_time'])
    if not in_closing_time:
        return _err("闭关数据异常")
        
    exp_time = int((now_time - in_closing_time).total_seconds() // 60)
    
    # 逻辑参考 xiuxian_buff
    level_rate = game_sql.get_root_rate(user_info['root_type'], player_id)
    realm_rate = jsondata.level_data()[level]["spend"]
    user_buff_data = UserBuffDate(player_id)
    user_blessed_spot_data = user_buff_data.BuffInfo['blessed_spot'] * 0.5
    mainbuffdata = user_buff_data.get_user_main_buff_data()
    
    mainbuffratebuff = mainbuffdata['ratebuff'] if mainbuffdata else 0
    mainbuffcloexp = mainbuffdata['clo_exp'] if mainbuffdata else 0
    
    # 计算效率
    efficiency = (level_rate * realm_rate * (1 + mainbuffratebuff) * (1 + mainbuffcloexp) * (1 + user_blessed_spot_data))
    exp_per_min = XiuConfig().closing_exp * efficiency
    current_exp = int(exp_time * exp_per_min)
    
    # 上限检查
    max_exp_limit = int(OtherSet().set_closing_type(level)) * XiuConfig().closing_exp_upper_limit
    user_get_exp_max = max(0, int(max_exp_limit) - int(user_info['exp']))
    
    return _ok(retreat={
        "in_retreat": True,
        "start_time": user_cd['create_time'],
        "elapsed_minutes": exp_time,
        "exp_per_min": round(exp_per_min, 2),
        "current_exp": current_exp,
        "max_exp": user_get_exp_max,
        "is_max": current_exp >= user_get_exp_max and user_get_exp_max > 0
    })

@app.route('/game/api/retreat/start', methods=['POST'])
@game_login_required
def game_api_retreat_start():
    player_id = _current_player_id()
    user_info = game_sql.get_user_info_with_id(player_id)
    
    if user_info['root_type'] == '伪灵根':
        return _err("凡人无法闭关！")
        
    is_type, msg = check_user_type(player_id, 0)
    if not is_type:
        return _err(msg or "当前状态无法开始闭关")
        
    game_sql.in_closing(player_id, 1)
    return _ok(message="已进入闭关状态，如需出关请点击结算。")

@app.route('/game/api/retreat/stop', methods=['POST'])
@game_login_required
def game_api_retreat_stop():
    player_id = _current_player_id()
    payload = request.get_json(silent=True) or {}
    use_stone = bool(payload.get('use_stone'))
    
    is_type, msg = check_user_type(player_id, 1)
    if not is_type:
        return _err(msg or "当前不在闭关状态")
        
    user_info = game_sql.get_user_info_with_id(player_id)
    user_cd = game_sql.get_user_cd(player_id)
    level = user_info['level']
    use_exp = user_info['exp']
    
    now_time = datetime.now()
    in_closing_time = _parse_datetime(user_cd['create_time'])
    exp_time = int((now_time - in_closing_time).total_seconds() // 60)
    
    # 收益计算逻辑 (完全复刻 xiuxian_buff)
    level_rate = game_sql.get_root_rate(user_info['root_type'], player_id)
    realm_rate = jsondata.level_data()[level]["spend"]
    user_buff_data = UserBuffDate(player_id)
    user_blessed_spot_data = user_buff_data.BuffInfo['blessed_spot'] * 0.5
    mainbuffdata = user_buff_data.get_user_main_buff_data()
    mainbuffratebuff = mainbuffdata['ratebuff'] if mainbuffdata else 0
    mainbuffcloexp = mainbuffdata['clo_exp'] if mainbuffdata else 0
    
    exp = int(
        (exp_time * XiuConfig().closing_exp) * 
        ((level_rate * realm_rate * (1 + mainbuffratebuff) * (1 + mainbuffcloexp) * (1 + user_blessed_spot_data)))
    )
    
    max_exp_limit = int(OtherSet().set_closing_type(level)) * XiuConfig().closing_exp_upper_limit
    user_get_exp_max = max(0, int(max_exp_limit) - int(use_exp))
    
    final_exp = exp
    stone_consumed = 0
    
    if final_exp >= user_get_exp_max and user_get_exp_max > 0:
        final_exp = user_get_exp_max
        msg = f"闭关结束，本次闭关到达上限，共增加修为：{number_to(final_exp)}"
    else:
        if use_stone:
            user_stone = user_info['stone']
            if user_stone <= 0:
                msg = f"灵石不足，无法加速。本次闭关增加修为：{number_to(final_exp)}"
            elif final_exp <= user_stone:
                stone_consumed = final_exp
                final_exp = final_exp * 2
                game_sql.update_ls(player_id, stone_consumed, 2)
                msg = f"闭关结束，消耗 {number_to(stone_consumed)} 灵石加速，增加修为：{number_to(final_exp)}"
            else:
                stone_consumed = user_stone
                final_exp = final_exp + stone_consumed
                game_sql.update_ls(player_id, stone_consumed, 2)
                msg = f"闭关结束，消耗全部 {number_to(stone_consumed)} 灵石加速，增加修为：{number_to(final_exp)}"
        else:
            msg = f"闭关结束，共增加修为：{number_to(final_exp)}"

    # 更新数据
    game_sql.in_closing(player_id, 0)
    game_sql.update_exp(player_id, final_exp)
    game_sql.update_power2(player_id)
    
    # 状态恢复
    result_msg, result_hp_mp = OtherSet().send_hp_mp(player_id, int(use_exp / 10 * exp_time), int(use_exp / 20 * exp_time))
    game_sql.update_user_attribute(player_id, result_hp_mp[0], result_hp_mp[1], int(result_hp_mp[2] / 10))
    update_statistics_value(player_id, "闭关时长", increment=exp_time)
    
    return _ok(message=msg + result_msg[0] + result_msg[1], profile=_build_player_profile(player_id))


# =========================
# 突破系统 API
# =========================

@app.route('/game/api/breakthrough/status')
@game_login_required
def game_api_breakthrough_status():
    player_id = _current_player_id()
    user_info = game_sql.get_user_info_with_id(player_id)
    if not user_info:
        return _err("角色不存在")

    level_name = user_info['level']
    levels = convert_rank('江湖好手')[1]
    now_index = levels.index(level_name)
    
    if now_index >= len(levels) - 1:
        return _ok(can_breakthrough=False, reason="已达到最高境界")

    next_level = levels[now_index + 1]
    need_exp = game_sql.get_level_power(next_level)
    user_exp = user_info['exp']
    
    # 检查是否需要渡劫
    is_tribulation = level_name.endswith('圆满') and now_index >= levels.index(XiuConfig().tribulation_min_level)
    
    # 检查CD
    cd_status = {"ready": True, "remaining_minutes": 0}
    level_cd = user_info.get('level_up_cd')
    if level_cd:
        time_now = datetime.now()
        cd_seconds = OtherSet().date_diff(time_now, level_cd)
        limit_seconds = XiuConfig().level_up_cd * 60
        if cd_seconds < limit_seconds:
            cd_status = {
                "ready": False,
                "remaining_minutes": int((limit_seconds - cd_seconds) // 60) + 1
            }

    # 概率计算
    base_rate = jsondata.level_rate_data().get(level_name, 0)
    bonus_rate = int(user_info.get('level_up_rate') or 0)
    main_rate_buff = UserBuffDate(player_id).get_user_main_buff_data()
    buff_rate = main_rate_buff['number'] if main_rate_buff else 0
    total_rate = base_rate + bonus_rate + buff_rate

    # 检查丹药
    pills = {
        "dr": 0,   # 渡厄丹 1999
        "drjd": 0  # 渡厄金丹 1998
    }
    user_backs = game_sql.get_back_msg(player_id) or []
    for back in user_backs:
        gid = int(back.get('goods_id') or 0)
        if gid == 1999: pills["dr"] = back.get('goods_num') or 0
        elif gid == 1998: pills["drjd"] = back.get('goods_num') or 0

    return _ok(
        current_level=level_name,
        next_level=next_level,
        user_exp=user_exp,
        need_exp=need_exp,
        is_tribulation=is_tribulation,
        cd_status=cd_status,
        rates={
            "base": base_rate,
            "bonus": bonus_rate,
            "buff": buff_rate,
            "total": min(total_rate, 100)
        },
        pills=pills,
        can_breakthrough=(user_exp >= need_exp and cd_status["ready"] and not is_tribulation)
    )


@app.route('/game/api/breakthrough/perform', methods=['POST'])
@game_login_required
def game_api_breakthrough_perform():
    player_id = _current_player_id()
    data = request.json or {}
    mode = data.get('mode', 'direct') # direct, dr, drjd
    
    user_info = game_sql.get_user_info_with_id(player_id)
    if not user_info: return _err("角色不存在")
    
    # 基本检查
    level_name = user_info['level']
    levels = convert_rank('江湖好手')[1]
    now_index = levels.index(level_name)
    if now_index >= len(levels) - 1: return _err("已达到最高境界")
    
    next_level = levels[now_index + 1]
    need_exp = game_sql.get_level_power(next_level)
    user_exp = user_info['exp']
    if user_exp < need_exp: return _err("修为不足")
    
    level_cd = user_info.get('level_up_cd')
    if level_cd:
        time_now = datetime.now()
        cd_seconds = OtherSet().date_diff(time_now, level_cd)
        if cd_seconds < XiuConfig().level_up_cd * 60:
            return _err("突破冷却中")
            
    if level_name.endswith('圆满') and now_index >= levels.index(XiuConfig().tribulation_min_level):
        return _err("当前境界需要渡劫，Web版暂不支持渡劫，请使用机器人指令")

    # 检查丹药
    if mode == 'dr':
        back = execute_sql(DATABASE, "SELECT goods_num FROM back WHERE user_id=? AND goods_id=1999", (player_id,))
        if not back or back[0].get('goods_num', 0) <= 0:
            return _err("背包中没有渡厄丹")
    elif mode == 'drjd':
        back = execute_sql(DATABASE, "SELECT goods_num FROM back WHERE user_id=? AND goods_id=1998", (player_id,))
        if not back or back[0].get('goods_num', 0) <= 0:
            return _err("背包中没有渡厄金丹")

    # 概率计算
    base_rate = jsondata.level_rate_data().get(level_name, 0)
    bonus_rate = int(user_info.get('level_up_rate') or 0)
    main_buff = UserBuffDate(player_id).get_user_main_buff_data()
    buff_rate = main_buff['number'] if main_buff else 0
    total_rate = base_rate + bonus_rate + buff_rate
    
    # 随机结果
    is_success = random.randint(0, 100) < total_rate
    
    if is_success:
        # 成功逻辑
        game_sql.updata_level(player_id, next_level)
        game_sql.update_power2(player_id)
        game_sql.updata_level_cd(player_id)
        game_sql.update_levelrate(player_id, 0)
        game_sql.update_user_hp(player_id)
        update_statistics_value(player_id, "突破成功")
        
        gain_exp = 0
        if mode == 'drjd':
            gain_exp = int(user_exp * 0.1)
            game_sql.update_exp(player_id, gain_exp)
            game_sql.update_back_j(player_id, 1998, use_key=1)
            msg = f"恭喜道友突破至 {next_level} 成功！使用了渡厄金丹，修为增加了一成！"
        else:
            msg = f"恭喜道友突破至 {next_level} 成功！"
            
        return _ok(success=True, message=msg, new_level=next_level, gain_exp=gain_exp)
    else:
        # 失败逻辑
        game_sql.updata_level_cd(player_id)
        update_rate = max(1, int(base_rate * XiuConfig().level_up_probability))
        game_sql.update_levelrate(player_id, bonus_rate + update_rate)
        update_statistics_value(player_id, "突破失败")
        
        lost_exp = 0
        if mode == 'dr':
            game_sql.update_back_j(player_id, 1999, use_key=1)
            msg = f"突破失败！幸好有渡厄丹护持，未损修为。下次成功率增加 {update_rate}%。"
        elif mode == 'drjd':
            game_sql.update_back_j(player_id, 1998, use_key=1)
            gain_exp = int(user_exp * 0.1)
            game_sql.update_exp(player_id, gain_exp)
            msg = f"突破失败！使用了渡厄金丹，修为增加了一成，下次成功率增加 {update_rate}%。"
        else:
            percentage = random.randint(XiuConfig().level_punishment_floor, XiuConfig().level_punishment_limit)
            exp_buff = main_buff['exp_buff'] if main_buff else 0
            lost_exp = int(user_exp * (percentage / 100) * (1 - exp_buff))
            game_sql.update_j_exp(player_id, lost_exp)
            
            now_hp = max(1, (user_info.get('hp') or 100) - (lost_exp / 2))
            now_mp = max(1, (user_info.get('mp') or 100) - lost_exp)
            game_sql.update_user_hp_mp(player_id, now_hp, now_mp)
            
            msg = f"突破失败！境界受损，修为减少了 {number_to(lost_exp)}。下次成功率增加 {update_rate}%。"
            
        return _ok(success=False, message=msg, lost_exp=lost_exp, bonus_rate=update_rate)


@app.route('/game/api/battle/scarecrow', methods=['POST'])
@game_login_required
def game_api_battle_scarecrow():
    player_id = _current_player_id()
    user = game_sql.get_user_info_with_id(player_id)
    if not user:
        return _err("角色不存在", 404)
    if not user.get('hp'):
        game_sql.update_user_hp(player_id)
        user = game_sql.get_user_info_with_id(player_id)

    scarecrow_hp = max(int(user.get('exp') or 100) * 2, 1000)
    scarecrow = {
        "name": "稻草人",
        "气血": scarecrow_hp,
        "攻击": 0,
        "真元": 0,
        "会心": 0,
        "jj": user.get('level') or "江湖好手",
        "is_scarecrow": True,
    }
    play_list, winner, _ = _run_async(Boss_fight(player_id, scarecrow, type_in=1, bot_id=0))
    events = _normalize_battle_nodes(play_list, player_id, enemy_name="稻草人", is_boss=True)
    return _ok(battle=_build_battle_payload("训练稻草人", winner, events, player_id, enemy_name="稻草人", is_boss=True))


@app.route('/game/api/battle/boss/list')
@game_login_required
def game_api_battle_boss_list():
    """获取可挑战的世界 Boss 列表"""
    player_id = _current_player_id()
    user = game_sql.get_user_info_with_id(player_id)
    if not user: return _err("角色不存在")
    
    # 获取最高境界
    level = user.get('level', '江湖好手')
    
    # 生成各境界 Boss
    bosses = create_all_bosses(level)
    
    # 转换为前端格式
    boss_list = []
    for b in bosses:
        boss_list.append({
            "name": b['name'],
            "jj": b['jj'],
            "hp": int(b['气血']),
            "hp_display": _display_number(b['气血']),
            "atk": int(b['攻击']),
            "atk_display": _display_number(b['攻击']),
            "stone": b.get('max_stone', 0),
            "stone_display": _display_number(b.get('max_stone', 0)),
            "img": f"/assets/boss/{b['name']}"
        })
    
    # 按境界排序（假设境界列表是有序的，create_all_bosses 应该已经处理好）
    return _ok(bosses=boss_list)


@app.route('/game/api/world-boss/shop')
@game_login_required
def game_api_world_boss_shop():
    """获取世界 Boss 积分商店商品与当前积分。"""
    player_id = _current_player_id()
    if not game_sql.get_user_info_with_id(player_id):
        return _err("角色不存在", 404)
    return _ok(shop=_build_world_boss_shop_payload(player_id))


@app.route('/game/api/world-boss/exchange', methods=['POST'])
@game_login_required
def game_api_world_boss_exchange():
    """兑换世界 Boss 积分商店商品。"""
    player_id = _current_player_id()
    if not game_sql.get_user_info_with_id(player_id):
        return _err("角色不存在", 404)

    payload = request.get_json(silent=True) or {}
    shop_id_raw = payload.get("shop_id", payload.get("item_id"))
    quantity_raw = payload.get("quantity", 1)

    try:
        shop_id = int(shop_id_raw)
    except (TypeError, ValueError):
        return _err("商品编号错误")

    try:
        quantity = int(quantity_raw)
    except (TypeError, ValueError):
        return _err("兑换数量错误")

    result, error = _exchange_world_boss_shop_item(player_id, shop_id, quantity)
    if error:
        return _err(error)

    shop_payload = _build_world_boss_shop_payload(player_id)
    return _ok(
        message=f"兑换成功：{result['name']} x{result['quantity']}，消耗世界积分 {result['total_cost']} 点",
        exchange=result,
        shop=shop_payload,
        backpack=_build_backpack(player_id),
    )


@app.route('/game/api/battle/boss/challenge', methods=['POST'])
@game_login_required
def game_api_battle_boss_challenge():
    """挑战指定的世界 Boss"""
    player_id = _current_player_id()
    payload = request.get_json(silent=True) or {}
    boss_name = payload.get('name')
    boss_jj = payload.get('jj')
    
    if not boss_name or not boss_jj:
        return _err("参数错误，请选择要挑战的 Boss")
        
    # 消耗体力
    boss_config = get_boss_config()
    stamina_cost = boss_config.get("讨伐世界Boss体力消耗", 10)
    ok, msg = _consume_stamina(player_id, stamina_cost)
    if not ok: return _err(msg)
    
    # 构造 Boss 数据
    boss = createboss_jj(boss_jj, boss_name)
    if not boss: return _err("Boss 构造失败")
    
    # 战斗
    play_list, winner, _ = _run_async(Boss_fight(player_id, boss, type_in=1, bot_id=0))
    events = _normalize_battle_nodes(play_list, player_id, enemy_name=boss_name, is_boss=True)

    # 世界 Boss 结算：保留原网页端胜利给灵石逻辑，并补齐世界积分持久化。
    user_info = game_sql.get_user_info_with_id(player_id) or {}
    reward = _calc_world_boss_web_reward(player_id, user_info, boss, winner, events)
    boss_limit.update_battle_count(player_id)
    reward_msg = _format_world_boss_reward_message(reward) if winner == "群友赢了" else "未击败 Boss，未获得胜利奖励"

    return _ok(
        battle=_build_battle_payload(f"挑战世界Boss：{boss_name}", winner, events, player_id, enemy_name=boss_name, is_boss=True),
        reward=reward,
        message=f"战斗结束！{reward_msg}"
    )


@app.route('/game/api/battle/player', methods=['POST'])
@game_login_required
def game_api_battle_player():
    player_id = _current_player_id()
    payload = request.get_json(silent=True) or {}
    target = str(payload.get('target', '')).strip()
    if not target:
        return _err("请输入对手 QQ 号或道号")
    target_user = get_user_by_id(target) if target.isdigit() else get_user_by_name(target)
    if not target_user:
        return _err("没有找到对手")
    target_id = int(target_user['user_id'])
    if target_id == player_id:
        return _err("不能和自己切磋")
    play_list, winner = _run_async(Player_fight(player_id, target_id, 1, 0))
    title = f"{(game_sql.get_user_info_with_id(player_id) or {}).get('user_name', player_id)} VS {target_user.get('user_name', target_id)}"
    events = _normalize_battle_nodes(play_list, player_id)
    return _ok(battle=_build_battle_payload(title, winner, events, player_id, enemy_name=target_user.get('user_name')))


# =========================
# 独立 SPA + API（骨架）
# =========================
api_v1 = Blueprint("xiuxian_api_v1", __name__, url_prefix="/api/v1")


def api_session_required(view_func):
    @wraps(view_func)
    def wrapper(*args, **kwargs):
        player_id = _current_player_id()
        if not player_id:
            return jsonify({"success": False, "error": "未登录", "code": 40101}), 401
        return view_func(*args, **kwargs)
    return wrapper


@api_v1.get("/health")
def api_v1_health():
    return jsonify({
        "success": True,
        "service": "nonebot_plugin_xiuxian_2",
        "api_version": "v1",
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    })


@api_v1.get("/auth/session")
def api_v1_auth_session():
    player_id = _current_player_id()
    if not player_id:
        return jsonify({"success": True, "logged_in": False, "player_id": None, "password_configured": False})
    return jsonify({"success": True, "logged_in": True, "player_id": player_id,
                    "password_configured": _auth_has_password(player_id)})


@api_v1.get("/auth/password")
@api_session_required
def api_v1_auth_password_status():
    player_id = _current_player_id()
    return jsonify({"success": True, "password_configured": _auth_has_password(player_id)})


@api_v1.post("/auth/password")
@api_session_required
def api_v1_auth_password_set():
    player_id = _current_player_id()
    payload = request.get_json(silent=True) or {}
    new_password = (payload.get("new_password") or "")
    current_password = (payload.get("current_password") or "")

    err = _auth_validate_password(new_password)
    if err:
        return jsonify({"success": False, "error": err, "code": 40120}), 400

    configured = _auth_has_password(player_id)
    if configured:
        # 已配置密码时，普通入口永远要求当前密码正确（无论本次经 token 还是密码登录）
        if not current_password:
            return jsonify({"success": False, "error": "请输入当前密码", "code": 40121}), 400
        if not _auth_verify_password(player_id, current_password):
            return jsonify({"success": False, "error": "当前密码错误", "code": 40122}), 400

    _auth_set_password(player_id, new_password)
    _consume_token_auth()
    return jsonify({"success": True, "message": "Web 密码已设置" if not configured else "Web 密码已更新",
                    "password_configured": True})


@api_v1.post("/auth/password/reset")
@api_session_required
def api_v1_auth_password_reset():
    # 忘记密码：必须处于 Token 登录后的短期窗口（fresh token auth）内，才可免旧密码重设
    if not _has_fresh_token_auth():
        return jsonify({"success": False, "error": "请先在 QQ 中发送【网页登录令】登录后再重设密码", "code": 40123}), 403
    player_id = _current_player_id()
    payload = request.get_json(silent=True) or {}
    new_password = (payload.get("new_password") or "")

    err = _auth_validate_password(new_password)
    if err:
        return jsonify({"success": False, "error": err, "code": 40120}), 400

    _auth_set_password(player_id, new_password)
    _consume_token_auth()
    return jsonify({"success": True, "message": "Web 密码已重设", "password_configured": True})


@api_v1.get("/player/profile")
@api_session_required
def api_v1_player_profile():
    player_id = _current_player_id()
    profile = _build_player_profile(player_id)
    if not profile:
        return jsonify({"success": False, "error": "角色不存在", "code": 40401}), 404
    return jsonify({"success": True, "profile": profile})


@api_v1.get("/rankings")
def api_v1_rankings():
    return jsonify({"success": True, "rankings": _build_rankings()})


@app.route('/spa')
@app.route('/spa/<path:_path>')
def game_spa_entry(_path=None):
    """SPA 入口路由（history fallback）。"""
    return render_template('spa_index.html')


app.register_blueprint(api_v1)

@app.route('/')
def home():
    if 'admin_id' not in session:
        return redirect(url_for('login'))
    return render_template('home.html', admin_id=session['admin_id'])

@app.route('/login')
def login():
    # 仅支持 URL 参数直接登录，不再支持表单提交
    token_arg = request.args.get('token', '').strip()
    if token_arg:
        admin_id, err = _consume_admin_token(token_arg)
        if admin_id:
            session.clear()
            session.permanent = False
            session['admin_id'] = admin_id
            return redirect(url_for('home'))
        else:
            return render_template('login.html', error=err or "登录令无效或已过期")
    
    # 直接访问 /login 时，显示引导信息
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('admin_id', None)
    return redirect(url_for('login'))

@app.route('/update')
def update():
    if 'admin_id' not in session:
        return redirect(url_for('login'))
    return render_template('update.html')

@app.route('/check_update')
def check_update():
    if 'admin_id' not in session:
        return jsonify({"success": False, "error": "未登录"})
    
    try:
        latest_release, message = update_manager.check_update()
        
        if latest_release:
            return jsonify({
                "success": True,
                "update_available": True,
                "current_version": update_manager.current_version,
                "latest_version": latest_release['tag_name'],
                "release_name": latest_release['name'],
                "published_at": latest_release['published_at'],
                "changelog": latest_release['body'],
                "message": message
            })
        else:
            return jsonify({
                "success": True,
                "update_available": False,
                "current_version": update_manager.current_version,
                "message": message
            })
            
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

@app.route('/get_releases')
def get_releases():
    if 'admin_id' not in session:
        return jsonify({"success": False, "error": "未登录"})
    
    try:
        releases = update_manager.get_latest_releases(10)
        
        return jsonify({
            "success": True,
            "releases": releases,
            "current_version": update_manager.current_version
        })
        
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

@app.route('/perform_update', methods=['POST'])
def perform_update():
    if 'admin_id' not in session:
        return jsonify({"success": False, "error": "未登录"})
    
    try:
        data = request.get_json()
        release_tag = data.get('release_tag')
        
        if not release_tag:
            return jsonify({"success": False, "error": "未指定release标签"})
        
        success, message = update_manager.perform_update_with_backup(release_tag)
        
        return jsonify({
            "success": success,
            "message": message
        })
        
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

@app.route('/get_backups')
def get_backups():
    if 'admin_id' not in session:
        return jsonify({"success": False, "error": "未登录"})
    
    try:
        backups = update_manager.get_backups()
        return jsonify({
            "success": True,
            "backups": backups
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

@app.route('/restore_backup', methods=['POST'])
def restore_backup():
    if 'admin_id' not in session:
        return jsonify({"success": False, "error": "未登录"})
    
    try:
        data = request.get_json()
        backup_filename = data.get('backup_filename')
        
        if not backup_filename:
            return jsonify({"success": False, "error": "未指定备份文件"})
        
        # 执行恢复操作
        success, message = update_manager.restore_backup(backup_filename)
        
        return jsonify({
            "success": success,
            "message": message
        })
        
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

# 配置导入导出路由
@app.route('/export_config', methods=['POST'])
def export_config():
    if 'admin_id' not in session:
        return jsonify({"success": False, "error": "未登录"})
    
    try:
        data = request.get_json()
        selected_fields = data.get('selected_fields', [])
        export_all = data.get('export_all', False)
        
        config_values = get_config_values()
        
        # 如果选择全部导出或者没有选择任何字段，则导出所有配置
        if export_all or not selected_fields:
            export_data = config_values
        else:
            # 只导出选中的字段
            export_data = {field: config_values[field] for field in selected_fields if field in config_values}
        
        # 添加元数据
        export_data['_metadata'] = {
            'backup_time': datetime.now().isoformat(),
            'backup_fields': list(export_data.keys()) if export_all else selected_fields,
            'version': update_manager.current_version
        }
        
        return jsonify({
            "success": True,
            "data": export_data,
            "filename": f"xiuxian_config_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        })
        
    except Exception as e:
        return jsonify({"success": False, "error": f"导出配置失败: {str(e)}"})

@app.route('/import_config', methods=['POST'])
def import_config():
    if 'admin_id' not in session:
        return jsonify({"success": False, "error": "未登录"})
    
    try:
        if 'config_file' not in request.files:
            return jsonify({"success": False, "error": "没有上传文件"})
        
        file = request.files['config_file']
        if file.filename == '':
            return jsonify({"success": False, "error": "没有选择文件"})
        
        if not file.filename.endswith('.json'):
            return jsonify({"success": False, "error": "只支持JSON格式文件"})
        
        # 读取并解析JSON文件
        file_content = file.read().decode('utf-8')
        config_data = json.loads(file_content)
        
        # 移除元数据字段
        if '_metadata' in config_data:
            del config_data['_metadata']
        
        return jsonify({
            "success": True,
            "data": config_data,
            "message": "配置导入成功，请点击保存按钮应用配置"
        })
        
    except json.JSONDecodeError:
        return jsonify({"success": False, "error": "文件格式错误，不是有效的JSON"})
    except Exception as e:
        return jsonify({"success": False, "error": f"导入配置失败: {str(e)}"})

@app.route('/backup_config', methods=['POST'])
def backup_config():
    if 'admin_id' not in session:
        return jsonify({"success": False, "error": "未登录"})
    
    try:
        data = request.get_json()
        selected_fields = data.get('selected_fields', [])
        backup_all = data.get('backup_all', False)
        
        config_values = get_config_values()
        
        # 如果选择全部备份或者没有选择任何字段，则备份所有配置
        if backup_all or not selected_fields:
            backup_data = config_values
        else:
            # 只备份选中的字段
            backup_data = {field: config_values[field] for field in selected_fields if field in config_values}
        
        # 创建备份目录
        backup_dir = Path() / "data" / "config_backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        
        # 生成备份文件名
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_filename = f"config_backup_{timestamp}.json"
        backup_path = backup_dir / backup_filename
        
        # 添加元数据
        backup_data['_metadata'] = {
            'backup_time': datetime.now().isoformat(),
            'backup_fields': list(backup_data.keys()) if backup_all else selected_fields,
            'version': update_manager.current_version
        }
        
        # 保存备份文件
        with open(backup_path, 'w', encoding='utf-8') as f:
            json.dump(backup_data, f, ensure_ascii=False, indent=2)
        
        return jsonify({
            "success": True,
            "message": f"配置备份成功: {backup_filename}",
            "backup_path": str(backup_path)
        })
        
    except Exception as e:
        return jsonify({"success": False, "error": f"备份配置失败: {str(e)}"})

@app.route('/get_config_backups')
def get_config_backups():
    if 'admin_id' not in session:
        return jsonify({"success": False, "error": "未登录"})
    
    try:
        backup_dir = Path() / "data" / "config_backups"
        backups = []
        
        if backup_dir.exists():
            for file in backup_dir.glob("config_backup_*.json"):
                try:
                    with open(file, 'r', encoding='utf-8') as f:
                        metadata = json.load(f).get('_metadata', {})
                    
                    backups.append({
                        'filename': file.name,
                        'path': str(file),
                        'backup_time': metadata.get('backup_time', ''),
                        'version': metadata.get('version', 'unknown'),
                        'size': file.stat().st_size,
                        'created_at': datetime.fromtimestamp(file.stat().st_ctime).isoformat()
                    })
                except:
                    continue
        
        # 按创建时间倒序排列
        backups.sort(key=lambda x: x['created_at'], reverse=True)
        return jsonify({
            "success": True,
            "backups": backups
        })
    except Exception as e:
        return jsonify({"success": False, "error": f"获取备份列表失败: {str(e)}"})

@app.route('/restore_config_backup', methods=['POST'])
def restore_config_backup():
    if 'admin_id' not in session:
        return jsonify({"success": False, "error": "未登录"})
    
    try:
        data = request.get_json()
        backup_filename = data.get('backup_filename')
        
        if not backup_filename:
            return jsonify({"success": False, "error": "未指定备份文件"})
        
        backup_path = Path() / "data" / "config_backups" / backup_filename
        
        if not backup_path.exists():
            return jsonify({"success": False, "error": f"备份文件不存在: {backup_filename}"})
        
        # 读取备份文件
        with open(backup_path, 'r', encoding='utf-8') as f:
            backup_data = json.load(f)
        
        # 保存元数据
        metadata = backup_data.get('_metadata', {})
        
        # 移除元数据字段
        if '_metadata' in backup_data:
            del backup_data['_metadata']
        
        return jsonify({
            "success": True,
            "data": backup_data,
            "metadata": metadata,
            "message": "配置恢复成功，请点击保存按钮应用配置"
        })
        
    except Exception as e:
        return jsonify({"success": False, "error": f"恢复配置失败: {str(e)}"})

@app.route('/manual_backup', methods=['POST'])
def manual_backup():
    if 'admin_id' not in session:
        return jsonify({"success": False, "error": "未登录"})
    
    try:
        # 执行插件备份
        plugin_success, plugin_result = update_manager.enhanced_backup_current_version()
        
        # 执行配置备份
        config_success, config_result = update_manager.backup_all_configs()
        
        if plugin_success and config_success:
            return jsonify({
                "success": True,
                "message": "手动备份成功完成",
                "plugin_backup": str(plugin_result) if isinstance(plugin_result, Path) else plugin_result,
                "config_backup": str(config_result) if isinstance(config_result, Path) else config_result
            })
        else:
            error_msg = []
            if not plugin_success:
                error_msg.append(f"插件备份失败: {plugin_result}")
            if not config_success:
                error_msg.append(f"配置备份失败: {config_result}")
            
            return jsonify({
                "success": False,
                "error": "; ".join(error_msg)
            })
            
    except Exception as e:
        return jsonify({"success": False, "error": f"备份过程中出现错误: {str(e)}"})

@app.route('/download_backup/<filename>')
def download_backup(filename):
    if 'admin_id' not in session:
        return redirect(url_for('login'))
    
    backup_path = Path() / "data" / "backups" / filename
    
    if not backup_path.exists():
        return "备份文件不存在", 404
    
    return send_file(
        str(backup_path.absolute()),
        as_attachment=True,
        download_name=filename,
        mimetype='application/zip'
    )

@app.route('/delete_backup', methods=['POST'])
def delete_backup():
    if 'admin_id' not in session:
        return jsonify({"success": False, "error": "未登录"})
    
    try:
        data = request.get_json()
        backup_filename = data.get('backup_filename')
        
        if not backup_filename:
            return jsonify({"success": False, "error": "未指定备份文件"})
        
        backup_path = Path() / "data" / "backups" / backup_filename
        
        if not backup_path.exists():
            return jsonify({"success": False, "error": f"备份文件不存在: {backup_filename}"})
        
        # 删除备份文件
        backup_path.unlink()
        
        return jsonify({
            "success": True,
            "message": f"备份文件 {backup_filename} 删除成功"
        })
        
    except Exception as e:
        return jsonify({"success": False, "error": f"删除备份失败: {str(e)}"})

@app.route('/delete_config_backup', methods=['POST'])
def delete_config_backup():
    if 'admin_id' not in session:
        return jsonify({"success": False, "error": "未登录"})
    
    try:
        data = request.get_json()
        backup_filename = data.get('backup_filename')
        
        if not backup_filename:
            return jsonify({"success": False, "error": "未指定备份文件"})

        backup_path = Path() / "data" / "config_backups" / backup_filename
        
        if not backup_path.exists():
            return jsonify({"success": False, "error": f"备份文件不存在: {backup_filename}"})
        
        # 删除文件
        backup_path.unlink()
        
        logger.info(f"配置备份文件已删除: {backup_filename}")
        return jsonify({"success": True, "message": f"配置备份文件删除成功: {backup_filename}"})
        
    except Exception as e:
        logger.error(f"删除配置备份失败: {str(e)}")
        return jsonify({"success": False, "error": f"删除配置备份失败: {str(e)}"})

@app.route('/database')
def database():
    if 'admin_id' not in session:
        return redirect(url_for('login'))
    all_tables = get_tables()
    return render_template('database.html', tables=all_tables)

@app.route('/table/<table_name>')
def table_view(table_name):
    if 'admin_id' not in session:
        return redirect(url_for('login'))
    
    # 获取所有表结构（按数据库分组）
    all_tables_grouped = get_tables()
    
    # 确定表属于哪个数据库
    db_path = None
    table_info = None
    
    for db_name, db_info in all_tables_grouped.items():
        if table_name in db_info["tables"]:
            db_path = db_info["path"]
            table_info = db_info["tables"][table_name]
            break
    
    if not db_path:
        return "表不存在", 404
    
    page = int(request.args.get('page', 1))
    per_page = int(request.args.get('per_page', 20))
    search_field = request.args.get('search_field')
    search_value = request.args.get('search_value')
    
    table_data = get_table_data(
        db_path, table_name, 
        page=page, per_page=per_page,
        search_field=search_field, search_value=search_value
    )
    
    return render_template(
        'table_view.html',
        table_name=table_name,
        table_info=table_info,
        data=table_data,
        search_field=search_field,
        search_value=search_value,
        primary_key=table_info.get('primary_key', 'id')
    )

@app.route('/table/<table_name>/<row_id>', methods=['GET', 'POST'])
def row_edit(table_name, row_id):
    if 'admin_id' not in session:
        return redirect(url_for('login'))
    
    # 获取所有表结构（按数据库分组）
    all_tables_grouped = get_tables()
    
    # 确定表属于哪个数据库
    db_path = None
    table_info = None
    
    for db_name, db_info in all_tables_grouped.items():
        if table_name in db_info["tables"]:
            db_path = db_info["path"]
            table_info = db_info["tables"][table_name]
            break
    
    if not db_path:
        return "表不存在", 404
    
    # 特殊处理复合主键表
    if table_name == "impart_cards":
        # 解析复合主键（格式：user_id_card_name）
        key_parts = row_id.split('_')
        if len(key_parts) < 2:
            return "无效的主键格式", 400
            
        # 构建复合主键条件
        primary_conditions = {
            "user_id": key_parts[0],
            "card_name": "_".join(key_parts[1:])
        }
    elif table_name == "back" and "composite_key" in table_info and table_info["composite_key"]:
        # 其他复合主键表的处理
        primary_keys = table_info["primary_key"]
        key_parts = row_id.split('_')
        if len(key_parts) != len(primary_keys):
            return "无效的主键格式", 400
            
        primary_conditions = {}
        for i, key in enumerate(primary_keys):
            primary_conditions[key] = key_parts[i]
    else:
        # 普通单主键处理
        primary_key = table_info.get('primary_key', 'id')
        primary_conditions = {primary_key: row_id}
    
    # 确定数据库路径
    db_path = IMPART_DB if table_name in get_database_tables(IMPART_DB) else DATABASE
    
    if request.method == 'POST':
        # 处理更新或删除
        action = request.form.get('action')
        
        if action == 'update':
            # 获取表单数据并进行空值转换
            update_data = {}
            for field in table_info['fields']:
                if field in request.form:
                    value = request.form[field]
                    # 将空字符串转换为None（NULL）
                    if value == '':
                        update_data[field] = None
                    else:
                        update_data[field] = value
            
            # 构建UPDATE语句
            set_clause = ", ".join([f"{field} = ?" for field in update_data.keys()])
            
            # 构建WHERE条件（支持复合主键）
            where_conditions = " AND ".join([f"{key} = ?" for key in primary_conditions.keys()])
            
            sql = f"UPDATE {table_name} SET {set_clause} WHERE {where_conditions}"
            
            # 执行更新
            params = list(update_data.values()) + list(primary_conditions.values())
            result = execute_sql(db_path, sql, params)
            
            if 'error' in result:
                return jsonify({"success": False, "error": result['error']})
            
            return jsonify({"success": True, "message": "更新成功"})
        
        elif action == 'delete':
            # 构建DELETE语句（支持复合主键）
            where_conditions = " AND ".join([f"{key} = ?" for key in primary_conditions.keys()])
            sql = f"DELETE FROM {table_name} WHERE {where_conditions}"
            result = execute_sql(db_path, sql, list(primary_conditions.values()))
            
            if 'error' in result:
                return jsonify({"success": False, "error": result['error']})
            
            return jsonify({"success": True, "message": "删除成功"})
    
    # GET请求，获取行数据
    where_conditions = " AND ".join([f"{key} = ?" for key in primary_conditions.keys()])
    sql = f"SELECT * FROM {table_name} WHERE {where_conditions}"
    row_data = execute_sql(db_path, sql, list(primary_conditions.values()))
    
    if not row_data:
        return "记录不存在", 404

    display_data = {}
    for key, value in row_data[0].items():
        if value is None:
            display_data[key] = ''
        else:
            display_data[key] = value
    
    return render_template(
        'row_edit.html',
        table_name=table_name,
        table_info=table_info,
        row_data=display_data,
        primary_key=primary_conditions  # 传递主键信息给模板
    )

@app.route('/batch_edit/<table_name>', methods=['POST'])
def batch_edit(table_name):
    if 'admin_id' not in session:
        return jsonify({"success": False, "error": "未登录"})
    
    # 获取表单数据
    search_field = request.form.get('search_field')
    search_value = request.form.get('search_value')
    batch_field = request.form.get('batch_field')
    operation = request.form.get('operation')
    value = request.form.get('value')
    apply_to_all = request.form.get('apply_to_all') == 'on'
    
    # 验证参数
    if not all([batch_field, operation, value]):
        return jsonify({"success": False, "error": "参数不完整"})
    
    # 如果是全字段搜索但未选择批量修改字段
    if (not search_field or search_field == '') and not batch_field:
        return jsonify({"success": False, "error": "全字段搜索时请选择要修改的字段"})
    
    # 确定数据库路径
    db_path = IMPART_DB if table_name in get_database_tables(IMPART_DB) else DATABASE
    
    try:
        # 构建更新语句
        if operation == "set":
            sql = f"UPDATE {table_name} SET {batch_field} = ?"
            params = [value]
        elif operation == "add":
            sql = f"UPDATE {table_name} SET {batch_field} = {batch_field} + ?"
            params = [value]
        elif operation == "subtract":
            sql = f"UPDATE {table_name} SET {batch_field} = {batch_field} - ?"
            params = [value]
        else:
            return jsonify({"success": False, "error": "无效的操作类型"})
        
        # 添加WHERE条件
        if not apply_to_all:
            if search_field and search_value:  # 指定字段搜索
                values = search_value.split()
                if len(values) > 1:
                    condition = " OR ".join([f"{search_field} LIKE ?" for _ in values])
                    sql += f" WHERE ({condition})"
                    params.extend([f"%{v}%" for v in values])
                else:
                    sql += f" WHERE {search_field} LIKE ?"
                    params.append(f"%{search_value}%")
            elif search_value:  # 全字段搜索
                # 获取所有字段
                tables = get_database_tables(db_path)
                table_fields = tables.get(table_name, {}).get('fields', [])
            
                if table_fields:
                    conditions = []
                    for field in table_fields:
                        if field != tables[table_name].get('primary_key'):
                            conditions.append(f"{field} LIKE ?")
                            params.append(f"%{search_value}%")
                    
                    # 确保有搜索条件时才添加WHERE
                    if conditions:
                        sql += f" WHERE ({' OR '.join(conditions)})"
                    else:
                        # 如果没有可搜索的字段，不执行任何操作
                        return jsonify({"success": False, "error": "没有可搜索的字段"})
        
        # 执行更新
        result = execute_sql(db_path, sql, params)
        
        if 'error' in result:
            return jsonify({"success": False, "error": result['error']})
        
        affected_rows = result.get('affected_rows', 0)
        
        return jsonify({
            "success": True, 
            "message": f"成功更新 {affected_rows} 条记录"
        })
        
    except Exception as e:
        return jsonify({"success": False, "error": f"执行错误: {str(e)}"})

@app.route('/commands')
def commands():
    if 'admin_id' not in session:
        return redirect(url_for('login'))
    return render_template('commands.html', commands=ADMIN_COMMANDS)

@app.route('/execute_command', methods=['POST'])
def execute_command():
    if 'admin_id' not in session:
        return jsonify({"success": False, "error": "未登录"})
    
    data = request.get_json()
    command_name = data.get('command_name')
    
    if not command_name:
        return jsonify({"success": False, "error": "未指定命令"})
    
    try:
        if command_name == "gm_command":
            # 神秘力量 - 修改灵石
            target = data.get('target')
            username = data.get('username')
            amount = int(data.get('amount', 0))
            
            if target == "指定用户" and username:
                user_info = get_user_by_name(username)
                if not user_info:
                    return jsonify({"success": False, "error": f"用户 {username} 不存在"})
                
                # 使用execute_sql更新灵石
                sql = "UPDATE user_xiuxian SET stone = stone + ? WHERE user_id = ?"
                execute_sql(DATABASE, sql, (amount, user_info['user_id']))
                
                return jsonify({
                    "success": True, 
                    "message": f"成功向 {username} {'增加' if amount >= 0 else '减少'} {abs(amount)} 灵石"
                })
            else:
                # 全服发放
                sql = "UPDATE user_xiuxian SET stone = stone + ?"
                execute_sql(DATABASE, sql, (amount,))
                return jsonify({
                    "success": True, 
                    "message": f"全服{'发放' if amount >= 0 else '扣除'} {abs(amount)} 灵石成功"
                })
        
        elif command_name == "adjust_exp_command":
            # 修为调整
            target = data.get('target')
            username = data.get('username')
            amount = int(data.get('amount', 0))
            
            if target == "指定用户" and username:
                user_info = get_user_by_name(username)
                if not user_info:
                    return jsonify({"success": False, "error": f"用户 {username} 不存在"})
                
                if amount > 0:
                    sql = "UPDATE user_xiuxian SET exp = exp + ? WHERE user_id = ?"
                    execute_sql(DATABASE, sql, (amount, user_info['user_id']))
                    return jsonify({
                        "success": True, 
                        "message": f"成功向 {username} 增加 {amount} 修为"
                    })
                else:
                    sql = "UPDATE user_xiuxian SET exp = exp - ? WHERE user_id = ?"
                    execute_sql(DATABASE, sql, (abs(amount), user_info['user_id']))
                    return jsonify({
                        "success": True, 
                        "message": f"成功从 {username} 减少 {abs(amount)} 修为"
                    })
            else:
                # 全服调整
                if amount > 0:
                    sql = "UPDATE user_xiuxian SET exp = exp + ?"
                else:
                    sql = "UPDATE user_xiuxian SET exp = exp - ?"
                execute_sql(DATABASE, sql, (abs(amount),))
                return jsonify({
                    "success": True, 
                    "message": f"全服{'增加' if amount >= 0 else '减少'} {abs(amount)} 修为成功"
                })
        
        elif command_name == "gmm_command":
            # 轮回力量 - 修改灵根
            username = data.get('username')
            root_type = data.get('root_type')
            
            if not username:
                return jsonify({"success": False, "error": "请指定用户名"})
            
            user_info = get_user_by_name(username)
            if not user_info:
                return jsonify({"success": False, "error": f"用户 {username} 不存在"})
            
            # 根据root_type设置灵根名称
            root_names = {
                "1": "全属性灵根",
                "2": "融合万物灵根", 
                "3": "月灵根",
                "4": "言灵灵根",
                "5": "金灵根",
                "6": "轮回千次不灭，只为臻至巅峰",
                "7": "轮回万次不灭，只为超越巅峰", 
                "8": "轮回无尽不灭，只为触及永恒之境",
                "9": f"轮回命主·{username}"
            }
            
            root_name = root_names.get(root_type, "未知灵根")
            root_type_name = ROOTS.get(root_type, "混沌灵根")
            
            # 更新灵根
            sql = "UPDATE user_xiuxian SET root = ?, root_type = ? WHERE user_id = ?"
            execute_sql(DATABASE, sql, (root_name, root_type_name, user_info['user_id']))
            
            # 更新战力
            sql_power = "UPDATE user_xiuxian SET power = round(exp * ? * (SELECT spend FROM level_data WHERE level = user_xiuxian.level), 0) WHERE user_id = ?"
            root_rate = get_root_rate(root_type, user_info['user_id'])
            execute_sql(DATABASE, sql_power, (root_rate, user_info['user_id']))
            
            return jsonify({
                "success": True, 
                "message": f"成功将 {username} 的灵根修改为 {root_name}"
            })
        
        elif command_name == "zaohua_xiuxian":
            # 造化力量 - 修改境界
            username = data.get('username')
            level = data.get('level')
            
            if not username:
                return jsonify({"success": False, "error": "请指定用户名"})
            
            user_info = get_user_by_name(username)
            if not user_info:
                return jsonify({"success": False, "error": f"用户 {username} 不存在"})
            
            # 检查境界是否有效
            levels = convert_rank('江湖好手')[1]
            if level not in levels:
                return jsonify({"success": False, "error": f"无效的境界: {level}"})
            
            # 获取境界所需的最大修为
            sql_level = "SELECT power FROM level_data WHERE level = ?"
            level_data = jsondata.level_data()
            if not level_data:
                return jsonify({"success": False, "error": f"无法获取境界 {level} 的数据"})
            
            max_exp = int(level_data[level]['power'])
            
            # 重置用户修为到刚好满足境界要求
            sql = "UPDATE user_xiuxian SET exp = ?, level = ? WHERE user_id = ?"
            execute_sql(DATABASE, sql, (max_exp, level, user_info['user_id']))
            
            # 更新用户状态和战力
            sql_hp = "UPDATE user_xiuxian SET hp = exp / 2, mp = exp, atk = exp / 10 WHERE user_id = ?"
            execute_sql(DATABASE, sql_hp, (user_info['user_id'],))
            
            sql_power = "UPDATE user_xiuxian SET power = round(exp * ? * (SELECT spend FROM level_data WHERE level = ?), 0) WHERE user_id = ?"
            root_rate = get_root_rate(user_info['root_type'], user_info['user_id'])
            execute_sql(DATABASE, sql_power, (root_rate, level, user_info['user_id']))
            
            return jsonify({
                "success": True, 
                "message": f"成功将 {username} 的境界修改为 {level}"
            })
        
        elif command_name == "cz":
            # 创造力量 - 发放物品
            target = data.get('target')
            username = data.get('username')
            item_input = data.get('item')
            amount = int(data.get('amount', 1))
            
            if not item_input:
                return jsonify({"success": False, "error": "请指定物品"})
            
            # 查找物品ID
            goods_id = None
            if item_input.isdigit():
                goods_id = int(item_input)
                # 检查物品是否存在
                sql_item = "SELECT * FROM back WHERE goods_id = ? LIMIT 1"
                item_check = execute_sql(DATABASE, sql_item, (goods_id,))
                if not item_check:
                    return jsonify({"success": False, "error": f"物品ID {goods_id} 不存在"})
            else:
                # 按名称查找物品
                sql_item = "SELECT goods_id FROM back WHERE goods_name = ? LIMIT 1"
                item_check = execute_sql(DATABASE, sql_item, (item_input,))
                if not item_check:
                    return jsonify({"success": False, "error": f"物品 {item_input} 不存在"})
                goods_id = item_check[0]['goods_id']
            
            # 获取物品信息
            sql_item_info = "SELECT goods_name, goods_type FROM back WHERE goods_id = ? LIMIT 1"
            item_info = execute_sql(DATABASE, sql_item_info, (goods_id,))[0]
            goods_name = item_info['goods_name']
            goods_type = item_info['goods_type']
            
            if target == "指定用户" and username:
                user_info = get_user_by_name(username)
                if not user_info:
                    return jsonify({"success": False, "error": f"用户 {username} 不存在"})
                
                # 发放物品
                now_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')
                sql_check = "SELECT * FROM back WHERE user_id = ? AND goods_id = ?"
                existing_item = execute_sql(DATABASE, sql_check, (user_info['user_id'], goods_id))
                
                if existing_item:
                    sql_update = "UPDATE back SET goods_num = goods_num + ?, update_time = ? WHERE user_id = ? AND goods_id = ?"
                    execute_sql(DATABASE, sql_update, (amount, now_time, user_info['user_id'], goods_id))
                else:
                    sql_insert = """
                        INSERT INTO back (user_id, goods_id, goods_name, goods_type, goods_num, create_time, update_time, bind_num)
                        VALUES (?, ?, ?, ?, ?, ?, ?, 0)
                    """
                    execute_sql(DATABASE, sql_insert, (user_info['user_id'], goods_id, goods_name, goods_type, amount, now_time, now_time))
                
                return jsonify({
                    "success": True, 
                    "message": f"成功向 {username} 发放 {goods_name} x{amount}"
                })
            else:
                # 全服发放 - 获取所有用户
                sql_users = "SELECT user_id FROM user_xiuxian"
                all_users = execute_sql(DATABASE, sql_users, ())
                success_count = 0
                
                now_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')
                for user in all_users:
                    try:
                        user_id = user['user_id']
                        sql_check = "SELECT * FROM back WHERE user_id = ? AND goods_id = ?"
                        existing_item = execute_sql(DATABASE, sql_check, (user_id, goods_id))
                        
                        if existing_item:
                            sql_update = "UPDATE back SET goods_num = goods_num + ?, update_time = ? WHERE user_id = ? AND goods_id = ?"
                            execute_sql(DATABASE, sql_update, (amount, now_time, user_id, goods_id))
                        else:
                            sql_insert = """
                                INSERT INTO back (user_id, goods_id, goods_name, goods_type, goods_num, create_time, update_time, bind_num)
                                VALUES (?, ?, ?, ?, ?, ?, ?, 0)
                            """
                            execute_sql(DATABASE, sql_insert, (user_id, goods_id, goods_name, goods_type, amount, now_time, now_time))
                        
                        success_count += 1
                    except Exception as e:
                        continue
                
                return jsonify({
                    "success": True, 
                    "message": f"全服发放 {goods_name} x{amount} 成功，影响 {success_count} 名用户"
                })
        
        elif command_name == "hmll":
            # 毁灭力量 - 扣除物品
            target = data.get('target')
            username = data.get('username')
            item_input = data.get('item')
            amount = int(data.get('amount', 1))
            
            if not item_input:
                return jsonify({"success": False, "error": "请指定物品"})
            
            # 查找物品ID
            goods_id = None
            if item_input.isdigit():
                goods_id = int(item_input)
                # 检查物品是否存在
                sql_item = "SELECT * FROM back WHERE goods_id = ? LIMIT 1"
                item_check = execute_sql(DATABASE, sql_item, (goods_id,))
                if not item_check:
                    return jsonify({"success": False, "error": f"物品ID {goods_id} 不存在"})
            else:
                # 按名称查找物品
                sql_item = "SELECT goods_id FROM back WHERE goods_name = ? LIMIT 1"
                item_check = execute_sql(DATABASE, sql_item, (item_input,))
                if not item_check:
                    return jsonify({"success": False, "error": f"物品 {item_input} 不存在"})
                goods_id = item_check[0]['goods_id']
            
            # 获取物品信息
            sql_item_info = "SELECT goods_name FROM back WHERE goods_id = ? LIMIT 1"
            item_info = execute_sql(DATABASE, sql_item_info, (goods_id,))[0]
            goods_name = item_info['goods_name']
            
            if target == "指定用户" and username:
                user_info = get_user_by_name(username)
                if not user_info:
                    return jsonify({"success": False, "error": f"用户 {username} 不存在"})
                
                # 检查用户是否有该物品
                sql_check = "SELECT goods_num FROM back WHERE user_id = ? AND goods_id = ?"
                user_item = execute_sql(DATABASE, sql_check, (user_info['user_id'], goods_id))
                
                if not user_item or user_item[0]['goods_num'] < amount:
                    return jsonify({"success": False, "error": f"用户 {username} 没有足够的 {goods_name}"})
                
                # 扣除物品
                sql_update = "UPDATE back SET goods_num = goods_num - ? WHERE user_id = ? AND goods_id = ?"
                execute_sql(DATABASE, sql_update, (amount, user_info['user_id'], goods_id))
                
                # 如果数量为0则删除记录
                sql_clean = "DELETE FROM back WHERE user_id = ? AND goods_id = ? AND goods_num <= 0"
                execute_sql(DATABASE, sql_clean, (user_info['user_id'], goods_id))
                
                return jsonify({
                    "success": True, 
                    "message": f"成功从 {username} 扣除 {goods_name} x{amount}"
                })
            else:
                # 全服扣除
                sql_users = "SELECT user_id FROM user_xiuxian"
                all_users = execute_sql(DATABASE, sql_users, ())
                success_count = 0
                
                for user in all_users:
                    try:
                        user_id = user['user_id']
                        sql_check = "SELECT goods_num FROM back WHERE user_id = ? AND goods_id = ?"
                        user_item = execute_sql(DATABASE, sql_check, (user_id, goods_id))
                        
                        if user_item and user_item[0]['goods_num'] >= amount:
                            sql_update = "UPDATE back SET goods_num = goods_num - ? WHERE user_id = ? AND goods_id = ?"
                            execute_sql(DATABASE, sql_update, (amount, user_id, goods_id))
                            
                            # 清理空记录
                            sql_clean = "DELETE FROM back WHERE user_id = ? AND goods_id = ? AND goods_num <= 0"
                            execute_sql(DATABASE, sql_clean, (user_id, goods_id))
                            
                            success_count += 1
                    except Exception as e:
                        continue
                
                return jsonify({
                    "success": True, 
                    "message": f"全服扣除 {goods_name} x{amount} 成功，影响 {success_count} 名用户"
                })
        
        elif command_name == "ccll_command":
            # 传承力量 - 修改思恋结晶数量
            target = data.get('target')
            username = data.get('username')
            amount = int(data.get('amount', 0))
            
            if target == "指定用户" and username:
                user_info = get_user_by_name(username)
                if not user_info:
                    return jsonify({"success": False, "error": f"用户 {username} 不存在"})
                
                # 更新思恋结晶
                sql_check = "SELECT * FROM xiuxian_impart WHERE user_id = ?"
                impart_data = execute_sql(IMPART_DB, sql_check, (user_info['user_id'],))
                
                if impart_data:
                    sql_update = "UPDATE xiuxian_impart SET stone_num = stone_num + ? WHERE user_id = ?"
                    execute_sql(IMPART_DB, sql_update, (amount, user_info['user_id']))
                else:
                    sql_insert = "INSERT INTO xiuxian_impart (user_id, stone_num) VALUES (?, ?)"
                    execute_sql(IMPART_DB, sql_insert, (user_info['user_id'], amount))
                
                return jsonify({
                    "success": True, 
                    "message": f"成功向 {username} {'增加' if amount >= 0 else '减少'} {abs(amount)} 思恋结晶"
                })
            else:
                # 全服调整
                sql_users = "SELECT user_id FROM user_xiuxian"
                all_users = execute_sql(DATABASE, sql_users, ())
                success_count = 0
                
                for user in all_users:
                    try:
                        user_id = user['user_id']
                        sql_check = "SELECT * FROM xiuxian_impart WHERE user_id = ?"
                        impart_data = execute_sql(IMPART_DB, sql_check, (user_id,))
                        
                        if impart_data:
                            sql_update = "UPDATE xiuxian_impart SET stone_num = stone_num + ? WHERE user_id = ?"
                            execute_sql(IMPART_DB, sql_update, (amount, user_id))
                        else:
                            sql_insert = "INSERT INTO xiuxian_impart (user_id, stone_num) VALUES (?, ?)"
                            execute_sql(IMPART_DB, sql_insert, (user_id, amount))
                        
                        success_count += 1
                    except Exception as e:
                        continue
                
                return jsonify({
                    "success": True, 
                    "message": f"全服{'发放' if amount >= 0 else '扣除'} {abs(amount)} 思恋结晶成功，影响 {success_count} 名用户"
                })
        
        else:
            return jsonify({"success": False, "error": f"未知命令: {command_name}"})
    
    except ValueError as e:
        return jsonify({"success": False, "error": f"参数格式错误: {str(e)}"})
    except Exception as e:
        return jsonify({"success": False, "error": f"执行错误: {str(e)}"})

CONFIG_EDITABLE_FIELDS = {
    "put_bot": {
        "name": "接收消息QQ",
        "description": "负责接收消息的QQ号列表",
        "type": "list[str]",
        "category": "基础设置"
    },
    "main_bo": {
        "name": "主QQ",
        "description": "负责发送消息的QQ号列表",
        "type": "list[str]",
        "category": "基础设置"
    },
    "shield_group": {
        "name": "屏蔽群聊",
        "description": "屏蔽的群聊ID列表",
        "type": "list[str]",
        "category": "群聊设置"
    },
    "response_group": {
        "name": "反转屏蔽",
        "description": "是否反转屏蔽的群聊（仅响应这些群的消息）",
        "type": "bool",
        "category": "群聊设置"
    },
    "shield_private": {
        "name": "屏蔽私聊",
        "description": "是否屏蔽私聊消息",
        "type": "bool",
        "category": "私聊设置"
    },
    "admin_debug": {
        "name": "管理员调试模式",
        "description": "开启后只响应超管指令",
        "type": "bool",
        "category": "调试设置"
    },
    "at_response": {
        "name": "艾特响应命令",
        "description": "是否只接收艾特命令",
        "type": "bool",
        "category": "消息设置"
    },
    "at_sender": {
        "name": "消息是否艾特",
        "description": "发送消息是否艾特",
        "type": "bool",
        "category": "消息设置"
    },
    "img": {
        "name": "图片发送",
        "description": "是否使用图片发送消息",
        "type": "bool",
        "category": "消息设置"
    },
    "user_info_image": {
        "name": "个人信息图片",
        "description": "是否使用图片发送个人信息",
        "type": "bool",
        "category": "消息设置"
    },
    "xiuxian_info_img": {
        "name": "网络背景图",
        "description": "开启则使用网络背景图",
        "type": "bool",
        "category": "消息设置"
    },
    "use_network_avatar": {
        "name": "网络头像",
        "description": "开启则使用网络头像",
        "type": "bool",
        "category": "消息设置"
    },
    "private_chat_enabled": {
        "name": "私聊功能",
        "description": "私聊功能开关",
        "type": "bool",
        "category": "私聊设置"
    },
    "web_port": {
        "name": "管理面板端口",
        "description": "修仙管理面板端口号",
        "type": "int",
        "category": "Web设置"
    },
    "web_host": {
        "name": "管理面板IP",
        "description": "修仙管理面板IP地址",
        "type": "str",
        "category": "Web设置"
    },
    "level_up_cd": {
        "name": "突破CD",
        "description": "突破CD（分钟）",
        "type": "int",
        "category": "修炼设置"
    },
    "closing_exp": {
        "name": "闭关修为",
        "description": "闭关每分钟获取的修为",
        "type": "int",
        "category": "修炼设置"
    },
    "tribulation_min_level": {
        "name": "最低渡劫境界",
        "description": "最低渡劫境界",
        "type": "select",
        "options": LEVELS,
        "category": "渡劫设置"
    },
    "tribulation_base_rate": {
        "name": "基础渡劫概率",
        "description": "基础渡劫概率（百分比）",
        "type": "int",
        "category": "渡劫设置"
    },
    "tribulation_max_rate": {
        "name": "最大渡劫概率",
        "description": "最大渡劫概率（百分比）",
        "type": "int",
        "category": "渡劫设置"
    },
    "tribulation_cd": {
        "name": "渡劫CD",
        "description": "渡劫冷却时间（分钟）",
        "type": "int",
        "category": "渡劫设置"
    },
    "sect_min_level": {
        "name": "创建宗门境界",
        "description": "创建宗门最低境界",
        "type": "select",
        "options": LEVELS,
        "category": "宗门设置"
    },
    "sect_create_cost": {
        "name": "创建宗门消耗",
        "description": "创建宗门消耗灵石",
        "type": "int",
        "category": "宗门设置"
    },
    "sect_rename_cost": {
        "name": "宗门改名消耗",
        "description": "宗门改名消耗灵石",
        "type": "int",
        "category": "宗门设置"
    },
    "sect_rename_cd": {
        "name": "宗门改名CD",
        "description": "宗门改名冷却时间（天）",
        "type": "int",
        "category": "宗门设置"
    },
    "auto_change_sect_owner_cd": {
        "name": "自动换宗主CD",
        "description": "自动换长时间不玩宗主CD（天）",
        "type": "int",
        "category": "宗门设置"
    },
    "closing_exp_upper_limit": {
        "name": "闭关修为上限",
        "description": "闭关获取修为上限倍数",
        "type": "float",
        "category": "修炼设置"
    },
    "level_punishment_floor": {
        "name": "突破失败惩罚下限",
        "description": "突破失败扣除修为惩罚下限（百分比）",
        "type": "int",
        "category": "修炼设置"
    },
    "level_punishment_limit": {
        "name": "突破失败惩罚上限",
        "description": "突破失败扣除修为惩罚上限（百分比）",
        "type": "int",
        "category": "修炼设置"
    },
    "level_up_probability": {
        "name": "失败增加概率",
        "description": "突破失败增加当前境界突破概率的比例",
        "type": "float",
        "category": "修炼设置"
    },
    "sign_in_lingshi_lower_limit": {
        "name": "签到灵石下限",
        "description": "每日签到灵石下限",
        "type": "int",
        "category": "经济设置"
    },
    "sign_in_lingshi_upper_limit": {
        "name": "签到灵石上限",
        "description": "每日签到灵石上限",
        "type": "int",
        "category": "经济设置"
    },
    "beg_max_level": {
        "name": "奇缘最高境界",
        "description": "仙途奇缘能领灵石最高境界",
        "type": "select",
        "options": LEVELS,
        "category": "经济设置"
    },
    "beg_max_days": {
        "name": "奇缘最多天数",
        "description": "仙途奇缘能领灵石最多天数",
        "type": "int",
        "category": "经济设置"
    },
    "beg_lingshi_lower_limit": {
        "name": "奇缘灵石下限",
        "description": "仙途奇缘灵石下限",
        "type": "int",
        "category": "经济设置"
    },
    "beg_lingshi_upper_limit": {
        "name": "奇缘灵石上限",
        "description": "仙途奇缘灵石上限",
        "type": "int",
        "category": "经济设置"
    },
    "tou": {
        "name": "偷灵石惩罚",
        "description": "偷灵石惩罚金额",
        "type": "int",
        "category": "经济设置"
    },
    "tou_lower_limit": {
        "name": "偷灵石下限",
        "description": "偷灵石下限（百分比）",
        "type": "float",
        "category": "经济设置"
    },
    "tou_upper_limit": {
        "name": "偷灵石上限",
        "description": "偷灵石上限（百分比）",
        "type": "float",
        "category": "经济设置"
    },
    "auto_select_root": {
        "name": "自动选择灵根",
        "description": "默认开启自动选择最佳灵根",
        "type": "bool",
        "category": "灵根设置"
    },
    "remake": {
        "name": "重入仙途消费",
        "description": "重入仙途的消费灵石",
        "type": "int",
        "category": "经济设置"
    },
    "remaname": {
        "name": "修仙改名消费",
        "description": "修仙改名的消费灵石",
        "type": "int",
        "category": "经济设置"
    },
    "max_stamina": {
        "name": "体力上限",
        "description": "体力上限值",
        "type": "int",
        "category": "体力设置"
    },
    "stamina_recovery_points": {
        "name": "体力恢复",
        "description": "体力恢复点数/分钟",
        "type": "int",
        "category": "体力设置"
    },
    "lunhui_min_level": {
        "name": "千世轮回境界",
        "description": "千世轮回最低境界",
        "type": "select",
        "options": LEVELS,
        "category": "轮回设置"
    },
    "twolun_min_level": {
        "name": "万世轮回境界",
        "description": "万世轮回最低境界",
        "type": "select",
        "options": LEVELS,
        "category": "轮回设置"
    },
    "threelun_min_level": {
        "name": "永恒轮回境界",
        "description": "永恒轮回最低境界",
        "type": "select",
        "options": LEVELS,
        "category": "轮回设置"
    },
    "Infinite_reincarnation_min_level": {
        "name": "无限轮回境界",
        "description": "无限轮回最低境界",
        "type": "select",
        "options": LEVELS,
        "category": "轮回设置"
    },
    "merge_forward_send": {
        "name": "消息发送方式",
        "description": "1=长文本,2=合并转发,3=合并转长图,4=长文本合并转发",
        "type": "int",
        "category": "消息设置"
    },
    "message_optimization": {
        "name": "消息优化",
        "description": "是否开启信息优化",
        "type": "bool",
        "category": "消息设置"
    },
    "img_compression_limit": {
        "name": "图片压缩率",
        "description": "图片压缩率（0-100）",
        "type": "int",
        "category": "消息设置"
    },
    "img_type": {
        "name": "图片类型",
        "description": "webp或者jpeg",
        "type": "str",
        "category": "消息设置"
    },
    "img_send_type": {
        "name": "图片发送类型",
        "description": "io或base64",
        "type": "str",
        "category": "消息设置"
    }
}

# 排除数据库相关的配置字段
EXCLUDED_CONFIG_FIELDS = [
    'sql_table', 'sql_user_xiuxian', 'sql_user_cd', 'sql_sects', 
    'sql_buff', 'sql_back', 'level', 'version'
]

def get_config_values():
    """获取当前配置值"""
    config = XiuConfig()
    values = {}
    
    for field_name, field_info in CONFIG_EDITABLE_FIELDS.items():
        if hasattr(config, field_name):
            value = getattr(config, field_name)
            values[field_name] = value
    
    return values

def save_config_values(new_values):
    """保存配置到文件"""
    config_file_path = Xiu_Plugin / "xiuxian" / "xiuxian_config.py"
    
    if not config_file_path.exists():
        return False, "配置文件不存在"
    
    try:
        # 读取原文件内容
        with open(config_file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # 更新配置值
        for field_name, new_value in new_values.items():
            if field_name in CONFIG_EDITABLE_FIELDS:
                field_type = CONFIG_EDITABLE_FIELDS[field_name]["type"]
                
                # 根据类型格式化值
                if field_type == "list[int]":
                    # 清理输入：移除所有非数字字符（除了逗号和空格）
                    if isinstance(new_value, str):
                        # 移除方括号、引号等字符
                        cleaned_value = re.sub(r'[\[\]\'"\s]', '', new_value)
                        if cleaned_value:
                            # 分割并转换为整数列表
                            try:
                                int_list = [int(x.strip()) for x in cleaned_value.split(',') if x.strip()]
                                formatted_value = f"[{', '.join(map(str, int_list))}]"
                            except ValueError:
                                formatted_value = "[]"
                        else:
                            formatted_value = "[]"
                    else:
                        formatted_value = str(new_value)
                
                elif field_type == "list[str]":
                    # 清理输入：移除方括号和多余的引号
                    if isinstance(new_value, str):
                        # 移除方括号
                        cleaned_value = re.sub(r'[\[\]]', '', new_value)
                        # 分割并清理每个元素
                        str_list = []
                        for item in cleaned_value.split(','):
                            item = item.strip()
                            # 移除两端的引号（单引号或双引号）
                            item = re.sub(r'^[\'"]|[\'"]$', '', item)
                            if item:
                                str_list.append(f'"{item}"')
                        formatted_value = f"[{', '.join(str_list)}]"
                    else:
                        formatted_value = str(new_value)
                
                elif field_type == "bool":
                    formatted_value = "True" if str(new_value).lower() in ('true', '1', 'yes') else "False"
                
                elif field_type == "select":
                    formatted_value = f'"{new_value}"'
                
                elif field_type == "int":
                    try:
                        formatted_value = str(int(new_value))
                    except (ValueError, TypeError):
                        formatted_value = "0"
                
                elif field_type == "float":
                    try:
                        formatted_value = str(float(new_value))
                    except (ValueError, TypeError):
                        formatted_value = "0.0"
                
                else:
                    # 字符串类型：确保有引号包围
                    if not (new_value.startswith('"') and new_value.endswith('"')) and \
                       not (new_value.startswith("'") and new_value.endswith("'")):
                        formatted_value = f'"{new_value}"'
                    else:
                        formatted_value = new_value
                
                # 在文件中查找并替换配置项
                pattern = rf"self\.{field_name}\s*=\s*.+"
                replacement = f"self.{field_name} = {formatted_value}"
                content = re.sub(pattern, replacement, content)
        
        # 写入新内容
        with open(config_file_path, 'w', encoding='utf-8') as f:
            f.write(content)
        
        return True, "配置保存成功"
    
    except Exception as e:
        return False, f"保存配置时出错: {str(e)}"

# 配置管理路由
@app.route('/config')
def config_management():
    if 'admin_id' not in session:
        return redirect(url_for('login'))
    
    current_config = get_config_values()
    
    # 预处理列表值用于显示
    for field_name, value in current_config.items():
        if field_name in CONFIG_EDITABLE_FIELDS:
            field_type = CONFIG_EDITABLE_FIELDS[field_name]["type"]
            if field_type in ['list[int]', 'list[str]']:
                # 格式化列表值用于显示
                current_config[field_name] = format_list_value_for_display(value, field_type)
    
    # 按分类分组配置项
    config_by_category = {}
    for field_name, field_info in CONFIG_EDITABLE_FIELDS.items():
        category = field_info["category"]
        if category not in config_by_category:
            config_by_category[category] = []
        
        config_item = {
            "field_name": field_name,
            "name": field_info["name"],
            "description": field_info["description"],
            "type": field_info["type"],
            "value": current_config.get(field_name, "")
        }
        
        if field_info["type"] == "select" and "options" in field_info:
            config_item["options"] = field_info["options"]
        
        config_by_category[category].append(config_item)
    
    return render_template('config.html', config_by_category=config_by_category)

def format_list_value_for_display(value, field_type):
    """格式化列表值用于显示"""
    if not value:
        return ''
    
    try:
        if isinstance(value, str):
            import ast
            value = ast.literal_eval(value)
        
        if isinstance(value, (list, tuple)):
            if field_type == 'list[int]':
                return ', '.join(str(x) for x in value)
            else:
                return ', '.join(str(x).strip('"\'') for x in value)
        else:
            return str(value)
    except (ValueError, SyntaxError):
        # 如果解析失败，返回清理后的值
        cleaned = str(value).replace('[', '').replace(']', '').replace('"', '').replace("'", '')
        return cleaned

@app.route('/save_config', methods=['POST'])
def save_config():
    if 'admin_id' not in session:
        return jsonify({"success": False, "error": "未登录"})
    
    try:
        config_data = request.get_json()
        if not config_data:
            return jsonify({"success": False, "error": "无效的配置数据"})
        
        success, message = save_config_values(config_data)
        return jsonify({"success": success, "message": message})
    
    except Exception as e:
        return jsonify({"success": False, "error": f"保存配置时出错: {str(e)}"})

@app.context_processor
def inject_navigation():
    """注入导航栏状态和辅助函数到所有模板"""
    def is_active(endpoint):
        """检查当前路由是否匹配给定的端点"""
        if isinstance(endpoint, (list, tuple)):
            return request.endpoint in endpoint
        return request.endpoint == endpoint
    
    return dict(
        get_command_icon=get_command_icon,
        get_config_category_icon=get_config_category_icon,
        is_active=is_active
    )

def get_root_rate(root_type, user_id):
    """获取灵根倍率（完整版本，参考原版实现）"""
    # 获取灵根数据
    root_data = jsondata.root_data()
    
    # 特殊处理命运道果
    if root_type == '命运道果':
        # 获取用户信息
        user_info = get_user_by_id(user_id)
        if not user_info:
            return 1.0
            
        root_level = user_info.get('root_level', 0)
        
        # 获取永恒道果和命运道果的倍率
        eternal_rate = root_data['永恒道果']['type_speeds']
        fate_rate = root_data['命运道果']['type_speeds']
        
        # 计算最终倍率：永恒道果倍率 + (轮回等级 × 命运道果倍率)
        return eternal_rate + (root_level * fate_rate)
    else:
        # 普通灵根，直接从数据中获取倍率
        if root_type in root_data:
            return root_data[root_type]['type_speeds']
        else:
            # 如果找不到对应的灵根类型，返回默认值
            return 1.0

def get_command_icon(command_name):
    """获取命令对应的图标"""
    icon_map = {
        "gm_command": "fas fa-gem",
        "adjust_exp_command": "fas fa-fire",
        "gmm_command": "fas fa-recycle",
        "zaohua_xiuxian": "fas fa-mountain",
        "cz": "fas fa-gift",
        "hmll": "fas fa-trash",
        "ccll_command": "fas fa-history"
    }
    return icon_map.get(command_name, "fas fa-cog")

def get_config_category_icon(category):
    """获取配置分类对应的图标"""
    icon_map = {
        "基础设置": "fas fa-cube",
        "群聊设置": "fas fa-users",
        "私聊设置": "fas fa-user",
        "调试设置": "fas fa-bug",
        "消息设置": "fas fa-comment",
        "Web设置": "fas fa-globe",
        "修炼设置": "fas fa-medal",
        "渡劫设置": "fas fa-bolt",
        "宗门设置": "fas fa-landmark",
        "经济设置": "fas fa-coins",
        "灵根设置": "fas fa-seedling",
        "体力设置": "fas fa-heart",
        "轮回设置": "fas fa-infinity"
    }
    return icon_map.get(category, "fas fa-cog")

@app.route('/get_stats')
def get_stats():
    if 'admin_id' not in session:
        return jsonify({"success": False, "error": "未登录"})
    
    try:
        # 获取总用户数
        total_users_result = execute_sql(DATABASE, "SELECT COUNT(*) FROM user_xiuxian")
        total_users = total_users_result[0]['COUNT(*)'] if total_users_result else 0
        
        # 获取宗门数量
        total_sects_result = execute_sql(DATABASE, "SELECT COUNT(*) FROM sects WHERE sect_owner IS NOT NULL")
        total_sects = total_sects_result[0]['COUNT(*)'] if total_sects_result else 0
        
        # 获取今日活跃用户数（今天有操作记录的用户）
        today = datetime.now().strftime('%Y-%m-%d')
        active_users_result = execute_sql(DATABASE, 
            "SELECT COUNT(DISTINCT user_id) FROM user_cd WHERE date(create_time) = ?", (today,))
        active_users = active_users_result[0]['COUNT(DISTINCT user_id)'] if active_users_result else 0
        
        return jsonify({
            "success": True,
            "total_users": total_users,
            "total_sects": total_sects,
            "active_users": active_users
        })
        
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

@app.route('/get_system_info')
def get_system_info():
    if 'admin_id' not in session:
        return jsonify({"success": False, "error": "未登录"})
    
    try:
        
        # 获取CPU使用率
        cpu_usage = psutil.cpu_percent(interval=1)
        
        # 获取内存使用率
        memory = psutil.virtual_memory()
        memory_usage = memory.percent
        
        # 获取磁盘使用率
        disk = psutil.disk_usage('/')
        disk_usage = disk.percent
        
        return jsonify({
            "success": True,
            "cpu_usage": round(cpu_usage, 1),
            "memory_usage": round(memory_usage, 1),
            "disk_usage": round(disk_usage, 1)
        })
        
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

@app.route('/get_system_info_extended')
def get_system_info_extended():
    if 'admin_id' not in session:
        return jsonify({"success": False, "error": "未登录"})
    
    try:
        
        # 获取系统信息
        system_info = {
            "平台": platform.platform(),
            "系统": platform.system(),
            "版本": platform.version(),
            "机器": platform.machine(),
            "处理器": platform.processor(),
            "Python版本": platform.python_version(),
        }
        
        # 获取CPU信息
        try:
            cpu_info = {
                "物理核心数": psutil.cpu_count(logical=False),
                "逻辑核心数": psutil.cpu_count(logical=True),
                "CPU使用率": f"{psutil.cpu_percent()}%",
                "CPU频率": f"{psutil.cpu_freq().current:.2f}MHz" if hasattr(psutil, "cpu_freq") else "未知"
            }
        except Exception:
            cpu_info = {"CPU信息": "获取失败"}
        
        # 获取内存信息
        try:
            mem = psutil.virtual_memory()
            mem_info = {
                "总内存": f"{mem.total / (1024**3):.2f}GB",
                "已用内存": f"{mem.used / (1024**3):.2f}GB",
                "内存使用率": f"{mem.percent}%"
            }
        except Exception:
            mem_info = {"内存信息": "获取失败"}
        
        # 获取磁盘信息
        try:
            disk = psutil.disk_usage('/')
            disk_info = {
                "总磁盘空间": f"{disk.total / (1024**3):.2f}GB",
                "已用空间": f"{disk.used / (1024**3):.2f}GB",
                "磁盘使用率": f"{disk.percent}%"
            }
        except Exception:
            disk_info = {"磁盘信息": "获取失败"}
        
        # 获取系统启动时间
        try:
            boot_time = psutil.boot_time()
            current_time = time.time()
            uptime_seconds = current_time - boot_time
            
            system_uptime_info = {
                "系统启动时间": f"{datetime.fromtimestamp(boot_time):%Y-%m-%d %H:%M:%S}",
                "系统运行时间": format_time(uptime_seconds)
            }
        except Exception:
            system_uptime_info = {"系统运行时间": "获取失败"}
        
        return jsonify({
            "success": True,
            "system_info": system_info,
            "cpu_info": cpu_info,
            "mem_info": mem_info,
            "disk_info": disk_info,
            "system_uptime": system_uptime_info
        })
        
    except Exception as e:
        return jsonify({"success": False, "error": f"获取系统信息失败: {str(e)}"})

@app.route('/get_process_info')
def get_process_info():
    if 'admin_id' not in session:
        return jsonify({"success": False, "error": "未登录"})
    
    try:
        processes = []
        for proc in psutil.process_iter(['pid', 'name', 'memory_percent', 'create_time']):
            try:
                memory_mb = proc.memory_info().rss / 1024 / 1024
                create_time = datetime.fromtimestamp(proc.create_time())
                run_time = datetime.now() - create_time
                
                processes.append({
                    "name": proc.name(),
                    "memory": f"{memory_mb:.1f}MB",
                    "time": str(run_time).split('.')[0]  # 去除毫秒部分
                })
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        
        # 按内存使用排序并取前5
        processes.sort(key=lambda x: float(x['memory'].replace('MB', '')), reverse=True)
        top_processes = processes[:5]
        
        return jsonify({
            "success": True,
            "processes": top_processes
        })
        
    except Exception as e:
        return jsonify({"success": False, "error": f"获取进程信息失败: {str(e)}"})

def format_time(seconds: float) -> str:
    """将秒数格式化为 'X天X小时X分X秒'"""
    days, remainder = divmod(seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{int(days)}天{int(hours)}小时{int(minutes)}分{int(seconds)}秒"

@app.route('/search_users')
def search_users():
    if 'admin_id' not in session:
        return jsonify([])
    
    query = request.args.get('query', '')
    sql = "SELECT user_id, user_name FROM user_xiuxian WHERE user_name LIKE ? LIMIT 10"
    results = execute_sql(DATABASE, sql, (f"%{query}%",))
    
    return jsonify([{"id": r['user_id'], "name": r['user_name']} for r in results])

import threading

def run_flask():
    app.run(host=HOST, port=PORT, debug=False)

if XiuConfig().web_status:
    # 创建并启动线程
    flask_thread = threading.Thread(target=run_flask)
    flask_thread.daemon = True  # 设置为守护线程，主程序退出时会自动结束
    flask_thread.start()
    logger.info(f"修仙管理面板已启动：{HOST}:{PORT}")
