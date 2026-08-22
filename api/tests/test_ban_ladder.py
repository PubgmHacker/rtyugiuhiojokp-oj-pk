"""Лестница сроков бана: рецидив удлиняет срок, отсиженный срок снимает бан.

Что закрепляется:

* ступень выбирается по числу прошлых банов в журнале (ban_applied), а не по
  полю на пользователе: журнал пишется своей сессией и переживает откат
  запроса и удаление аккаунта;
* окно рецидива — 180 дней; древние баны лестницу не двигают;
* лестницу сбрасывает ТОЛЬКО разбан админом (unban_admin). Платный разбан
  (unban_purchase) снимает текущий бан, но ступень сохраняет — иначе 349 ₽
  покупали бы вечный сброс счётчика;
* сбой журнала читается как ноль: нарушитель получает первую ступень, а не
  фантомную эскалацию;
* duration_hours из админки идёт мимо лестницы;
* истёкший срок снимается лениво (lift_ban_if_expired) вместе с памятью банов,
  но БЕЗ журнальной амнистии: следующее нарушение получает ступень выше.

Журнал — настоящая таблица на SQLite, как в test_unban_purchase: окно — это
SQL с датами, фейковая сессия проверяла бы plumbing, а не срез.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from tests.test_unban_purchase import _журнал_на_sqlite, _записать


# ── Заготовки ─────────────────────────────────────────────────────

class _Сессия:
    async def flush(self):
        pass


@pytest.fixture
def тихий_бан(monkeypatch):
    """Заглушить побочные эффекты бана, оставив журнал настоящим."""
    import services.enforcement as e
    import services.realtime as rt

    class _Redis:
        async def publish(self, *_a, **_kw):
            pass

    async def _редис():
        return _Redis()

    async def _тихо(*a, **kw):
        return True

    monkeypatch.setattr(rt, "get_redis", _редис)
    monkeypatch.setattr(e, "remember_ban", _тихо)
    monkeypatch.setattr(e, "revoke_all_for_user", _тихо)


def _нарушитель(**kw):
    основа = dict(
        id="u1", role="user", telegram_id=1, apple_id=None,
        is_banned=False, banned_until=None,
    )
    основа.update(kw)
    return SimpleNamespace(**основа)


def _остаток(user) -> timedelta | None:
    if user.banned_until is None:
        return None
    return user.banned_until - datetime.now(timezone.utc)


# ── prior_ban_count: счёт рецидива ────────────────────────────────

async def test_счёт_пустого_журнала_ноль(monkeypatch):
    import services.enforcement as e

    await _журнал_на_sqlite(monkeypatch)
    assert await e.prior_ban_count("u1") == 0


async def test_счёт_считает_только_ban_applied_в_окне(monkeypatch):
    import services.enforcement as e

    фабрика, Журнал = await _журнал_на_sqlite(monkeypatch)
    await _записать(фабрика, Журнал, "u1", "ban_applied", "blocked", дней_назад=10)
    await _записать(фабрика, Журнал, "u1", "ban_applied", "blocked", дней_назад=100)
    # Древний бан — за окном 180 дней, не считается
    await _записать(фабрика, Журнал, "u1", "ban_applied", "blocked", дней_назад=200)
    # Страйки и чужие записи — не баны
    await _записать(фабрика, Журнал, "u1", "photo_identity", "blocked", дней_назад=5)
    await _записать(фабрика, Журнал, "другой", "ban_applied", "blocked", дней_назад=5)

    assert await e.prior_ban_count("u1") == 2


async def test_разбан_админом_сбрасывает_лестницу(monkeypatch):
    import services.enforcement as e

    фабрика, Журнал = await _журнал_на_sqlite(monkeypatch)
    await _записать(фабрика, Журнал, "u1", "ban_applied", "blocked", дней_назад=30)
    await _записать(фабрика, Журнал, "u1", "ban_applied", "blocked", дней_назад=20)
    await _записать(фабрика, Журнал, "u1", "unban_admin", "safe", дней_назад=10)

    assert await e.prior_ban_count("u1") == 0

    # Бан после амнистии — счёт заново, с единицы
    await _записать(фабрика, Журнал, "u1", "ban_applied", "blocked", дней_назад=1)
    assert await e.prior_ban_count("u1") == 1


async def test_платный_разбан_лестницу_не_сбрасывает(monkeypatch):
    """349 ₽ покупают досрочный выход, а не сброс счётчика рецидива."""
    import services.enforcement as e

    фабрика, Журнал = await _журнал_на_sqlite(monkeypatch)
    await _записать(фабрика, Журнал, "u1", "ban_applied", "blocked", дней_назад=20)
    await _записать(фабрика, Журнал, "u1", "unban_purchase", "safe", дней_назад=10)

    assert await e.prior_ban_count("u1") == 1


async def test_сбой_журнала_даёт_первую_ступень(monkeypatch):
    """Лучше короткий бан рецидивисту, чем вечный — новичку по фантому."""
    import services.enforcement as e

    class _Ломаный:
        def __call__(self):
            raise RuntimeError("db down")

    monkeypatch.setattr("database.connection.async_session_factory", _Ломаный())
    assert await e.prior_ban_count("u1") == 0


# ── ban_user_for_violation: ступени и сроки ───────────────────────

async def test_первый_бан_категории_ad_сутки(monkeypatch, тихий_бан):
    import services.enforcement as e

    await _журнал_на_sqlite(monkeypatch)
    user = _нарушитель()

    assert await e.ban_user_for_violation(_Сессия(), user, "реклама", category="ad")
    assert user.is_banned is True
    assert timedelta(hours=23) < _остаток(user) <= timedelta(hours=24)


async def test_рецидив_поднимается_по_лестнице_до_вечного(monkeypatch, тихий_бан):
    """Каждый бан пишет ban_applied сам — следующий выбирает ступень выше.

    Проверяется вся петля: бан → запись в журнал → счёт → срок.
    """
    import services.enforcement as e

    await _журнал_на_sqlite(monkeypatch)

    ожидания = [
        timedelta(hours=24),
        timedelta(hours=72),
        timedelta(days=7),
        None,  # конец лестницы
        None,  # и дальше вечный: ступень не выходит за край
    ]
    for номер, ожидание in enumerate(ожидания, start=1):
        user = _нарушитель()
        assert await e.ban_user_for_violation(
            _Сессия(), user, f"нарушение №{номер}", category="ad"
        )
        if ожидание is None:
            assert user.banned_until is None, f"бан №{номер} обязан быть вечным"
        else:
            assert ожидание - timedelta(hours=1) < _остаток(user) <= ожидание, (
                f"бан №{номер}: ждали {ожидание}, получили {_остаток(user)}"
            )


async def test_неизвестная_категория_читается_как_manual(monkeypatch, тихий_бан):
    """Опечатка в категории не должна дарить нарушителю короткий срок."""
    import services.enforcement as e

    await _журнал_на_sqlite(monkeypatch)
    user = _нарушитель()

    assert await e.ban_user_for_violation(
        _Сессия(), user, "тест", category="несуществующая"
    )
    assert user.banned_until is None


async def test_явный_срок_из_админки_идёт_мимо_лестницы(monkeypatch, тихий_бан):
    import services.enforcement as e

    фабрика, Журнал = await _журнал_на_sqlite(monkeypatch)
    # Богатая история — лестница дала бы вечный
    for _ in range(5):
        await _записать(фабрика, Журнал, "u1", "ban_applied", "blocked", дней_назад=3)

    user = _нарушитель()
    assert await e.ban_user_for_violation(
        _Сессия(), user, "ручной бан", category="manual", duration_hours=48
    )
    assert timedelta(hours=47) < _остаток(user) <= timedelta(hours=48)

    # Ноль часов — не «мгновенный разбан», а вечный, как задокументировано
    другой = _нарушитель(id="u2")
    assert await e.ban_user_for_violation(
        _Сессия(), другой, "ручной бан", category="manual", duration_hours=0
    )
    assert другой.banned_until is None


async def test_бан_пишет_ban_applied_со_сроком_в_журнал(monkeypatch, тихий_бан):
    """Запись — топливо лестницы и след для разбора: без неё рецидив не виден."""
    from sqlalchemy import select

    import services.enforcement as e

    фабрика, Журнал = await _журнал_на_sqlite(monkeypatch)
    user = _нарушитель()
    await e.ban_user_for_violation(_Сессия(), user, "реклама", category="ad")

    async with фабрика() as session:
        result = await session.execute(
            select(Журнал).where(Журнал.content_type == e.BAN_APPLIED_TYPE)
        )
        (запись,) = result.scalars().all()
    assert запись.user_id == "u1"
    assert запись.content == "ad", "категория — в content: по ней разбирают споры"
    assert запись.result == "blocked"
    assert "реклама" in (запись.reason or "")
    assert "до " in (запись.reason or ""), "в журнале должен быть виден срок"


async def test_автобан_не_трогает_админов_и_не_пишет_журнал(monkeypatch, тихий_бан):
    from sqlalchemy import select

    import services.enforcement as e

    фабрика, Журнал = await _журнал_на_sqlite(monkeypatch)
    админ = _нарушитель(role="admin")

    assert await e.ban_user_for_violation(_Сессия(), админ, "сговор жалобами") is False
    assert админ.is_banned is False

    async with фабрика() as session:
        result = await session.execute(select(Журнал))
        assert result.scalars().all() == [], (
            "несостоявшийся бан не должен двигать лестницу"
        )


# ── lift_ban_if_expired: ленивое истечение ────────────────────────

@pytest.fixture
def прощение(monkeypatch):
    import services.enforcement as e

    вызовы: list[dict] = []

    async def _forgive(session, telegram_id=None, apple_id=None):
        вызовы.append({"telegram_id": telegram_id, "apple_id": apple_id})

    monkeypatch.setattr(e, "forgive", _forgive)
    return вызовы


async def test_истёкший_срок_снимается_вместе_с_памятью_банов(прощение):
    import services.enforcement as e

    user = _нарушитель(
        is_banned=True,
        banned_until=datetime.now(timezone.utc) - timedelta(minutes=1),
    )
    assert await e.lift_ban_if_expired(_Сессия(), user) is True
    assert user.is_banned is False
    assert user.banned_until is None
    assert прощение == [{"telegram_id": 1, "apple_id": None}], (
        "без чистки памяти удаление аккаунта воскресило бы отбытый бан"
    )


async def test_наивная_дата_из_sqlite_тоже_истекает(прощение):
    import services.enforcement as e

    user = _нарушитель(
        is_banned=True,
        banned_until=datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=1),
    )
    assert await e.lift_ban_if_expired(_Сессия(), user) is True


async def test_действующий_и_вечный_баны_не_снимаются(прощение):
    import services.enforcement as e

    действующий = _нарушитель(
        is_banned=True,
        banned_until=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    вечный = _нарушитель(is_banned=True, banned_until=None)
    чистый = _нарушитель()

    assert await e.lift_ban_if_expired(_Сессия(), действующий) is False
    assert действующий.is_banned is True
    assert await e.lift_ban_if_expired(_Сессия(), вечный) is False
    assert вечный.is_banned is True
    assert await e.lift_ban_if_expired(_Сессия(), чистый) is False
    assert прощение == []


async def test_отсиженный_срок_не_амнистирует_лестницу(monkeypatch, прощение):
    """Истечение — не прощение: следующий бан обязан взять ступень выше."""
    import services.enforcement as e

    фабрика, Журнал = await _журнал_на_sqlite(monkeypatch)
    await _записать(фабрика, Журнал, "u1", "ban_applied", "blocked", дней_назад=2)

    user = _нарушитель(
        is_banned=True,
        banned_until=datetime.now(timezone.utc) - timedelta(minutes=1),
    )
    assert await e.lift_ban_if_expired(_Сессия(), user) is True
    assert await e.prior_ban_count("u1") == 1, (
        "lift_ban_if_expired не должен писать амнистию в журнал"
    )


# ── Текст срока ───────────────────────────────────────────────────

def test_текст_срока():
    from services.enforcement import ban_term_text

    assert ban_term_text(None) == "навсегда"
    точка = datetime(2026, 8, 21, 18, 30, tzinfo=timezone.utc)
    assert ban_term_text(точка) == "до 21.08.2026 18:30 (UTC)"


# ── Бот: ленивое истечение и срок на экране бана ──────────────────
#
# Бот живёт в отдельном venv — проверяем его же интерпретатором через
# subprocess, тем же хелпером, что и платёжные сценарии.

from tests.test_unban_purchase import _в_боте  # noqa: E402


def test_бот_снимает_истёкший_бан_при_заходе():
    """/start после срока: бан и память банов сняты, действующий — держится.

    У бота нет get_current_user — его точка ленивого истечения это
    get_or_create_user, через который проходит каждый апдейт
    (RegistrationMiddleware). Без неё отсидевший срок человек оставался бы
    забаненным в боте, пока не зайдёт в мини-апп.
    """
    итог = _в_боте(
        """
import asyncio, json
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

import database.connection as conn
from database.models import Base, BannedIdentity, User


async def main():
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
    conn.async_session_factory = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )
    async with engine.begin() as c:
        await c.run_sync(Base.metadata.create_all)

    вчера = datetime.now(timezone.utc) - timedelta(days=1)
    завтра = datetime.now(timezone.utc) + timedelta(days=1)
    async with conn.async_session_factory() as s:
        async with s.begin():
            s.add(User(id="u1", telegram_id=111, is_banned=True, banned_until=вчера))
            s.add(BannedIdentity(telegram_id=111, reason="спам", banned_until=вчера))
            s.add(User(id="u2", telegram_id=222, is_banned=True, banned_until=завтра))
            s.add(User(id="u3", telegram_id=333, is_banned=True, banned_until=None))

    отсидел = await conn.get_or_create_user(111)
    действует = await conn.get_or_create_user(222)
    вечный = await conn.get_or_create_user(333)

    async with conn.async_session_factory() as s:
        память = (
            await s.execute(
                select(func.count(BannedIdentity.id)).where(
                    BannedIdentity.telegram_id == 111
                )
            )
        ).scalar()

    print(json.dumps({
        "отсидел": {к: отсидел[к] for к in ("is_banned", "banned_until")},
        "действует_бан": действует["is_banned"],
        "действует_срок_есть": bool(действует["banned_until"]),
        "вечный_бан": вечный["is_banned"],
        "вечный_срок": вечный["banned_until"],
        "память": память,
    }, ensure_ascii=False))


asyncio.run(main())
"""
    )

    assert итог["отсидел"] == {"is_banned": False, "banned_until": None}
    assert итог["память"] == 0, "память банов воскресила бы бан после удаления аккаунта"
    assert итог["действует_бан"] is True
    assert итог["действует_срок_есть"] is True, "словарь обязан нести срок для гейта"
    assert итог["вечный_бан"] is True
    assert итог["вечный_срок"] is None


def test_бот_текст_бана_показывает_срок():
    """Временный бан обещает вернуть доступ сам; кривая строка не роняет текст."""
    итог = _в_боте(
        """
import json
import texts as T

print(json.dumps({
    "временный": T.ban_notice(349, until_iso="2099-01-02T03:04:00+00:00"),
    "вечный": T.ban_notice(349),
    "кривой": T.ban_notice(349, until_iso="не дата"),
}, ensure_ascii=False))
"""
    )

    assert "до 02.01.2099 03:04 (UTC)" in итог["временный"]
    assert "вернётся сам" in итог["временный"]
    assert "349" in итог["временный"]

    assert "бессрочная" in итог["вечный"]
    assert "до " not in итог["вечный"].split("Досрочная")[0], (
        "вечному бану нечего обещать про срок"
    )

    assert "бессрочная" in итог["кривой"], "непарсибельный срок читается как вечный"
