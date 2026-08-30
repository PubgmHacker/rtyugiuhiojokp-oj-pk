"""Ремонт легаси-схемы: колонки, добавленные ревизиями, должны появляться.

Сценарий из прода: база размечена до Alembic — create_all поднял таблицы,
схема штампуется как head без прогона цепочки, и каждая колонка из новых
ревизий (videos, email, apple_id…) на существующих таблицах отсутствует.
Любое чтение модели падает UndefinedColumn-ом, для человека это «не удалось
войти» у всех сразу. `_догнать_колонки` достраивает недостающее по моделям —
здесь проверяем именно его, на живой базе в файле.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import inspect as sa_inspect
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from main import _догнать_колонки


@pytest.fixture
async def легаси_база(tmp_path: Path):
    """База со схемой, из которой удалены «поздние» колонки моделей."""
    from models.models import Base

    файл = tmp_path / f"legacy-{uuid.uuid4().hex}.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{файл}")
    async with engine.begin() as c:
        await c.run_sync(Base.metadata.create_all)

    # Выкидываем колонки, которые в реальной истории появлялись ревизиями
    # позже начальной схемы: именно их отсутствие валило вход. SQLite не
    # даёт дропать колонки под UNIQUE-индексом (apple_id, email), поэтому
    # берём неиндексированные поздние колонки — механика та же.
    for stmt in (
        "ALTER TABLE dating_profiles DROP COLUMN videos",
        "ALTER TABLE dating_profiles DROP COLUMN sticker",
        "ALTER TABLE dating_profiles DROP COLUMN decor",
        "ALTER TABLE dating_profiles DROP COLUMN app_theme",
        "ALTER TABLE dating_users DROP COLUMN locale",
    ):
        async with engine.begin() as conn:
            await conn.execute(text(stmt))

    yield engine

    await engine.dispose()


async def _колонки(engine, таблица: str) -> set[str]:
    """Имена колонок таблицы — через асинхронное соединение."""
    async with engine.connect() as conn:
        return await conn.run_sync(
            lambda c: {col["name"] for col in sa_inspect(c).get_columns(таблица)}
        )


@pytest.mark.anyio
async def test_ремонт_возвращает_удалённые_колонки(легаси_база):
    добавлено = await _догнать_колонки(легаси_база)

    assert добавлено >= 5  # videos, sticker, decor, app_theme, locale — минимум

    колонки_профилей = await _колонки(легаси_база, "dating_profiles")
    колонки_юзеров = await _колонки(легаси_база, "dating_users")
    assert "videos" in колонки_профилей
    assert "locale" in колонки_юзеров

    # Повторный запуск — no-op: ремонт идемпотентен
    снова = await _догнать_колонки(легаси_база)
    assert снова == 0


@pytest.mark.anyio
async def test_отремонтированная_база_читает_модели(легаси_база):
    """После ремонта запись и чтение модели работают — то есть логин жив."""
    from models.models import Profile, User

    await _догнать_колонки(легаси_база)

    Session = async_sessionmaker(легаси_база, expire_on_commit=False)
    async with Session() as s:
        s.add(User(telegram_id=424242, role="user"))
        await s.flush()
        юзер = (
            await s.execute(select(User).where(User.telegram_id == 424242))
        ).scalar_one()
        s.add(Profile(user_id=юзер.id, display_name="Аня"))
        await s.commit()

        анкета = (
            await s.execute(select(Profile).where(Profile.user_id == юзер.id))
        ).scalar_one()
        assert анкета.videos == []  # default модели применился
        assert анкета.display_name == "Аня"
        assert юзер.created_at is not None
