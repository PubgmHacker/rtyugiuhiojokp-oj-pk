"""Рассылка через бота: постановка задачи в админке (/api/admin/broadcast).

Что закрепляется:

* создание пишет строку dating_broadcasts (queued), аудит «broadcast» и
  публикует событие боту В ЭТОМ порядке — строка коммитится до publish,
  иначе бот мог бы получить событие раньше, чем увидит задачу;
* валидация: пустой текст, текст длиннее лимита Telegram С УЧЁТОМ
  экранирования (бот шлёт через html.escape), кривой сегмент — 400;
* Redis лёг — статус error и 503, а не вечный queued;
* список отдаёт свежие сверху.

Сама отправка живёт в боте (bot/services/broadcast.py) — у него нет тестов,
API закрепляет свою половину контракта.
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

АДМИН = SimpleNamespace(id="adm", role="admin")


async def _база(monkeypatch):
    from sqlalchemy.ext.asyncio import (
        AsyncSession, async_sessionmaker, create_async_engine,
    )
    from sqlalchemy.pool import StaticPool

    import database.connection as dbc
    from models.models import AdminAuditLog, Broadcast, Profile

    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
    фабрика = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        for модель in (Profile, Broadcast, AdminAuditLog):
            await conn.run_sync(модель.__table__.create)
    monkeypatch.setattr(dbc, "async_session_factory", фабрика)
    return фабрика


class _Редис:
    """Считает publish; поднятый flag роняет соединение."""

    def __init__(self, сломан=False):
        self.сломан = сломан
        self.публикации: list[tuple[str, str]] = []

    async def publish(self, канал, тело):
        if self.сломан:
            raise ConnectionError("redis лёг")
        self.публикации.append((канал, тело))


@pytest.fixture
def редис(monkeypatch):
    import services.realtime as realtime

    r = _Редис()

    async def _get_redis():
        return r

    monkeypatch.setattr(realtime, "get_redis", _get_redis)
    return r


async def _создать(фабрика, text, segment="all"):
    from routers.admin import BroadcastCreate, create_broadcast

    async with фабрика() as session:
        return await create_broadcast(
            BroadcastCreate(text=text, segment=segment),
            user=АДМИН, session=session,
        )


async def test_создание_пишет_строку_аудит_и_событие(monkeypatch, редис):
    from sqlalchemy import select

    from models.models import AdminAuditLog, Broadcast, Profile

    фабрика = await _база(monkeypatch)
    async with фабрика() as session:
        session.add(Profile(user_id="adm", display_name="Настя"))
        await session.commit()

    ответ = await _создать(фабрика, "  Всем привет!  ")
    assert ответ.status == "queued"
    assert ответ.text == "Всем привет!", "текст обрезается по краям"
    assert ответ.created_by_name == "Настя"
    assert (ответ.total, ответ.sent, ответ.failed) == (0, 0, 0)

    async with фабрика() as session:
        строка = (await session.execute(select(Broadcast))).scalars().one()
        assert (строка.id, строка.segment) == (ответ.id, "all")

        аудит = (await session.execute(select(AdminAuditLog))).scalars().one()
        assert аудит.action == "broadcast"
        assert аудит.details == {
            "broadcast_id": ответ.id, "segment": "all", "chars": 12,
        }

    (канал, тело), = редис.публикации
    assert канал == "dating:bot:events"
    assert json.loads(тело) == {"type": "broadcast", "broadcast_id": ответ.id}


async def test_валидация_текста_и_сегмента(monkeypatch, редис):
    фабрика = await _база(monkeypatch)

    with pytest.raises(HTTPException) as ошибка:
        await _создать(фабрика, "   ")
    assert ошибка.value.status_code == 400

    # 900 амперсандов — 900 символов, но после html.escape это 4500 > 4096:
    # лимит Telegram меряется по тому тексту, который реально уйдёт
    with pytest.raises(HTTPException) as ошибка:
        await _создать(фабрика, "&" * 900)
    assert ошибка.value.status_code == 400
    assert "длинно" in ошибка.value.detail.lower()

    with pytest.raises(HTTPException) as ошибка:
        await _создать(фабрика, "привет", segment="premium")
    assert ошибка.value.status_code == 400

    assert редис.публикации == [], "невалидное не будит бота"


async def test_редис_упал_статус_error_и_503(monkeypatch):
    from sqlalchemy import select

    import services.realtime as realtime
    from models.models import Broadcast

    фабрика = await _база(monkeypatch)

    async def _сломанный():
        return _Редис(сломан=True)

    monkeypatch.setattr(realtime, "get_redis", _сломанный)

    with pytest.raises(HTTPException) as ошибка:
        await _создать(фабрика, "привет")
    assert ошибка.value.status_code == 503

    async with фабрика() as session:
        строка = (await session.execute(select(Broadcast))).scalars().one()
        assert строка.status == "error", "вечный queued хуже честного error"


async def test_список_свежие_сверху(monkeypatch, редис):
    from datetime import datetime, timedelta, timezone

    from sqlalchemy import update

    from models.models import Broadcast
    from routers.admin import list_broadcasts

    фабрика = await _база(monkeypatch)
    первый = await _создать(фабрика, "первая")
    # Секундной точности server_default мало, когда обе строки рождаются в
    # одном тесте, — отодвигаем первую в прошлое руками
    async with фабрика() as session:
        await session.execute(
            update(Broadcast).where(Broadcast.id == первый.id).values(
                created_at=datetime.now(timezone.utc).replace(tzinfo=None)
                - timedelta(minutes=1)
            )
        )
        await session.commit()
    второй = await _создать(фабрика, "вторая, тест", segment="test")

    async with фабрика() as session:
        список = await list_broadcasts(page=1, limit=20, user=АДМИН, session=session)
    assert [б.id for б in список] == [второй.id, первый.id]
    assert список[0].segment == "test"

    async with фабрика() as session:
        хвост = await list_broadcasts(page=2, limit=1, user=АДМИН, session=session)
    assert [б.id for б in хвост] == [первый.id]


def test_маршруты_в_схеме(openapi):
    создание = openapi["paths"]["/api/admin/broadcast"]["post"]
    схема = создание["responses"]["200"]["content"]["application/json"]["schema"]
    assert схема["$ref"].endswith("BroadcastOut")
    assert "get" in openapi["paths"]["/api/admin/broadcasts"]
