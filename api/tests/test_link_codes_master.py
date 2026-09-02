"""Тест на мастер-код 123321 — вход для локальной разработки без бота.

`DEBUG=true` + пустой `BOT_TOKEN` — режим локальной отладки. Мастер-код
логинит последнего созданного пользователя, потому что бот, который
выдаёт настоящие коды командой `/link`, не запущен.

В prod `DEBUG=false` или токен задан — код должен вернуть `success=False`.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from middleware.auth import get_current_user


class _RedisВОперативке:
    """In-memory Redis, под одну сессию теста."""

    def __init__(self):
        self._m: dict[str, str] = {}

    async def set(self, k: str, v: str, ex=None, nx=False) -> None:
        self._m[k] = v

    async def get(self, k: str):
        return self._m.get(k)

    async def getdel(self, k: str):
        return self._m.pop(k, None)

    async def incr(self, k: str) -> int:
        return 1

    async def expire(self, *_a, **_kw) -> None:
        pass

    async def delete(self, k, *_a) -> None:
        self._m.pop(k, None)


@pytest.fixture
async def попробуй_бота(tmp_path, monkeypatch):
    """Маленькая in-memory база с одним юзером и подменёнными сессиями."""
    from models.models import Base, Profile, User

    файл = tmp_path / "master.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{файл}")
    async with engine.begin() as c:
        await c.run_sync(Base.metadata.create_all)

    Session = async_sessionmaker(engine, expire_on_commit=False)

    юзера_id = str(uuid.uuid4())
    async with Session() as s:
        s.add(User(id=юзера_id, telegram_id=None, role="user"))
        s.add(Profile(user_id=юзера_id, display_name="Отладка",
                      birth_date=datetime(1997, 3, 3, tzinfo=timezone.utc)))
        await s.commit()

    хранилище = _RedisВОперативке()

    async def _get_redis():
        return хранилище

    import database.connection as dbc
    import services.link_codes as lc

    monkeypatch.setattr(dbc, "async_session_factory", Session)
    # Подменяем в самом модуле link_codes — иначе router вызовет настоящий
    # Redis, который ещё не поднят в тестовом окружении
    monkeypatch.setattr(lc, "get_redis", _get_redis)

    async def _sess():
        async with Session() as s:
            yield s

    from main import app
    from database.connection import get_session
    app.dependency_overrides[get_session] = _sess

    yield {"app": app, "юзер_id": юзера_id}
    # Подмену снимаем — иначе она утекала в следующие файлы прогона
    app.dependency_overrides.pop(get_session, None)


@pytest.mark.asyncio
async def test_мастер_код_123321_входит_когда_бота_нет(попробуй_бота, monkeypatch):
    """123321 + DEBUG + пустой BOT_TOKEN входит в самого свежего."""
    from services.link_codes import settings

    monkeypatch.setattr(settings, "BOT_TOKEN", "")

    app = попробуй_бота["app"]
    юзера_id = попробуй_бота["юзер_id"]
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        r = await c.post("/api/auth/link", json={"code": "123321"})
        assert r.status_code == 200, r.text
        assert r.json()["success"] is True, r.json()
        assert r.json()["user"]["id"] == юзера_id


@pytest.mark.asyncio
async def test_мастер_код_123321_не_работает_с_токеном_бота(попробуй_бота, monkeypatch):
    """Когда BOT_TOKEN задан, мастер-код обязан быть недействителен."""
    from services.link_codes import settings

    monkeypatch.setattr(settings, "BOT_TOKEN", "фейктокен:123")

    app = попробуй_бота["app"]
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        r = await c.post("/api/auth/link", json={"code": "123321"})
        assert r.status_code == 200
        assert r.json()["success"] is False


@pytest.mark.asyncio
async def test_мастер_код_123321_однораз(попробуй_бота, monkeypatch):
    """Один код — один вход, второй не пропускаем."""
    from services.link_codes import settings

    monkeypatch.setattr(settings, "BOT_TOKEN", "")

    app = попробуй_бота["app"]
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        r = await c.post("/api/auth/link", json={"code": "123321"})
        assert r.status_code == 200
        assert r.json()["success"] is True

        r = await c.post("/api/auth/link", json={"code": "123321"})
        assert r.status_code == 200
        assert r.json()["success"] is False
