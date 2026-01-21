"""
数据库会话管理
提供异步数据库连接
"""
from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from src.database.models import Base
from pathlib import Path

# 数据库文件路径
DB_DIR = Path(__file__).resolve().parent.parent.parent / "data"
DB_DIR.mkdir(parents=True, exist_ok=True)
DB_URL = f"sqlite+aiosqlite:///{DB_DIR}/customs_audit.db"

# 创建异步引擎
engine = create_async_engine(
    DB_URL,
    echo=False,  # 设置为True可查看SQL日志
    connect_args={"check_same_thread": False}  # SQLite特有配置
)

# 创建会话工厂
async_session_maker = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False
)

async def get_async_session() -> AsyncGenerator[AsyncSession, None]:
    """
    获取异步数据库会话

    Usage:
        async with get_async_session() as db:
            result = await db.execute(select(User))
    """
    async with async_session_maker() as session:
        yield session

async def init_database():
    """
    初始化数据库表结构
    (仅在首次启动时调用，生产环境建议使用Alembic迁移)
    """
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
