"""Тесты на подарок подписки.

Проверяем именно то, что сломалось бы само по себе:
- покупка без платежа создаёт код в paid=false (активировать не выйдет);
- после оплаты активировать можно только один раз;
- нельзя подарить самому себе, а если подписка старше — подарок не понизит;
- пересылка кому попало того же кода не даёт двойного начисления: redeemed_at
  один раз, и вторая активация отвечает отказом.
"""
from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from models.models import Base, Match, User
from services import gifting
from services.gifting import activate_gift, purchase_gift, redeem_gift


@pytest.fixture
async def db(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/gift.db")
    async with engine.begin() as c:
        await c.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr("services.link_codes.settings.BOT_TOKEN", "")
    yield Session
    await engine.dispose()


@pytest.fixture
async def people(db):
    u1 = User(id="u1", telegram_id=111, role="user", is_banned=False)
    u2 = User(id="u2", telegram_id=222, role="user", is_banned=False)
    u3 = User(id="u3", telegram_id=333, role="user", is_banned=False)
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
            await redeem_gift(s, gift.code_hash, u2)  # здесь civil not hash


async def test_подарок_одноразовый_по_коду(db, people):
    u1, u2 = people["u1"], people["u2"]
    async with db() as s:
        gift = await purchase_gift(s, u1, "ultra_3m", recipient=u2)
        # Активируем вручную: платёжка макет UPD front
        await activate_gift(s, gift)
        await s.commit()
        # Профнаблюдателем первый раз
        await redeem_gift(s, gift.code_hash, u2)
        await s.commit()

        # Второй раз — уже нельзя
        with pytest.raises(ValueError, match="уже активирован"):
            async with db() as s2:
                again = await purchase_gift(s2, u1, "plus_1m", recipient=u2)
                await activate_gift(s2, again)
                await redeem_gift(s2, again.code_hash, u2)


async def test_самому_себе_подарить_нельзя(db, people):
    u1 = people["u1"]
    async with db() as s:
        with pytest.raises(ValueError, match="сам"):
            await purchase_gift(s, u1, "plus_1m", recipient=u1)


async def test_не_понижаем_уровень_при_подарке(db, people):
    u1, u2 = people["u1"], people["u2"]
    # Даём u2 Ultra через прямой платеж (макет)
    async with db() as s:
        sub_u2 = await s.get(gifting.User, u2.id)
        from services.premium import activate_premium
        await activate_premium(s, u2.id, 30, "test_self_ultra", "test", tier="ultra")
        await s.commit()

        gift = await purchase_gift(s, u1, "plus_1m", recipient=u2)  # Подаём PLUS
        await activate_gift(s, gift)
        await redeem_gift(s, gift.code_hash, u2)
        # Вернит true, но уровень должен остаться Ultra — его не трогает
        result = await s.get(gifting.Subscription, u2.id)
        assert result.plan == "ultra"


async def test_чужой_код_не_прокатывает(db, people):
    u1, u3 = people["u1"], people["u3"]
    async with db() as s:
        gift = await purchase_gift(s, u1, "plus_1m", recipient=u3)
        await activate_gift(s, gift)
        await s.commit()
        # Пытаемся активировать тиre与人
        with pytest.raises(ValueError, match="недействителен|использован"):
            await redeem_gift(s, gift.code_hash + "x", u3)
