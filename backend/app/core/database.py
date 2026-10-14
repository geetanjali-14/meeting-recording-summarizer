from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import get_settings


def get_engine() -> AsyncEngine:
    """Creates and returns the async SQLAlchemy engine using psycopg."""
    settings = get_settings()

    engine_kwargs: dict[str, Any] = {
        "echo": settings.DEBUG,
        "pool_pre_ping": True,
    }

    if not settings.DATABASE_URL.startswith("sqlite"):
        engine_kwargs.update(
            {
                "pool_size": settings.DATABASE_POOL_SIZE,
                "max_overflow": settings.DATABASE_MAX_OVERFLOW,
                "pool_timeout": settings.DATABASE_POOL_TIMEOUT_SECONDS,
                "pool_recycle": settings.DATABASE_POOL_RECYCLE_SECONDS,
                "connect_args": {"prepare_threshold": None},
            }
        )

    return create_async_engine(settings.DATABASE_URL, **engine_kwargs)


engine = get_engine()

async_session_factory = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


@asynccontextmanager
async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Context manager for obtaining an async database session."""
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
