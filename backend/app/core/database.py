from typing import AsyncGenerator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings


def _make_engine():
    """Create a fresh async engine safe for the current event loop."""
    connect_args = {}
    # Disable SSL for local dev — Coolify Postgres serves plaintext
    if settings.ENVIRONMENT == "development":
        connect_args["ssl"] = False

    return create_async_engine(
        settings.DATABASE_URL,
        echo=False,
        future=True,
        pool_pre_ping=True,  # verify connections before checkout
        pool_size=10,
        max_overflow=20,
        pool_timeout=30,
        pool_recycle=1800,  # recycle every 30 minutes
        connect_args=connect_args,
    )


class _SessionFactory:
    """Session factory that creates a fresh engine per event loop.

    asyncpg connection pools are bound to the event loop where they
    were created. Celery tasks call asyncio.run() which creates a new
    loop each time. This factory creates a fresh engine (and pool)
    on every call, so sessions always work in the current loop.
    """

    def __call__(self) -> AsyncSession:
        eng = _make_engine()
        factory = async_sessionmaker(
            bind=eng,
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
        )
        return factory()


AsyncSessionLocal = _SessionFactory()


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()


async def check_db_health() -> bool:
    try:
        eng = _make_engine()
        async with eng.connect() as conn:
            await conn.execute(text("SELECT 1"))
        await eng.dispose()
        return True
    except Exception:
        return False
