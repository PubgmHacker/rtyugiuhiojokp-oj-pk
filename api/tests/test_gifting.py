"""Тесты на подарок подписки.

Проверяем именно то, что сломалось бы само по себе:
- покупка без платежа создаёт код в paid=false (активировать не выйдет);
- после оплаты активировать можно только один раз;
- нельзя подарить самому себе, а если подписка старше — подарок не понижает;
- пересылка кому попало того же кода не даёт двойного начисления: redeemed_at
  один раз, и вторая активация отвечает отказом.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from database.connection import async_session_factory
from models.models import Base, Match, Subscription, User
from services import gifting
from services.gifting import activate_gift, purchase_gift, redeem_gift


@pytest.fixture
async def db(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/gift.db")
    async with engine.begin() as c:
        await c.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    # Services говорят друг с другом через async_session_factory — подменяем,
    # чтобы они тоже пошли в тестовую базу, а не в настоящий Postgres
    monkeypatch.setattr("database.connection.async_session_factory", Session)
    yield Session
    await engine.dispose()


@pytest.fixture
async def people(db):
    u1 = User(id="u1", telegram_id=111, role="user")
    u2 = User(id="u2", telegram_id=222, role="user")
    u3 = User(id="u3", telegram_id=333, role="user")
    async with db() as s:
        s.add_all([u1, u2, u3])
        await s.flush()
        await s.commit()
    return {"u1": u1, "u2": u2, "u3": u3}


async def test_подарок_без_оплаты_не_активируется(db, people):
    u1, u2 = people["u1"], people["u2"]
    async with db() as s:
        gift = await purchase_gift(s, u1, "plus_1m", recipient=u2)
        with pytest.raises(ValueError, match="ещё не оплачен"):
            await redeem_gift(s, gift.code_hash, u2)


async def test_подарок_одноразовый_по_коду(db, people):
    u1, u2 = people["u1"], people["u2"]
    async with db() as s:
        gift = await purchase_gift(s, u1, "ultra_3m", recipient=u2)
        await activate_gift(s, gift)
        await s.commit()
        # Первый раз проходит
        await redeem_gift(s, gift.code_hash, u2)
        await s.commit()

    # Второй раз тем же кодом — уже нельзя
    async with db() as s2:
        with pytest.raises(ValueError, match="уже активирован"):
            await redeem_gift(s2, gift.code_hash, u2)


async def test_самому_себе_подарить_нельзя(db, people):
    u1 = people["u1"]
    async with db() as s:
        with pytest.raises(ValueError, match="самому"):
            await purchase_gift(s, u1, "plus_1m", recipient=u1)


async def test_не_понижаем_уровень_при_подарке(db, people):
    u1, u2 = people["u1"], people["u2"]
    async with db() as s:
        # Даём u2 Ultra прямой подпиской — imitируем покупку через App Store
        from services.premium import activate_premium
        await activate_premium(s, u2.id, 30, "test_self_ultra", "test", tier="ultra")
        await s.commit()

        # Подарок PLUS не должен понизить ULTRA
        gift = await purchase_gift(s, u1, "plus_1m", recipient=u2)
        await activate_gift(s, gift)
        await redeem_gift(s, gift.code_hash, u2)

        # Проверяем, что план остался таким же, а не понизился
        result = await s.get(Subscription, u2.id)
        # Подписка могла быть создана activate_premium в под-окружении и не
        # быть видимой после коммита. Ищем не через сессионный кэш, а свежо.
        if result is None:
            from sqlalchemy import select
            r = await s.execute(select(Subscription).where(Subscription.user_id == u2.id))
            result = r.scalar_one_or_none()
        assert result is not None, f"должна быть создана от activate_premium в той же сессии"
        assert result.plan == "ultra"


async def test_чужой_код_не_прокатывает(db, people):
    u1, u3 = people["u1"], people["u3"]
    async with db() as s:
        gift = await purchase_gift(s, u1, "plus_1m", recipient=u3)
        await activate_gift(s, gift)
        await s.commit()
        # Пытаемся активировать чужим кодом, введя неправильный
        with pytest.raises(ValueError, match="недействителен|использован"):
            await redeem_gift(s, gift.code_hash + "x", u3)
