from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from src.database.models import Base
import os
from typing import AsyncGenerator

# 1. 设置数据库文件的位置
# 我们把它放在项目根目录下，叫 customs_audit.db
# sqlite+aiosqlite:// 表示我们要用异步的方式连接 SQLite
DATABASE_URL = "sqlite+aiosqlite:///./customs_audit.db"

# 2. 创建异步引擎 (Engine)
# echo=True 表示会在控制台打印出它执行的 SQL 语句，方便你调试学习
engine = create_async_engine(DATABASE_URL, echo=False)

# 3. 创建会话工厂 (SessionLocal)
# 以后每次要操作数据库，都找它要一个 "session" (会话)
AsyncSessionLocal = async_sessionmaker(bind=engine, expire_on_commit=False)

# 4. 初始化数据库函数
async def init_db():
    """
    程序启动时运行一次，如果表不存在，就自动创建表
    """
    async with engine.begin() as conn:
        # 按照 models.py 里的定义，创建所有表
        await conn.run_sync(Base.metadata.create_all)
    print("[Database] Database tables initialized")


# 5. 依赖注入函数：获取异步会话
async def get_async_session() -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI 依赖注入：用于在路由中获取数据库会话
    用法：
        async with get_async_session() as db:
            # 数据库操作
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()