from __future__ import annotations

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from config import get_settings

settings = get_settings()

# Арифметика пула на запуск: 2 воркера API × (12+18) = 60 соединений
# максимум, плюс пул бота (10+20=30) — итого 90 при дефолтном
# max_connections=100 у Railway Postgres. Поднимать pool_size без
# пересчёта этой суммы нельзя: 101-е соединение Postgres просто отвергнет,
# и это уронит случайный запрос, а не самый жадный.
#
# pool_timeout=10 — очередь за соединением не длиннее десяти секунд:
# лучше отдать 500 одному запросу при исчерпанном пуле, чем копить
# висящие запросы, которые держат память и клиентские таймауты.
# pool_recycle закрывает соединения старше получаса — Railway рвёт
# долгоживущие TCP тихо, pre_ping ловит это, но recycle дешевле.
engine = create_async_engine(
    settings.DATABASE_URL,
    pool_size=settings.DB_POOL_SIZE,
    max_overflow=settings.DB_MAX_OVERFLOW,
    pool_timeout=10,
    pool_recycle=1800,
    pool_pre_ping=True,
    echo=settings.DEBUG,
)

async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_session() -> AsyncSession:
    """Зависимость для FastAPI — выдаёт сессию на каждый запрос."""
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
