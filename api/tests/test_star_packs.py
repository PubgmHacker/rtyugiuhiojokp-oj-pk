"""Паки за Stars: разовые покупки суперлайков и бустов (Блок В1).

Пак — вторая денежная механика после подписок, и ломается она там же, где
первая: в зазоре между ботом (продаёт) и API (даёт потратить). Бот держит
свою копию каталога — разойдись цены, человек заплатил бы не ту сумму;
зачёт платежа без идемпотентности удвоил бы покупку на дубле апдейта
Telegram; а возврат Stars без списания баланса раздавал бы паки бесплатно.

Порядок трат закреплён отдельно: суточные включения сгорают в полночь,
купленные — нет, поэтому суточные тратятся первыми. Обратный порядок тихо
воровал бы у человека купленное.
"""

from __future__ import annotations

import ast
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from services.plans import (
    PACK_BOOSTS,
    PACK_SUPERLIKES,
    PACKS,
    PACKS_BY_CODE,
    TIER_AURORA,
    boosts_per_day,
)
from tests.test_unban_purchase import _ШАПКА, _в_боте


# ════════════════════════════════════════════════════════════════
#  Каталог: цены и объёмы согласованы сами с собой
# ════════════════════════════════════════════════════════════════

def test_каталог_паков_согласован():
    """Коды уникальны, объёмы и цены положительны, вид — из известных."""
    assert len(PACKS_BY_CODE) == len(PACKS), "дубль кода затёр бы пак в словаре"
    for pack in PACKS:
        assert pack.kind in (PACK_SUPERLIKES, PACK_BOOSTS)
        assert pack.qty > 0
        assert pack.price_stars > 0


def test_крупный_пак_дешевле_за_штуку():
    """Скидка за объём — иначе большой пак покупать незачем. Но общая
    сумма растёт с объёмом: крупный пак дешевле мелкого выглядел бы ошибкой."""
    for kind in (PACK_SUPERLIKES, PACK_BOOSTS):
        ряд = sorted((p for p in PACKS if p.kind == kind), key=lambda p: p.qty)
        assert len(ряд) >= 2, f"у вида {kind} нет линейки объёмов"
        for мелкий, крупный in zip(ряд, ряд[1:]):
            assert крупный.price_per_item < мелкий.price_per_item, (
                f"{крупный.code} за штуку не дешевле {мелкий.code}"
            )
            assert крупный.price_stars > мелкий.price_stars


def test_названия_паков_склоняются():
    """Имя пака попадает в счёт Telegram — «5 суперлайк» там читался бы
    как небрежность в момент оплаты."""
    assert PACKS_BY_CODE["superlikes_5"].title == "5 суперлайков"
    assert PACKS_BY_CODE["boosts_1"].title == "1 буст"
    assert PACKS_BY_CODE["boosts_3"].title == "3 буста"


def test_паки_совпадают_в_боте_и_api():
    """Бот и API держат каталог раздельно — бот не может импортировать код
    API. Разойдись копии, бот продал бы пак, которого API не начислит,
    или по цене, которой нет (та же сверка, что у тарифов в
    test_audit_fixes.test_тарифы_совпадают_в_боте_и_api)."""
    бот = (
        Path(__file__).resolve().parents[2] / "bot" / "services" / "plans.py"
    ).read_text(encoding="utf-8")
    дерево = ast.parse(бот)

    паки_бота = {}
    for узел in ast.walk(дерево):
        if not (isinstance(узел, ast.Call) and getattr(узел.func, "id", "") == "Pack"):
            continue
        # kind передаётся константой PACK_SUPERLIKES/PACK_BOOSTS, остальное —
        # литералы
        значения = []
        for арг in узел.args:
            if isinstance(арг, ast.Constant):
                значения.append(арг.value)
            elif isinstance(арг, ast.Name):
                значения.append(арг.id.removeprefix("PACK_").lower())
        паки_бота[значения[0]] = tuple(значения[1:4])

    паки_api = {p.code: (p.kind, p.qty, p.price_stars) for p in PACKS}
    assert паки_бота == паки_api, (
        f"расходятся: {set(паки_бота.items()) ^ set(паки_api.items())}"
    )


# ════════════════════════════════════════════════════════════════
#  API: купленные бусты работают и тратятся в правильном порядке
# ════════════════════════════════════════════════════════════════

@pytest.fixture
async def живая_база(tmp_path):
    """Настоящая БД: платящая Вера (Aurora) и бесплатный Гоша.

    Буст пишет в БД и берёт суточную блокировку — подменённой сессией не
    обойтись (та же причина, что у фикстур test_feature_gates.py).
    """
    from models.models import Base, Profile, Subscription, User

    файл = tmp_path / "packs.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{файл}")
    async with engine.begin() as c:
        await c.run_sync(Base.metadata.create_all)

    Session = async_sessionmaker(engine, expire_on_commit=False)

    вера, гоша = str(uuid.uuid4()), str(uuid.uuid4())
    async with Session() as s:
        for uid, имя, пол, tg in ((вера, "Вера", "female", 1), (гоша, "Гоша", "male", 2)):
            s.add(User(
                id=uid, telegram_id=tg, role="user",
                last_seen_at=datetime.now(timezone.utc),
            ))
            s.add(Profile(
                user_id=uid, display_name=имя, gender=пол,
                birth_date=datetime(1997, 3, 3, tzinfo=timezone.utc),
                city="Москва", photos=["https://x/1.jpg"],
                interests=["кино"], looking_for="any",
            ))
        s.add(Subscription(
            user_id=вера, plan="aurora",
            expires_at=datetime.now(timezone.utc) + timedelta(days=30),
        ))
        await s.commit()

    yield {"engine": engine, "Session": Session, "вера": вера, "гоша": гоша}
    await engine.dispose()


@pytest.fixture
async def клиент(app, живая_база, monkeypatch):
    """Клиент с живой БД. `от_имени` переключает текущего пользователя."""
    from database.connection import get_session
    from middleware.auth import get_current_user
    from models.models import User
    import routers.profiles as profiles_mod

    Session = живая_база["Session"]

    # pg_advisory_xact_lock есть только в Postgres, а тест идёт на SQLite
    настоящий = profiles_mod.sa_text
    монк = (lambda н: lambda sql: н("SELECT 1") if "advisory" in sql else н(sql))(настоящий)
    monkeypatch.setattr(profiles_mod, "sa_text", монк)

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


async def _выставить_бонус(живая_база, uid: str, сколько: int) -> None:
    from models.models import Profile

    async with живая_база["Session"]() as s:
        профиль = (
            await s.execute(select(Profile).where(Profile.user_id == uid))
        ).scalar_one()
        профиль.bonus_boosts = сколько
        await s.commit()


async def _бонус_в_базе(живая_база, uid: str) -> int:
    from models.models import Profile

    async with живая_база["Session"]() as s:
        return (
            await s.execute(
                select(Profile.bonus_boosts).where(Profile.user_id == uid)
            )
        ).scalar_one()


async def test_бесплатный_с_купленным_паком_включает_буст(клиент, живая_база):
    """Смысл пака: гейт тарифа пускает по балансу. Бонус — сам себе оплата:
    закрыть его тарифом значило бы продать бесплатному то, чем нельзя
    воспользоваться. У free суточных нет — списывается купленное."""
    гоша = живая_база["гоша"]
    await _выставить_бонус(живая_база, гоша, 2)

    клиент.от_имени(гоша)
    r = await клиент.post("/api/profiles/me/boost")
    assert r.status_code == 200, r.text
    тело = r.json()
    assert тело["active"] is True
    assert тело["bonus"] == 1
    assert await _бонус_в_базе(живая_база, гоша) == 1


async def test_бонус_кончился_и_дверь_закрылась(клиент, живая_база):
    """Потратил последнее купленное включение — бесплатному снова 403, даже
    поверх ещё активного буста: право продлевать не входило в пак."""
    гоша = живая_база["гоша"]
    await _выставить_бонус(живая_база, гоша, 1)

    клиент.от_имени(гоша)
    первый = await клиент.post("/api/profiles/me/boost")
    assert первый.status_code == 200, первый.text
    assert await _бонус_в_базе(живая_база, гоша) == 0

    второй = await клиент.post("/api/profiles/me/boost")
    assert второй.status_code == 403, "пустой баланс держал бы дверь открытой"


async def test_суточные_тратятся_первыми(клиент, живая_база):
    """Суточные вернутся завтра сами, купленное не сгорает — обратный
    порядок тихо воровал бы у человека оплаченное."""
    вера = живая_база["вера"]
    await _выставить_бонус(живая_база, вера, 2)

    клиент.от_имени(вера)
    r = await клиент.post("/api/profiles/me/boost")
    assert r.status_code == 200, r.text
    # Aurora: суточная квота не пуста — списана она, купленное цело
    assert await _бонус_в_базе(живая_база, вера) == 2
    assert r.json()["bonus"] == 2


async def test_бонус_списывается_после_исчерпания_суточных(клиент, живая_база):
    """Суточные выбраны — тратится купленное; кончилось и оно — 429."""
    from models.models import BoostActivation

    вера = живая_база["вера"]
    квота = boosts_per_day(TIER_AURORA)
    недавно = datetime.now(timezone.utc) - timedelta(hours=1)
    async with живая_база["Session"]() as s:
        for _ in range(квота):
            s.add(BoostActivation(user_id=вера, created_at=недавно))
        await s.commit()
    await _выставить_бонус(живая_база, вера, 1)

    клиент.от_имени(вера)
    r = await клиент.post("/api/profiles/me/boost")
    assert r.status_code == 200, r.text
    assert await _бонус_в_базе(живая_база, вера) == 0

    # Пусто с обеих сторон: и суточные, и купленные
    r = await клиент.post("/api/profiles/me/boost")
    assert r.status_code == 429, r.text


async def test_состояние_буста_отдаёт_баланс_пака(клиент, живая_база):
    """Мини-апп рисует бейдж по этому полю: free с тремя купленными видит
    left_today=3 при per_day=0 — обе цифры из одного ответа."""
    гоша = живая_база["гоша"]
    await _выставить_бонус(живая_база, гоша, 3)

    клиент.от_имени(гоша)
    r = await клиент.get("/api/profiles/me/boost")
    assert r.status_code == 200, r.text
    тело = r.json()
    assert тело["bonus"] == 3
    assert тело["per_day"] == 0
    assert тело["left_today"] == 3


def test_openapi_буст_описывает_бонус(openapi):
    """Контракт для веба: поле bonus объявлено в схеме BoostOut."""
    свойства = openapi["components"]["schemas"]["BoostOut"]["properties"]
    assert "bonus" in свойства


# ════════════════════════════════════════════════════════════════
#  Бот: зачёт и возврат на настоящей базе (его же интерпретатором)
# ════════════════════════════════════════════════════════════════

def test_бот_зачёт_и_возврат_пака_на_настоящей_базе():
    """Полный круг денег на настоящей схеме (SQLite): зачёт обоих видов →
    дубль отбит → без анкеты платёж не пишется → возврат списывает и
    удаляет платёж → повторный возврат пуст → потраченное не уводит
    баланс в минус."""
    итог = _в_боте(
        """
import asyncio, json

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

import database.connection as conn
from database.models import Base, ProcessedPayment, Profile, User


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
            # 2 суперлайка уже лежат: зачёт должен прибавлять, не затирать
            s.add(Profile(user_id="u1", bonus_superlikes=2))
            s.add(User(id="u2", telegram_id=222))  # без анкеты

    бусты = await conn.credit_pack("u1", "ch_b", kind="boosts", qty=3, stars=69)
    дубль = await conn.credit_pack("u1", "ch_b", kind="boosts", qty=3, stars=69)
    лайки = await conn.credit_pack("u1", "ch_s", kind="superlikes", qty=5, stars=25)
    без_анкеты = await conn.credit_pack("u2", "ch_x", kind="boosts", qty=1, stars=29)

    async with conn.async_session_factory() as s:
        строки = (await s.execute(select(ProcessedPayment))).scalars().all()
        платежи = sorted(
            [р.provider, р.external_id, р.days, р.amount, р.currency]
            for р in строки
        )
        профиль = (
            await s.execute(select(Profile).where(Profile.user_id == "u1"))
        ).scalar_one()
        после_зачёта = [профиль.bonus_boosts, профиль.bonus_superlikes]

    возврат = await conn.revoke_pack("ch_b", kind="boosts", qty=3)
    повторный = await conn.revoke_pack("ch_b", kind="boosts", qty=3)

    # Человек успел потратить 4 из 7 суперлайков — возврат пака на 5 не
    # должен уводить баланс в минус
    async with conn.async_session_factory() as s:
        async with s.begin():
            п = (
                await s.execute(select(Profile).where(Profile.user_id == "u1"))
            ).scalar_one()
            п.bonus_superlikes = 3
    возврат_лайков = await conn.revoke_pack("ch_s", kind="superlikes", qty=5)

    async with conn.async_session_factory() as s:
        профиль = (
            await s.execute(select(Profile).where(Profile.user_id == "u1"))
        ).scalar_one()
        после_возврата = [профиль.bonus_boosts, профиль.bonus_superlikes]
        остались = [
            р.external_id
            for р in (await s.execute(select(ProcessedPayment))).scalars().all()
        ]

    print(json.dumps({
        "бусты": бусты, "дубль": дубль, "лайки": лайки,
        "без_анкеты": без_анкеты, "платежи": платежи,
        "после_зачёта": после_зачёта, "возврат": возврат,
        "повторный": повторный, "возврат_лайков": возврат_лайков,
        "после_возврата": после_возврата, "остались": остались,
    }, ensure_ascii=False))


asyncio.run(main())
"""
    )

    assert итог["бусты"] == {"credited": True, "reason": "", "balance": 3}
    assert итог["дубль"]["reason"] == "already_processed", (
        "дубль апдейта Telegram удвоил бы покупку"
    )
    assert итог["лайки"]["balance"] == 7, "зачёт затёр бы лежавшие 2 суперлайка"
    assert итог["без_анкеты"]["reason"] == "no_profile"
    assert итог["после_зачёта"] == [3, 7]

    # Журнал выручки: оба зачтённых платежа с фактическими Stars; ch_x без
    # анкеты НЕ записан — иначе возврат Stars выглядел бы уже обработанным
    assert итог["платежи"] == [
        ["stars", "ch_b", 0, 69, "XTR"],
        ["stars", "ch_s", 0, 25, "XTR"],
    ]

    assert итог["возврат"] == {"revoked": True, "user_id": "u1"}
    assert итог["повторный"]["revoked"] is False, (
        "повторный возврат списал бы баланс второй раз"
    )
    assert итог["возврат_лайков"]["revoked"] is True
    assert итог["после_возврата"] == [0, 0], (
        "потраченное не должно уводить баланс в минус"
    )
    assert итог["остались"] == [], "возврат не почистил журнал выручки"


# ════════════════════════════════════════════════════════════════
#  Бот: хендлеры — счёт, диспетчеризация payload, возвраты
# ════════════════════════════════════════════════════════════════

_ПАКИ = _ШАПКА + """
from handlers import premium


async def main():
    # 1. Кнопка пака выставляет Stars-счёт с кодом в payload
    кнопка = CallbackQuery.model_construct(
        id="1", from_user=_кто, chat_instance="c", data="packbuy:superlikes_5",
        message=сообщение(),
    ).as_(бот)
    await premium.buy_pack(кнопка)

    # 2. Оплата пака зачитывается как пак, не как подписка
    оплата = сообщение(successful_payment=SuccessfulPayment.model_construct(
        currency="XTR", total_amount=69, invoice_payload="pack:boosts_3",
        telegram_payment_charge_id="ch_pack",
    ))
    await premium.on_successful_payment(оплата)

    # 3. Возврат Stars за пак идёт в списание баланса, не в возврат подписки
    возврат = сообщение(refunded_payment=RefundedPayment.model_construct(
        currency="XTR", total_amount=69, invoice_payload="pack:boosts_3",
        telegram_payment_charge_id="ch_pack",
    ))
    await premium.on_refunded_payment(возврат)

    # 4. Оплата снятого с продажи пака возвращает Stars, а не дарит plus_1m
    мёртвый = сообщение(successful_payment=SuccessfulPayment.model_construct(
        currency="XTR", total_amount=10, invoice_payload="pack:такого_нет",
        telegram_payment_charge_id="ch_dead",
    ))
    await premium.on_successful_payment(мёртвый)

    print(json.dumps({"вызовы": вызовы}, ensure_ascii=False))


asyncio.run(main())
"""


def test_бот_платежи_за_паки_разводятся_по_payload():
    """Telegram шлёт successful_payment одним типом на все покупки. Уйди
    оплата пака в фолбэк «неизвестный код → plus_1m» — человек заплатил бы
    за суперлайки, а получил чужую подписку."""
    итог = _в_боте(_ПАКИ.replace("ЗАБАНЕН", "False").replace(
        "ОТВЕТ_РАЗБАНА", '{"unbanned": True, "reason": ""}'
    ))
    вызовы = [tuple(в) for в in итог["вызовы"]]

    счета = [в for в in вызовы if в[0] == "SendInvoice"]
    assert счета == [("SendInvoice", "pack:superlikes_5")], (
        "кнопка не выставила Stars-счёт за пак"
    )

    assert ("credit_pack", "u1", "ch_pack", "boosts", 3, 69) in вызовы
    assert not any(
        в[0] == "premium" for в in вызовы
    ), "оплата пака зачлась бы как подписка"

    assert ("revoke_pack", "ch_pack", "boosts", 3) in вызовы
    assert not any(
        в[0] == "revoke_premium" for в in вызовы
    ), "возврат пака отменил бы подписку с тем же charge_id"

    # Мёртвый код: деньги вернулись, подписка не начислена
    assert any(в[0] == "RefundStarPayment" for в in вызовы), (
        "деньги за снятый с продажи пак остались бы у нас"
    )
    отправки = [в for в in вызовы if в[0] == "send"]
    assert any("+3 к балансу" in в[1] for в in отправки)
    assert any("списаны с баланса" in в[1] for в in отправки)
    assert any("больше не продаётся" in в[1] for в in отправки)


def test_бот_пак_без_анкеты():
    """Бонусы лежат на анкете. Кнопка без анкеты не выставляет счёт, а
    оплата, догнавшая удалённую анкету, возвращает Stars — деньги за
    пустоту не держим."""
    сценарий = _ШАПКА + """
async def _нет_анкеты(uid):
    return None
db.get_profile = _нет_анкеты

async def _некуда(user_id, charge_id, kind, qty, stars):
    вызовы.append(("credit_pack", user_id, charge_id, kind, qty, stars))
    return {"credited": False, "reason": "no_profile", "balance": 0}
db.credit_pack = _некуда

from handlers import premium


async def main():
    кнопка = CallbackQuery.model_construct(
        id="1", from_user=_кто, chat_instance="c", data="packbuy:boosts_1",
        message=сообщение(),
    ).as_(бот)
    await premium.buy_pack(кнопка)

    оплата = сообщение(successful_payment=SuccessfulPayment.model_construct(
        currency="XTR", total_amount=29, invoice_payload="pack:boosts_1",
        telegram_payment_charge_id="ch_lost",
    ))
    await premium.on_successful_payment(оплата)
    print(json.dumps({"вызовы": вызовы}, ensure_ascii=False))


asyncio.run(main())
"""
    итог = _в_боте(сценарий.replace("ЗАБАНЕН", "False").replace(
        "ОТВЕТ_РАЗБАНА", '{"unbanned": True, "reason": ""}'
    ))
    вызовы = [tuple(в) for в in итог["вызовы"]]

    assert not any(в[0] == "SendInvoice" for в in вызовы), (
        "счёт без анкеты — деньги возьмём, а класть некуда"
    )
    assert ("credit_pack", "u1", "ch_lost", "boosts", 1, 29) in вызовы
    assert any(в[0] == "RefundStarPayment" for в in вызовы), (
        "оплата без анкеты осталась бы у нас"
    )
    отправки = [в for в in вызовы if в[0] == "send"]
    assert any("Stars возвращены" in в[1] for в in отправки)
