from __future__ import annotations

import asyncio
from typing import Optional

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from config import get_settings

settings = get_settings()

# Арифметика пула на запуск: 2 воркера API × (12+18) = 60 соединений
# максимум, плюс журнальный пул (2 × 2 = 4, см. log_session_factory ниже),
# плюс пул бота (10+20=30) — итого 94 при дефолтном max_connections=100
# у Railway Postgres. Поднимать pool_size без пересчёта этой суммы нельзя:
# 101-е соединение Postgres просто отвергнет, и это уронит случайный
# запрос, а не самый жадный.
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

#: Снимок фабрики на момент импорта. Тесты подменяют модульный атрибут
#: async_session_factory на SQLite-фабрику (monkeypatch в test_admin_audit
#: и других) — сравнение с этим снимком отличает подмену от продовой фабрики.
_основная_фабрика = async_session_factory

#: (event loop, фабрика). Кэш привязан к циклу: пул asyncpg держит
#: примитивы asyncio, созданные на первом цикле, и переиспользование
#: фабрики из другого цикла даёт «Future attached to a different loop».
#: В проде цикл один на весь процесс — движок создаётся ровно один раз;
#: в тестах каждый тест живёт на своём цикле и получает свежий движок,
#: а прежний (вместе с мёртвым циклом) забирает сборщик мусора.
_журнальный_кэш: Optional[tuple[object, async_sessionmaker[AsyncSession]]] = None


def log_session_factory() -> async_sessionmaker[AsyncSession]:
    """Фабрика сессий для журнальных записей — ОТДЕЛЬНЫЙ крошечный пул.

    Журнал модерации пишется второй сессией при ещё удерживаемой сессии
    запроса: запись обязана пережить rollback при блокировке, поэтому в
    сессии запроса ей нельзя. Но вторая сессия из ОБЩЕГО пула — это
    самоблокировка под залпом: все соединения розданы обработчикам, каждый
    обработчик держит своё и ждёт второе из пустого пула, отпускает только
    pool_timeout. Смоук 300 юзеров / 100 конкурентных давал p95 в 10 секунд
    и 500-е ровно из-за этого.

    Отдельный пул разрывает цикл: журнальные сессии не конкурируют с
    сессиями запросов за одни соединения. Двух соединений на воркер хватает —
    запись журнала это один INSERT на миллисекунды, а при исчерпании ждём
    не дольше 5 секунд и роняем только журнал (log_moderation глотает сбой),
    не сценарий пользователя.

    Возвращает фабрику, а не сессию: вызывающий делает
    `async with log_session_factory()() as session`.
    """
    global _журнальный_кэш
    # Тестовая подмена: если модульную фабрику заменили (SQLite in-memory
    # со StaticPool), журнал обязан писать через неё же — в тестовой базе
    # нет самоблокировки, зато есть тесты, читающие журнал сразу после
    # запроса. И наоборот: заводить второй движок на :memory: бессмысленно,
    # он не увидит таблиц первого.
    if async_session_factory is not _основная_фабрика:
        return async_session_factory
    цикл = asyncio.get_running_loop()
    if _журнальный_кэш is not None and _журнальный_кэш[0] is цикл:
        return _журнальный_кэш[1]
    движок = create_async_engine(
        settings.DATABASE_URL,
        pool_size=2,
        max_overflow=0,
        pool_timeout=5,
        pool_recycle=1800,
        pool_pre_ping=True,
    )
    фабрика = async_sessionmaker(
        движок,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    _журнальный_кэш = (цикл, фабрика)
    return фабрика


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
