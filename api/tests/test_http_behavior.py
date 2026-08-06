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


# ── Дека: анкеты без координат и фильтр расстояния ──────────────


async def test_анкета_без_координат_не_выпадает_из_деки_по_расстоянию(app):
    """Фильтр расстояния должен быть ЧАСТИЧНЫМ: у кого нет геопозиции — не
    исключается, а просто идёт без километража. Иначе человек без координат
    невидим для всех, кто задал расстояние, и об этом никто не предупреждал."""
    моя_анкета = _profile("u-me", latitude=None, longitude=None, distance_max=50)
    кандидат = _profile("u-other", latitude=None, longitude=None)

    session = _Session([
        _Result(scalar=моя_анкета),   # моя анкета
        _Result(rows=[]),             # кого лайкнул
        _Result(rows=[]),             # кого заблокировал
        _Result(rows=[]),             # кто заблокировал меня
        _Result(rows=[]),             # кто пропустил меня
        _Result(rows=[кандидат]),     # первый проход выборки (меньше лимита)
        _Result(rows=[]),             # добор с начала ключа
        _Result(rows=[]),             # активные подписки среди кандидатов
        _Result(rows=[]),             # реферальный буст
    ])

    async with await _client(app, session, _user("u-me")) as client:
        r = await client.get("/api/profiles/deck")

    assert r.status_code == 200, r.text
    карточки = r.json()
    ids = [к["id"] for к in карточки]
    assert "u-other" in ids, "анкета без координат молча выпала из деки"
    (карточка,) = [к for к in карточки if к["id"] == "u-other"]
    assert карточка["distance"] is None, "расстояние посчиталось без координат"


# ── Гости без Ultra видят число, но не имена ─────────────────────


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


async def test_health_показывает_деградацию_redis(app, monkeypatch):
    """Сбой внешней зависимости (Redis) должен быть виден в /health, а не
    молча проглочен: сервис остаётся живым (200), но checks говорит правду."""
    from services import realtime

    async def _broken_get_redis():
        raise RuntimeError("redis is down")

    monkeypatch.setattr(realtime, "get_redis", _broken_get_redis)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        r = await client.get("/health")

    данные = r.json()
    assert данные["checks"]["redis"] == "degraded"


async def test_без_sentry_dsn_приложение_поднимается_и_работает(app):
    """Без SENTRY_DSN (дефолт — пустая строка) поведение не должно меняться
    ни на йоту: приложение поднимается, /health отвечает как обычно."""
    from config import get_settings

    assert get_settings().SENTRY_DSN == ""

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        r = await client.get("/health")

    assert r.status_code in (200, 503)
    assert r.json()["service"] == "souldawn-dating-api"


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


# ── Модерация кадров ролика ─────────────────────────────────────


#: Минимальный валидный JPEG (1×1) — санитайзер в тестах подменён, но
#: content-type и непустое тело нужны, чтобы FastAPI собрал UploadFile.
_КАДР = b"\xff\xd8\xff\xe0\x00\x10JFIF" + b"\x00" * 32
#: Сигнатура mp4 — её проверяет _looks_like_video до всякой модерации.
_ВИДЕО = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 64


@pytest.fixture
def кадры_ролика(monkeypatch):
    """Публикация ролика без R2, Zhipu и Postgres.

    Возвращает список кадров, дошедших до модерации: аудит нашёл, что
    проверялась только присланная клиентом обложка, поэтому тесту важно не
    «ответ 201», а сколько именно кадров реально проверено.
    """
    from routers import reels

    проверенные: list[bytes] = []
    вердикт = {"blocked": False}

    def _sanitize(raw: bytes):
        return raw, "image/jpeg", "jpg"

    async def _moderate_image(данные: bytes):
        проверенные.append(данные)
        return dict(вердикт)

    async def _moderate_text(_текст: str):
        return {"blocked": False}

    monkeypatch.setattr(reels, "sanitize_image", _sanitize)
    monkeypatch.setattr(reels, "moderate_image", _moderate_image)
    monkeypatch.setattr(reels, "moderate_text", _moderate_text)
    monkeypatch.setattr(reels, "log_moderation", _async_return(None))
    monkeypatch.setattr(reels, "upload_photo_to_r2", _async_return("https://example.test/x"))
    return SimpleNamespace(проверенные=проверенные, вердикт=вердикт)


def _файлы_ролика(кадров: int):
    """multipart-тело публикации с заданным числом кадров."""
    files = [("video", ("v.mp4", _ВИДЕО, "video/mp4"))]
    files += [
        ("covers", (f"c{i + 1}.jpg", _КАДР, "image/jpeg")) for i in range(кадров)
    ]
    return files


class _SessionСДефолтами(_Session):
    """Сессия, проставляющая на flush() дефолты колонок.

    Настоящий Postgres заполняет id и счётчики сам, и без этого роутер падает
    на сборке ответа — по причине, не имеющей отношения к проверяемому.
    """

    async def flush(self):
        for obj in self.added:
            for column in obj.__table__.columns:
                if getattr(obj, column.key, None) is not None:
                    continue
                default = column.default
                if default is None:
                    continue
                значение = default.arg
                setattr(obj, column.key, значение(None) if callable(значение) else значение)


async def test_модерация_проверяет_все_присланные_кадры(app, кадры_ролика):
    """Раньше проверялся один кадр: безобидное начало пропускало весь ролик."""
    session = _SessionСДефолтами([_Result(scalar=0)])  # лимит за сутки не выбран

    async with await _client(app, session, _user()) as client:
        r = await client.post(
            "/api/reels", files=_файлы_ролика(3), data={"caption": ""}
        )

    assert r.status_code == 201, r.text
    assert len(кадры_ролика.проверенные) == 3, (
        "модерация увидела не все кадры — вернулась проверка только обложки"
    )


async def test_одного_кадра_недостаточно_для_публикации(app, кадры_ролика):
    """Клиент, присылающий один кадр, снова свёл бы проверку к обложке."""
    session = _SessionСДефолтами([_Result(scalar=0)])

    async with await _client(app, session, _user()) as client:
        r = await client.post(
            "/api/reels", files=_файлы_ролика(1), data={"caption": ""}
        )

    assert r.status_code == 400
    assert not кадры_ролика.проверенные, "ролик пошёл в модерацию с одним кадром"


async def test_нарушение_в_последнем_кадре_блокирует_ролик(app, кадры_ролика):
    """Нарушение в конце видео — ровно тот случай, который обложка не ловила."""
    from routers import reels

    вызовы = {"n": 0}

    async def _moderate_image(данные: bytes):
        вызовы["n"] += 1
        кадры_ролика.проверенные.append(данные)
        # Чисто в начале и середине, нарушение — в последнем кадре
        return {"blocked": вызовы["n"] == reels.MIN_COVERS}

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(reels, "moderate_image", _moderate_image)
    session = _Session([_Result(scalar=0)])
    try:
        async with await _client(app, session, _user()) as client:
            r = await client.post(
                "/api/reels", files=_файлы_ролика(reels.MIN_COVERS), data={"caption": ""}
            )
    finally:
        monkeypatch.undo()

    assert r.status_code == 422, "ролик с нарушением в конце опубликовался"
    assert not session.added, "заблокированный ролик всё равно сохранён в базу"


async def test_скрытый_возраст_не_приходит_в_видео_ленте(app):
    """Пятая копия расчёта возраста отдавала его мимо `hide_age`.

    Настройку чинили в четырёх местах, а в ленте роликов забыли — и тесты
    этого не заметили, потому что проверяли слово в исходнике, а не ответ.
    Здесь настоящий запрос: смотрим, что в JSON возраста нет.
    """
    ролик = SimpleNamespace(
        id="r1", user_id="u-author",
        video_url="https://example.test/v.mp4",
        cover_url="https://example.test/c.jpg",
        caption="подпись", is_hidden=False,
        likes_count=0, comments_count=0, views_count=0,
        created_at=datetime.now(timezone.utc),
    )
    session = _Session([
        _Result(rows=[]),                                   # кого я заблокировал
        _Result(rows=[]),                                   # кто заблокировал меня
        _Result(rows=[ролик]),                              # сама лента
        _Result(scalar=_profile("u-author", hide_age=True)),  # анкета автора
        _Result(scalar=None),                               # мой лайк на ролике
    ])

    async with await _client(app, session, _user()) as client:
        r = await client.get("/api/reels")

    assert r.status_code == 200, r.text
    (карточка,) = r.json()["reels"]
    assert карточка["author_age"] is None, "возраст утёк в ленте роликов"
    # Скрыли возраст, а не автора целиком
    assert карточка["author_name"] == "Имя-u-author"


async def test_возраст_виден_в_ленте_если_его_не_прятали(app):
    """Обратная сторона: иначе «починка» свелась бы к тому, что возраст
    пропал у всех, и подмены никто бы не заметил."""
    ролик = SimpleNamespace(
        id="r1", user_id="u-author",
        video_url="https://example.test/v.mp4",
        cover_url="https://example.test/c.jpg",
        caption="подпись", is_hidden=False,
        likes_count=0, comments_count=0, views_count=0,
        created_at=datetime.now(timezone.utc),
    )
    session = _Session([
        _Result(rows=[]),
        _Result(rows=[]),
        _Result(rows=[ролик]),
        _Result(scalar=_profile("u-author", hide_age=False)),
        _Result(scalar=None),
    ])

    async with await _client(app, session, _user()) as client:
        r = await client.get("/api/reels")

    (карточка,) = r.json()["reels"]
    assert карточка["author_age"] is not None, "возраст пропал у всех подряд"


async def test_чужую_ссылку_нельзя_подставить_в_фото_анкеты(app, monkeypatch):
    """Модерация фото живёт в загрузке, а анкета обновляется другим роутом.

    Без проверки можно было один раз честно загрузить фото, а потом положить
    в анкету ссылку на любую картинку: она попала бы в деку и чаты, не увидев
    ни AI-модерации, ни срезания EXIF.
    """
    from config import get_settings

    настройки = get_settings()
    monkeypatch.setattr(настройки, "R2_PUBLIC_URL", "https://media.souldawn.test", raising=False)

    анкета = _profile("u-me", photos=["https://media.souldawn.test/photos/u-me/1.jpg"])
    session = _Session([_Result(scalar=анкета)])

    async with await _client(app, session, _user()) as client:
        r = await client.patch(
            "/api/profiles/me",
            json={"photos": ["https://evil.test/что-угодно.jpg"]},
        )

    assert r.status_code == 400, "чужая ссылка принята в анкету"
    assert анкета.photos == ["https://media.souldawn.test/photos/u-me/1.jpg"], (
        "анкета изменена, несмотря на отказ"
    )


async def test_своё_загруженное_фото_в_анкету_принимается(app, monkeypatch):
    """Обратная сторона: проверка не должна ломать нормальную загрузку."""
    from config import get_settings

    настройки = get_settings()
    monkeypatch.setattr(настройки, "R2_PUBLIC_URL", "https://media.souldawn.test", raising=False)

    анкета = _profile("u-me", photos=[])
    session = _Session([_Result(scalar=анкета)])

    новое = "https://media.souldawn.test/photos/u-me/2.jpg"
    async with await _client(app, session, _user()) as client:
        r = await client.patch("/api/profiles/me", json={"photos": [новое]})

    assert r.status_code == 200, r.text
    assert новое in анкета.photos


async def test_фото_из_бота_переживают_обновление_анкеты(app, monkeypatch):
    """Без R2 бот кладёт file_id Telegram — это не ссылка, и принимать её надо:
    иначе у пришедших из бота анкета молча осталась бы без фотографий.

    Новый file_id, которого в анкете ещё нет: если проверять только «было
    раньше», бот перестал бы добавлять фото вообще.
    """
    from config import get_settings

    настройки = get_settings()
    monkeypatch.setattr(настройки, "R2_PUBLIC_URL", "https://media.souldawn.test", raising=False)

    анкета = _profile("u-me", photos=["AgACAgIAAxkBAAI-старое"])
    session = _Session([_Result(scalar=анкета)])

    async with await _client(app, session, _user()) as client:
        r = await client.patch(
            "/api/profiles/me",
            json={"photos": ["AgACAgIAAxkBAAI-старое", "AgACAgIAAxkBAAI-новое"]},
        )

    assert r.status_code == 200, r.text
    assert "AgACAgIAAxkBAAI-новое" in анкета.photos


async def test_автобан_по_жалобам_отзывает_токены(app, monkeypatch):
    """Бан обязан гасить уже выданные сессии, а не только запрещать вход.

    Ручной бан в админке это делал, а автобан по жалобам — нет: у забаненного
    оставался живой WebSocket, и жертва харассмента продолжала получать от
    него сообщения до истечения токена (до 72 часов).
    """
    from routers import report

    отозваны: list[str] = []

    async def _revoke(user_id: str):
        отозваны.append(user_id)
        return True

    monkeypatch.setattr(report, "revoke_all_for_user", _revoke)
    monkeypatch.setattr(report, "remember_ban", _async_return(None))

    нарушитель = _user("u-нарушитель", telegram_id=222)
    session = _Session([
        _Result(scalar=нарушитель),   # на кого жалуются
        _Result(scalar=None),         # своей жалобы ещё не было
        _Result(scalar=5),            # пять разных жалобщиков — порог автобана
    ])

    async with await _client(app, session, _user()) as client:
        r = await client.post(
            "/api/report",
            json={"reported_id": "u-нарушитель", "reason": "harassment"},
        )

    assert r.status_code in (200, 201), r.text
    assert нарушитель.is_banned is True, "автобан не сработал"
    assert отозваны == ["u-нарушитель"], (
        "бан выдан, но токены не отозваны — открытый сокет продолжит работать"
    )


class _SessionСЖурналом(_Session):
    """Сессия, запоминающая порядок запросов.

    Для суточных лимитов важен именно порядок: блокировка обязана быть взята
    ДО подсчёта использованного. Если сначала посчитать, а потом блокировать,
    гонка остаётся — параллельные запросы уже прочитали «использовано 0».
    """

    def __init__(self, plan):
        super().__init__(plan)
        self.запросы: list[str] = []

    async def execute(self, statement=None, *a, **kw):
        self.запросы.append(str(statement))
        return await super().execute(statement, *a, **kw)


async def test_кейс_берёт_блокировку_до_подсчёта_попыток(app, monkeypatch):
    """Пять параллельных запросов не должны дать пять наград за одну попытку.

    Проверяем не «ответ 200», а что блокировка взята и взята вовремя: сначала
    lock, потом подсчёт использованного за сутки.
    """
    from routers import cases

    monkeypatch.setattr(cases, "current_tier", _async_return("plus"))

    session = _SessionСЖурналом([
        _Result(scalar=None),   # advisory-lock
        _Result(scalar=0),      # открыто за сутки
        _Result(scalar=None),   # анкета (не дойдём — важен порядок выше)
    ])

    async with await _client(app, session, _user()) as client:
        await client.post("/api/cases/open")

    блокировки = [i for i, q in enumerate(session.запросы) if "advisory" in q]
    подсчёты = [i for i, q in enumerate(session.запросы) if "count" in q.lower()]
    assert блокировки, "открытие кейса идёт без блокировки — лимит обходится гонкой"
    if подсчёты:
        assert блокировки[0] < подсчёты[0], (
            "блокировка взята после подсчёта — гонка осталась"
        )


async def test_буст_берёт_блокировку_до_подсчёта(app, monkeypatch):
    """Тот же лимит и та же гонка, что у кейсов: второй путь из пары."""
    session = _SessionСЖурналом([
        _Result(scalar=_profile("u-me")),   # анкета
        _Result(scalar=None),               # advisory-lock
        _Result(scalar=0),                  # включений за сутки
    ])

    async with await _client(app, session, _user()) as client:
        await client.post("/api/profiles/me/boost")

    блокировки = [i for i, q in enumerate(session.запросы) if "advisory" in q]
    подсчёты = [i for i, q in enumerate(session.запросы) if "count" in q.lower()]
    assert блокировки, "включение буста идёт без блокировки — лимит обходится гонкой"
    if подсчёты:
        assert блокировки[0] < подсчёты[0], (
            "блокировка взята после подсчёта — гонка осталась"
        )


async def test_имя_анкеты_проходит_модерацию(app, monkeypatch):
    """Модерация стояла только на био, а имя видно чаще самой анкеты — в деке,
    в списке чатов, в комнатах, в уведомлениях. Через него уходили реклама,
    контакты и брань."""
    from routers import profiles

    проверено: list[str] = []

    async def _moderate(текст: str):
        проверено.append(текст)
        return {"blocked": "реклама" in текст, "reason": "спам"}

    monkeypatch.setattr(profiles, "moderate_text", _moderate)
    monkeypatch.setattr(profiles, "log_moderation", _async_return(None))

    анкета = _profile("u-me")
    session = _Session([_Result(scalar=анкета)])

    async with await _client(app, session, _user()) as client:
        r = await client.patch(
            "/api/profiles/me", json={"display_name": "реклама @spam_channel"}
        )

    assert r.status_code == 422, "имя с рекламой прошло в анкету"
    assert проверено, "имя вообще не отправлялось на модерацию"


async def test_обычное_имя_принимается(app, monkeypatch):
    """Иначе «починка» свелась бы к тому, что имя нельзя поменять вовсе."""
    from routers import profiles

    monkeypatch.setattr(profiles, "moderate_text", _async_return({"blocked": False}))
    monkeypatch.setattr(profiles, "log_moderation", _async_return(None))

    анкета = _profile("u-me")
    session = _Session([_Result(scalar=анкета)])

    async with await _client(app, session, _user()) as client:
        r = await client.patch("/api/profiles/me", json={"display_name": "Анна"})

    assert r.status_code == 200, r.text
    assert анкета.display_name == "Анна"


async def test_подделанный_токен_apple_не_пускает(app, monkeypatch):
    """Тело JWT — обычный base64: без проверки подписи любой мог бы подставить
    чужой `sub` и войти под чужим аккаунтом. Вход обязан отказать."""
    from routers import auth
    from services.apple_auth import AppleAuthError

    async def _не_прошёл(_токен: str):
        raise AppleAuthError("подпись не сошлась")

    monkeypatch.setattr(auth, "verify_identity_token", _не_прошёл)
    monkeypatch.setattr(auth, "is_banned_identity", _async_return(False))

    session = _SessionСДефолтами([_Result(scalar=None), _Result(scalar=None)])
    async with await _client(app, session, _user()) as client:
        r = await client.post("/api/auth/apple", json={"identity_token": "подделка"})

    данные = r.json()
    assert данные["success"] is False, "подделанный токен пустил в аккаунт"
    assert not данные["token"], "выдан рабочий токен по непроверенному входу"
    assert not session.added, "создан аккаунт по непроверенному токену"


async def test_вход_через_apple_создаёт_аккаунт_без_телеграма(app, monkeypatch):
    """У пришедшего из App Store Telegram может не быть вовсе — аккаунт всё
    равно должен создаться, иначе Sign in with Apple бесполезен."""
    from routers import auth

    async def _прошёл(_токен: str):
        return {"sub": "apple-подпись-12345", "email": "x@privaterelay.appleid.com"}

    monkeypatch.setattr(auth, "verify_identity_token", _прошёл)
    monkeypatch.setattr(auth, "is_banned_identity", _async_return(False))

    session = _SessionСДефолтами([
        _Result(scalar=None),   # такого apple_id ещё нет
        _Result(scalar=None),   # анкеты тоже нет
    ])

    async with await _client(app, session, _user()) as client:
        r = await client.post(
            "/api/auth/apple",
            json={"identity_token": "ок", "full_name": "Анна"},
        )

    данные = r.json()
    assert данные["success"] is True, r.text
    assert данные["token"], "вход прошёл, но токен не выдан"
    созданные = {type(o).__name__ for o in session.added}
    assert "User" in созданные and "Profile" in созданные
    юзер = next(o for o in session.added if type(o).__name__ == "User")
    assert юзер.apple_id == "apple-подпись-12345"
    assert юзер.telegram_id is None, "аккаунту из App Store приписан Telegram"


async def test_забаненный_не_возвращается_через_apple(app, monkeypatch):
    """Бан живёт отдельно от аккаунта. Если это не проверить, забаненный
    заходит через Apple и получает чистую историю."""
    from routers import auth

    async def _прошёл(_токен: str):
        return {"sub": "apple-забаненный"}

    monkeypatch.setattr(auth, "verify_identity_token", _прошёл)
    monkeypatch.setattr(auth, "is_banned_identity", _async_return(True))

    session = _SessionСДефолтами([_Result(scalar=None), _Result(scalar=None)])

    async with await _client(app, session, _user()) as client:
        await client.post("/api/auth/apple", json={"identity_token": "ок"})

    юзер = next(o for o in session.added if type(o).__name__ == "User")
    assert юзер.is_banned is True, "забаненный вернулся через Apple с чистой историей"


async def test_поддельное_уведомление_apple_не_гасит_подписку(app, monkeypatch):
    """Адрес уведомлений открытый — его зовёт сама Apple. Без проверки подписи
    любой прислал бы REFUND и погасил подписку кому угодно."""
    from routers import iap
    from services.appstore import ReceiptInvalid

    def _не_прошло(_payload: str):
        raise ReceiptInvalid("подпись не сошлась")

    monkeypatch.setattr(iap, "is_configured", lambda: True)
    monkeypatch.setattr(iap, "разобрать_уведомление", _не_прошло)

    гасили: list[str] = []

    async def _отзыв(*a, **kw):
        гасили.append("да")
        return {"revoked": True}

    monkeypatch.setattr(iap, "отозвать_покупку", _отзыв)

    session = _Session([])
    async with await _client(app, session, _user()) as client:
        r = await client.post(
            "/api/iap/appstore/notifications", json={"signedPayload": "подделка"}
        )

    assert r.status_code == 400, "поддельное уведомление принято"
    assert not гасили, "подписку погасили по неподтверждённому уведомлению"


async def test_возврат_в_app_store_закрывает_доступ(app, monkeypatch):
    """Раньше отзыв замечали, только когда клиент сам предъявлял чек: до
    этого вернувший деньги пользовался подпиской, а мог и не открывать
    приложение вовсе."""
    from routers import iap

    monkeypatch.setattr(iap, "is_configured", lambda: True)
    monkeypatch.setattr(
        iap,
        "разобрать_уведомление",
        lambda _p: {
            "тип": "REFUND",
            "подтип": "",
            "отзыв": True,
            "original_transaction_id": "ориг-1",
            "transaction_id": "сделка-2",
        },
    )

    вызов = {}

    async def _отзыв(_session, payment_id, provider="appstore", original_id=None):
        вызов.update(payment_id=payment_id, original_id=original_id)
        return {"revoked": True, "user_id": "u"}

    monkeypatch.setattr(iap, "отозвать_покупку", _отзыв)

    session = _Session([])
    async with await _client(app, session, _user()) as client:
        r = await client.post(
            "/api/iap/appstore/notifications", json={"signedPayload": "ок"}
        )

    assert r.status_code == 200, r.text
    assert r.json()["handled"] is True, "возврат пришёл, а доступ не закрыт"
    # У продления transactionId свой, и в журнале лежит именно он —
    # искать обязаны по обоим, иначе продлённая подписка не найдётся
    assert вызов["payment_id"] == "сделка-2"
    assert вызов["original_id"] == "ориг-1"


async def test_обычное_уведомление_apple_ничего_не_ломает(app, monkeypatch):
    """Продление и прочие события приходят на тот же адрес — они не должны
    приводить к отзыву доступа."""
    from routers import iap

    monkeypatch.setattr(iap, "is_configured", lambda: True)
    monkeypatch.setattr(
        iap,
        "разобрать_уведомление",
        lambda _p: {
            "тип": "DID_RENEW",
            "подтип": "",
            "отзыв": False,
            "original_transaction_id": "ориг-1",
            "transaction_id": "сделка-2",
        },
    )

    гасили: list[str] = []

    async def _отзыв(*a, **kw):
        гасили.append("да")
        return {"revoked": True}

    monkeypatch.setattr(iap, "отозвать_покупку", _отзыв)

    session = _Session([])
    async with await _client(app, session, _user()) as client:
        r = await client.post(
            "/api/iap/appstore/notifications", json={"signedPayload": "ок"}
        )

    assert r.status_code == 200
    assert not гасили, "продление подписки погасило доступ"


# ── Вспомогательное ─────────────────────────────────────────────


def _async_return(value):
    """Заглушка async-функции с фиксированным результатом."""

    async def _f(*_a, **_kw):
        return value

    return _f
