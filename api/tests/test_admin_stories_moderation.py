"""Модерация историй в админке (/api/admin/stories).

Что закрепляется:

* список отдаёт свежие сверху с именем автора, аудиторией и сроком —
  модератору важно, сколько людей это видело и жив ли ещё кадр;
* only_visible прячет уже снятые;
* hide/show переключают is_hidden и пишут аудит story_action — не удаляем:
  жалоба могла быть ложной, а удалённый кадр нечем показать поддержке;
* кривое действие — 400, чужой id — 404.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

АДМИН = SimpleNamespace(id="adm", role="admin")
СЕЙЧАС = datetime.now(timezone.utc).replace(tzinfo=None)


async def _база(monkeypatch):
    from sqlalchemy.ext.asyncio import (
        AsyncSession, async_sessionmaker, create_async_engine,
    )
    from sqlalchemy.pool import StaticPool

    import database.connection as dbc
    from models.models import AdminAuditLog, Profile, Story, User

    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
    фабрика = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        for модель in (User, Profile, Story, AdminAuditLog):
            await conn.run_sync(модель.__table__.create)
    monkeypatch.setattr(dbc, "async_session_factory", фабрика)
    return фабрика


def _история(уид, *, часов_назад=0.0, hidden=False, **правки):
    from models.models import Story

    поля = dict(
        user_id=уид,
        media_url=f"https://cdn/{уид}.jpg",
        caption="",
        audience="matches",
        is_hidden=hidden,
        created_at=СЕЙЧАС - timedelta(hours=часов_назад),
        expires_at=СЕЙЧАС + timedelta(hours=24 - часов_назад),
    )
    поля.update(правки)
    return Story(**поля)


async def _список(фабрика, **правки):
    from routers.admin import list_stories_for_moderation

    # Прямой вызов минует FastAPI, Query-дефолты не подставляются —
    # все параметры передаются явно
    параметры = dict(only_visible=False, page=1, limit=50, user=АДМИН)
    параметры.update(правки)
    async with фабрика() as session:
        return await list_stories_for_moderation(**параметры, session=session)


async def test_список_свежие_сверху_и_фильтр_видимых(monkeypatch):
    from models.models import Profile, User

    фабрика = await _база(monkeypatch)
    async with фабрика() as session:
        session.add_all([
            User(id="автор", telegram_id=1),
            Profile(user_id="автор", display_name="Ума"),
            _история(
                "автор", часов_назад=1,
                caption="привет", audience="everyone", views_count=7,
            ),
            _история("автор", часов_назад=5, hidden=True),
        ])
        await session.commit()

    все = await _список(фабрика)
    assert [(с.caption, с.is_hidden) for с in все] == [("привет", False), ("", True)]
    свежая = все[0]
    assert свежая.author_id == "автор"
    assert свежая.author_name == "Ума"
    assert свежая.audience == "everyone"
    assert свежая.views_count == 7
    assert свежая.media_url == "https://cdn/автор.jpg"
    assert свежая.expires_at is not None, "по сроку UI помечает истёкшие"

    видимые = await _список(фабрика, only_visible=True)
    assert [с.caption for с in видимые] == ["привет"]


async def test_скрыть_и_вернуть_с_аудитом(monkeypatch):
    from sqlalchemy import select

    from models.models import AdminAuditLog, Story, User
    from routers.admin import StoryModerationAction, moderate_story

    фабрика = await _база(monkeypatch)
    async with фабрика() as session:
        session.add_all([User(id="автор", telegram_id=1), _история("автор")])
        await session.commit()
        story_id = (await session.execute(select(Story.id))).scalar_one()

    async with фабрика() as session:
        ответ = await moderate_story(
            StoryModerationAction(story_id=story_id, action="hide"),
            user=АДМИН, session=session,
        )
    assert ответ == {"success": True, "is_hidden": True}

    async with фабрика() as session:
        assert (await session.get(Story, story_id)).is_hidden is True
        запись = (await session.execute(select(AdminAuditLog))).scalars().one()
        assert запись.action == "story_action"
        assert запись.admin_id == "adm"
        assert запись.target_user_id == "автор"
        assert запись.details == {"story_id": story_id, "action": "hide"}

        ответ = await moderate_story(
            StoryModerationAction(story_id=story_id, action="show"),
            user=АДМИН, session=session,
        )
        assert ответ == {"success": True, "is_hidden": False}

    async with фабрика() as session:
        assert (await session.get(Story, story_id)).is_hidden is False


async def test_кривое_действие_и_чужой_id(monkeypatch):
    from routers.admin import StoryModerationAction, moderate_story

    фабрика = await _база(monkeypatch)

    async with фабрика() as session:
        with pytest.raises(HTTPException) as ошибка:
            await moderate_story(
                StoryModerationAction(story_id="х", action="delete"),
                user=АДМИН, session=session,
            )
        assert ошибка.value.status_code == 400

        with pytest.raises(HTTPException) as ошибка:
            await moderate_story(
                StoryModerationAction(story_id="нет-такой", action="hide"),
                user=АДМИН, session=session,
            )
        assert ошибка.value.status_code == 404


def test_маршруты_в_схеме(openapi):
    список = openapi["paths"]["/api/admin/stories"]["get"]
    схема = список["responses"]["200"]["content"]["application/json"]["schema"]
    assert схема["items"]["$ref"].endswith("AdminStory")
    assert "post" in openapi["paths"]["/api/admin/stories/action"]
