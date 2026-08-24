"""Событийная аналитика: девять событий воронки (Блок 4, P0-2).

Аналитики не было вообще — первый же вопрос инвестора или закупщика трафика
(«какая конверсия из /start в покупку?») оставался без ответа. Теперь события
пишутся в свой Postgres (services/analytics.py), и ломаются они там же, где
деньги: повтор вехи не должен задваивать строку (first-touch у bot_start),
повторный зачёт платежа — рисовать вторую покупку, а сбой аналитики — ронять
свайп или начисление.

Точки записи проверяются живьём на SQLite тем же приёмом, что
test_direct_messages.py: настоящие таблицы, HTTP через ASGITransport,
pg_advisory_xact_lock подменён. Бот — subprocess'ом его же интерпретатором
(паттерн test_unban_purchase.py::_в_боте): у него свой зеркальный track_event.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from services.analytics import СОБЫТИЯ, track
from tests.test_unban_purchase import _в_боте


async def _пропустить(_текст):
    return {"blocked": False}


async def _ничего(*_a, **_kw):
    return None


async def _события(Session, user_id: str | None = None, event: str | None = None):
    """Все строки событий (или срез по человеку/событию) — для проверок."""
    from models.models import AnalyticsEvent

    q = select(AnalyticsEvent)
    if user_id is not None:
        q = q.where(AnalyticsEvent.user_id == user_id)
    if event is not None:
        q = q.where(AnalyticsEvent.event == event)
    async with Session() as s:
        return list((await s.execute(q)).scalars())


# ════════════════════════════════════════════════════════════════
#  Семантика track(): once / daily / без дедупа / сбой
# ════════════════════════════════════════════════════════════════

@pytest.fixture
async def база(tmp_path):
    """Живая SQLite и один человек — для прямых вызовов track()."""
    from models.models import Base, User

    файл = tmp_path / "analytics.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{файл}")
    async with engine.begin() as c:
        await c.run_sync(Base.metadata.create_all)

    Session = async_sessionmaker(engine, expire_on_commit=False)
    юзер = str(uuid.uuid4())
    async with Session() as s:
        s.add(User(id=юзер, telegram_id=1, role="user"))
        await s.commit()

    yield {"Session": Session, "юзер": юзер}
    await engine.dispose()


def test_кортеж_событий_ровно_девять():
    """Словарь воронки закреплён: новое событие добавляется осознанно —
    вместе со строкой в docstring и точкой записи, а не тихой константой."""
    assert len(СОБЫТИЯ) == 9
    assert set(СОБЫТИЯ) == {
        "bot_start", "profile_created", "app_open", "first_swipe",
        "first_match", "first_message", "paywall_view",
        "purchase_started", "purchase_completed",
    }


async def test_once_веха_пишется_один_раз_и_хранит_первый_источник(база):
    """first-touch: повторный /start с другой меткой канал не крадёт —
    закупщик видит, какой канал ПРИВЁЛ человека, а не какой был последним."""
    Session, юзер = база["Session"], база["юзер"]

    async with Session() as s:
        await track(s, юзер, "bot_start", {"source": "tiktok"}, once=True)
        await s.commit()
    async with Session() as s:
        await track(s, юзер, "bot_start", {"source": "telegram_ads"}, once=True)
        await s.commit()

    (строка,) = await _события(Session, юзер, "bot_start")
    assert строка.props["source"] == "tiktok", "второй /start украл источник"
    assert строка.dedup_key == f"{юзер}:bot_start"


async def test_daily_одна_строка_на_день(база):
    """app_open — сетка D1/D7: сто заходов за день дают одну строку,
    иначе таблица пухла бы от каждого пинга клиента."""
    Session, юзер = база["Session"], база["юзер"]

    for _ in range(3):
        async with Session() as s:
            await track(s, юзер, "app_open", daily=True)
            await s.commit()

    (строка,) = await _события(Session, юзер, "app_open")
    день = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    assert строка.dedup_key == f"{юзер}:app_open:{день}"


async def test_без_дедупа_каждая_попытка_отдельной_строкой(база):
    """purchase_started считает ПОПЫТКИ: три выставленных счёта — три строки,
    по разрыву с purchase_completed видно брошенные счета."""
    Session, юзер = база["Session"], база["юзер"]

    for план in ("plus_1m", "plus_1m", "ultra_1m"):
        async with Session() as s:
            await track(s, юзер, "purchase_started",
                        {"provider": "stars", "plan": план})
            await s.commit()

    строки = await _события(Session, юзер, "purchase_started")
    assert len(строки) == 3
    assert all(с.dedup_key is None for с in строки)


async def test_сбой_аналитики_не_ломает_бизнес_транзакцию(база):
    """Свайп важнее строки в отчёте: несериализуемые props (или лежащая
    таблица) — warning в лог, а бизнес-изменения того же запроса коммитятся."""
    from models.models import User

    Session, юзер = база["Session"], база["юзер"]

    async with Session() as s:
        # set() не сериализуется в JSON — flush события падает внутри track
        await track(s, юзер, "first_swipe", {"мусор": {1, 2}})
        # ...а бизнес-запись в той же сессии обязана дойти до базы
        s.add(User(id="выживший", telegram_id=2, role="user"))
        await s.commit()

    async with Session() as s:
        выжил = (await s.execute(
            select(User).where(User.id == "выживший")
        )).scalar_one_or_none()
    assert выжил is not None, "сбой аналитики откатил бизнес-транзакцию"
    assert await _события(Session, юзер, "first_swipe") == []


async def test_повторный_зачёт_платежа_не_рисует_вторую_покупку(база):
    """activate_premium — единая точка purchase_completed для App Store,
    промо и подарков: props.provider отличает деньги от promo/gift, а
    идемпотентность журнала платежей гасит и событие тоже."""
    from services.premium import activate_premium

    Session, юзер = база["Session"], база["юзер"]

    async with Session() as s:
        итог = await activate_premium(
            s, юзер, days=30, payment_id="txn-1", provider="appstore",
            tier="plus",
        )
        await s.commit()
    assert not итог.get("already_processed")

    # Повтор ТОГО ЖЕ платежа (двойное server notification) — зачёт один
    async with Session() as s:
        итог = await activate_premium(
            s, юзер, days=30, payment_id="txn-1", provider="appstore",
            tier="plus",
        )
        await s.commit()
    assert итог.get("already_processed") is True

    (строка,) = await _события(Session, юзер, "purchase_completed")
    assert строка.props["provider"] == "appstore"
    assert строка.props["tier"] == "plus"

    # Промокод идёт через ту же точку с provider="promo" — в воронке
    # это НЕ выручка, отчёты отсекают по провайдеру
    async with Session() as s:
        await activate_premium(
            s, юзер, days=7, payment_id=f"promo-{uuid.uuid4()}",
            provider="promo", tier="plus",
        )
        await s.commit()

    провайдеры = sorted(
        с.props["provider"]
        for с in await _события(Session, юзер, "purchase_completed")
    )
    assert провайдеры == ["appstore", "promo"]


# ════════════════════════════════════════════════════════════════
#  Точки в потоках API: свайп → мэтч → сообщение (живой HTTP)
# ════════════════════════════════════════════════════════════════

@pytest.fixture
async def пара(tmp_path):
    """Аня (верхний тариф — ей доступна личка) и Боря — путь до мэтча."""
    from models.models import Base, Profile, Subscription, User
    from services.plans import FEATURE_MIN_TIER

    файл = tmp_path / "funnel.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{файл}")
    async with engine.begin() as c:
        await c.run_sync(Base.metadata.create_all)

    Session = async_sessionmaker(engine, expire_on_commit=False)
    аня, боря = str(uuid.uuid4()), str(uuid.uuid4())
    async with Session() as s:
        for uid, имя, пол, tg in ((аня, "Аня", "female", 1), (боря, "Боря", "male", 2)):
            s.add(User(id=uid, telegram_id=tg, role="user"))
            s.add(Profile(
                user_id=uid, display_name=имя, gender=пол,
                birth_date=datetime(1997, 3, 3, tzinfo=timezone.utc),
                city="Москва", photos=["https://x/1.jpg"], looking_for="any",
            ))
        s.add(Subscription(
            user_id=аня, plan=FEATURE_MIN_TIER["direct_messages"],
            expires_at=datetime.now(timezone.utc) + timedelta(days=30),
        ))
        await s.commit()

    yield {"engine": engine, "Session": Session, "аня": аня, "боря": боря}
    await engine.dispose()


@pytest.fixture
async def клиент(app, пара, monkeypatch):
    """HTTP-клиент на живой базе — приём test_direct_messages.py целиком."""
    from database.connection import get_session
    from middleware.auth import get_current_user
    from models.models import User
    import database.connection as dbc
    import routers.chat as chat_mod
    import routers.likes as likes_mod
    import routers.matches as matches_mod
    import services.chat_delivery as delivery
    import services.direct_messages as dm_mod
    import services.quotas as quotas_mod

    Session = пара["Session"]

    # save_message открывает сессию сам, мимо FastAPI Depends
    monkeypatch.setattr(dbc, "async_session_factory", Session)
    monkeypatch.setattr(chat_mod, "async_session_factory", Session)
    monkeypatch.setattr(delivery, "async_session_factory", Session)

    # pg_advisory_xact_lock есть только в Postgres
    for мод in (likes_mod, dm_mod, delivery, quotas_mod):
        настоящий = мод.sa_text
        монк = (
            lambda н: lambda sql: н("SELECT 1") if "advisory" in sql else н(sql)
        )(настоящий)
        monkeypatch.setattr(мод, "sa_text", монк)

    # Модерация и рассылка — не то, что здесь проверяется
    monkeypatch.setattr(matches_mod, "moderate_text", _пропустить)
    monkeypatch.setattr(matches_mod, "log_moderation", _ничего)
    monkeypatch.setattr(matches_mod, "fan_out", _ничего)

    текущий = {"id": пара["аня"]}

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
        for ключ, значение in было.items():
            if значение is None:
                app.dependency_overrides.pop(ключ, None)
            else:
                app.dependency_overrides[ключ] = значение


async def test_свайп_мэтч_и_сообщение_оставляют_вехи(клиент, пара):
    """Сердце воронки живьём: первый лайк — first_swipe; взаимный —
    first_match ОБОИМ (иначе половина людей выпадала бы из отчёта: мэтч
    случается на свайпе одного); первое сообщение — first_message.
    Повторы ничего не задваивают."""
    Session, аня, боря = пара["Session"], пара["аня"], пара["боря"]

    # Боря лайкает Аню: свайп есть, мэтча ещё нет
    клиент.от_имени(боря)
    r = await клиент.post("/api/likes", json={"target_id": аня, "type": "like"})
    assert r.status_code == 200, r.text
    assert not r.json()["matched"]

    (свайп,) = await _события(Session, боря, "first_swipe")
    assert свайп.dedup_key == f"{боря}:first_swipe"
    assert await _события(Session, event="first_match") == []

    # Аня отвечает лайком: мэтч — и веха у ОБОИХ
    клиент.от_имени(аня)
    r = await клиент.post("/api/likes", json={"target_id": боря, "type": "like"})
    assert r.status_code == 200, r.text
    assert r.json()["matched"]
    match_id = r.json()["match"]["id"]

    assert len(await _события(Session, аня, "first_swipe")) == 1
    мэтчи = await _события(Session, event="first_match")
    assert sorted(с.user_id for с in мэтчи) == sorted([аня, боря])

    # Первое сообщение — через общий путь доставки save_message
    r = await клиент.post(
        f"/api/matches/{match_id}/messages", json={"text": "Привет!"}
    )
    assert r.status_code == 200, r.text
    r = await клиент.post(
        f"/api/matches/{match_id}/messages", json={"text": "Как дела?"}
    )
    assert r.status_code == 200, r.text

    (письмо,) = await _события(Session, аня, "first_message")
    assert письмо.dedup_key == f"{аня}:first_message"


# ════════════════════════════════════════════════════════════════
#  Точки, которые не прогнать HTTP'ом без Telegram: сторожа исходника
# ════════════════════════════════════════════════════════════════

def test_точки_записи_стоят_на_своих_местах():
    """Сторож против рефакторинга: auth_telegram и /profiles/me держат
    app_open (клиент бутстрапится ровно этими двумя запросами — api.ts),
    витрина тарифов — paywall_view, порог анкеты — profile_created.
    Живой прогон auth_telegram требует подписи initData Телеграма — дороже,
    чем даёт: сама механика track уже проверена выше."""
    import inspect

    import routers.auth as auth_mod
    import routers.iap as iap_mod
    import routers.profiles as profiles_mod

    assert "EVENT_APP_OPEN" in inspect.getsource(auth_mod.auth_telegram)
    assert "EVENT_APP_OPEN" in inspect.getsource(profiles_mod.get_my_profile)
    assert "EVENT_PROFILE_CREATED" in inspect.getsource(
        profiles_mod.update_my_profile
    )
    assert "EVENT_PAYWALL_VIEW" in inspect.getsource(iap_mod.list_plans)


def test_бот_точки_стоят_на_своих_местах():
    """То же для хендлеров бота: /start пишет bot_start ДО ранней ветки
    deep-link'а premium (иначе пришедший по рекламе premium-ссылки исчезал
    из воронки), конец анкеты — profile_created, витрина — paywall_view,
    выставленные счета Stars/CryptoBot — purchase_started."""
    from pathlib import Path

    бот = Path(__file__).resolve().parents[2] / "bot"
    старт = (бот / "bot.py").read_text(encoding="utf-8")
    анкета = (бот / "handlers" / "registration.py").read_text(encoding="utf-8")
    премиум = (бот / "handlers" / "premium.py").read_text(encoding="utf-8")

    точка = старт.index('"bot_start"')
    ветка_premium = старт.index('if arg == "premium":\n        from handlers.premium')
    assert точка < ветка_premium, "bot_start уехал ниже ранней ветки premium"

    assert '"profile_created"' in анкета
    assert '"paywall_view"' in премиум
    assert '"provider": "stars"' in премиум and '"purchase_started"' in премиум
    assert '"provider": "cryptobot"' in премиум


# ════════════════════════════════════════════════════════════════
#  Бот: зеркальный track_event на его же интерпретаторе
# ════════════════════════════════════════════════════════════════

def test_бот_пишет_воронку_на_настоящей_базе():
    """Зеркало в bot/database/connection.py живьём: first-touch у bot_start,
    единственная строка purchase_completed на повторный зачёт Stars, и
    provider=promo у активации промокода (у бота это СВОЯ транзакция, не
    вызов activate_premium — точку легко потерять)."""
    итог = _в_боте(
        """
import asyncio, json

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

import database.connection as conn
from database.models import AnalyticsEvent, Base, PromoCode, User


async def события(user_id, event):
    async with conn.async_session_factory() as s:
        return list((await s.execute(
            select(AnalyticsEvent).where(
                AnalyticsEvent.user_id == user_id,
                AnalyticsEvent.event == event,
            )
        )).scalars())


async def main():
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
    conn.async_session_factory = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )
    async with engine.begin() as c:
        await c.run_sync(Base.metadata.create_all)

    async with conn.async_session_factory() as s:
        async with s.begin():
            s.add(User(id="u1", telegram_id=111))
            s.add(PromoCode(code="LAUNCH", tier="plus", days=7,
                            max_uses=0, is_active=True))

    # first-touch: второй /start с другой меткой источник не крадёт
    await conn.track_event("u1", "bot_start", {"source": "tiktok"}, once=True)
    await conn.track_event("u1", "bot_start", {"source": "ads"}, once=True)
    старты = await события("u1", "bot_start")

    # Повторный зачёт того же charge_id — одна строка purchase_completed
    await conn.activate_premium("u1", days=30, payment_id="ch-1",
                                provider="stars", tier="plus")
    await conn.activate_premium("u1", days=30, payment_id="ch-1",
                                provider="stars", tier="plus")
    покупки = await события("u1", "purchase_completed")

    # Промокод — отдельная транзакция бота со своей точкой
    промо = await conn.activate_promo_code("u1", "launch")
    все_покупки = await события("u1", "purchase_completed")

    print(json.dumps({
        "стартов": len(старты),
        "источник": старты[0].props.get("source") if старты else None,
        "покупок_после_повтора": len(покупки),
        "провайдер": покупки[0].props.get("provider") if покупки else None,
        "промо_активирован": bool(промо.get("activated")),
        "провайдеры_в_итоге": sorted(
            с.props.get("provider") for с in все_покупки
        ),
    }))


asyncio.run(main())
"""
    )
    assert итог == {
        "стартов": 1,
        "источник": "tiktok",
        "покупок_после_повтора": 1,
        "провайдер": "stars",
        "промо_активирован": True,
        "провайдеры_в_итоге": ["promo", "stars"],
    }
