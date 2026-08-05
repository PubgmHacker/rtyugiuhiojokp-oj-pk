"""Тесты, которые действительно вызывают API по HTTP.

Аудит показал главную слабость прежних тестов: 95 проверок читали текст
исходника через inspect.getsource, и ни одна не делала запрос. Такой тест
проходит, даже если роут отвечает 500 — он проверяет, что нужные слова есть
в файле, а не что поведение верное.

Здесь по-другому: поднимаем приложение, подменяем сессию БД и текущего
пользователя, делаем настоящий запрос и смотрим на ответ. Postgres не нужен —
подменённая сессия отдаёт заранее заготовленные объекты.

Что проверяем именно так: платные гейты (за них платят деньги) и приватность
(за неё отвечаем перед людьми). Остальное можно и текстом.
"""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient


# ── Заготовки ───────────────────────────────────────────────────


def _user(uid: str = "u-me", telegram_id: int = 111, banned: bool = False):
    return SimpleNamespace(
        id=uid,
        telegram_id=telegram_id,
        role="user",
        is_banned=banned,
        is_verified=False,
        created_at=datetime.now(timezone.utc),
        phone=None,
        last_seen_at=None,
    )


def _profile(uid: str, **over):
    """Анкета с полями, которые читают роутеры."""
    поля = dict(
        user_id=uid,
        display_name=f"Имя-{uid}",
        bio="о себе",
        gender="female",
        birth_date=datetime(1998, 5, 10, tzinfo=timezone.utc),
        city="Москва",
        latitude=None,
        longitude=None,
        photos=["https://example.test/1.jpg"],
        interests=["кино"],
        ai_bio=None,
        goal="friendship",
        subculture="",
        mbti="",
        height_cm=170,
        is_incognito=False,
        hide_age=False,
        hide_distance=False,
        hide_from_visitors=False,
        boost_until=None,
        bonus_superlikes=0,
        looking_for="any",
        age_min=18,
        age_max=99,
        distance_max=100,
        filter_goal="",
        filter_subculture="",
        filter_city="",
        filter_height_min=None,
        filter_height_max=None,
        sample_key=0.5,
    )
    поля.update(over)
    return SimpleNamespace(**поля)


class _Result:
    """Минимальный результат session.execute()."""

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
        return self._rows[0] if self._rows else (None, 0)


class _Session:
    """Подменённая сессия: отвечает по сценарию, заданному тестом.

    `plan` — список результатов в порядке вызовов execute(). Так тест остаётся
    читаемым: видно, на какой запрос что вернётся.
    """

    def __init__(self, plan):
        self.plan = list(plan)
        self.added = []

    async def execute(self, *_a, **_kw):
        return self.plan.pop(0) if self.plan else _Result()

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        pass

    async def commit(self):
        pass

    async def rollback(self):
        pass


async def _client(app, session, user):
    """Клиент с подменёнными зависимостями сессии и пользователя."""
    from database.connection import get_session
    from middleware.auth import get_current_user

    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[get_current_user] = lambda: user
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.fixture(autouse=True)
def _clear_overrides(app):
    yield
    app.dependency_overrides.clear()


# ── Платный гейт «кто меня лайкнул» ─────────────────────────────


async def test_бесплатному_не_отдаём_имя_лайкнувшего(app, monkeypatch):
    """Главный платный гейт. Проверяем не текст кода, а сам ответ: в нём не
    должно быть ни имени, ни фото — иначе подписку можно не покупать."""
    from routers import likes

    monkeypatch.setattr(likes, "current_tier", _async_return("free"))

    лайк = SimpleNamespace(
        liker_id="u-fan", liked_id="u-me", type="like", message="привет",
        id="l1", created_at=datetime.now(timezone.utc),
    )
    session = _Session([
        _Result(rows=[]),          # кого я уже оценил
        _Result(rows=[лайк]),      # входящие лайки
    ])

    async with await _client(app, session, _user()) as client:
        r = await client.get("/api/likes/received")

    assert r.status_code == 200
    (карточка,) = r.json()
    assert карточка["is_locked"] is True
    assert карточка["display_name"] == ""
    assert карточка["photos"] == []
    assert карточка["like_message"] == "", "текст лайка утёк мимо гейта"


async def test_подписчику_отдаём_имя_и_текст_лайка(app, monkeypatch):
    """Обратная сторона: заплатил — увидел. Иначе гейт просто ломает функцию."""
    from routers import likes

    monkeypatch.setattr(likes, "current_tier", _async_return("plus"))

    лайк = SimpleNamespace(
        liker_id="u-fan", liked_id="u-me", type="like", message="привет",
        id="l1", created_at=datetime.now(timezone.utc),
    )
    session = _Session([
        _Result(rows=[]),                       # кого я оценил
        _Result(rows=[лайк]),                   # входящие
        _Result(scalar=_profile("u-fan")),      # анкета лайкнувшего
    ])

    async with await _client(app, session, _user()) as client:
        r = await client.get("/api/likes/received")

    (карточка,) = r.json()
    assert карточка["is_locked"] is False
    assert карточка["display_name"] == "Имя-u-fan"
    assert карточка["like_message"] == "привет"


# ── Приватность на живых ответах ────────────────────────────────


async def test_скрытый_возраст_не_приходит_в_ответе(app, monkeypatch):
    """Прежний тест проверял, что в файле есть слово hide_age. Этот проверяет,
    что возраста нет в JSON — то есть что настройка реально работает."""
    from routers import likes

    monkeypatch.setattr(likes, "current_tier", _async_return("plus"))

    лайк = SimpleNamespace(
        liker_id="u-fan", liked_id="u-me", type="like", message="",
        id="l1", created_at=datetime.now(timezone.utc),
    )
    session = _Session([
        _Result(rows=[]),
        _Result(rows=[лайк]),
        _Result(scalar=_profile("u-fan", hide_age=True)),
    ])

    async with await _client(app, session, _user()) as client:
        r = await client.get("/api/likes/received")

    (карточка,) = r.json()
    assert карточка["age"] is None, "возраст пришёл, хотя человек его скрыл"
    # Остальное на месте — скрыли возраст, а не всю анкету
    assert карточка["display_name"] == "Имя-u-fan"


async def test_гости_без_ultra_показывают_число_но_не_имена(app, monkeypatch):
    """Число видно всем — иначе непонятно, за что платить. Имена — за Ultra."""
    from routers import profiles

    monkeypatch.setattr(profiles, "current_tier", _async_return("plus"))
    monkeypatch.setattr(profiles, "count_visits", _async_return(7))

    session = _Session([])

    async with await _client(app, session, _user()) as client:
        r = await client.get("/api/profiles/me/visitors")

    данные = r.json()
    assert данные["total"] == 7
    assert данные["revealed"] is False
    assert данные["visitors"] == []


async def test_гости_с_ultra_раскрываются(app, monkeypatch):
    from routers import profiles

    monkeypatch.setattr(profiles, "current_tier", _async_return("ultra"))
    monkeypatch.setattr(profiles, "count_visits", _async_return(1))
    monkeypatch.setattr(
        profiles,
        "list_visitors",
        _async_return([(_profile("u-guest"), "u-guest", 3, datetime.now(timezone.utc))]),
    )

    session = _Session([])

    async with await _client(app, session, _user()) as client:
        r = await client.get("/api/profiles/me/visitors")

    данные = r.json()
    assert данные["revealed"] is True
    assert данные["visitors"][0]["profile"]["display_name"] == "Имя-u-guest"
    assert данные["visitors"][0]["visits"] == 3


# ── Кейсы: гейт по уровню ───────────────────────────────────────


async def test_бесплатному_кейс_не_открыть(app, monkeypatch):
    """Кейсы — бонус подписки. Бесплатный уровень должен получить отказ, а не
    награду: иначе платить незачем."""
    from routers import cases

    monkeypatch.setattr(cases, "current_tier", _async_return("free"))

    session = _Session([_Result(scalar=0)])

    async with await _client(app, session, _user()) as client:
        r = await client.post("/api/cases/open")

    assert r.status_code == 403
    assert "Plus" in r.json()["detail"]


# ── Оценка фото: нельзя оценить себя ────────────────────────────


async def test_себя_оценить_нельзя_по_http(app):
    """Проверяем реальный код ответа, а не наличие условия в файле."""
    session = _Session([])

    async with await _client(app, session, _user("u-me")) as client:
        r = await client.post(
            "/api/photo-ratings", json={"target_id": "u-me", "score": 5}
        )

    assert r.status_code == 400


async def test_оценка_вне_шкалы_отклоняется_по_http(app):
    session = _Session([])

    async with await _client(app, session, _user()) as client:
        r = await client.post(
            "/api/photo-ratings", json={"target_id": "u-other", "score": 9}
        )

    # Валидация схемы: 422 от FastAPI
    assert r.status_code == 422


# ── Health-check честно сообщает о состоянии ────────────────────


async def test_health_отдаёт_состояние_модерации_фото(app):
    """Молчаливое отключение модерации фото должно быть видно в мониторинге."""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        r = await client.get("/health")

    данные = r.json()
    assert "photo_moderation" in данные["checks"]
    # Без ключа в тестовом окружении — disabled, и это честный ответ
    assert данные["checks"]["photo_moderation"] in ("ok", "disabled", "unknown")


# ── Пересыл ролика в чат и в комнату ────────────────────────────


def _reel(rid: str = "r1", author: str = "u-author", hidden: bool = False):
    return SimpleNamespace(
        id=rid,
        user_id=author,
        video_url="https://example.test/v.mp4",
        cover_url="https://example.test/c.jpg",
        caption="подпись",
        is_hidden=hidden,
    )


@pytest.fixture
def тихая_доставка(monkeypatch):
    """Пересыл в личку идёт через сервис доставки — Redis и APNs в тестах нет.

    Возвращает список отправленных payload-ов, чтобы проверять не только код
    ответа, но и что событие вообще собрано и содержит превью.
    """
    from routers import reels

    отправленное: list[dict] = []

    async def _save(match_id, sender_id, text, image_url=None, reel_id=None):
        return {
            "type": "message", "id": "m1", "match_id": match_id,
            "sender_id": sender_id, "text": text, "image_url": image_url,
            "reel": {"id": reel_id, "video_url": "https://example.test/v.mp4",
                     "cover_url": "https://example.test/c.jpg", "caption": "подпись"}
            if reel_id else None,
            "created_at": None,
        }

    async def _fan_out(payload, *_a, **_kw):
        отправленное.append(payload)

    monkeypatch.setattr(reels, "save_message", _save)
    monkeypatch.setattr(reels, "fan_out", _fan_out)
    return отправленное


async def test_пересыл_в_личку_рассылает_событие_с_превью(app, тихая_доставка):
    """Раньше сообщение молча ложилось в базу: собеседник с открытым чатом
    ничего не видел, пока не перезагрузит переписку."""
    матч = SimpleNamespace(
        id="m-1", user1_id="u-me", user2_id="u-partner", is_active=True,
    )
    session = _Session([
        _Result(scalar=_reel()),      # сам ролик
        _Result(scalar=None),         # блокировки нет
        _Result(scalar=матч),         # мэтч свой и живой
    ])

    async with await _client(app, session, _user()) as client:
        r = await client.post("/api/reels/r1/forward", json={"match_id": "m-1"})

    assert r.status_code == 204
    (payload,) = тихая_доставка
    assert payload["reel"]["id"] == "r1", "событие ушло без превью ролика"


async def test_скрытый_ролик_не_пересылается(app):
    """Снятое модерацией видео не должно продолжать ходить по чатам."""
    session = _Session([_Result(scalar=_reel(hidden=True))])

    async with await _client(app, session, _user()) as client:
        r = await client.post("/api/reels/r1/forward", json={"match_id": "m-1"})

    assert r.status_code == 404


async def test_заблокировавшему_автору_ролик_не_перешлёшь(app):
    """Как и с комментарием: чужое видео не растаскивают по чатам в обход блока."""
    session = _Session([
        _Result(scalar=_reel()),
        _Result(scalar="есть-блокировка"),
    ])

    async with await _client(app, session, _user()) as client:
        r = await client.post("/api/reels/r1/forward", json={"match_id": "m-1"})

    assert r.status_code == 403


async def test_в_чужой_чат_переслать_нельзя(app, тихая_доставка):
    """Мэтч чужой или уже разорван — запрос не должен ничего писать."""
    session = _Session([
        _Result(scalar=_reel()),
        _Result(scalar=None),   # блока нет
        _Result(scalar=None),   # мэтч не найден: чужой либо неактивный
    ])

    async with await _client(app, session, _user()) as client:
        r = await client.post("/api/reels/r1/forward", json={"match_id": "m-чужой"})

    assert r.status_code == 404
    assert not тихая_доставка, "событие ушло, хотя чат не найден"


async def test_пересыл_без_адресата_отклоняется(app):
    session = _Session([
        _Result(scalar=_reel()),
        _Result(scalar=None),
    ])

    async with await _client(app, session, _user()) as client:
        r = await client.post("/api/reels/r1/forward", json={})

    assert r.status_code == 400


async def test_в_комнате_ролик_без_подписи_получает_понятный_текст(app):
    """Пустое сообщение с одним превью читается как сбой приложения."""
    комната = SimpleNamespace(id="room-1", is_active=True)
    session = _Session([
        _Result(scalar=_reel()),
        _Result(scalar=None),        # блока нет
        _Result(scalar=комната),     # комната живая
        _Result(scalar=0),           # антифлуд: сообщений за минуту нет
    ])

    async with await _client(app, session, _user()) as client:
        r = await client.post("/api/reels/r1/forward", json={"room_id": "room-1"})

    assert r.status_code == 204
    (сообщение,) = session.added
    assert сообщение.reel_id == "r1"
    assert сообщение.text, "сообщение в комнате осталось без текста"


async def test_роликами_комнату_не_зальёшь(app):
    """Пересыл шёл мимо антифлуда, и лимит на сообщения обходился роликами."""
    from routers import rooms

    комната = SimpleNamespace(id="room-1", is_active=True)
    session = _Session([
        _Result(scalar=_reel()),
        _Result(scalar=None),
        _Result(scalar=комната),
        _Result(scalar=rooms.FLOOD_PER_MINUTE),   # лимит уже исчерпан
    ])

    async with await _client(app, session, _user()) as client:
        r = await client.post("/api/reels/r1/forward", json={"room_id": "room-1"})

    assert r.status_code == 429
    assert not session.added


async def test_подпись_пересыла_модерируется(app, monkeypatch):
    """Текст под роликом — такой же публичный текст, как сообщение в комнате."""
    from routers import reels

    monkeypatch.setattr(
        reels, "moderate_text",
        _async_return({"blocked": True, "safe": False, "reason": "мат"}),
    )
    monkeypatch.setattr(reels, "log_moderation", _async_return(None))

    session = _Session([
        _Result(scalar=_reel()),
        _Result(scalar=None),
    ])

    async with await _client(app, session, _user()) as client:
        r = await client.post(
            "/api/reels/r1/forward",
            json={"match_id": "m-1", "text": "нехороший текст"},
        )

    assert r.status_code == 422


async def test_история_комнаты_отдаёт_превью_ролика(app):
    """В комнате пересланный ролик выглядел как «поделился видео» без видео."""
    сообщение = SimpleNamespace(
        id="rm1", room_id="room-1", sender_id="u-other", text="смотрите",
        reel_id="r1", is_hidden=False, created_at=datetime.now(timezone.utc),
    )
    session = _Session([
        _Result(scalar=SimpleNamespace(id="room-1", is_active=True)),  # комната
        _Result(rows=[]),                    # кого я заблокировал
        _Result(rows=[]),                    # кто заблокировал меня
        _Result(rows=[сообщение]),           # сообщения
        _Result(rows=[_profile("u-other")]), # анкеты авторов
        _Result(rows=[_reel()]),             # ролики
    ])

    async with await _client(app, session, _user()) as client:
        r = await client.get("/api/rooms/room-1/messages")

    assert r.status_code == 200
    (сообщение_json,) = r.json()["messages"]
    assert сообщение_json["reel"]["video_url"] == "https://example.test/v.mp4"


async def test_снятый_модерацией_ролик_исчезает_из_истории_комнаты(app):
    """Ролик сняли после пересыла — превью не отдаём, сообщение остаётся."""
    сообщение = SimpleNamespace(
        id="rm1", room_id="room-1", sender_id="u-other", text="смотрите",
        reel_id="r1", is_hidden=False, created_at=datetime.now(timezone.utc),
    )
    session = _Session([
        _Result(scalar=SimpleNamespace(id="room-1", is_active=True)),
        _Result(rows=[]),
        _Result(rows=[]),
        _Result(rows=[сообщение]),
        _Result(rows=[_profile("u-other")]),
        _Result(rows=[_reel(hidden=True)]),
    ])

    async with await _client(app, session, _user()) as client:
        r = await client.get("/api/rooms/room-1/messages")

    (сообщение_json,) = r.json()["messages"]
    assert сообщение_json["reel"] is None
    assert сообщение_json["text"] == "смотрите"


# ── Вспомогательное ─────────────────────────────────────────────


def _async_return(value):
    """Заглушка async-функции с фиксированным результатом."""

    async def _f(*_a, **_kw):
        return value

    return _f
