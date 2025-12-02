from typing import Tuple, Optional, Union, Dict, List
from pathlib import Path

import aiosqlite
from nonebot.log import logger
import os


class BattleFieldDataBase:
    bf_db_name = "battle_filed_tool.db"

    def __init__(self, bf_data_dir: Optional[Path] = None):
        """
        数据库存储路径:
        默认放在：plugins/nonebot_plugin_battlefield_tool/data/
        """
        if bf_data_dir is None:
            # 自动定位 plugin 根目录
            base_dir = Path(__file__).resolve().parent.parent
            bf_data_dir = base_dir / "data"

        bf_data_dir.mkdir(parents=True, exist_ok=True)
        self.bf_db_path = bf_data_dir / self.bf_db_name

        self._conn: Optional[aiosqlite.Connection] = None

    async def _init_db(self, conn: aiosqlite.Connection):
        """执行 SQL 初始化脚本"""

        # SQL 文件路径修正，跟随项目原结构
        sql_path = Path(__file__).resolve().parent / "sql" / "battleField_tool_plugin_init.sql"

        logger.debug(f"尝试从路径加载初始化SQL: {sql_path}")

        if not sql_path.exists():
            logger.error(f"初始化SQL文件不存在: {sql_path}")
            raise FileNotFoundError(f"初始化SQL文件不存在: {sql_path}")

        try:
            sql_script = sql_path.read_text(encoding="utf-8")
            logger.debug(f"开始执行数据库初始化脚本，文件大小: {len(sql_script)} 字节")

            await conn.executescript(sql_script)
            await conn.commit()
            logger.debug("数据库表结构初始化成功")

        except aiosqlite.Error as e:
            logger.exception(f"数据库初始化失败: {e}")
            raise RuntimeError(f"数据库初始化失败: {e}") from e
        except Exception:
            logger.exception("未知错误发生在数据库初始化过程中")
            raise

    async def initialize(self):
        """初始化数据库连接 + 表结构"""
        logger.debug(f"开始初始化战地风云数据库: {self.bf_db_path}")
        self._conn = await self._get_conn()
        await self._init_db(self._conn)
        logger.debug("战地风云数据库初始化完成")

    async def _get_conn(self) -> aiosqlite.Connection:
        """获取数据库连接(缓存复用)"""
        if self._conn:
            return self._conn

        try:
            conn = await aiosqlite.connect(self.bf_db_path)
            conn.text_factory = str
            return conn
        except aiosqlite.Error as e:
            logger.error(f"数据库连接失败: {e}")
            raise RuntimeError(f"无法连接到数据库: {e}")

    async def close(self):
        """关闭数据库连接"""
        if self._conn:
            await self._conn.close()
            self._conn = None

    async def exec_sql(self, sql: str, params: Tuple = None):
        """执行非查询 SQL"""
        conn = await self._get_conn()
        try:
            cursor = await conn.cursor()
            await cursor.execute(sql, params or ())
            await conn.commit()
        except aiosqlite.Error:
            await conn.rollback()
            raise

    async def query(
        self,
        sql: str,
        params: Optional[Union[Tuple, Dict]] = None,
        fetch_all: bool = True,
    ) -> Union[List[Dict], Optional[Dict]]:
        """执行查询 SQL"""
        conn = await self._get_conn()
        try:
            conn.row_factory = aiosqlite.Row
            cursor = await conn.cursor()

            if isinstance(params, dict):
                await cursor.execute(sql, params)
            else:
                await cursor.execute(sql, params or ())

            if fetch_all:
                return [dict(row) for row in await cursor.fetchall()]
            else:
                row = await cursor.fetchone()
                return dict(row) if row else None

        except aiosqlite.Error as e:
            logger.error(f"查询失败: {e}\nSQL: {sql}\nParams: {params}")
            raise
