"""Пауза анкеты — включение, выключение и честность ответов.

Пауза была фичей одного лишь Telegram-бота: колонка `is_paused` в базе была,
бот писал в неё, но мини-апп и iOS-аккаунт не могли ни включить её, ни
выключить, ни даже узнать о ней — `ProfileUpdate` её не принимал, ответы её
не отдавали. Человек, скрывший анкету в боте, открывал приложение и видел
тишину без объяснения.

Здесь проверяем сам контракт по HTTP, а не текст исходников: включение и
выключение паузой, отсутствие платного гейта (убрать себя с витрины — не
товар), честность ответов и то, что чужая пауза наружу не уходит.
"""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient


def _profile(пауза: bool = False, **over):
    """Анкета с полями, которые читает `update_my_profile`."""
    поля = dict(
        user_id="u-me",
        display_name="Боря",
        bio="о себе",
        gender="male",
        birth_date=datetime(1996, 3, 3, tzinfo=timezone.utc),
        city="Казань",
        latitude=None,
        longitude=None,
        photos=[],
        videos=[],
        interests=[],
        ai_bio=None,
        goal="",
        relation_type="",
        subculture="",
        mbti="",
        height_cm=None,
        is_incognito=False,
        is_paused=пауза,
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
        filter_height_min=None,
        filter_height_max=None,
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


class _Session:
    """Сессия: первый execute — анкета, дальше пустота.

    `change` — то, что накапливает `update_my_profile` до flush: по нему
    проверяем, что пауза реально доехала до строки, а не только до ответа.
    """

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
        # update_my_profile пишет циклом setattr по анкете — снимаем снимок
        self.change = {
            k: getattr(self.профиль, k)
            for k in ("is_paused", "is_incognito", "display_name")
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


# ── Включение и выключение ─────────────────────────────────────


async def test_пауза_включается_правкой_анкеты(app):
    """Главный контракт: мини-апп может скрыть анкету."""
    user, профиль = _user(), _profile(пауза=False)
    сессия = _Session(профиль)
    async with await _client(app, сессия, user) as client:
        r = await client.patch("/api/profiles/me", json={"is_paused": True})

    assert r.status_code == 200, r.text
    assert r.json()["is_paused"] is True, (
        f"ответ не отразил паузу ({r.json().get('is_paused')!r}) — клиент "
        f"не узнает, что анкета скрыта"
    )
    assert сессия.change and сессия.change["is_paused"] is True, (
        "пауза не доехала до строки анкеты: ответ выглядит успешным, "
        "а база не тронута"
    )


async def test_пауза_выключается(app):
    """Снятие паузы — тот же путь: правка анкеты."""
    user, профиль = _user(), _profile(пауза=True)
    сессия = _Session(профиль)
    async with await _client(app, сессия, user) as client:
        r = await client.patch("/api/profiles/me", json={"is_paused": False})

    assert r.status_code == 200, r.text
    assert r.json()["is_paused"] is False
    assert сессия.change and сессия.change["is_paused"] is False, (
        "пауза не снята в базе — человек уверен, что вернулся в выдачу, "
        "а его по-прежнему никто не видит"
    )


async def test_пауза_не_требует_подписки(app):
    """Убрать себя с витрины — не платная возможность.

    Инкогнито продаётся, пауза — нет: иначе у бесплатного аккаунта не было
    бы способа уйти, кроме удаления, и пришлось бы выдумывать оправдание
    человеку, который просто взял перерыв.
    """
    async with await _client(app, _Session(_profile(пауза=False)), _user()) as client:
        r = await client.patch("/api/profiles/me", json={"is_paused": True})

    assert r.status_code == 200, r.text
    assert r.json()["is_paused"] is True


async def test_пауза_в_своей_анкете(app):
    """GET /me отдаёт паузу: по ней мини-апп показывает предупреждение."""
    async with await _client(app, _Session(_profile(пауза=True)), _user()) as client:
        r = await client.get("/api/profiles/me")

    assert r.status_code == 200, r.text
    assert r.json()["is_paused"] is True, (
        "своя анкета не сообщает о паузе — мини-апп не узнает, что его "
        "владельца никто не видит"
    )


async def test_пауза_в_ответе_на_вход(app):
    """Ответ входа несёт паузу с первого кадра.

    Плашку предупреждения рисует оболочка приложения по данным store,
    которые приходят из /auth/telegram. Забудь паузу здесь — человек,
    скрывший анкету месяц назад, снова увидит тишину без объяснения.
    """
    from routers.auth import _user_to_profile

    профиль = _profile(пауза=True)
    ответ = _user_to_profile(_user(), профиль)

    assert ответ.is_paused is True, (
        "пауза не попала в ответ на вход — до первого запроса анкеты "
        "клиент считает, что всё видно"
    )


async def test_пауза_не_уходит_в_чужую_анкету(app):
    """Чужая пауза наружу не отдаётся.

    Снаружи пауза выглядит просто отсутствием анкеты — раскрывать, что
    человек «взял перерыв», нечего и незачем: это его личное состояние.
    Проверяем на том же хелпере, который собирает карточку в деке и в
    разделе «Гости».
    """
    from routers.profiles import _deck_like_profile

    чужая = await _deck_like_profile(
        _Session(None), _profile(пауза=True), "u-other", is_verified=False
    )

    assert чужая.is_paused is False, (
        "открытая анкета несёт чужую паузу — состояние человека разглашено "
        "и, что хуже, клиент отрисовал бы плашку «вас никто не видит» "
        "тому, у кого пауза не включена"
    )
