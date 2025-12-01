import asyncio
from typing import Dict, Callable
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_scoped_session
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy.exc import SQLAlchemyError
from nonebot.log import logger

# ----------------- Base Model -----------------
Model = declarative_base()

# ----------------- 数据库配置 -----------------
DATABASE_URL = "sqlite+aiosqlite:///./bot_data.db"  # 可替换为你的数据库URL

engine = create_async_engine(DATABASE_URL, echo=False, future=True)
async_session_factory = sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
)

# ----------------- 获取普通 session -----------------
def get_session() -> AsyncSession:
    """
    直接返回 AsyncSession 实例，非作用域
    """
    return async_session_factory()

# ----------------- 获取作用域 session -----------------
def get_scoped_session() -> Callable[[], AsyncSession]:
    """
    返回一个线程安全的 async_scoped_session 工厂。
    调用返回 AsyncSession 实例。
    """
    try:
        asyncio.get_running_loop()
        # async_scoped_session 返回的本身是可调用工厂
        scoped_factory = async_scoped_session(async_session_factory, scopefunc=asyncio.current_task)
        return scoped_factory  # 调用时使用 scoped_factory()
    except RuntimeError:
        # fallback: 无事件循环时返回普通 session 工厂
        return async_session_factory

# ----------------- ORM 初始化 -----------------
_initialized: Dict[str, bool] = {}

def init_orm(plugin_name: str):
    """
    初始化 ORM（创建表）。
    通过 plugin_name 避免重复初始化。
    """
    if _initialized.get(plugin_name):
        return
    _initialized[plugin_name] = True

    async def _init():
        try:
            async with engine.begin() as conn:
                await conn.run_sync(Model.metadata.create_all)
            logger.info(f"ORM 已初始化: {plugin_name}")
        except SQLAlchemyError:
            logger.exception(f"初始化 ORM 时发生错误: {plugin_name}")

    # 异步任务执行初始化
    asyncio.create_task(_init())

# ----------------- 数据库工具函数 -----------------
async def commit_session(session: AsyncSession):
    try:
        await session.commit()
    except SQLAlchemyError:
        logger.exception("提交事务失败")
        await session.rollback()

async def rollback_session(session: AsyncSession):
    try:
        await session.rollback()
    except SQLAlchemyError:
        logger.exception("回滚事务失败")
