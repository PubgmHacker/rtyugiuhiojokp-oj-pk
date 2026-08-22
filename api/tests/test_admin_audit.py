"""Аудит-лог админки (models.AdminAuditLog, GET /api/admin/audit).

Что закрепляется:

* каждое мутирующее действие админки — бан, разбан, галочка, вердикт по
  жалобе — оставляет запись: кто, что, с кем, с какими параметрами;
* имена лежат снапшотами и запись не привязана FK: журнал переживает
  удаление и админа, и цели — иначе каскад стирал бы историю ровно тогда,
  когда она нужна (человек удалился после жалобы);
* листинг: свежие сверху, фильтр по действию и админу, пагинация.

Механика самого бана (лестница, память банов, отзыв токенов) покрыта в
test_text_strikes/test_unban_purchase — здесь она заглушена: цель тестов —
след действия, а не его побочные эффекты.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

pytestmark = pytest.mark.usefixtures("тихие_побочки")


async def _база_аудита(monkeypatch):
    """SQLite с таблицами, которые трогают мутирующие ручки админки."""
    from sqlalchemy.ext.asyncio import (
        AsyncSession, async_sessionmaker, create_async_engine,
    )
    from sqlalchemy.pool import StaticPool

    import database.connection as dbc
    from models.models import (
        AdminAuditLog, AiModerationLog, Notification, Profile, Reel, Report,
        User, VerificationAttempt,
    )

    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
    фабрика = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        for модель in (
            User, Profile, Reel, Report, AdminAuditLog, AiModerationLog,
            VerificationAttempt, Notification,
        ):
            await conn.run_sync(модель.__table__.create)

    # log_moderation в ручке разбана пишет своей сессией из модуля
    monkeypatch.setattr(dbc, "async_session_factory", фабрика)
    return фабрика


@pytest.fixture
def тихие_побочки(monkeypatch):
    """Бан/разбан без Redis, уведомлений и памяти банов — журнал настоящий."""
    import routers.admin as adm

    async def _забанен(*_a, **_kw):
        return True

    async def _тихо(*_a, **_kw):
        return None

    monkeypatch.setattr(adm, "ban_user_for_violation", _забанен)
    monkeypatch.setattr(adm, "forgive", _тихо)
    monkeypatch.setattr(adm, "clear_user_revocation", _тихо)
    monkeypatch.setattr(adm, "notify_report_outcome", _тихо)


АДМИН = SimpleNamespace(id="adm", role="admin")


async def _люди(фабрика):
    """Админ «Босс» и обычная «Ума» — имена должны попасть в снапшоты."""
    from models.models import Profile, User

    async with фабрика() as session:
        session.add(User(id="adm", telegram_id=1, role="admin"))
        session.add(Profile(user_id="adm", display_name="Босс"))
        session.add(User(id="u1", telegram_id=2))
        session.add(Profile(user_id="u1", display_name="Ума"))
        await session.commit()


async def _записи(фабрика):
    from sqlalchemy import select
    from models.models import AdminAuditLog

    async with фабрика() as session:
        result = await session.execute(select(AdminAuditLog))
        return list(result.scalars().all())


# ── Записи из ручек ───────────────────────────────────────────────

async def test_бан_пишет_кто_кого_срок_и_причину(monkeypatch):
    from routers.admin import BanRequest, ban_user

    фабрика = await _база_аудита(monkeypatch)
    await _люди(фабрика)

    async with фабрика() as session:
        await ban_user(
            BanRequest(user_id="u1", reason="реклама", duration_hours=72),
            user=АДМИН, session=session,
        )
        await session.commit()

    (запись,) = await _записи(фабрика)
    assert (запись.admin_id, запись.admin_name) == ("adm", "Босс")
    assert (запись.target_user_id, запись.target_name) == ("u1", "Ума")
    assert запись.action == "ban"
    assert запись.details == {"reason": "реклама", "duration_hours": 72}


async def test_разбан_и_галочка_оставляют_свои_записи(monkeypatch):
    from routers.admin import (
        BanRequest, SetVerifiedRequest, set_verified, unban_user,
    )
    from models.models import User
    from sqlalchemy import select

    фабрика = await _база_аудита(monkeypatch)
    await _люди(фабрика)
    async with фабрика() as session:
        цель = (await session.execute(select(User).where(User.id == "u1"))).scalar_one()
        цель.is_banned = True
        await session.commit()

    async with фабрика() as session:
        await unban_user(BanRequest(user_id="u1"), user=АДМИН, session=session)
        await session.commit()
    async with фабрика() as session:
        await set_verified(
            SetVerifiedRequest(user_id="u1", verified=True),
            user=АДМИН, session=session,
        )
        await session.commit()

    записи = {з.action: з for з in await _записи(фабрика)}
    assert set(записи) == {"unban", "set_verified"}
    assert записи["set_verified"].details == {"verified": True}
    assert all(з.target_name == "Ума" for з in записи.values())


async def test_вердикт_по_жалобе_с_удалённой_целью_не_теряет_след(monkeypatch):
    """Цель удалилась до разбора — след остаётся через id из самой жалобы."""
    from routers.admin import ReportAction, report_action
    from models.models import Report

    фабрика = await _база_аудита(monkeypatch)
    await _люди(фабрика)
    async with фабрика() as session:
        session.add(Report(
            id="r1", reporter_id="u1", reported_id="призрак", reason="спам",
        ))
        await session.commit()

    async with фабрика() as session:
        await report_action(
            ReportAction(report_id="r1", action="dismiss", note="фото норм"),
            user=АДМИН, session=session,
        )
        await session.commit()

    (запись,) = await _записи(фабрика)
    assert запись.action == "report_action"
    assert запись.target_user_id == ""  # снапшота нет — аккаунт уже удалён
    assert запись.details["reported_id"] == "призрак"
    assert запись.details["outcome"] == "dismissed"
    assert запись.details["note"] == "фото норм"


async def test_скрытие_ролика_пишет_автора_и_действие(monkeypatch):
    from routers.admin import ReelModerationAction, moderate_reel
    from models.models import Reel

    фабрика = await _база_аудита(monkeypatch)
    await _люди(фабрика)
    async with фабрика() as session:
        session.add(Reel(id="reel1", user_id="u1", video_url="v.mp4"))
        await session.commit()

    async with фабрика() as session:
        await moderate_reel(
            ReelModerationAction(reel_id="reel1", action="hide"),
            user=АДМИН, session=session,
        )

    (запись,) = await _записи(фабрика)
    assert запись.action == "reel_action"
    assert запись.target_name == "Ума"
    assert запись.details == {"reel_id": "reel1", "action": "hide"}


# ── Листинг ───────────────────────────────────────────────────────

async def test_листинг_свежие_сверху_фильтр_и_страницы(monkeypatch):
    from routers.admin import list_audit
    from models.models import AdminAuditLog

    фабрика = await _база_аудита(monkeypatch)
    старт = datetime.now(timezone.utc).replace(tzinfo=None)
    async with фабрика() as session:
        for i, действие in enumerate(["ban", "unban", "ban", "set_verified"]):
            session.add(AdminAuditLog(
                id=f"a{i}", admin_id="adm", admin_name="Босс",
                action=действие, target_user_id="u1", target_name="Ума",
                details={"n": i}, created_at=старт + timedelta(minutes=i),
            ))
        await session.commit()

    # Прямой вызов минует FastAPI, поэтому Query-дефолты не подставляются —
    # все параметры передаются явно
    def _параметры(**правки):
        база = dict(action="all", admin_id="", page=1, limit=50,
                    user=АДМИН)
        база.update(правки)
        return база

    async with фабрика() as session:
        всё = await list_audit(**_параметры(), session=session)
        баны = await list_audit(**_параметры(action="ban"), session=session)
        чужого = await list_audit(**_параметры(admin_id="другой"), session=session)
        хвост = await list_audit(**_параметры(page=2, limit=3), session=session)

    assert [з.details["n"] for з in всё] == [3, 2, 1, 0]  # свежие сверху
    assert [з.details["n"] for з in баны] == [2, 0]
    assert чужого == []
    assert [з.details["n"] for з in хвост] == [0]


# ── Маршрут снаружи ───────────────────────────────────────────────

def test_маршрут_в_схеме(openapi):
    ручка = openapi["paths"]["/api/admin/audit"]["get"]
    схема = ручка["responses"]["200"]["content"]["application/json"]["schema"]
    assert схема["items"]["$ref"].endswith("AdminAuditEntry")
