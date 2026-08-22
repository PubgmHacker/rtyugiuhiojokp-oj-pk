"""Очередь верификации в админке (GET /api/admin/verification-queue).

Что закрепляется:

* в очереди — неверифицированные и незабаненные с хотя бы одним отказом за
  окно days. Это единственный ручной участок верификации: кадры проверки —
  биометрия и не хранятся, админ решает по фото анкеты и причинам отказов AI
  (ручкой set-verified, у неё свои тесты в test_admin_audit);
* агрегаты честные: попытки и отказы считаются за окно, отказы за сутки —
  отдельным счётчиком (виден упор в суточный лимит), последняя попытка даёт
  статус, причину и провайдера;
* сортировка «больше отказов — выше», страницы работают;
* окно days отсекает старые попытки: очередь рассасывается сама, отдельного
  статуса «разобрано» нет нарочно.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

АДМИН = SimpleNamespace(id="adm", role="admin")
СЕЙЧАС = datetime.now(timezone.utc).replace(tzinfo=None)


async def _база(monkeypatch):
    from sqlalchemy.ext.asyncio import (
        AsyncSession, async_sessionmaker, create_async_engine,
    )
    from sqlalchemy.pool import StaticPool

    import database.connection as dbc
    from models.models import Profile, User, VerificationAttempt

    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
    фабрика = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        for модель in (User, Profile, VerificationAttempt):
            await conn.run_sync(модель.__table__.create)
    monkeypatch.setattr(dbc, "async_session_factory", фабрика)
    return фабрика


def _человек(uid, *, tg, имя="", verified=False, banned=False, **профиль):
    from models.models import Profile, User

    return [
        User(id=uid, telegram_id=tg, is_verified=verified, is_banned=banned),
        Profile(user_id=uid, display_name=имя, **профиль),
    ]


def _попытка(uid, status, *, дней_назад=0.0, reason="", provider="builtin"):
    from models.models import VerificationAttempt

    return VerificationAttempt(
        user_id=uid, poses=[], status=status, reason=reason, provider=provider,
        created_at=СЕЙЧАС - timedelta(days=дней_назад),
    )


async def _очередь(фабрика, **правки):
    from routers.admin import verification_queue

    # Прямой вызов минует FastAPI, Query-дефолты не подставляются —
    # все параметры передаются явно
    параметры = dict(days=14, page=1, limit=50, user=АДМИН)
    параметры.update(правки)
    async with фабрика() as session:
        return await verification_queue(**параметры, session=session)


async def test_застрявший_виден_с_агрегатами_и_последней_причиной(monkeypatch):
    from routers.verification import СУТОЧНЫЙ_ЛИМИТ_ОТКАЗОВ

    фабрика = await _база(monkeypatch)
    async with фабрика() as session:
        session.add_all(_человек(
            "u1", tg=1, имя="Ума", city="Тверь",
            photos=["a.jpg", "b.jpg"],
            birth_date=СЕЙЧАС - timedelta(days=25 * 365),
        ))
        session.add_all([
            _попытка("u1", "issued", дней_назад=5),
            _попытка("u1", "rejected", дней_назад=2, reason="плохой свет"),
            _попытка(
                "u1", "rejected", дней_назад=0.1,
                reason="Лицо на кадрах не совпало с фото анкеты",
                provider="sumsub",
            ),
        ])
        await session.commit()

    (строка,) = await _очередь(фабрика)
    assert строка.user_id == "u1"
    assert (строка.display_name, строка.city) == ("Ума", "Тверь")
    assert строка.photos == ["a.jpg", "b.jpg"]
    assert строка.age == 25
    assert (строка.attempts_total, строка.rejected_total) == (3, 2)
    assert строка.rejected_24h == 1, "отказ двухдневной давности в сутки не входит"
    assert строка.daily_limit == СУТОЧНЫЙ_ЛИМИТ_ОТКАЗОВ
    assert строка.last_status == "rejected"
    assert строка.last_reason == "Лицо на кадрах не совпало с фото анкеты"
    assert строка.last_provider == "sumsub"
    assert строка.last_attempt_at is not None


async def test_верифицированные_забаненные_и_без_отказов_скрыты(monkeypatch):
    """Очередь — «кому нужна помощь», а не журнал всех попыток."""
    фабрика = await _база(monkeypatch)
    async with фабрика() as session:
        session.add_all(_человек("застрял", tg=1, имя="Ума"))
        session.add_all(_человек("прошёл", tg=2, verified=True))
        session.add_all(_человек("забанен", tg=3, banned=True))
        session.add_all(_человек("не_пробовал", tg=4))
        session.add_all([
            _попытка("застрял", "rejected", дней_назад=1),
            # Прошёл сам после отказа — помощь уже не нужна
            _попытка("прошёл", "rejected", дней_назад=2),
            _попытка("прошёл", "approved", дней_назад=1),
            # Забаненный проверку не пройдёт — его разбор в жалобах
            _попытка("забанен", "rejected", дней_назад=1),
            # Висящее задание без единого отказа — человек ещё не споткнулся
            _попытка("не_пробовал", "issued", дней_назад=1),
        ])
        await session.commit()

    очередь = await _очередь(фабрика)
    assert [с.user_id for с in очередь] == ["застрял"]


async def test_сортировка_по_отказам_и_страницы(monkeypatch):
    фабрика = await _база(monkeypatch)
    async with фабрика() as session:
        for i, uid in enumerate(["один", "три", "два"], start=1):
            session.add_all(_человек(uid, tg=i))
        session.add_all([
            _попытка("один", "rejected", дней_назад=1),
            *[_попытка("три", "rejected", дней_назад=д) for д in (1, 2, 3)],
            *[_попытка("два", "rejected", дней_назад=д) for д in (1, 2)],
        ])
        await session.commit()

    очередь = await _очередь(фабрика)
    assert [с.user_id for с in очередь] == ["три", "два", "один"], "больше отказов — выше"
    assert [с.rejected_total for с in очередь] == [3, 2, 1]

    хвост = await _очередь(фабрика, page=2, limit=2)
    assert [с.user_id for с in хвост] == ["один"]


async def test_попытки_за_окном_не_считаются(monkeypatch):
    """Очередь рассасывается сама: попытки ушли за окно — строка исчезла."""
    фабрика = await _база(monkeypatch)
    async with фабрика() as session:
        session.add_all(_человек("u1", tg=1))
        session.add(_попытка("u1", "rejected", дней_назад=20, reason="давно"))
        await session.commit()

    assert await _очередь(фабрика, days=14) == []

    (строка,) = await _очередь(фабрика, days=30)
    assert строка.rejected_total == 1
    assert строка.rejected_24h == 0


def test_маршрут_в_схеме(openapi):
    ручка = openapi["paths"]["/api/admin/verification-queue"]["get"]
    схема = ручка["responses"]["200"]["content"]["application/json"]["schema"]
    assert схема["items"]["$ref"].endswith("AdminVerificationQueueItem")
