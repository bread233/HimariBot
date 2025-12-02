from typing import Tuple, Optional, Union, Dict, List
from pathlib import Path
import aiosqlite
from nonebot.log import logger


class BattleFieldDataBase:
    bf_db_name = "battle_filed_tool.db"

    def __init__(self, bf_data_dir: Optional[Path] = None):
        """
        数据库存储路径:
        默认: ./data/nonebot_plugin_battlefield_tool/
        """
        if bf_data_dir is None:
            bf_data_dir = Path("data") / "nonebot_plugin_battlefield_tool"

        bf_data_dir.mkdir(parents=True, exist_ok=True)
        self.bf_db_path = bf_data_dir / self.bf_db_name

        self._conn: Optional[aiosqlite.Connection] = None

    async def _init_db(self, conn: aiosqlite.Connection):
        """执行 SQL 初始化脚本"""

        sql_path = Path(__file__).parent / "sql" / "battleField_tool_plugin_init.sql"

        logger.debug(f"加载数据库初始化 SQL: {sql_path}")

        if not sql_path.exists():
            raise FileNotFoundError(f"初始化SQL文件不存在: {sql_path}")

        try:
            sql_script = sql_path.read_text(encoding="utf-8")
            await conn.executescript(sql_script)
            await conn.commit()
            logger.info("数据库表初始化完成")
        except aiosqlite.Error as e:
            logger.exception("数据库初始化失败")
            raise RuntimeError(f"数据库初始化失败: {e}")

    async def initialize(self):
        """初始化数据库"""
        if self._conn is None:
            self._conn = await self._get_conn()
            await self._init_db(self._conn)

    async def _get_conn(self) -> aiosqlite.Connection:
        """获取数据库连接(缓存复用)"""
        if self._conn:
            return self._conn

        return await aiosqlite.connect(self.bf_db_path)

    async def close(self):
        """关闭数据库连接"""
        if self._conn:
            await self._conn.close()
            self._conn = None

    async def exec_sql(self, sql: str, params: Tuple = None):
        """执行非查询 SQL"""
        await self.initialize()
        conn = await self._get_conn()
        try:
            await conn.execute(sql, params or ())
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
        await self.initialize()
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

            row = await cursor.fetchone()
            return dict(row) if row else None

        except aiosqlite.Error as e:
            logger.error(f"查询失败: {e}\nSQL: {sql}\nParams: {params}")
            raise
