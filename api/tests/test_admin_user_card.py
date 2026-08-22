"""Карточка пользователя в админке (GET /api/admin/users/{user_id}).

Что закрепляется:

* досье собирается по живым таблицам: счётчики активности, жалобы с обеих
  сторон, последняя попытка верификации, хвост журнала модерации;
* страйки в карточке считаются ТЕМИ ЖЕ функциями и окнами, которыми банит
  автоматика (text_strike_count, TEXT_STRIKE_RULES, CONTENT_STRIKE_*) — включая
  амнистию разбаном: карточка показывает ровно то, из чего сложится следующий
  бан, и не может разойтись с services/enforcement.py;
* аккаунт без анкеты и подписки (создан ботом, онбординг брошен) — валидная
  карточка с пустыми полями, а не 500;
* PII наружу не уходит: вместо почты и apple_id — флаги привязок.

Таблицы — настоящие, на SQLite: досье это SQL, фейковая сессия проверяла бы
plumbing. Создаём только нужные модели: create_all всех тянет постгресовую
специфику (как в test_unban_purchase).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

АДМИН = SimpleNamespace(id="adm", role="admin")


async def _база_досье(monkeypatch):
    """SQLite со всеми таблицами, которые читает карточка."""
    from sqlalchemy.ext.asyncio import (
        AsyncSession, async_sessionmaker, create_async_engine,
    )
    from sqlalchemy.pool import StaticPool

    import database.connection as dbc
    from models.models import (
        AiModerationLog, Like, Match, Profile, Reel, Report, Story,
        Subscription, User, VerificationAttempt,
    )

    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
    фабрика = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        for модель in (
            User, Profile, Subscription, Like, Match, Reel, Story, Report,
            AiModerationLog, VerificationAttempt,
        ):
            await conn.run_sync(модель.__table__.create)

    # text_strike_count / prior_ban_count берут фабрику из модуля сами
    monkeypatch.setattr(dbc, "async_session_factory", фабрика)
    return фабрика


def _момент(дней_назад: float = 0) -> datetime:
    # Наивный UTC: строки сравнимы в SQLite независимо от сериализации tz
    return datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=дней_назад)


async def _журнал(фабрика, user_id, category, *, content_type="text", result="blocked",
                  content="", дней_назад: float = 0):
    from models.models import AiModerationLog

    async with фабрика() as session:
        session.add(AiModerationLog(
            user_id=user_id, content_type=content_type, content=content,
            result=result, action="none", reason="", category=category,
            created_at=_момент(дней_назад),
        ))
        await session.commit()


async def _карточка(фабрика, user_id):
    from routers.admin import get_user_card

    async with фабрика() as session:
        return await get_user_card(user_id, user=АДМИН, session=session)


# ── Скелет и вырожденные случаи ───────────────────────────────────

async def test_несуществующий_пользователь_404(monkeypatch):
    фабрика = await _база_досье(monkeypatch)
    with pytest.raises(HTTPException) as exc:
        await _карточка(фабрика, "нет-такого")
    assert exc.value.status_code == 404


async def test_аккаунт_без_анкеты_и_подписки_отдаёт_пустые_поля(monkeypatch):
    """Создан ботом, онбординг брошен — частый гость в тикетах поддержки."""
    from models.models import User

    фабрика = await _база_досье(monkeypatch)
    async with фабрика() as session:
        session.add(User(id="u1", telegram_id=1))
        await session.commit()

    карточка = await _карточка(фабрика, "u1")
    assert карточка.display_name == ""
    assert карточка.photos == []
    assert карточка.plan == "free"
    assert карточка.matches_count == 0
    assert карточка.last_verification is None
    assert карточка.recent_moderation == []
    assert all(блок.count == 0 for блок in карточка.strikes.values())


# ── Полное досье ──────────────────────────────────────────────────

async def test_досье_собирает_анкету_подписку_и_счётчики(monkeypatch):
    from models.models import (
        Like, Match, Profile, Report, Subscription, User, VerificationAttempt,
    )

    фабрика = await _база_досье(monkeypatch)
    async with фабрика() as session:
        session.add(User(
            id="u1", telegram_id=100, email="u@example.com", apple_id=None,
        ))
        for другой in ("u2", "u3", "u4"):
            session.add(User(id=другой, telegram_id=hash(другой) % 10_000))
        session.add(Profile(
            user_id="u1", display_name="Ума", gender="female",
            birth_date=datetime(2000, 1, 15), city="Ташкент", bio="привет",
            photos=["a.jpg", "b.jpg"], interests=["кино"], is_paused=True,
        ))
        session.add(Subscription(user_id="u1", plan="plus"))
        # Лайки: pass не считается ни в одну сторону
        session.add(Like(liker_id="u1", liked_id="u2", type="like"))
        session.add(Like(liker_id="u1", liked_id="u3", type="pass"))
        session.add(Like(liker_id="u4", liked_id="u1", type="superlike"))
        # Пары: неактивная (разошлись) в счёт не идёт
        session.add(Match(user1_id="u1", user2_id="u2", is_active=True))
        session.add(Match(user1_id="u1", user2_id="u3", is_active=False))
        # Жалобы: две на него (одна ждёт), одна от него
        session.add(Report(reporter_id="u2", reported_id="u1", reason="спам"))
        session.add(Report(
            reporter_id="u3", reported_id="u1", reason="спам", status="resolved",
        ))
        session.add(Report(reporter_id="u1", reported_id="u2", reason="фейк"))
        session.add(VerificationAttempt(
            user_id="u1", poses=[], status="approved", provider="sumsub",
            reason="", created_at=_момент(1), decided_at=_момент(1),
        ))
        await session.commit()

    карточка = await _карточка(фабрика, "u1")

    assert карточка.display_name == "Ума"
    assert карточка.age is not None and карточка.age >= 26
    assert карточка.photos == ["a.jpg", "b.jpg"]
    assert карточка.is_paused is True
    assert карточка.plan == "plus"

    # Флаги привязок есть, самих значений в схеме нет
    assert карточка.has_email is True
    assert карточка.has_apple is False
    assert not hasattr(карточка, "email")

    assert карточка.likes_sent == 1
    assert карточка.likes_received == 1
    assert карточка.matches_count == 1
    assert (карточка.reports_against, карточка.reports_pending) == (2, 1)
    assert карточка.reports_by == 1
    assert карточка.last_verification is not None
    assert карточка.last_verification.status == "approved"
    assert карточка.last_verification.provider == "sumsub"


async def test_хвост_журнала_обрезает_длинный_текст(monkeypatch):
    from models.models import User

    фабрика = await _база_досье(monkeypatch)
    async with фабрика() as session:
        session.add(User(id="u1", telegram_id=1))
        await session.commit()

    await _журнал(фабрика, "u1", "text", content="х" * 300, дней_назад=1)
    await _журнал(фабрика, "u1", "", content_type="profile_bio",
                  result="safe", content="коротко", дней_назад=0)

    карточка = await _карточка(фабрика, "u1")
    assert len(карточка.recent_moderation) == 2
    # Свежие сверху
    assert карточка.recent_moderation[0].content_type == "profile_bio"
    assert карточка.recent_moderation[0].content_preview == "коротко"
    assert карточка.recent_moderation[1].content_preview == "х" * 100 + "..."


# ── Страйки: карточка не может разойтись с автоматикой ────────────

async def test_страйки_считаются_окнами_автоматики(monkeypatch):
    from models.models import User
    import services.enforcement as e

    фабрика = await _база_досье(monkeypatch)
    async with фабрика() as session:
        session.add(User(id="u1", telegram_id=1))
        await session.commit()

    # Два рекламных в окне 30 дней, один — за окном
    await _журнал(фабрика, "u1", "ad", дней_назад=1)
    await _журнал(фабрика, "u1", "ad", дней_назад=5)
    await _журнал(фабрика, "u1", "ad", дней_назад=40)
    # Контентный страйк живёт в своём окне 90 дней
    await _журнал(фабрика, "u1", "content", content_type="content_removed",
                  дней_назад=60)

    карточка = await _карточка(фабрика, "u1")

    assert карточка.strikes["ad"].count == 2
    assert карточка.strikes["content"].count == 1
    # Лимиты и окна — прямо из правил enforcement, не своя копия
    for категория, (лимит, окно) in e.TEXT_STRIKE_RULES.items():
        assert карточка.strikes[категория].limit == лимит
        assert карточка.strikes[категория].window_days == окно.days
    assert карточка.strikes["content"].limit == e.CONTENT_STRIKE_LIMIT
    assert карточка.strikes["content"].window_days == e.CONTENT_STRIKE_WINDOW.days


async def test_разбан_амнистирует_страйки_и_в_карточке(monkeypatch):
    from models.models import User

    фабрика = await _база_досье(monkeypatch)
    async with фабрика() as session:
        session.add(User(id="u1", telegram_id=1))
        await session.commit()

    await _журнал(фабрика, "u1", "ad", дней_назад=5)
    await _журнал(фабрика, "u1", "ad", дней_назад=4)
    # Разбан админом обрезает окно: счёт начинается заново
    await _журнал(фабрика, "u1", "", content_type="unban_admin",
                  result="safe", дней_назад=3)

    карточка = await _карточка(фабрика, "u1")
    assert карточка.strikes["ad"].count == 0


async def test_счёт_прошлых_банов_попадает_в_карточку(monkeypatch):
    from models.models import User

    фабрика = await _база_досье(monkeypatch)
    async with фабрика() as session:
        session.add(User(id="u1", telegram_id=1))
        await session.commit()

    await _журнал(фабрика, "u1", "", content_type="ban_applied", дней_назад=10)
    await _журнал(фабрика, "u1", "", content_type="ban_applied", дней_назад=30)
    # Древний бан — за окном лестницы (180 дней)
    await _журнал(фабрика, "u1", "", content_type="ban_applied", дней_назад=200)

    карточка = await _карточка(фабрика, "u1")
    assert карточка.prior_bans == 2


# ── Маршрут снаружи ───────────────────────────────────────────────

def test_маршрут_в_схеме(openapi):
    ручка = openapi["paths"]["/api/admin/users/{user_id}"]["get"]
    схема = ручка["responses"]["200"]["content"]["application/json"]["schema"]
    assert схема["$ref"].endswith("AdminUserCard")
