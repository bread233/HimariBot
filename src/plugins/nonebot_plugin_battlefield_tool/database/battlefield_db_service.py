from typing import Optional, Dict
from .battlefield_database import (
    BattleFieldDataBase,
)


class BattleFieldDBService:
    def __init__(self, db: BattleFieldDataBase):
        self.db = db

    async def upsert_user_bind(self, qq_id: str, ea_name: str, ea_id: str) -> str:
        """更新或插入用户绑定"""
        old_data = await self.query_bind_user(qq_id)
        await self.db.exec_sql(
            """
            INSERT INTO battleField_user_binds (qq_id, ea_name, ea_id)
            VALUES (?, ?, ?) ON CONFLICT(qq_id) DO
            UPDATE SET
                ea_name = excluded.ea_name,
                ea_id = excluded.ea_id
            """,
            (qq_id, ea_name, ea_id),
        )
        return (
            f"更新绑定数据: {old_data['ea_name']}-->{ea_name}，ps:本插件不做用户名校验请务必确认是否正确"
            if old_data
            else f"成功绑定EA_NAME：{ea_name}，ps:本插件不做用户名校验请务必确认EA用户名是否正确"
        )

    async def upsert_session_channel(
        self, session_channel_id: str, default_game_tag: str
    ) -> str:
        """更新或插入会话渠道设置"""
        old_data = await self.query_session_channel(session_channel_id)
        await self.db.exec_sql(
            """
            INSERT INTO battleField_session_tags (session_channel_id, default_game_tag)
            VALUES (?, ?) ON CONFLICT(session_channel_id) DO
            UPDATE SET
                default_game_tag = excluded.default_game_tag
            """,
            (session_channel_id, default_game_tag),
        )
        return (
            f"更新渠道数据: {old_data['default_game_tag']}-->{default_game_tag}"
            if old_data
            else f"成功绑定DEFAULT_GAME_TAG：{default_game_tag}"
        )

    async def query_bind_user(self, qq_id: str) -> Optional[Dict]:
        """查询绑定用户"""
        return await self.db.query(
            "SELECT * FROM battleField_user_binds WHERE qq_id = ?",
            (qq_id,),
            fetch_all=False,
        )

    async def query_session_channel(self, session_channel_id: str) -> Optional[Dict]:
        """查询会话渠道设置"""
        return await self.db.query(
            "SELECT default_game_tag FROM battleField_session_tags WHERE session_channel_id = ?",
            (session_channel_id,),
            fetch_all=False,
        )
