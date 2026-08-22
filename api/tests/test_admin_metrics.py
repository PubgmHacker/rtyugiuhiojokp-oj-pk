"""Метрики админки (/api/admin/metrics): активность, retention, выручка.

Что закрепляется:

* DAU/WAU/MAU считаются по last_seen_at (вход в мини-апп), stickiness —
  их отношение, и пустая база не делит на ноль;
* retention — 8 недельных когорт по created_at: dN — «вернулся спустя
  N дней или позже», сессия регистрации возвратом не считается, а окно,
  которое ещё не дожило до N дней, отдаёт None, а не заниженную долю;
* выручка группируется по валютам, строки без суммы (старый журнал,
  App Store) не считаются, 30-дневное окно отсекает старые платежи,
  revenue_since — момент самого раннего платежа с суммой.

Даты вставляются naive UTC — как их пишет server_default в SQLite;
endpoint обязан переварить и их, и aware из кода.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

АДМИН = SimpleNamespace(id="adm", role="admin")


async def _база(monkeypatch):
    from sqlalchemy.ext.asyncio import (
        AsyncSession, async_sessionmaker, create_async_engine,
    )
    from sqlalchemy.pool import StaticPool

    import database.connection as dbc
    from models.models import ProcessedPayment, User

    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
    фабрика = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        for модель in (User, ProcessedPayment):
            await conn.run_sync(модель.__table__.create)
    monkeypatch.setattr(dbc, "async_session_factory", фабрика)
    return фабрика


def _naive(dt: datetime) -> datetime:
    """Как хранит SQLite server_default — без tzinfo."""
    return dt.replace(tzinfo=None)


async def _метрики(фабрика):
    from routers.admin import get_admin_metrics

    async with фабрика() as session:
        return await get_admin_metrics(user=АДМИН, session=session)


async def test_пустая_база_не_падает(monkeypatch):
    фабрика = await _база(monkeypatch)
    метрики = await _метрики(фабрика)

    assert (метрики.dau, метрики.wau, метрики.mau) == (0, 0, 0)
    assert метрики.stickiness == 0.0, "деление на пустой mau"
    assert метрики.revenue == []
    assert метрики.revenue_since is None
    assert len(метрики.cohorts) == 8
    for когорта in метрики.cohorts:
        assert когорта.size == 0
        assert (когорта.d1, когорта.d7, когорта.d30) == (None, None, None)


async def test_активность_и_прилипчивость(monkeypatch):
    from models.models import User

    фабрика = await _база(monkeypatch)
    now = datetime.now(timezone.utc)
    async with фабрика() as session:
        session.add_all([
            User(id="час", telegram_id=1, last_seen_at=_naive(now - timedelta(hours=1))),
            User(id="3дня", telegram_id=2, last_seen_at=_naive(now - timedelta(days=3))),
            User(id="20дней", telegram_id=3, last_seen_at=_naive(now - timedelta(days=20))),
            User(id="40дней", telegram_id=4, last_seen_at=_naive(now - timedelta(days=40))),
            User(id="никогда", telegram_id=5, last_seen_at=None),
        ])
        await session.commit()

    метрики = await _метрики(фабрика)
    assert (метрики.dau, метрики.wau, метрики.mau) == (1, 2, 3)
    assert метрики.stickiness == round(1 / 3, 3)


async def test_когорты_возвраты_и_окна(monkeypatch):
    from models.models import User

    фабрика = await _база(monkeypatch)
    now = datetime.now(timezone.utc)
    понедельник = now.replace(
        hour=0, minute=0, second=0, microsecond=0
    ) - timedelta(days=now.weekday())
    старт = понедельник - timedelta(weeks=7)

    # Когорта 0 — все окна давно закрыты (от старта прошло 49+ дней)
    к0 = старт + timedelta(hours=1)
    # Когорта 4 — d1/d7 закрыты при любом дне недели, d30 ещё нет
    к4 = старт + timedelta(weeks=4, hours=1)
    # Когорта 7 — текущая неделя, не закрыто ни одно окно
    к7 = понедельник + timedelta(hours=1)

    def _юзер(uid, tg, created, вернулся_через=None):
        seen = None if вернулся_через is None else created + вернулся_через
        return User(
            id=uid, telegram_id=tg,
            created_at=_naive(created),
            last_seen_at=_naive(seen) if seen else None,
        )

    async with фабрика() as session:
        session.add_all([
            _юзер("а", 1, к0, timedelta(days=2)),    # d1
            _юзер("б", 2, к0, timedelta(days=10)),   # d1+d7
            _юзер("в", 3, к0, timedelta(days=35)),   # d1+d7+d30
            _юзер("г", 4, к0),                        # не вернулся
            _юзер("д", 5, к4, timedelta(0)),          # сессия регистрации — не возврат
            _юзер("е", 6, к4, timedelta(days=3)),     # d1
            _юзер("ж", 7, к7),
            # Старше восьми недель — в когорты не входит
            _юзер("з", 8, старт - timedelta(days=10), timedelta(days=2)),
        ])
        await session.commit()

    метрики = await _метрики(фабрика)
    когорты = метрики.cohorts

    assert [к.week for к in когорты] == [
        (старт + timedelta(weeks=i)).strftime("%Y-%m-%d") for i in range(8)
    ]

    assert когорты[0].size == 4
    assert (когорты[0].d1, когорты[0].d7, когорты[0].d30) == (0.75, 0.5, 0.25)

    assert когорты[4].size == 2
    assert (когорты[4].d1, когорты[4].d7) == (0.5, 0.0)
    assert когорты[4].d30 is None, "окно d30 когорты ещё не закрыто"

    assert когорты[7].size == 1
    assert (когорты[7].d1, когорты[7].d7, когорты[7].d30) == (None, None, None)

    for i in (1, 2, 3, 5, 6):
        assert когорты[i].size == 0
        assert (когорты[i].d1, когорты[i].d7, когорты[i].d30) == (None, None, None)


async def test_выручка_по_валютам(monkeypatch):
    from models.models import ProcessedPayment, User

    фабрика = await _база(monkeypatch)
    now = datetime.now(timezone.utc)
    давно = _naive(now - timedelta(days=40)).replace(microsecond=0)

    async with фабрика() as session:
        session.add_all([
            User(id="u1", telegram_id=1),
            User(id="u2", telegram_id=2),
            User(id="u3", telegram_id=3),
        ])
        session.add_all([
            ProcessedPayment(
                provider="stars", external_id="p1", user_id="u1",
                days=30, amount=100, currency="XTR",
            ),
            ProcessedPayment(
                provider="stars", external_id="p2", user_id="u2",
                days=30, amount=50, currency="XTR",
            ),
            # Старше 30 дней: в total входит, в окно — нет
            ProcessedPayment(
                provider="stars", external_id="p3", user_id="u1",
                days=30, amount=200, currency="XTR", created_at=давно,
            ),
            ProcessedPayment(
                provider="sbp", external_id="p4", user_id="u1",
                days=30, amount=12900, currency="RUB",
            ),
            # Без суммы (App Store, старый журнал) — не выручка
            ProcessedPayment(
                provider="appstore", external_id="p5", user_id="u3", days=30,
            ),
        ])
        await session.commit()

    метрики = await _метрики(фабрика)

    assert [строка.currency for строка in метрики.revenue] == ["RUB", "XTR"]

    rub, xtr = метрики.revenue
    assert (rub.count_total, rub.amount_total, rub.payers_total) == (1, 12900, 1)
    assert (rub.count_30d, rub.amount_30d) == (1, 12900)

    assert (xtr.count_total, xtr.amount_total) == (3, 350)
    assert xtr.payers_total == 2, "u1 платил дважды, но человек один"
    assert (xtr.count_30d, xtr.amount_30d) == (2, 150), "старый платёж вне окна"

    assert метрики.revenue_since is not None
    assert метрики.revenue_since.replace(tzinfo=None) == давно


def test_маршрут_в_схеме(openapi):
    метрики = openapi["paths"]["/api/admin/metrics"]["get"]
    схема = метрики["responses"]["200"]["content"]["application/json"]["schema"]
    assert схема["$ref"].endswith("AdminMetrics")
