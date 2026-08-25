"""Точечное редактирование анкеты — явный null стирает только то, что можно.

Экран «Редактирование» шлёт PATCH из одних изменённых полей, а пустой рост —
явным null: раньше setattr-цикл в `update_my_profile` глушил ВСЕ null подряд,
и указанный однажды рост оставался в анкете навсегда (онбординг пустое поле
просто не отправляет — стереть было нечем). Той же болезнью страдал фильтр
по росту: тумблер «Не важен» в Discover всегда слал `filter_height_min/max:
null`, ответ выглядел успешным, а после перезапуска фильтр возвращался.

Проверяем контракт по HTTP: null стирает ровно поля из СБРАСЫВАЕМЫЕ, null
в остальных полях по-прежнему пропускается (не 500 и не затирание), а
частичный PATCH не трогает не присланные поля — точечность и есть смысл
экрана редактирования.
"""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient


def _profile(**over):
    """Анкета с полями, которые читает `update_my_profile` (как в test_pause)."""
    поля = dict(
        user_id="u-me",
        display_name="Боря",
        bio="о себе",
        gender="male",
        birth_date=datetime(1996, 3, 3, tzinfo=timezone.utc),
        city="Казань",
        latitude=None,
        longitude=None,
        photos=["https://cdn/1.jpg"],
        videos=[],
        interests=["кино"],
        ai_bio=None,
        goal="",
        relation_type="",
        subculture="",
        mbti="",
        height_cm=180,
        is_incognito=False,
        is_paused=False,
        hide_age=False,
        hide_distance=False,
        hide_from_visitors=False,
        boost_until=None,
        bonus_superlikes=0,
        sticker=None,
        verified_photo="",
        decor=None,
        app_theme="",
        looking_for="any",
        age_min=18,
        age_max=99,
        distance_max=100,
        filter_goal="",
        filter_relation_type="",
        filter_subculture="",
        filter_city="",
        filter_height_min=160,
        filter_height_max=190,
        filter_verified=False,
        sample_key=0.5,
        tg_channel="",
    )
    поля.update(over)
    return SimpleNamespace(**поля)


def _user(uid: str = "u-me"):
    return SimpleNamespace(
        id=uid,
        telegram_id=111,
        apple_id=None,
        role="user",
        is_banned=False,
        is_verified=False,
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        phone=None,
        email=None,
        last_seen_at=None,
        locale="ru",
    )


class _Result:
    def __init__(self, rows=None, scalar=None):
        self._rows = rows or []
        self._scalar = scalar

    def scalar_one_or_none(self):
        return self._scalar

    def scalar(self):
        return self._scalar

    def scalars(self):
        return SimpleNamespace(all=lambda: self._rows)

    def all(self):
        return self._rows

    def one(self):
        return (None, 0)


#: Что снимаем со строки анкеты на flush: сбрасываемые поля + пара обычных,
#: по которым проверяется «null не затирает» и «не прислано — не тронуто».
СНИМОК = (
    "height_cm",
    "filter_height_min",
    "filter_height_max",
    "display_name",
    "bio",
    "city",
)


class _Session:
    """Сессия: первый execute — анкета, дальше пустота (как в test_pause)."""

    def __init__(self, профиль):
        self.профиль = профиль
        self.первый = True
        self.change: dict | None = None

    async def execute(self, *_a, **_kw):
        if self.первый:
            self.первый = False
            return _Result(scalar=self.профиль)
        return _Result()

    def add(self, _obj):
        pass

    async def flush(self):
        self.change = {
            k: getattr(self.профиль, k)
            for k in СНИМОК
            if hasattr(self.профиль, k)
        }

    async def commit(self):
        pass

    async def rollback(self):
        pass


async def _client(app, session, user):
    from database.connection import get_session
    from middleware.auth import get_current_user

    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[get_current_user] = lambda: user
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.fixture(autouse=True)
def _clear_overrides(app):
    yield
    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def _без_модерации(monkeypatch):
    """Модерация текста ходит во внешний сервис — здесь проверяется не она."""
    from routers import profiles

    async def _чисто(*_a, **_kw):
        return {"blocked": False, "reason": ""}

    async def _в_журнал(*_a, **_kw):
        return None

    monkeypatch.setattr(profiles, "moderate_text", _чисто)
    monkeypatch.setattr(profiles, "log_moderation", _в_журнал)


# ── Сбрасываемые поля: null стирает ─────────────────────────────


async def test_null_стирает_рост(app):
    """Главный контракт экрана редактирования: пустое поле роста — это null,
    и рост из анкеты пропадает. Другого способа стереть его нет."""
    сессия = _Session(_profile(height_cm=180))
    async with await _client(app, сессия, _user()) as client:
        r = await client.patch("/api/profiles/me", json={"height_cm": None})

    assert r.status_code == 200, r.text
    assert r.json().get("height_cm") is None, (
        "ответ всё ещё показывает рост — клиент решит, что сброс не сработал"
    )
    assert сессия.change and сессия.change["height_cm"] is None, (
        "null не доехал до строки анкеты: ответ выглядит успешным, "
        "а рост остался в базе навсегда"
    )


async def test_null_стирает_фильтр_роста(app):
    """Тумблер «Не важен» в Discover шлёт обе границы null — и это обязано
    доезжать до базы, иначе фильтр воскресает при следующем входе."""
    сессия = _Session(_profile(filter_height_min=160, filter_height_max=190))
    async with await _client(app, сессия, _user()) as client:
        r = await client.patch(
            "/api/profiles/me",
            json={"filter_height_min": None, "filter_height_max": None},
        )

    assert r.status_code == 200, r.text
    assert сессия.change is not None
    assert сессия.change["filter_height_min"] is None, (
        "нижняя граница фильтра не стёрлась — «Не важен» не пережил перезапуск"
    )
    assert сессия.change["filter_height_max"] is None, (
        "верхняя граница фильтра не стёрлась — «Не важен» не пережил перезапуск"
    )


# ── Остальные поля: null по-прежнему пропускается ───────────────


async def test_null_в_обычных_полях_не_затирает(app):
    """Optional в схеме значит «можно не присылать», а не «можно стереть»:
    null в non-nullable полях пропускается, не роняя 500 и не трогая строку."""
    сессия = _Session(_profile(display_name="Боря", bio="о себе"))
    async with await _client(app, сессия, _user()) as client:
        r = await client.patch(
            "/api/profiles/me",
            json={"display_name": None, "bio": None, "city": None},
        )

    assert r.status_code == 200, r.text
    assert сессия.change is not None
    assert сессия.change["display_name"] == "Боря", (
        "null затёр имя — экран редактирования не шлёт null для текстов, "
        "но прямой PATCH не должен уметь ломать анкету"
    )
    assert сессия.change["bio"] == "о себе"
    assert сессия.change["city"] == "Казань"


async def test_точечный_патч_не_трогает_остальное(app):
    """PATCH из одного поля меняет одно поле — точечность и есть смысл экрана
    редактирования: правка био не должна пересохранять рост или имя."""
    сессия = _Session(_profile(height_cm=180, display_name="Боря"))
    async with await _client(app, сессия, _user()) as client:
        r = await client.patch("/api/profiles/me", json={"bio": "новое био"})

    assert r.status_code == 200, r.text
    assert сессия.change is not None
    assert сессия.change["bio"] == "новое био"
    assert сессия.change["height_cm"] == 180, "рост изменился без запроса"
    assert сессия.change["display_name"] == "Боря", "имя изменилось без запроса"
