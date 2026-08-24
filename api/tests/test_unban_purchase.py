"""Платная досрочная разблокировка (349 ₽) и бан-гейт бота.

Три слоя одной механики:

* API: страйки за чужое лицо считаются заново после разбана (амнистия по
  журналу), автобан публикует событие и для бота;
* бот: забаненный упирается в гейт с кнопкой оплаты, оплата снимает бан,
  возврат Stars возвращает его на место;
* деньги: оплата без бана (двойное нажатие, разбан админом) возвращается.

Бот живёт в отдельном venv — его код проверяется его же интерпретатором
через subprocess, как в test_identity_enforcement.py.
"""
import json
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest


# ════════════════════════════════════════════════════════════════
#  API: амнистия страйков после разбана
# ════════════════════════════════════════════════════════════════

async def _журнал_на_sqlite(monkeypatch):
    """Настоящая таблица журнала в памяти вместо фейков.

    Окно страйков — это SQL с датами; фейковая сессия проверяла бы только
    plumbing, а не саму логику среза. Создаём одну таблицу AiModerationLog:
    create_all всех моделей тянет постгресовую специфику, которая SQLite
    не нужна и не по зубам.
    """
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
    from sqlalchemy.pool import StaticPool

    import database.connection as dbc
    from models.models import AiModerationLog

    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
    фабрика = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(AiModerationLog.__table__.create)

    # identity_strikes берёт фабрику из модуля при каждом вызове
    monkeypatch.setattr(dbc, "async_session_factory", фабрика)
    return фабрика, AiModerationLog


async def _записать(фабрика, модель, user_id, content_type, result, дней_назад):
    # Наивный UTC: так строки сравнимы между собой в SQLite независимо от
    # того, как диалект сериализует tz-aware границу
    момент = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=дней_назад)
    async with фабрика() as session:
        session.add(
            модель(
                user_id=user_id,
                content_type=content_type,
                content="",
                result=result,
                action="none",
                reason="",
                created_at=момент,
            )
        )
        await session.commit()


async def test_страйки_обнуляются_после_покупки_разбана(monkeypatch):
    """Три старых страйка + оплаченный разбан = чистый счёт.

    Без амнистии покупка была бы ловушкой: первый же спорный кадр после
    оплаты складывался бы со старыми страйками и банил обратно.
    """
    import services.enforcement as e

    фабрика, Журнал = await _журнал_на_sqlite(monkeypatch)

    for _ in range(3):
        await _записать(фабрика, Журнал, "u1", "photo_identity", "blocked", дней_назад=5)
    assert await e.identity_strikes("u1") == 3

    await _записать(фабрика, Журнал, "u1", "unban_purchase", "safe", дней_назад=1)
    assert await e.identity_strikes("u1") == 0

    # Новое нарушение после разбана — счёт идёт заново, а не с третьего
    await _записать(фабрика, Журнал, "u1", "photo_identity", "blocked", дней_назад=0)
    assert await e.identity_strikes("u1") == 1


async def test_разбан_админом_тоже_амнистирует(monkeypatch):
    import services.enforcement as e

    фабрика, Журнал = await _журнал_на_sqlite(monkeypatch)
    await _записать(фабрика, Журнал, "u1", "verification_identity", "blocked", дней_назад=3)
    await _записать(фабрика, Журнал, "u1", "unban_admin", "safe", дней_назад=2)

    assert await e.identity_strikes("u1") == 0


async def test_древний_разбан_не_расширяет_окно(monkeypatch):
    """Разбан старше окна не должен ни обнулять свежие страйки, ни
    поднимать в счёт страйки старше 30 дней."""
    import services.enforcement as e

    фабрика, Журнал = await _журнал_на_sqlite(monkeypatch)
    await _записать(фабрика, Журнал, "u1", "unban_purchase", "safe", дней_назад=40)
    await _записать(фабрика, Журнал, "u1", "photo_identity", "blocked", дней_назад=35)
    await _записать(фабрика, Журнал, "u1", "photo_identity", "blocked", дней_назад=5)

    assert await e.identity_strikes("u1") == 1


async def test_амнистия_чужого_пользователя_не_действует(monkeypatch):
    import services.enforcement as e

    фабрика, Журнал = await _журнал_на_sqlite(monkeypatch)
    await _записать(фабрика, Журнал, "u1", "photo_identity", "blocked", дней_назад=5)
    await _записать(фабрика, Журнал, "другой", "unban_purchase", "safe", дней_назад=1)

    assert await e.identity_strikes("u1") == 1


# ════════════════════════════════════════════════════════════════
#  API: автобан говорит боту, разбан админом пишет амнистию
# ════════════════════════════════════════════════════════════════

async def test_автобан_публикует_событие_боту(monkeypatch):
    """Бан должен долетать до Telegram: бот слушает dating:bot:events и
    шлёт сообщение с кнопкой платной разблокировки."""
    import services.enforcement as e
    import services.realtime as rt

    опубликовано = []

    class _Redis:
        async def publish(self, канал, тело):
            опубликовано.append((канал, json.loads(тело)))

    async def _редис():
        return _Redis()

    monkeypatch.setattr(rt, "get_redis", _редис)

    async def _тихо(*a, **kw):
        return True

    monkeypatch.setattr(e, "remember_ban", _тихо)
    monkeypatch.setattr(e, "revoke_all_for_user", _тихо)

    class _Сессия:
        async def flush(self):
            pass

    цель = SimpleNamespace(
        id="u9", role="user", telegram_id=99, apple_id=None, is_banned=False,
        banned_until=None,
    )
    assert await e.ban_user_for_violation(
        _Сессия(), цель, "чужие фото", category="identity"
    ) is True

    каналы = {к: тело for к, тело in опубликовано}
    assert "dating:user:u9" in каналы, "веб-сокет остался без события"
    assert каналы["dating:bot:events"] == {
        "type": "banned",
        "user_id": "u9",
        "reason": "чужие фото",
        # Катфишинг — вечный с первой ступени, поэтому срока нет
        "banned_until": None,
    }


def test_разбан_админом_пишет_амнистию():
    """Хвост test_бан_переживает_удаление_аккаунта: разбан обязан не только
    чистить память банов, но и обнулять счёт страйков."""
    import inspect

    from routers import admin

    исходник = inspect.getsource(admin.unban_user)
    assert "unban_admin" in исходник, "разбан не амнистирует страйки"
    assert "log_moderation" in исходник


# ════════════════════════════════════════════════════════════════
#  Бот: subprocess-проверки его же интерпретатором
# ════════════════════════════════════════════════════════════════

БОТ = Path(__file__).resolve().parents[2] / "bot"


def _в_боте(скрипт: str) -> dict:
    python = БОТ / ".venv" / "bin" / "python"
    if not python.exists():
        pytest.skip("venv бота не поднят в этом окружении")
    результат = subprocess.run(
        [str(python), "-c", скрипт], cwd=БОТ, capture_output=True, text=True, timeout=120,
    )
    assert результат.returncode == 0, результат.stderr[-1500:]
    return json.loads(результат.stdout.strip().splitlines()[-1])


def test_бот_покупка_и_возврат_разбана_на_настоящей_базе():
    """Полный круг на настоящей схеме (SQLite): бан → оплата → разбан с
    чисткой памяти банов и амнистией → повтор ТОГО ЖЕ апдейта → зачёт один
    и без возврата → новый бан + повтор старого апдейта → старые деньги
    не снимают новый бан → повторная оплата НОВЫМ charge_id без бана →
    отказ → возврат Stars → бан на месте, след в журнале."""
    итог = _в_боте(
        """
import asyncio, json

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

import database.connection as conn
from database.models import (
    AiModerationLog, BannedIdentity, Base, ProcessedPayment, User,
)


async def main():
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
    conn.async_session_factory = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )
    async with engine.begin() as c:
        await c.run_sync(Base.metadata.create_all)

    async with conn.async_session_factory() as s:
        async with s.begin():
            s.add(User(id="u1", telegram_id=111, is_banned=True))
            s.add(BannedIdentity(telegram_id=111, reason="чужие фото"))

    покупка = await conn.unban_after_payment("u1", "ch_1", 349, stars=184)

    async with conn.async_session_factory() as s:
        флаг_после_покупки = (
            await s.execute(select(User.is_banned).where(User.id == "u1"))
        ).scalar()
        память_после_покупки = (
            await s.execute(select(func.count(BannedIdentity.id)))
        ).scalar()
        амнистия = (
            await s.execute(
                select(func.count(AiModerationLog.id)).where(
                    AiModerationLog.user_id == "u1",
                    AiModerationLog.content_type == "unban_purchase",
                    AiModerationLog.content == "ch_1",
                )
            )
        ).scalar()
        платёж = (
            await s.execute(select(ProcessedPayment))
        ).scalars().one()
        платёж_после_покупки = [
            платёж.provider, платёж.external_id, платёж.days,
            платёж.amount, платёж.currency,
        ]

    # Telegram повторил доставку ТОГО ЖЕ апдейта (тот же charge_id)
    ретрай = await conn.unban_after_payment("u1", "ch_1", 349, stars=184)

    async with conn.async_session_factory() as s:
        платежей_после_ретрая = (
            await s.execute(select(func.count(ProcessedPayment.id)))
        ).scalar()

    # Новый бан за новые грехи, и следом — повтор СТАРОГО оплаченного апдейта
    async with conn.async_session_factory() as s:
        async with s.begin():
            u = (await s.execute(select(User).where(User.id == "u1"))).scalar_one()
            u.is_banned = True
    ретрай_после_ребана = await conn.unban_after_payment("u1", "ch_1", 349)
    async with conn.async_session_factory() as s:
        async with s.begin():
            u = (await s.execute(select(User).where(User.id == "u1"))).scalar_one()
            флаг_после_ретрая_ребана = u.is_banned
            # Возвращаем состояние «разбанен» — дальше круг идёт по старому пути
            u.is_banned = False

    повторно = await conn.unban_after_payment("u1", "ch_2", 349)

    возврат = await conn.reban_after_refund("ch_1")

    async with conn.async_session_factory() as s:
        флаг_после_возврата = (
            await s.execute(select(User.is_banned).where(User.id == "u1"))
        ).scalar()
        память_после_возврата = (
            await s.execute(
                select(func.count(BannedIdentity.id)).where(
                    BannedIdentity.telegram_id == 111
                )
            )
        ).scalar()
        след_возврата = (
            await s.execute(
                select(func.count(AiModerationLog.id)).where(
                    AiModerationLog.content_type == "unban_refund",
                    AiModerationLog.content == "ch_1",
                )
            )
        ).scalar()
        платежей_после_возврата = (
            await s.execute(select(func.count(ProcessedPayment.id)))
        ).scalar()

    возврат_повторно = await conn.reban_after_refund("ch_1")
    чужой_платёж = await conn.reban_after_refund("нет_такого")

    print(json.dumps({
        "покупка": покупка,
        "флаг_после_покупки": bool(флаг_после_покупки),
        "память_после_покупки": память_после_покупки,
        "амнистия": амнистия,
        "платёж_после_покупки": платёж_после_покупки,
        "ретрай": ретрай,
        "платежей_после_ретрая": платежей_после_ретрая,
        "ретрай_после_ребана": ретрай_после_ребана,
        "флаг_после_ретрая_ребана": bool(флаг_после_ретрая_ребана),
        "повторно": повторно,
        "возврат": возврат,
        "флаг_после_возврата": bool(флаг_после_возврата),
        "память_после_возврата": память_после_возврата,
        "след_возврата": след_возврата,
        "платежей_после_возврата": платежей_после_возврата,
        "возврат_повторно": возврат_повторно["rebanned"],
        "чужой_платёж": чужой_платёж["rebanned"],
    }, ensure_ascii=False))


asyncio.run(main())
"""
    )

    assert итог["покупка"] == {"unbanned": True, "reason": ""}
    assert итог["флаг_после_покупки"] is False
    assert итог["память_после_покупки"] == 0, "память банов держала бы бан после оплаты"
    assert итог["амнистия"] == 1
    # Выручка: разбан записан платежом (days=0 — подписку не двигает)…
    assert итог["платёж_после_покупки"] == ["stars", "ch_1", 0, 184, "XTR"]
    # Повтор того же апдейта: не «not_banned» с возвратом Stars, а зачёт
    # ровно один — иначе разбан бесплатный (оплатил → повтор → рефанд)
    assert итог["ретрай"] == {"unbanned": False, "reason": "already_processed"}
    assert итог["платежей_после_ретрая"] == 1, "повтор задвоил бы выручку"
    # Повтор старого апдейта после НОВОГО бана: старые деньги его не снимают
    assert итог["ретрай_после_ребана"] == {
        "unbanned": False, "reason": "already_processed",
    }
    assert итог["флаг_после_ретрая_ребана"] is True, (
        "повтор старого платежа снял бы новый бан"
    )
    assert итог["повторно"] == {"unbanned": False, "reason": "not_banned"}
    assert итог["возврат"]["rebanned"] is True
    assert итог["возврат"]["telegram_id"] == 111
    assert итог["флаг_после_возврата"] is True
    assert итог["память_после_возврата"] == 1, "возврат без памяти банов обходился бы удалением аккаунта"
    assert итог["след_возврата"] == 1
    # …а возврат денег стёр его из выручки
    assert итог["платежей_после_возврата"] == 0
    assert итог["возврат_повторно"] is False
    assert итог["чужой_платёж"] is False


# Общая шапка subprocess-сценариев: фейковый слой БД до импорта хендлеров
# (иначе они тянут настоящий постгрес) и Bot с фейковой сессией — реальные
# aiogram-типы, но каждый исходящий вызов Bot API оседает в списке.
_ШАПКА = """
import asyncio, json, sys, types
from datetime import datetime, timezone

вызовы = []

db = types.ModuleType("database")

async def get_or_create_user(tid, username="", name=""):
    return {"id": "u1", "is_banned": ЗАБАНЕН}

async def get_active_subscription(uid):
    return None

async def activate_premium(uid, days=0, payment_id="", provider="", tier="",
                           amount=None, currency=None):
    вызовы.append(("premium", uid, payment_id, tier, amount, currency))
    return {"expires_at": "2026-09-17T00:00:00", "already_processed": False}

async def revoke_premium_payment(charge_id, provider=""):
    вызовы.append(("revoke_premium", charge_id))
    return {"revoked": True, "user_id": "u1", "days": 30, "plan": "plus"}

async def unban_after_payment(uid, charge_id, price_rub, stars=None):
    вызовы.append(("unban", uid, charge_id, price_rub, stars))
    return dict(ОТВЕТ_РАЗБАНА)

async def reban_after_refund(charge_id):
    вызовы.append(("reban", charge_id))
    return {"rebanned": True, "user_id": "u1", "telegram_id": 42}

# Паки за Stars: premium.py импортирует их на уровне модуля, без заглушек
# сценарии разбана падали бы ImportError. Поведение проверяет test_star_packs;
# сценарии паков переопределяют ответы через db.<имя> после шапки.

async def get_profile(uid):
    return {"id": "p1"}

async def credit_pack(user_id, charge_id, kind, qty, stars):
    вызовы.append(("credit_pack", user_id, charge_id, kind, qty, stars))
    return {"credited": True, "reason": "ok", "balance": qty}

async def revoke_pack(charge_id, kind, qty):
    вызовы.append(("revoke_pack", charge_id, kind, qty))
    return {"revoked": True, "user_id": "u1"}

# Промокоды (В3) — тот же module-level импорт в premium.py, что и у паков.
# Поведение проверяет test_promo_codes; сценарии промо переопределяют ответ
# через db.activate_promo_code после шапки.

async def activate_promo_code(user_id, raw_code):
    вызовы.append(("activate_promo_code", user_id, raw_code))
    return {"activated": True, "tier": "plus", "days": 7,
            "plan": "plus", "expires_at": "2026-09-17T00:00:00"}

# Подарочные коды: каскад «промо not_found → подарок» живёт в том же
# хендлере промокода. Дефолт «нет такого» — чтобы сценарии, не думающие о
# подарках, проходили каскад насквозь; свои ответы промо-FSM ставит через
# db.redeem_gift_code после шапки (test_promo_codes).

async def redeem_gift_code(user_id, raw_code):
    вызовы.append(("redeem_gift_code", user_id, raw_code))
    return {"redeemed": False, "reason": "not_found"}

# Аналитика воронки: хендлеры пишут события (paywall_view, purchase_started)
# по пути к платежу — в сценариях этих тестов она лишь не должна мешать.
# Настоящую запись проверяет test_analytics.py на живой базе.

async def track_event(user_id, event, props=None, once=False, daily=False):
    вызовы.append(("track_event", user_id, event))

for имя in ("get_or_create_user", "get_active_subscription", "activate_premium",
            "revoke_premium_payment", "unban_after_payment", "reban_after_refund",
            "get_profile", "credit_pack", "revoke_pack", "activate_promo_code",
            "redeem_gift_code", "track_event"):
    setattr(db, имя, locals()[имя])
sys.modules["database"] = db

подписчик = types.ModuleType("services.redis_subscriber")

async def revoke_user_tokens(uid):
    вызовы.append(("revoke_tokens", uid))

подписчик.revoke_user_tokens = revoke_user_tokens
sys.modules["services.redis_subscriber"] = подписчик

from aiogram import Bot
from aiogram.client.session.base import BaseSession
from aiogram.types import (
    CallbackQuery, Chat, Message, SuccessfulPayment, RefundedPayment, User,
)


class Сессия(BaseSession):
    async def close(self):
        pass

    async def stream_content(self, *a, **kw):
        yield b""

    async def make_request(self, bot, method, timeout=None):
        имя = type(method).__name__
        if имя == "SendMessage":
            кнопки = []
            if method.reply_markup and hasattr(method.reply_markup, "inline_keyboard"):
                кнопки = [
                    к.callback_data
                    for ряд in method.reply_markup.inline_keyboard for к in ряд
                ]
            вызовы.append(("send", method.text, кнопки))
            return Message.model_construct(
                message_id=2, date=datetime.now(timezone.utc), chat=_чат
            )
        вызовы.append((имя, getattr(method, "payload", None)))
        return True


бот = Bot(token="42:TEST", session=Сессия())
_чат = Chat.model_construct(id=42, type="private")
_кто = User.model_construct(id=42, is_bot=False, first_name="Т")


def сообщение(**поля):
    return Message.model_construct(
        message_id=1, date=datetime.now(timezone.utc), chat=_чат, from_user=_кто,
        **поля,
    ).as_(бот)
"""

_ГЕЙТ = _ШАПКА + """
from middlewares.ban_gate import BanGateMiddleware

гейт = BanGateMiddleware()
пропущено = []

async def обработчик(event, data):
    пропущено.append(type(event).__name__)
    return "ok"


def колбэк(данные, msg=True):
    return CallbackQuery.model_construct(
        id="1", from_user=_кто, chat_instance="c", data=данные,
        message=сообщение() if msg else None,
    ).as_(бот)


async def main():
    данные_бана = {"db_user": {"id": "u1", "is_banned": True}}

    # 1. Текст забаненного: обработчик не зовётся, уходит экран бана с кнопкой
    await гейт(обработчик, сообщение(text="привет"), dict(данные_бана))
    # 2. Любая кнопка забаненного: часики гасятся, экран бана
    await гейт(обработчик, колбэк("menu"), dict(данные_бана))
    # 3. Кнопка оплаты разблокировки — проходит
    await гейт(обработчик, колбэк("unban:pay"), dict(данные_бана))
    # 4. Зачёт оплаты — проходит
    оплата = сообщение(successful_payment=SuccessfulPayment.model_construct(
        currency="XTR", total_amount=184, invoice_payload="unban:v1",
        telegram_payment_charge_id="ch",
    ))
    await гейт(обработчик, оплата, dict(данные_бана))
    # 5. Незабаненный — проходит без сообщений
    await гейт(обработчик, сообщение(text="привет"),
               {"db_user": {"id": "u1", "is_banned": False}})
    # 6. Сбой регистрации (нет db_user) — гейт не решает, пропускает
    await гейт(обработчик, сообщение(text="привет"), {})
    # 7. Временный бан: на экране виден срок и обещание вернуть доступ
    await гейт(обработчик, сообщение(text="привет"),
               {"db_user": {"id": "u1", "is_banned": True,
                            "banned_until": "2099-01-02T03:04:00+00:00"}})

    print(json.dumps({"вызовы": вызовы, "пропущено": пропущено}, ensure_ascii=False))


asyncio.run(main())
"""


def test_бот_гейт_останавливает_забаненного():
    итог = _в_боте(_ГЕЙТ.replace("ЗАБАНЕН", "True").replace(
        "ОТВЕТ_РАЗБАНА", '{"unbanned": True, "reason": ""}'
    ))

    # Прошли ровно кнопка оплаты, зачёт платежа и два незабаненных случая
    assert итог["пропущено"] == ["CallbackQuery", "Message", "Message", "Message"]

    отправки = [в for в in итог["вызовы"] if в[0] == "send"]
    assert len(отправки) == 3, (
        "экран бана должен уйти на текст, на чужую кнопку и на временный бан"
    )
    for _, текст, кнопки in отправки:
        assert "заблокирован" in текст.lower()
        assert "349" in текст
        assert кнопки == ["unban:pay"]
    # Без срока в db_user бан честно называется бессрочным…
    assert "бессрочная" in отправки[0][1]
    # …а со сроком гейт показывает, когда доступ вернётся сам
    assert "до 02.01.2099 03:04 (UTC)" in отправки[2][1]
    assert "вернётся сам" in отправки[2][1]
    assert any(в[0] == "AnswerCallbackQuery" for в in итог["вызовы"]), (
        "кнопка забаненного осталась бы с «часиками»"
    )


_ПЛАТЕЖИ = _ШАПКА + """
from handlers import premium
from handlers.unban import pay_unban
import texts as T


def оплата(payload):
    return сообщение(successful_payment=SuccessfulPayment.model_construct(
        currency="XTR", total_amount=184, invoice_payload=payload,
        telegram_payment_charge_id="ch_" + payload.split(":")[0],
    ))


async def main():
    # 1. Кнопка оплаты выставляет Stars-счёт
    кнопка = CallbackQuery.model_construct(
        id="1", from_user=_кто, chat_instance="c", data="unban:pay",
        message=сообщение(),
    ).as_(бот)
    await pay_unban(кнопка)

    # 2. Оплата разблокировки зачитывается как разбан, не как подписка
    await premium.on_successful_payment(оплата("unban:v1"))

    # 3. Подписка живёт как раньше
    await premium.on_successful_payment(оплата("plan:plus_1m"))

    # 4. Возврат Stars за разблокировку возвращает бан и гасит токены
    возврат = сообщение(refunded_payment=RefundedPayment.model_construct(
        currency="XTR", total_amount=184, invoice_payload="unban:v1",
        telegram_payment_charge_id="ch_unban",
    ))
    await premium.on_refunded_payment(возврат)

    # 5. Возврат за подписку идёт прежним путём
    возврат_плана = сообщение(refunded_payment=RefundedPayment.model_construct(
        currency="XTR", total_amount=500, invoice_payload="plan:plus_1m",
        telegram_payment_charge_id="ch_plan",
    ))
    await premium.on_refunded_payment(возврат_плана)

    print(json.dumps({"вызовы": вызовы, "разбан_текст": T.UNBAN_DONE[:20]},
                     ensure_ascii=False))


asyncio.run(main())
"""


def test_бот_платежи_разводятся_по_payload():
    итог = _в_боте(_ПЛАТЕЖИ.replace("ЗАБАНЕН", "True").replace(
        "ОТВЕТ_РАЗБАНА", '{"unbanned": True, "reason": ""}'
    ))
    вызовы = [tuple(в) for в in итог["вызовы"]]

    счета = [в for в in вызовы if в[0] == "SendInvoice"]
    assert счета == [("SendInvoice", "unban:v1")], "кнопка не выставила Stars-счёт"

    # Хвост кортежей — суммы для выручки: разбан несёт фактические Stars,
    # подписка — total_amount и валюту из successful_payment
    assert ("unban", "u1", "ch_unban", 349, 184) in вызовы
    assert ("premium", "u1", "ch_plan", "plus", 184, "XTR") in вызовы, (
        "подписка сломалась"
    )
    assert not any(
        в[0] == "premium" and в[2] == "ch_unban" for в in вызовы
    ), "оплата разблокировки зачлась бы как plus_1m"

    assert ("reban", "ch_unban") in вызовы
    assert ("revoke_tokens", "u1") in вызовы, "бан вернулся, а сессии мини-аппа живы"
    assert ("revoke_premium", "ch_plan") in вызовы

    # После возврата человеку снова показана кнопка оплаты (идёт после
    # reban; последним шлётся ответ возврата подписки — не он)
    после_возврата = вызовы[вызовы.index(("reban", "ch_unban")):]
    assert any(
        в[0] == "send" and в[2] == ["unban:pay"] for в in после_возврата
    ), "возврат бана остался без кнопки оплаты"


def test_бот_оплата_без_бана_возвращает_stars():
    """Разбанили админом, пока счёт лежал в чате, — деньги отдаём назад."""
    сценарий = _ШАПКА + """
from handlers import premium


async def main():
    оплата = сообщение(successful_payment=SuccessfulPayment.model_construct(
        currency="XTR", total_amount=184, invoice_payload="unban:v1",
        telegram_payment_charge_id="ch_x",
    ))
    await premium.on_successful_payment(оплата)
    print(json.dumps({"вызовы": вызовы}, ensure_ascii=False))


asyncio.run(main())
"""
    итог = _в_боте(сценарий.replace("ЗАБАНЕН", "False").replace(
        "ОТВЕТ_РАЗБАНА", '{"unbanned": False, "reason": "not_banned"}'
    ))
    вызовы = [tuple(в) for в in итог["вызовы"]]

    assert ("unban", "u1", "ch_x", 349, 184) in вызовы
    assert any(в[0] == "RefundStarPayment" for в in вызовы), (
        "деньги за отсутствующую услугу остались бы у нас"
    )
    assert "уже разблокирован" in [в for в in вызовы if в[0] == "send"][-1][1]


def test_бот_повтор_апдейта_разбана_не_возвращает_stars():
    """Telegram повторил доставку зачтённого апдейта: услуга по этому
    charge_id оказана, и возврат сделал бы разбан бесплатным — оплатил,
    разбанился, дождался ретрая, получил Stars назад. Повтор от честной
    двойной оплаты отличает журнал платежей (проверено на настоящей базе
    в test_бот_покупка_и_возврат_разбана); здесь фиксируем реакцию
    хендлера: «уже зачтён» и НИ ОДНОГО RefundStarPayment."""
    сценарий = _ШАПКА + """
from handlers import premium


async def main():
    оплата = сообщение(successful_payment=SuccessfulPayment.model_construct(
        currency="XTR", total_amount=184, invoice_payload="unban:v1",
        telegram_payment_charge_id="ch_x",
    ))
    await premium.on_successful_payment(оплата)
    print(json.dumps({"вызовы": вызовы}, ensure_ascii=False))


asyncio.run(main())
"""
    итог = _в_боте(сценарий.replace("ЗАБАНЕН", "False").replace(
        "ОТВЕТ_РАЗБАНА", '{"unbanned": False, "reason": "already_processed"}'
    ))
    вызовы = [tuple(в) for в in итог["вызовы"]]

    assert ("unban", "u1", "ch_x", 349, 184) in вызовы
    assert not any(в[0] == "RefundStarPayment" for в in вызовы), (
        "возврат на ретрае делал бы разбан бесплатным"
    )
    assert "уже зачтён" in [в for в in вызовы if в[0] == "send"][-1][1]


def test_бот_автобан_по_жалобам_пишет_память_банов():
    """Бан за жалобы в боте обязан переживать удаление аккаунта, как баны
    API: иначе платная разблокировка обходится бесплатным пересозданием.
    Сама механика вставки (BannedIdentity без дубля) проверена на настоящей
    базе в test_бот_покупка_и_возврат_разбана — здесь фиксируем, что
    create_report ею пользуется."""
    итог = _в_боте(
        """
import inspect, json
import database.connection as conn

src = inspect.getsource(conn.create_report)
print(json.dumps({
    "память": "BannedIdentity(" in src,
    "бан": "is_banned = True" in src,
}))
"""
    )
    assert итог["бан"]
    assert итог["память"], "автобан по жалобам не записал бы личность"
