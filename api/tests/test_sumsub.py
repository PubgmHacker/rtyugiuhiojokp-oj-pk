"""Провайдерская проверка (Sumsub): контракт эндпоинтов и границы безопасности.

Обещания, которые здесь закреплены:

* без ключей провайдерских эндпоинтов не существует, со включённым провайдером
  встроенная схема закрыта — сильную проверку нельзя обойти слабой;
* GREEN провайдера — ещё не галочка: без совпадения лица с фото анкеты отказ;
* вебхук без верной подписи — 401, песочница не дотягивается до боевых галочек;
* ретраи вебхука идемпотентны и не жгут суточный лимит по кругу;
* сбой Sumsub/AI не сжигает попытку и не раздаёт галочки (fail-closed).
"""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime, timezone
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


def _попытка_sumsub():
    return SimpleNamespace(
        id="att-s1",
        user_id="u-me",
        poses=[],
        status="issued",
        reason="",
        provider="sumsub",
        provider_ref="",
        decided_at=None,
        created_at=datetime.now(timezone.utc),
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

    def __init__(self, plan, users=None):
        self.plan = list(plan)
        self.added = []
        self.users = users or {}

    async def execute(self, *_a, **_kw):
        return self.plan.pop(0) if self.plan else _Result()

    async def get(self, _model, pk):
        return self.users.get(pk)

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        pass

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


@pytest.fixture
def включён(monkeypatch):
    """Провайдерский режим: ключи заданы (на общем singleton настроек)."""
    from routers import verification as v

    monkeypatch.setattr(v.settings, "SUMSUB_APP_TOKEN", "app-token")
    monkeypatch.setattr(v.settings, "SUMSUB_SECRET_KEY", "secret-key")
    monkeypatch.setattr(v.settings, "SUMSUB_LEVEL_NAME", "liveness-only")
    monkeypatch.setattr(v.settings, "SUMSUB_WEBHOOK_SECRET", "hook-secret")
    assert v.settings.sumsub_enabled


@pytest.fixture(autouse=True)
def журнал(monkeypatch):
    """Референс и журнал модерации — заглушки; сеть в тестах не участвует."""
    from routers import verification as v

    async def _референс(_url):
        return b"reference-bytes"

    monkeypatch.setattr(v, "_скачать_референс", _референс)

    записи: list[tuple] = []

    async def _лог(user_id, content_type, content, verdict):
        записи.append((user_id, content_type, content, verdict))

    monkeypatch.setattr(v, "log_moderation", _лог)
    return записи


def _сверка(monkeypatch, matches=True, unavailable=False):
    """Подменить verify_face_match фиксированным вердиктом."""
    from routers import verification as v

    async def _fake(selfie, reference):
        if unavailable:
            return {"matches_profile": False, "unavailable": True, "reason": "down"}
        return {"matches_profile": matches, "reason": "ok"}

    monkeypatch.setattr(v, "verify_face_match", _fake)


def _селфи(monkeypatch, кадр=b"selfie-bytes"):
    from services import sumsub

    async def _fake(_applicant_id):
        return кадр

    monkeypatch.setattr(sumsub, "best_selfie_frame", _fake)


def _заявитель(monkeypatch, answer="GREEN", reject_type="", comment="", отсутствует=False):
    from services import sumsub

    async def _fake(_user_id):
        if отсутствует:
            return None
        return {
            "applicant_id": "apl-1",
            "review_answer": answer,
            "reject_type": reject_type,
            "moderation_comment": comment,
        }

    monkeypatch.setattr(sumsub, "applicant_status", _fake)


# ── Подпись запросов и вебхука (чистые функции) ─────────────────


def test_подпись_запроса_считается_по_ts_методу_пути_и_телу():
    from services.sumsub import _sign

    ожидаемая = hmac.new(
        b"s3cret", b"1700000000POST/resources/accessTokens/sdk" + b'{"a":1}',
        hashlib.sha256,
    ).hexdigest()
    assert _sign("s3cret", 1700000000, "post", "/resources/accessTokens/sdk", b'{"a":1}') == ожидаемая


def test_подпись_вебхука_принимает_только_верный_hmac(monkeypatch, включён):
    from services import sumsub

    тело = b'{"type":"applicantReviewed"}'
    верная = hmac.new(b"hook-secret", тело, hashlib.sha256).hexdigest()
    assert sumsub.verify_webhook_digest(тело, верная, "HMAC_SHA256_HEX") is True
    assert sumsub.verify_webhook_digest(тело, верная, "") is True  # дефолт — sha256
    assert sumsub.verify_webhook_digest(тело, "deadbeef", "HMAC_SHA256_HEX") is False
    assert sumsub.verify_webhook_digest(тело, верная, "HMAC_MD5_HEX") is False

    sha512 = hmac.new(b"hook-secret", тело, hashlib.sha512).hexdigest()
    assert sumsub.verify_webhook_digest(тело, sha512, "HMAC_SHA512_HEX") is True

    monkeypatch.setattr(sumsub.settings, "SUMSUB_WEBHOOK_SECRET", "")
    assert sumsub.verify_webhook_digest(тело, верная, "HMAC_SHA256_HEX") is False


# ── Переключение режимов ────────────────────────────────────────


async def test_статус_отдаёт_провайдера_и_не_выдаёт_встроенное_задание(app, включён):
    session = _Session([_Result(scalar=0), _Result(scalar=None), _Result(scalar=_profile())])
    async with _client(app, session, _user()) as c:
        r = await c.get("/api/verification/status")
    тело = r.json()
    assert тело["provider"] == "sumsub"
    assert тело["provider_pending"] is False
    assert тело["challenge"] is None


async def test_статус_видит_начатую_провайдерскую_попытку(app, включён):
    session = _Session([
        _Result(scalar=0), _Result(scalar=_попытка_sumsub()), _Result(scalar=_profile()),
    ])
    async with _client(app, session, _user()) as c:
        r = await c.get("/api/verification/status")
    assert r.json()["provider_pending"] is True


async def test_без_ключей_провайдерских_эндпоинтов_нет(app):
    session = _Session([])
    async with _client(app, session, _user()) as c:
        assert (await c.post("/api/verification/sumsub/token")).status_code == 404
        assert (await c.post("/api/verification/sumsub/finalize")).status_code == 404
        assert (await c.post("/api/verification/sumsub/webhook", content=b"{}")).status_code == 404


async def test_встроенная_схема_закрыта_при_включённом_провайдере(app, включён):
    """Иначе сильная проверка обходится слабой: бей в старый эндпоинт — получай галочку."""
    session = _Session([])
    кадр = [("frames", ("f.jpg", b"jpg", "image/jpeg"))]
    async with _client(app, session, _user()) as c:
        assert (await c.post("/api/verification/challenge")).status_code == 409
        assert (await c.post("/api/verification/submit", files=кадр)).status_code == 409


# ── Токен WebSDK ────────────────────────────────────────────────


async def test_токен_выдаётся_и_заводит_попытку(app, включён, monkeypatch):
    from services import sumsub

    async def _токен(user_id):
        assert user_id == "u-me"
        return {"token": "sdk-token", "expires_in": 600}

    monkeypatch.setattr(sumsub, "create_access_token", _токен)
    session = _Session([_Result(scalar=0), _Result(scalar=_profile()), _Result(scalar=None)])
    async with _client(app, session, _user()) as c:
        r = await c.post("/api/verification/sumsub/token")
    assert r.status_code == 200
    тело = r.json()
    assert тело["token"] == "sdk-token"
    assert тело["attempts_left"] == 5
    assert len(session.added) == 1
    assert session.added[0].provider == "sumsub"
    assert session.added[0].status == "issued"


async def test_токен_не_плодит_попытки_при_повторном_запросе(app, включён, monkeypatch):
    from services import sumsub

    async def _токен(_uid):
        return {"token": "sdk-token", "expires_in": 600}

    monkeypatch.setattr(sumsub, "create_access_token", _токен)
    session = _Session([
        _Result(scalar=0), _Result(scalar=_profile()), _Result(scalar=_попытка_sumsub()),
    ])
    async with _client(app, session, _user()) as c:
        r = await c.post("/api/verification/sumsub/token")
    assert r.status_code == 200
    assert session.added == []


async def test_токен_недоступен_подтверждённому_без_фото_и_сверх_лимита(app, включён):
    async with _client(app, _Session([]), _user(verified=True)) as c:
        assert (await c.post("/api/verification/sumsub/token")).status_code == 409

    session = _Session([_Result(scalar=5)])
    async with _client(app, session, _user()) as c:
        assert (await c.post("/api/verification/sumsub/token")).status_code == 429

    session = _Session([_Result(scalar=0), _Result(scalar=_profile(photos=[]))])
    async with _client(app, session, _user()) as c:
        assert (await c.post("/api/verification/sumsub/token")).status_code == 400


async def test_недоступный_sumsub_не_сжигает_попытку_на_токене(app, включён, monkeypatch):
    from services import sumsub

    async def _падает(_uid):
        raise sumsub.SumsubUnavailable("down")

    monkeypatch.setattr(sumsub, "create_access_token", _падает)
    session = _Session([_Result(scalar=0), _Result(scalar=_profile()), _Result(scalar=None)])
    async with _client(app, session, _user()) as c:
        r = await c.post("/api/verification/sumsub/token")
    assert r.status_code == 503


# ── Финализация (опрос вердикта) ────────────────────────────────


async def test_финализация_green_и_совпавшее_лицо_ставят_галочку(app, включён, monkeypatch, журнал):
    _заявитель(monkeypatch, answer="GREEN")
    _селфи(monkeypatch)
    _сверка(monkeypatch, matches=True)
    попытка = _попытка_sumsub()
    пользователь = _user()
    session = _Session([_Result(scalar=попытка), _Result(scalar=_profile())])
    async with _client(app, session, пользователь) as c:
        r = await c.post("/api/verification/sumsub/finalize")
    assert r.status_code == 200
    assert r.json() == {"verified": True}
    assert пользователь.is_verified is True
    assert попытка.status == "approved"
    assert попытка.provider_ref == "apl-1"
    assert журнал[-1][3]["safe"] is True


async def test_финализация_green_но_чужое_лицо_это_отказ(app, включён, monkeypatch, журнал):
    """GREEN провайдера — не галочка: Sumsub не знает, чьи фото стоят в анкете."""
    _заявитель(monkeypatch, answer="GREEN")
    _селфи(monkeypatch)
    _сверка(monkeypatch, matches=False)
    попытка = _попытка_sumsub()
    пользователь = _user()
    session = _Session([
        _Result(scalar=попытка), _Result(scalar=_profile()), _Result(scalar=1),
    ])
    async with _client(app, session, пользователь) as c:
        r = await c.post("/api/verification/sumsub/finalize")
    assert r.status_code == 422
    тело = r.json()
    assert "не совпало" in тело["detail"]
    assert тело["attempts_left"] == 4
    assert пользователь.is_verified is False
    assert попытка.status == "rejected"
    assert журнал[-1][3]["blocked"] is True


async def test_финализация_red_сжигает_попытку_с_причиной_провайдера(app, включён, monkeypatch):
    _заявитель(monkeypatch, answer="RED", reject_type="RETRY", comment="Selfie is blurry")
    попытка = _попытка_sumsub()
    session = _Session([_Result(scalar=попытка), _Result(scalar=2)])
    async with _client(app, session, _user()) as c:
        r = await c.post("/api/verification/sumsub/finalize")
    assert r.status_code == 422
    тело = r.json()
    assert тело["detail"] == "Selfie is blurry"
    assert тело["attempts_left"] == 3
    assert попытка.status == "rejected"


async def test_финализация_до_вердикта_отвечает_pending(app, включён, monkeypatch):
    _заявитель(monkeypatch, отсутствует=True)
    async with _client(app, _Session([]), _user()) as c:
        assert (await c.post("/api/verification/sumsub/finalize")).json() == {"pending": True}

    _заявитель(monkeypatch, answer="")
    async with _client(app, _Session([]), _user()) as c:
        assert (await c.post("/api/verification/sumsub/finalize")).json() == {"pending": True}


async def test_сбой_сверки_не_сжигает_попытку(app, включён, monkeypatch):
    """Fail-closed: нет вердикта — нет галочки, но и попытка не потеряна."""
    _заявитель(monkeypatch, answer="GREEN")
    _селфи(monkeypatch)
    _сверка(monkeypatch, unavailable=True)
    попытка = _попытка_sumsub()
    session = _Session([_Result(scalar=попытка), _Result(scalar=_profile())])
    async with _client(app, session, _user()) as c:
        r = await c.post("/api/verification/sumsub/finalize")
    assert r.status_code == 503
    assert попытка.status == "issued"


async def test_green_без_селфи_в_заявке_не_раздаёт_галочку(app, включён, monkeypatch):
    """Уровень без шага Liveness — авария конфигурации, а не повод верить."""
    from services import sumsub

    _заявитель(monkeypatch, answer="GREEN")

    async def _пусто(_apl):
        return None

    monkeypatch.setattr(sumsub, "best_selfie_frame", _пусто)
    пользователь = _user()
    session = _Session([_Result(scalar=_попытка_sumsub()), _Result(scalar=_profile())])
    async with _client(app, session, пользователь) as c:
        r = await c.post("/api/verification/sumsub/finalize")
    assert r.status_code == 503
    assert пользователь.is_verified is False


# ── Вебхук ──────────────────────────────────────────────────────


def _вебхук_тело(**поля):
    payload = {
        "type": "applicantReviewed",
        "applicantId": "apl-1",
        "externalUserId": "u-me",
        "reviewResult": {"reviewAnswer": "GREEN"},
    }
    payload.update(поля)
    тело = json.dumps(payload).encode()
    подпись = hmac.new(b"hook-secret", тело, hashlib.sha256).hexdigest()
    return тело, {"x-payload-digest": подпись, "x-payload-digest-alg": "HMAC_SHA256_HEX"}


async def test_вебхук_без_верной_подписи_отвергается(app, включён):
    тело, _ = _вебхук_тело()
    async with _client(app, _Session([]), _user()) as c:
        r = await c.post(
            "/api/verification/sumsub/webhook",
            content=тело,
            headers={"x-payload-digest": "0" * 64},
        )
    assert r.status_code == 401


async def test_вебхук_green_ставит_галочку(app, включён, monkeypatch):
    _селфи(monkeypatch)
    _сверка(monkeypatch, matches=True)
    пользователь = _user()
    попытка = _попытка_sumsub()
    session = _Session(
        [_Result(scalar=попытка), _Result(scalar=_profile())],
        users={"u-me": пользователь},
    )
    тело, заголовки = _вебхук_тело()
    async with _client(app, session, пользователь) as c:
        r = await c.post("/api/verification/sumsub/webhook", content=тело, headers=заголовки)
    assert r.status_code == 200
    assert r.json()["outcome"] == "approved"
    assert пользователь.is_verified is True
    assert попытка.status == "approved"


async def test_ретрай_вебхука_red_не_жжёт_лимит_по_кругу(app, включён, monkeypatch):
    """Повторная доставка RED без нерешённой попытки ничего не пишет."""
    пользователь = _user()
    session = _Session([_Result(scalar=None)], users={"u-me": пользователь})
    тело, заголовки = _вебхук_тело(
        reviewResult={"reviewAnswer": "RED", "reviewRejectType": "RETRY"},
    )
    async with _client(app, session, пользователь) as c:
        r = await c.post("/api/verification/sumsub/webhook", content=тело, headers=заголовки)
    assert r.status_code == 200
    assert r.json()["outcome"] == "rejected"
    assert session.added == []


async def test_вебхук_песочницы_не_дотягивается_до_боевых_галочек(app, включён, monkeypatch):
    from routers import verification as v

    monkeypatch.setattr(v.settings, "DEBUG", False)
    пользователь = _user()
    session = _Session([], users={"u-me": пользователь})
    тело, заголовки = _вебхук_тело(sandboxMode=True)
    async with _client(app, session, пользователь) as c:
        r = await c.post("/api/verification/sumsub/webhook", content=тело, headers=заголовки)
    assert r.status_code == 200
    assert "outcome" not in r.json()
    assert пользователь.is_verified is False


async def test_вебхук_о_чужих_событиях_вежливо_игнорируется(app, включён):
    """Неизвестный тип и неизвестный пользователь — 200 без последствий."""
    session = _Session([], users={})
    тело, заголовки = _вебхук_тело(type="applicantCreated")
    async with _client(app, session, _user()) as c:
        r = await c.post("/api/verification/sumsub/webhook", content=тело, headers=заголовки)
        assert r.status_code == 200 and "outcome" not in r.json()

        тело2, заголовки2 = _вебхук_тело(externalUserId="ghost")
        r2 = await c.post("/api/verification/sumsub/webhook", content=тело2, headers=заголовки2)
        assert r2.status_code == 200 and "outcome" not in r2.json()
