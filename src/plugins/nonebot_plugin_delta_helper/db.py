from typing import Union, List, Optional
from sqlalchemy.future import select
from nonebot.log import logger
from src.service.nonebot_plugin_orm import async_scoped_session, AsyncSession, get_scoped_session
from .model import UserData, LatestRecord, SafehouseRecord


class UserDataDatabase:
    def __init__(self, session: Union[async_scoped_session, AsyncSession, None] = None) -> None:
        # 支持传入 session，也支持默认使用作用域 session
        self.session = session or get_scoped_session()()

    # ----------------- 用户信息 -----------------
    async def get_user_data(self, qq: int) -> Optional[UserData]:
        return await self.session.get(UserData, qq)

    async def add_user_data(self, external_user_data: UserData, commit: bool = True) -> bool:
        try:
            await self.session.merge(external_user_data)
            if commit:
                await self.session.commit()
            return True
        except Exception:
            logger.exception('插入信息表时发生错误')
            await self.session.rollback()
            return False

    async def update_user_data(self, external_user_data: UserData, commit: bool = True) -> bool:
        try:
            await self.session.merge(external_user_data)
            if commit:
                await self.session.commit()
            return True
        except Exception:
            logger.exception('更新信息表时发生错误')
            await self.session.rollback()
            return False

    async def get_user_data_list(self) -> List[UserData]:
        stmt = select(UserData)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    # ----------------- 最新战绩 -----------------
    async def get_latest_record(self, qq_id: int) -> Optional[LatestRecord]:
        return await self.session.get(LatestRecord, qq_id)

    async def update_latest_record(self, latest_record: LatestRecord, commit: bool = True) -> bool:
        try:
            await self.session.merge(latest_record)
            if commit:
                await self.session.commit()
            return True
        except Exception:
            logger.exception('更新最新战绩记录时发生错误')
            await self.session.rollback()
            return False

    # ----------------- 特勤处生产记录 -----------------
    async def get_safehouse_records(self, qq_id: int) -> List[SafehouseRecord]:
        stmt = select(SafehouseRecord).where(SafehouseRecord.qq_id == qq_id)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def update_safehouse_record(self, safehouse_record: SafehouseRecord, commit: bool = True) -> bool:
        try:
            await self.session.merge(safehouse_record)
            if commit:
                await self.session.commit()
            return True
        except Exception:
            logger.exception('更新特勤处生产记录时发生错误')
            await self.session.rollback()
            return False

    async def delete_safehouse_record(self, qq_id: int, device_id: str, commit: bool = True) -> bool:
        try:
            stmt = select(SafehouseRecord).where(
                SafehouseRecord.qq_id == qq_id,
                SafehouseRecord.device_id == device_id
            )
            record = (await self.session.execute(stmt)).scalar_one_or_none()
            if record:
                await self.session.delete(record)
                if commit:
                    await self.session.commit()
            return True
        except Exception:
            logger.exception('删除特勤处生产记录时发生错误')
            await self.session.rollback()
            return False

    # ----------------- 手动控制事务 -----------------
    async def commit(self):
        """手动提交事务"""
        await self.session.commit()

    async def rollback(self):
        """手动回滚事务"""
        await self.session.rollback()
