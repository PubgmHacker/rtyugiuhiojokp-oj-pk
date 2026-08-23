"""Тесты на подарок подписки.

Проверяем именно то, что сломалось бы само по себе:
- покупка без платежа создаёт код в paid=false (активировать не выйдет);
- активируется PLAINTEXT-код: в базе лежит хеш, и дыра жила ровно тут —
  сервис сравнивал колонку хеша с сырым вводом, то есть настоящий код не
  подходил никогда, а «кодом» работал сам хеш из дампа базы;
- ввод прощает регистр, пробелы и дефисы — код диктуют голосом;
- после оплаты активировать можно только один раз, кем угодно, но одним;
- подарок ниже действующего уровня не активируется И НЕ СГОРАЕТ: его можно
  отдать другому; равный уровень продлевает срок поверх остатка;
- HTTP-слой /gifts/redeem переводит причины в статусы и не оставляет
  следов на отказе.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from models.models import (
    Base, GiftSubscription, ProcessedPayment, Subscription, User,
)
from services.gifting import (
    GiftError, activate_gift, new_gift_code, purchase_gift, redeem_gift,
)


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


async def _оплаченный(s, buyer, plan_code, code, recipient=None):
    """Купленный и оплаченный подарок с известным plaintext-кодом."""
    gift = await purchase_gift(s, buyer, plan_code, recipient=recipient, code=code)
    await activate_gift(s, gift)
    return gift


async def test_подарок_без_оплаты_не_активируется(db, people):
    u1, u2 = people["u1"], people["u2"]
    async with db() as s:
        await purchase_gift(s, u1, "plus_1m", recipient=u2, code="WWWW23456789")
        with pytest.raises(GiftError, match="ещё не оплачен") as отказ:
            await redeem_gift(s, "WWWW23456789", u2)
        assert отказ.value.reason == "not_paid"


async def test_активируется_плейнтекст_и_прощает_оформление(db, people):
    """Счастливый путь целиком: код, как его прислал друг («wxyz-2345 6789»
    вместо WXYZ23456789), даёт подписку уровня и срока подарка, а в журнале
    платежей остаётся маркер gift_{id} без суммы — деньги учтены покупкой."""
    u1, u2 = people["u1"], people["u2"]
    async with db() as s:
        gift = await _оплаченный(s, u1, "ultra_3m", "WXYZ23456789", recipient=u2)
        await s.commit()

        итог = await redeem_gift(s, " wxyz-2345 6789 ", u2)
        await s.commit()
        assert (итог["tier"], итог["months"], итог["plan"]) == ("ultra", 3, "ultra")

        до = datetime.fromisoformat(итог["expires_at"])
        if до.tzinfo is None:
            до = до.replace(tzinfo=timezone.utc)
        ожидаемо = datetime.now(timezone.utc) + timedelta(days=90)
        assert abs((до - ожидаемо).total_seconds()) < 600

        подписка = (
            await s.execute(select(Subscription).where(Subscription.user_id == u2.id))
        ).scalar_one()
        assert подписка.plan == "ultra"

        маркер = (
            await s.execute(select(ProcessedPayment))
        ).scalars().one()
        assert (маркер.provider, маркер.external_id) == ("gift", f"gift_{gift.id}")
        assert маркер.amount is None, "активация подарка попала бы в выручку дважды"


async def test_хеш_вместо_кода_не_прокатывает(db, people):
    """Регресс дыры: до починки «кодом» работал sha256-хеш из дампа базы,
    а настоящий код не подходил никогда."""
    u1, u2 = people["u1"], people["u2"]
    async with db() as s:
        gift = await _оплаченный(s, u1, "plus_1m", "QQQQ23456789", recipient=u2)
        await s.commit()
        with pytest.raises(GiftError) as отказ:
            await redeem_gift(s, gift.code_hash, u2)
        assert отказ.value.reason == "not_found"


async def test_подарок_одноразовый_по_коду(db, people):
    u1, u2, u3 = people["u1"], people["u2"], people["u3"]
    async with db() as s:
        await _оплаченный(s, u1, "ultra_3m", "EEEE23456789", recipient=u2)
        await s.commit()
        # Первый раз проходит
        await redeem_gift(s, "EEEE23456789", u2)
        await s.commit()

    # Второй раз тем же кодом — уже нельзя, даже другому человеку
    async with db() as s2:
        with pytest.raises(GiftError, match="уже активирован"):
            await redeem_gift(s2, "EEEE23456789", u2)
        with pytest.raises(GiftError, match="уже активирован"):
            await redeem_gift(s2, "EEEE23456789", u3)


async def test_самому_себе_подарить_нельзя(db, people):
    u1 = people["u1"]
    async with db() as s:
        with pytest.raises(ValueError, match="самому"):
            await purchase_gift(s, u1, "plus_1m", recipient=u1)


async def test_ниже_уровня_не_активируется_и_не_сгорает(db, people):
    """Владелец Aurora получает Plus-код: отказ, но код ЦЕЛ — его можно
    активировать после окончания подписки или отдать другому. До починки
    redeemed_at ставился до проверки уровня: код сгорал, подписки не было."""
    u1, u2, u3 = people["u1"], people["u2"], people["u3"]
    async with db() as s:
        from services.premium import activate_premium
        await activate_premium(s, u2.id, 30, "test_self_aurora", "test", tier="aurora")
        gift = await _оплаченный(s, u1, "plus_1m", "RRRR23456789", recipient=u2)
        await s.commit()
        # id — до rollback: откат отвязывает инстанс от сессии
        gift_id = gift.id

        with pytest.raises(GiftError, match="уровень выше") as отказ:
            await redeem_gift(s, "RRRR23456789", u2)
        assert отказ.value.reason == "tier_lower"
        # Отказная ветка вернулась до сжигания — в HTTP-слое транзакцию
        # откатил бы get_session, здесь просто ничего не записано
        await s.rollback()

    async with db() as s2:
        живой = (
            await s2.execute(
                select(GiftSubscription).where(GiftSubscription.id == gift_id)
            )
        ).scalar_one()
        assert живой.redeemed_at is None, "код сгорел бы без начисления"

        # А бесплатный u3 тем же кодом активирует
        u3_свежий = await s2.get(User, u3.id)
        итог = await redeem_gift(s2, "RRRR23456789", u3_свежий)
        assert итог["plan"] == "plus"

        # Aurora у u2 осталась Aurora
        подписка = (
            await s2.execute(select(Subscription).where(Subscription.user_id == u2.id))
        ).scalar_one()
        assert подписка.plan == "aurora"


async def test_равный_уровень_продлевает_поверх_остатка(db, people):
    """Подарить Plus владельцу Plus — это продление: купленное время не
    сгорает, срок растёт от конца текущей подписки, а не от сегодня."""
    u1, u2 = people["u1"], people["u2"]
    async with db() as s:
        from services.premium import activate_premium
        await activate_premium(s, u2.id, 10, "test_self_plus", "test", tier="plus")
        await _оплаченный(s, u1, "plus_1m", "TTTT23456789", recipient=u2)
        await s.commit()

        итог = await redeem_gift(s, "TTTT23456789", u2)
        до = datetime.fromisoformat(итог["expires_at"])
        if до.tzinfo is None:
            до = до.replace(tzinfo=timezone.utc)
        ожидаемо = datetime.now(timezone.utc) + timedelta(days=40)
        assert итог["plan"] == "plus"
        assert abs((до - ожидаемо).total_seconds()) < 600, (
            "продление съело бы оплаченный остаток"
        )


async def test_просроченный_код_отвечает_expired(db, people):
    u1, u2 = people["u1"], people["u2"]
    async with db() as s:
        gift = await _оплаченный(s, u1, "plus_1m", "GGGG23456789", recipient=u2)
        gift.expires_at = datetime(2020, 1, 1)
        await s.commit()
        with pytest.raises(GiftError, match="истёк") as отказ:
            await redeem_gift(s, "GGGG23456789", u2)
        assert отказ.value.reason == "expired"


async def test_чужой_код_не_прокатывает(db, people):
    u3 = people["u3"]
    async with db() as s:
        with pytest.raises(GiftError, match="недействителен"):
            await redeem_gift(s, "нет такого кода", u3)
        with pytest.raises(GiftError, match="недействителен"):
            await redeem_gift(s, "   ", u3)


def test_генерированный_код_без_похожих_знаков():
    """Код диктуют голосом и перепечатывают с картинок: 0/O и 1/I в нём
    неразличимы, поэтому их в алфавите нет. Нормализация ввода (upper,
    без пробелов и дефисов) не должна ломать собственные коды."""
    from services.promo import normalize_code

    for _ in range(50):
        код = new_gift_code()
        assert len(код) == 12
        assert not set(код) & set("0O1I"), f"похожие знаки в коде {код}"
        assert normalize_code(код.lower()) == код


# ════════════════════════════════════════════════════════════════
#  HTTP: /gifts/redeem — статусы отказов и отсутствие следов
# ════════════════════════════════════════════════════════════════


@pytest.fixture
async def живая_база(tmp_path):
    """Настоящая БД: покупатель Боря, получатель Гоша, Вера с Aurora."""
    файл = tmp_path / "gifts_http.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{файл}")
    async with engine.begin() as c:
        await c.run_sync(Base.metadata.create_all)

    Session = async_sessionmaker(engine, expire_on_commit=False)

    боря, гоша, вера = (str(uuid.uuid4()) for _ in range(3))
    async with Session() as s:
        s.add(User(id=боря, telegram_id=1, role="user",
                   last_seen_at=datetime.now(timezone.utc)))
        s.add(User(id=гоша, telegram_id=2, role="user",
                   last_seen_at=datetime.now(timezone.utc)))
        s.add(User(id=вера, telegram_id=3, role="user",
                   last_seen_at=datetime.now(timezone.utc)))
        s.add(Subscription(
            user_id=вера, plan="aurora",
            expires_at=datetime.now(timezone.utc) + timedelta(days=30),
        ))
        await s.commit()

    yield {"engine": engine, "Session": Session, "боря": боря, "гоша": гоша, "вера": вера}
    await engine.dispose()


@pytest.fixture
async def клиент(app, живая_база):
    """Клиент с живой БД. `от_имени` переключает текущего пользователя."""
    from database.connection import get_session
    from middleware.auth import get_current_user

    Session = живая_база["Session"]
    текущий = {"id": живая_база["гоша"]}

    async def _sess():
        async with Session() as s:
            try:
                yield s
                await s.commit()
            except Exception:
                await s.rollback()
                raise

    async def _user():
        async with Session() as s:
            return (
                await s.execute(select(User).where(User.id == текущий["id"]))
            ).scalar_one()

    было = {
        get_session: app.dependency_overrides.get(get_session),
        get_current_user: app.dependency_overrides.get(get_current_user),
    }
    app.dependency_overrides[get_session] = _sess
    app.dependency_overrides[get_current_user] = _user
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as c:
            c.от_имени = lambda uid: текущий.update(id=uid)  # type: ignore[attr-defined]
            yield c
    finally:
        # app — session-scoped: возвращаем ровно то, что было до нас
        for ключ, значение in было.items():
            if значение is None:
                app.dependency_overrides.pop(ключ, None)
            else:
                app.dependency_overrides[ключ] = значение


async def _подарок_в_базе(живая_база, code: str, plan_code: str = "plus_1m",
                          paid: bool = True) -> str:
    """Оплаченный подарок от Бори с известным plaintext-кодом. Вернёт id."""
    Session = живая_база["Session"]
    async with Session() as s:
        боря = await s.get(User, живая_база["боря"])
        gift = await purchase_gift(s, боря, plan_code, code=code)
        if paid:
            await activate_gift(s, gift)
        await s.commit()
        return gift.id


async def test_редим_даёт_подписку_и_переводит_отказы_в_статусы(клиент, живая_база):
    """Счастливый путь: 200 с итоговой подпиской. Отказы: мусор — 404,
    повтор — 409, неоплаченный — 402."""
    гоша = живая_база["гоша"]
    await _подарок_в_базе(живая_база, "HTTP23456789", "ultra_3m")

    клиент.от_имени(гоша)
    r = await клиент.post("/api/gifts/redeem", json={"code": " http-2345 6789 "})
    assert r.status_code == 200, r.text
    тело = r.json()
    assert (тело["tier"], тело["months"], тело["plan"]) == ("ultra", 3, "ultra")
    assert тело["expires_at"]

    # Повтор того же кода — 409, подписка не удвоилась
    r2 = await клиент.post("/api/gifts/redeem", json={"code": "HTTP23456789"})
    assert r2.status_code == 409, r2.text

    r3 = await клиент.post("/api/gifts/redeem", json={"code": "МУСОР"})
    assert r3.status_code == 404

    await _подарок_в_базе(живая_база, "NOPAY2345678", paid=False)
    r4 = await клиент.post("/api/gifts/redeem", json={"code": "NOPAY2345678"})
    assert r4.status_code == 402

    Session = живая_база["Session"]
    async with Session() as s:
        маркеры = (
            await s.execute(select(ProcessedPayment).where(
                ProcessedPayment.provider == "gift"
            ))
        ).scalars().all()
        assert len(маркеры) == 1, "повтор начислил бы подписку второй раз"


async def test_редим_ниже_уровня_409_и_код_жив(клиент, живая_база):
    """Вера с Aurora вводит Plus-код: 409 с человеческим текстом, а код
    остаётся неиспользованным — get_session откатил транзакцию отказа."""
    вера = живая_база["вера"]
    gift_id = await _подарок_в_базе(живая_база, "AURA23456789")

    клиент.от_имени(вера)
    r = await клиент.post("/api/gifts/redeem", json={"code": "AURA23456789"})
    assert r.status_code == 409, r.text
    assert "уровень выше" in r.json()["detail"]

    Session = живая_база["Session"]
    async with Session() as s:
        живой = (
            await s.execute(
                select(GiftSubscription).where(GiftSubscription.id == gift_id)
            )
        ).scalar_one()
        assert живой.redeemed_at is None, "отказ сжёг бы код без начисления"

    # Гоша без подписки активирует тот же код
    клиент.от_имени(живая_база["гоша"])
    r2 = await клиент.post("/api/gifts/redeem", json={"code": "AURA23456789"})
    assert r2.status_code == 200, r2.text
