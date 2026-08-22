"""Верификация профиля (галочка): контракт эндпоинтов и границы безопасности.

Здесь проверяется не «код возвращает 200», а обещания фичи:

* галочку нельзя получить в обход живой проверки;
* отказ ОБЯЗАН сохраниться (иначе суточный лимит не считается и перебор
  чужих фото бесплатен) — поэтому 422 приходит ответом, а не исключением;
* сбой AI не сжигает попытку и не раздаёт галочки (fail-closed);
* кадры — биометрия: в журнал модерации уходит только текст вердикта.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient

# ── Заготовки ───────────────────────────────────────────────────


def _user(uid: str = "u-me", verified: bool = False):
    return SimpleNamespace(
        id=uid,
        telegram_id=111,
        role="user",
        is_banned=False,
        is_verified=verified,
        created_at=datetime.now(timezone.utc),
    )


def _profile(uid: str = "u-me", photos=None):
    return SimpleNamespace(
        user_id=uid,
        photos=["https://cdn.test/me.jpg"] if photos is None else photos,
    )


def _задание(poses=("straight", "left", "up"), минут_назад: int = 1):
    return SimpleNamespace(
        id="att-1",
        user_id="u-me",
        poses=list(poses),
        status="issued",
        reason="",
        decided_at=None,
        created_at=datetime.now(timezone.utc) - timedelta(minutes=минут_назад),
    )


class _Result:
    def __init__(self, scalar=None):
        self._scalar = scalar

    def scalar_one_or_none(self):
        return self._scalar

    def scalar(self):
        return self._scalar


class _Session:
    """Сессия по сценарию: plan — результаты execute() в порядке вызовов."""

    def __init__(self, plan):
        self.plan = list(plan)
        self.added = []

    async def execute(self, *_a, **_kw):
        return self.plan.pop(0) if self.plan else _Result()

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        pass

    async def refresh(self, obj):
        # Имитируем то, что в бою делает БД на flush/refresh: id из default,
        # created_at из server_default now()
        if getattr(obj, "id", None) is None:
            obj.id = "att-new"
        if getattr(obj, "created_at", None) is None:
            obj.created_at = datetime.now(timezone.utc)

    async def commit(self):
        pass

    async def rollback(self):
        pass


def _client(app, session, user):
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
def _без_настоящих_вызовов(monkeypatch):
    """Санитизация, скачивание референса и журнал — по умолчанию заглушки.

    Каждый тест при необходимости переопределяет вердикт AI сам; сеть и
    Pillow в этих тестах не участвуют.
    """
    from routers import verification as v

    monkeypatch.setattr(v, "sanitize_image", lambda b: (b, "image/jpeg", "jpg"))

    async def _референс(_url):
        return b"reference-bytes"

    monkeypatch.setattr(v, "_скачать_референс", _референс)

    журнал: list[tuple] = []

    async def _лог(user_id, content_type, content, verdict):
        журнал.append((user_id, content_type, content, verdict))

    monkeypatch.setattr(v, "log_moderation", _лог)
    yield журнал


def _кадры(n: int):
    return [("frames", (f"f{i}.jpg", b"jpg-bytes-%d" % i, "image/jpeg")) for i in range(n)]


def _вердикт(monkeypatch, **поля):
    """Подменить verify_liveness фиксированным вердиктом."""
    from routers import verification as v

    итог = {
        "live": True,
        "real_face": True,
        "poses_match": True,
        "same_person": True,
        "matches_profile": True,
        "reason": "ok",
    }
    итог.update(поля)

    async def _fake(frames, reference, poses):
        return dict(итог)

    monkeypatch.setattr(v, "verify_liveness", _fake)


# ── Статус ──────────────────────────────────────────────────────


async def test_статус_без_фото_ведёт_к_загрузке_фото(app):
    """has_photo=False — UI по нему отправляет человека сначала в анкету."""
    session = _Session([_Result(scalar=0), _Result(scalar=None), _Result(scalar=None)])
    async with _client(app, session, _user()) as c:
        r = await c.get("/api/verification/status")
    assert r.status_code == 200
    тело = r.json()
    assert тело["is_verified"] is False
    assert тело["has_photo"] is False
    assert тело["challenge"] is None
    assert тело["attempts_left"] == 5


async def test_статус_верифицированного_не_считает_фото(app):
    """У подтверждённого has_photo=True всегда: проверка ему уже не нужна."""
    session = _Session([_Result(scalar=0)])
    async with _client(app, session, _user(verified=True)) as c:
        r = await c.get("/api/verification/status")
    assert r.status_code == 200
    тело = r.json()
    assert тело["is_verified"] is True
    assert тело["has_photo"] is True
    assert тело["challenge"] is None


async def test_статус_отдаёт_живое_задание(app):
    """Обновление страницы не теряет задание: клиент продолжает по нему же."""
    задание = _задание(минут_назад=2)
    session = _Session([
        _Result(scalar=0),
        _Result(scalar=задание),
        _Result(scalar=_profile()),
    ])
    async with _client(app, session, _user()) as c:
        r = await c.get("/api/verification/status")
    тело = r.json()
    assert тело["challenge"]["id"] == "att-1"
    assert тело["challenge"]["poses"] == ["straight", "left", "up"]
    # 10 минут срока минус ~2 прошедшие: остаток в разумном окне
    assert 0 < тело["challenge"]["expires_in"] <= 8 * 60


# ── Выдача задания ──────────────────────────────────────────────


async def test_задание_начинается_с_анфаса_и_содержит_случайные_позы(app):
    """Первый кадр всегда анфас — он же база сравнения с фото анкеты."""
    session = _Session([
        _Result(scalar=0),
        _Result(scalar=_profile()),
        _Result(scalar=None),
    ])
    async with _client(app, session, _user()) as c:
        r = await c.post("/api/verification/challenge")
    assert r.status_code == 200
    тело = r.json()
    assert тело["poses"][0] == "straight"
    assert len(тело["poses"]) == 3
    # Случайные позы — из известного пула и без повторов
    хвост = тело["poses"][1:]
    assert set(хвост) <= {"left", "right", "up", "smile"}
    assert len(set(хвост)) == len(хвост)
    assert session.added, "задание должно сохраниться"


async def test_живое_задание_не_перевыпускается(app):
    """Обновлением страницы нельзя крутить позы под заготовленную запись."""
    задание = _задание()
    session = _Session([
        _Result(scalar=0),
        _Result(scalar=_profile()),
        _Result(scalar=задание),
    ])
    async with _client(app, session, _user()) as c:
        r = await c.post("/api/verification/challenge")
    assert r.status_code == 200
    assert r.json()["id"] == "att-1"
    assert not session.added, "новое задание не должно создаваться"


async def test_задание_не_выдаётся_без_фото(app):
    session = _Session([_Result(scalar=0), _Result(scalar=None)])
    async with _client(app, session, _user()) as c:
        r = await c.post("/api/verification/challenge")
    assert r.status_code == 400


async def test_задание_не_выдаётся_верифицированному(app):
    async with _client(app, _Session([]), _user(verified=True)) as c:
        r = await c.post("/api/verification/challenge")
    assert r.status_code == 409


async def test_лимит_отказов_закрывает_выдачу(app):
    """Пять отказов за сутки — до завтра ни заданий, ни отправок."""
    session = _Session([_Result(scalar=5)])
    async with _client(app, session, _user()) as c:
        r = await c.post("/api/verification/challenge")
    assert r.status_code == 429


# ── Отправка кадров ─────────────────────────────────────────────


async def test_успех_ставит_галочку(app, monkeypatch, _без_настоящих_вызовов):
    """Все проверки зелёные → is_verified и статус approved."""
    _вердикт(monkeypatch)
    user = _user()
    задание = _задание()
    session = _Session([
        _Result(scalar=0),
        _Result(scalar=задание),
        _Result(scalar=_profile()),
    ])
    async with _client(app, session, user) as c:
        r = await c.post("/api/verification/submit", files=_кадры(3))
    assert r.status_code == 200
    assert r.json() == {"verified": True}
    assert user.is_verified is True
    assert задание.status == "approved"
    # Биометрия не утекает в журнал: там текст про позы, не байты кадров
    журнал = _без_настоящих_вызовов
    assert журнал and "liveness" in журнал[0][2]
    assert b"jpg-bytes" not in журнал[0][2].encode()


async def test_отказ_отдаёт_422_ответом_и_помечает_попытку(app, monkeypatch):
    """Отказ обязан пережить запрос: get_session коммитит только на чистом
    возврате, поэтому 422 приходит ответом, а не исключением. Иначе суточный
    лимит не считается и перебор чужих фото бесплатен."""
    _вердикт(monkeypatch, matches_profile=False)
    user = _user()
    задание = _задание()
    session = _Session([
        _Result(scalar=0),
        _Result(scalar=задание),
        _Result(scalar=_profile()),
    ])
    async with _client(app, session, user) as c:
        r = await c.post("/api/verification/submit", files=_кадры(3))
    assert r.status_code == 422
    тело = r.json()
    assert тело["attempts_left"] == 4
    assert "не совпало" in тело["detail"]
    assert user.is_verified is False
    assert задание.status == "rejected"
    assert задание.reason == тело["detail"]


async def test_дипфейк_не_проходит_даже_живой(app, monkeypatch):
    """Нейросетевая подмена лица: все прочие оси зелёные (съёмка и правда
    живая, позы выполнены), но real_face=False — галочки нет. Это отдельная
    ось: live ловит экран и статичные фото, real_face — face swap поверх
    живого видео."""
    _вердикт(monkeypatch, real_face=False)
    user = _user()
    задание = _задание()
    session = _Session([
        _Result(scalar=0),
        _Result(scalar=задание),
        _Result(scalar=_profile()),
    ])
    async with _client(app, session, user) as c:
        r = await c.post("/api/verification/submit", files=_кадры(3))
    assert r.status_code == 422
    тело = r.json()
    assert "фильтр" in тело["detail"]
    assert user.is_verified is False
    assert задание.status == "rejected"


async def test_старый_вердикт_без_real_face_не_даёт_галочку(app, monkeypatch):
    """Ключа real_face в вердикте нет вовсе (модель ответила по старой схеме,
    урезанный JSON) — считаем ложью, а не правдой: отсутствие проверки не
    равно её прохождению."""
    from routers import verification as v

    async def _fake(frames, reference, poses):
        return {
            "live": True, "poses_match": True, "same_person": True,
            "matches_profile": True, "reason": "no real_face key",
        }

    monkeypatch.setattr(v, "verify_liveness", _fake)
    user = _user()
    задание = _задание()
    session = _Session([
        _Result(scalar=0),
        _Result(scalar=задание),
        _Result(scalar=_profile()),
    ])
    async with _client(app, session, user) as c:
        r = await c.post("/api/verification/submit", files=_кадры(3))
    assert r.status_code == 422
    assert user.is_verified is False
    assert задание.status == "rejected"


async def test_одинаковые_кадры_отклоняются_без_ai(app, monkeypatch):
    """Байт-в-байт одинаковые кадры живая съёмка не даёт (шум сенсора,
    перекодирование). Дубликаты — один файл, присланный мимо клиента:
    отказ без траты вызова AI, попытка сжигается как обычный отказ."""
    from routers import verification as v

    async def _fake(frames, reference, poses):
        raise AssertionError("AI не должен вызываться для дубликатов")

    monkeypatch.setattr(v, "verify_liveness", _fake)
    user = _user()
    задание = _задание()
    session = _Session([_Result(scalar=0), _Result(scalar=задание)])
    файлы = [("frames", (f"f{i}.jpg", b"same-bytes", "image/jpeg")) for i in range(3)]
    async with _client(app, session, user) as c:
        r = await c.post("/api/verification/submit", files=файлы)
    assert r.status_code == 422
    assert "живая съёмка" in r.json()["detail"]
    assert user.is_verified is False
    assert задание.status == "rejected"


async def test_сбой_ai_не_сжигает_попытку_и_не_даёт_галочку(app, monkeypatch):
    """Fail-closed: нет вердикта — нет галочки, задание остаётся issued,
    человек повторит отправку по нему же."""
    from routers import verification as v

    async def _fake(frames, reference, poses):
        return {"unavailable": True, "reason": "down"}

    monkeypatch.setattr(v, "verify_liveness", _fake)
    user = _user()
    задание = _задание()
    session = _Session([
        _Result(scalar=0),
        _Result(scalar=задание),
        _Result(scalar=_profile()),
    ])
    async with _client(app, session, user) as c:
        r = await c.post("/api/verification/submit", files=_кадры(3))
    assert r.status_code == 503
    assert user.is_verified is False
    assert задание.status == "issued"
    assert задание.decided_at is None


async def test_число_кадров_должно_совпадать_с_позами(app):
    """Меньше кадров, чем поз, — значит какая-то поза не снята."""
    session = _Session([_Result(scalar=0), _Result(scalar=_задание())])
    async with _client(app, session, _user()) as c:
        r = await c.post("/api/verification/submit", files=_кадры(1))
    assert r.status_code == 400


async def test_кадры_обязаны_быть_изображениями(app):
    session = _Session([_Result(scalar=0), _Result(scalar=_задание())])
    файлы = [("frames", (f"f{i}.txt", b"not an image", "text/plain")) for i in range(3)]
    async with _client(app, session, _user()) as c:
        r = await c.post("/api/verification/submit", files=файлы)
    assert r.status_code == 400


async def test_истёкшее_задание_даёт_410(app):
    """410, а не 404: клиент по нему молча берёт новое задание."""
    session = _Session([_Result(scalar=0), _Result(scalar=None)])
    async with _client(app, session, _user()) as c:
        r = await c.post("/api/verification/submit", files=_кадры(3))
    assert r.status_code == 410


async def test_отправка_верифицированным_даёт_409(app):
    async with _client(app, _Session([]), _user(verified=True)) as c:
        r = await c.post("/api/verification/submit", files=_кадры(3))
    assert r.status_code == 409


async def test_лимит_отказов_закрывает_отправку(app):
    session = _Session([_Result(scalar=5)])
    async with _client(app, session, _user()) as c:
        r = await c.post("/api/verification/submit", files=_кадры(3))
    assert r.status_code == 429
