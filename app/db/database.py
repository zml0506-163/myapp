from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from app.core.config import settings

# 数据库 URL 需要用异步驱动
# SQLite: "sqlite+aiosqlite:///./test.db"
# PostgreSQL: "postgresql+asyncpg://user:pass@localhost/db"
# MySQL: "mysql+aiomysql://user:pass@localhost/db"

engine = create_async_engine(
    settings.db_url,
    echo=False,
    pool_size=20,
    max_overflow=40,
    pool_timeout=30,
    pool_recycle=1800,
    pool_pre_ping=True,
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    expire_on_commit=False,
    autoflush=False,
    autocommit=False,
    class_=AsyncSession
)

# 依赖注入
async def get_db() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()  # 自动提交成功的事务
        except Exception:
            await session.rollback()  # 自动回滚失败的事务
            raise
        finally:
            await session.close()  # 确保关闭


@asynccontextmanager
async def get_db_session():
    """获取独立的数据库会话（用完自动关闭）"""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()