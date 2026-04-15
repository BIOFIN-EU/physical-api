from collections.abc import AsyncGenerator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.core.settings import settings


engine: AsyncEngine = create_async_engine(
    settings.database_url,
    pool_pre_ping=True,
)

SessionLocal: async_sessionmaker[AsyncSession] = async_sessionmaker(
    bind=engine,
    autoflush=False,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with SessionLocal() as session:
        yield session


async def init_db() -> None:
    async with engine.begin() as conn:

        # Create schema if it does not exist
        await conn.execute(
            text(f"CREATE SCHEMA IF NOT EXISTS {settings.WORKFLOW_DB_SCHEMA}")
        )

        # Create schema if it does not exist
        await conn.execute(
            text(f"CREATE SCHEMA IF NOT EXISTS {settings.CASE_DATA_DB_SCHEMA}")
        )

        # Create all tables
        await conn.run_sync(Base.metadata.create_all)