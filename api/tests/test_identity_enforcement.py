"""Идентичность анкеты: чужие фото не проходят, катфишинг копится в бан.

Обещания, которые здесь закрепляются:

* галочка «проверенный» описывает ВСЕ фото анкеты: добавленное фото сверяется
  с опорным, убранное опорное снимает галочку (api/routers/profiles.py);
* несовпадение лица — страйк; страйки копятся в бан, но не с первого раза:
  ложный бан живого человека дороже лишней попытки катфишера
  (api/services/enforcement.py);
* бан приходит готовым JSONResponse, а не исключением: get_session коммитит
  только чистый выход, HTTPException откатил бы сам бан;
* автоматика не банит админов и владельцев — их случай смотрит человек;
* бот сверять лица не умеет, поэтому смена состава фото через бота честно
  снимает галочку до повторной проверки в мини-аппе (bot/handlers/registration).
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

# ── Заготовки ───────────────────────────────────────────────────


def _user(uid: str = "u-me", verified: bool = True, role: str = "user"):
    return SimpleNamespace(
        id=uid,
        telegram_id=111,
        apple_id=None,
        role=role,
        is_banned=False,
        banned_until=None,
        is_verified=verified,
    )


def _profile(photos=None, verified_photo: str = "https://cdn.test/ref.jpg"):
    photos = ["https://cdn.test/ref.jpg", "https://cdn.test/b.jpg"] if photos is None else photos
    return SimpleNamespace(user_id="u-me", photos=photos, verified_photo=verified_photo)


class _Session:
    def __init__(self):
        self.added = []

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        pass

    async def execute(self, *_a, **_kw):
        raise AssertionError("юнит-тесты сверки не должны ходить в базу")


@pytest.fixture()
def сверка_без_сети(monkeypatch):
    """Скачивание фото и AI-сверка — заглушки; вердикт задаёт сам тест."""
    from routers import profiles as p

    async def _скачать(url):
        return f"bytes:{url}".encode()

    monkeypatch.setattr(p, "_скачать_фото", _скачать)

    вызовы: list[tuple] = []
    вердикты: dict = {"по_умолчанию": {"present": True, "reason": ""}}

    async def _verify(person, photo):
        вызовы.append((person, photo))
        return dict(вердикты["по_умолчанию"])

    monkeypatch.setattr(p, "verify_person_in_photo", _verify)
    return SimpleNamespace(вызовы=вызовы, вердикты=вердикты)


@pytest.fixture()
def страйки(monkeypatch):
    """register_identity_strike — журнал вызовов; бан включает сам тест."""
    from routers import profiles as p

    записи: list[tuple] = []
    ответ = {"бан": None}

    async def _strike(session, user, strike_type, content, reason):
        записи.append((user.id, strike_type, content, reason))
        return ответ["бан"]

    monkeypatch.setattr(p, "register_identity_strike", _strike)
    return SimpleNamespace(записи=записи, ответ=ответ)


# ── Сверка новых фото с опорным (PATCH /profiles/me) ────────────


async def test_не_верифицированного_сверка_не_касается(app, сверка_без_сети):
    from routers.profiles import _сверить_с_опорным

    user = _user(verified=False)
    profile = _profile()
    итог = await _сверить_с_опорным(_Session(), user, profile, ["https://cdn.test/new.jpg"])
    assert итог is None
    assert сверка_без_сети.вызовы == []
    assert profile.verified_photo  # ничего не тронуто


async def test_убранное_опорное_снимает_галочку(app, сверка_без_сети):
    """Совпадение больше нечем подтвердить — галочка и опорное обнуляются."""
    from routers.profiles import _сверить_с_опорным

    user = _user()
    profile = _profile()
    итог = await _сверить_с_опорным(
        _Session(), user, profile, ["https://cdn.test/b.jpg"]
    )
    assert итог is None
    assert user.is_verified is False
    assert profile.verified_photo == ""
    assert сверка_без_сети.вызовы == [], "сверять уже нечего"


async def test_перестановка_старых_фото_галочку_не_трогает(app, сверка_без_сети):
    """Старые фото прошли сверку при верификации — их порядок не важен."""
    from routers.profiles import _сверить_с_опорным

    user = _user()
    profile = _profile()
    итог = await _сверить_с_опорным(
        _Session(), user, profile,
        ["https://cdn.test/b.jpg", "https://cdn.test/ref.jpg"],
    )
    assert итог is None
    assert user.is_verified is True
    assert сверка_без_сети.вызовы == []


async def test_своё_новое_фото_проходит_и_галочка_остаётся(app, сверка_без_сети):
    from routers.profiles import _сверить_с_опорным

    user = _user()
    profile = _profile()
    итог = await _сверить_с_опорным(
        _Session(), user, profile,
        ["https://cdn.test/ref.jpg", "https://cdn.test/b.jpg", "https://cdn.test/new.jpg"],
    )
    assert итог is None
    assert user.is_verified is True
    # Сверялось только добавленное фото и именно с опорным
    assert сверка_без_сети.вызовы == [
        (b"bytes:https://cdn.test/ref.jpg", b"bytes:https://cdn.test/new.jpg")
    ]


async def test_чужое_фото_даёт_422_и_страйк(app, сверка_без_сети, страйки):
    """Лицо владельца не найдено: фото не входит, страйк записан."""
    from fastapi import HTTPException

    from routers.profiles import _сверить_с_опорным

    сверка_без_сети.вердикты["по_умолчанию"] = {"present": False, "reason": "another person"}
    user = _user()
    profile = _profile()
    with pytest.raises(HTTPException) as err:
        await _сверить_с_опорным(
            _Session(), user, profile,
            ["https://cdn.test/ref.jpg", "https://cdn.test/чужое.jpg"],
        )
    assert err.value.status_code == 422
    assert "только свои фото" in err.value.detail
    assert страйки.записи == [
        ("u-me", "photo_identity", "https://cdn.test/чужое.jpg", "another person")
    ]


async def test_третий_страйк_возвращает_бан_ответом(app, сверка_без_сети, страйки):
    """Бан отдаётся как JSONResponse, а не исключением: исключение откатило
    бы сам бан (get_session коммитит только чистый выход)."""
    from fastapi.responses import JSONResponse

    from routers.profiles import _сверить_с_опорным

    сверка_без_сети.вердикты["по_умолчанию"] = {"present": False, "reason": "another person"}
    страйки.ответ["бан"] = JSONResponse(status_code=403, content={"detail": "ban"})
    итог = await _сверить_с_опорным(
        _Session(), _user(), _profile(),
        ["https://cdn.test/ref.jpg", "https://cdn.test/чужое.jpg"],
    )
    assert итог is страйки.ответ["бан"]


async def test_сбой_сверки_не_пускает_фото(app, сверка_без_сети, страйки):
    """Fail-closed: без вердикта фото в подтверждённую анкету не входит,
    но и страйк не пишется — человек не виноват, что AI лёг."""
    from fastapi import HTTPException

    from routers.profiles import _сверить_с_опорным

    сверка_без_сети.вердикты["по_умолчанию"] = {"unavailable": True, "present": False}
    with pytest.raises(HTTPException) as err:
        await _сверить_с_опорным(
            _Session(), _user(), _profile(),
            ["https://cdn.test/ref.jpg", "https://cdn.test/new.jpg"],
        )
    assert err.value.status_code == 503
    assert страйки.записи == []


async def test_галочка_без_опорного_слетает_при_добавлении_фото(app, сверка_без_сети):
    """Аномалия (галочка есть, опорного нет): сверять не с чем, поэтому
    рост состава фото снимает галочку, а не проходит молча."""
    from routers.profiles import _сверить_с_опорным

    user = _user()
    profile = _profile(verified_photo="")
    итог = await _сверить_с_опорным(
        _Session(), user, profile,
        ["https://cdn.test/ref.jpg", "https://cdn.test/b.jpg", "https://cdn.test/new.jpg"],
    )
    assert итог is None
    assert user.is_verified is False
    assert сверка_без_сети.вызовы == []


async def test_галочка_без_опорного_переживает_перестановку(app, сверка_без_сети):
    from routers.profiles import _сверить_с_опорным

    user = _user()
    profile = _profile(verified_photo="")
    итог = await _сверить_с_опорным(
        _Session(), user, profile,
        ["https://cdn.test/b.jpg", "https://cdn.test/ref.jpg"],
    )
    assert итог is None
    assert user.is_verified is True


# ── Эскалация страйков в бан (services/enforcement.py) ──────────


@pytest.fixture()
def журнал_модерации(monkeypatch):
    import services.ai_moderation as m

    записи: list[tuple] = []

    async def _лог(user_id, content_type, content, verdict):
        записи.append((user_id, content_type, content, verdict))

    monkeypatch.setattr(m, "log_moderation", _лог)
    return записи


async def test_страйк_под_лимитом_не_банит(app, monkeypatch, журнал_модерации):
    import services.enforcement as e

    async def _мало(_uid):
        return e.IDENTITY_STRIKE_LIMIT - 1

    monkeypatch.setattr(e, "identity_strikes", _мало)
    user = _user()
    итог = await e.register_identity_strike(
        _Session(), user, "photo_identity", "url", "another person"
    )
    assert итог is None
    assert user.is_banned is False
    # Страйк лёг в журнал модерации как blocked — по нему и считается счёт
    assert журнал_модерации == [
        ("u-me", "photo_identity", "url", {"blocked": True, "reason": "another person"})
    ]


async def test_лимит_страйков_превращается_в_бан(app, monkeypatch, журнал_модерации):
    """Третье чужое лицо за окно — 403 с кодом бана, аккаунт заблокирован."""
    from middleware.auth import BANNED_CODE

    import services.enforcement as e

    async def _лимит(_uid):
        return e.IDENTITY_STRIKE_LIMIT

    monkeypatch.setattr(e, "identity_strikes", _лимит)

    забанены: list[str] = []
    категории: list[str] = []

    async def _бан(session, target, reason, *, category="manual", **kw):
        забанены.append(target.id)
        категории.append(category)
        target.is_banned = True
        return True

    monkeypatch.setattr(e, "ban_user_for_violation", _бан)
    user = _user()
    итог = await e.register_identity_strike(
        _Session(), user, "verification_identity", "liveness", "wrong face"
    )
    assert итог is not None and итог.status_code == 403
    тело = json.loads(итог.body)
    assert тело["code"] == BANNED_CODE
    # Срок уходит клиенту тем же ответом: экран бана показывает таймер
    assert тело["banned_until"] is None
    assert забанены == ["u-me"]
    assert категории == ["identity"], "катфишинг обязан идти по своей лестнице"


async def test_автобан_не_трогает_админов(app):
    """Ложное срабатывание AI не должно выносить команду."""
    from services.enforcement import ban_user_for_violation

    admin = _user(role="admin")
    итог = await ban_user_for_violation(_Session(), admin, "тест")
    assert итог is False
    assert admin.is_banned is False


async def test_бан_ставит_флаг_память_и_отзыв_токенов(app, monkeypatch, журнал_модерации):
    """Бан неделим: флаг, память банов (переживает удаление аккаунта),
    отзыв токенов (убивает WebSocket) и запись «бан применён» в журнал,
    по которой следующая лестница выберет ступень выше, — всё или ничего."""
    import services.enforcement as e

    память: list[dict] = []
    отозваны: list[str] = []

    async def _remember(session, telegram_id=None, apple_id=None, reason="", banned_until=None):
        память.append({
            "telegram_id": telegram_id, "reason": reason, "banned_until": banned_until,
        })

    async def _revoke(uid):
        отозваны.append(uid)

    monkeypatch.setattr(e, "remember_ban", _remember)
    monkeypatch.setattr(e, "revoke_all_for_user", _revoke)

    user = _user()
    итог = await e.ban_user_for_violation(
        _Session(), user, "чужие фото", category="identity"
    )
    assert итог is True
    assert user.is_banned is True
    assert user.banned_until is None, "лестница identity — вечный с первого раза"
    assert память and память[0]["telegram_id"] == 111
    assert память[0]["reason"] == "чужие фото"
    assert память[0]["banned_until"] is None, (
        "память банов обязана знать срок: вернувшийся после удаления аккаунта "
        "наследует остаток, а не вечность"
    )
    assert отозваны == ["u-me"]
    assert [(з[0], з[1]) for з in журнал_модерации] == [("u-me", "ban_applied")], (
        "без записи ban_applied рецидив не двигает лестницу"
    )


async def test_недоступный_журнал_не_даёт_фантомного_бана(app, monkeypatch):
    """Счёт страйков читается из журнала; журнал лёг — счёт 0, эскалации нет.
    Лучше пропустить бан, чем забанить по фантомному счёту."""
    import services.enforcement as e

    class _Ломаный:
        def __call__(self):
            raise RuntimeError("db down")

    monkeypatch.setattr("database.connection.async_session_factory", _Ломаный())
    assert await e.identity_strikes("u-me") == 0


# ── Бот: смена состава фото снимает галочку ─────────────────────
#
# Бот живёт в отдельном venv и код API импортировать не может — проверяем
# его собственным интерпретатором через subprocess, как в test_bot_infra.py.
# Слой БД подменяется фейковым модулем ДО импорта хендлера: тест смотрит,
# в каком порядке бот снимает галочку и пишет анкету и что говорит человеку.

БОТ = Path(__file__).resolve().parents[2] / "bot"


def _в_боте(скрипт: str) -> dict:
    python = БОТ / ".venv" / "bin" / "python"
    if not python.exists():
        pytest.skip("venv бота не поднят в этом окружении")
    результат = subprocess.run(
        [str(python), "-c", скрипт], cwd=БОТ, capture_output=True, text=True, timeout=120,
    )
    assert результат.returncode == 0, результат.stderr[-1500:]
    return json.loads(результат.stdout.strip().splitlines()[-1])


_СЦЕНАРИЙ = """
import sys, types, asyncio, json

вызовы = []

db = types.ModuleType("database")

async def get_or_create_user(tid, username="", name=""):
    return {"id": "u1", "is_verified": %(verified)s}

async def get_profile(uid):
    return {"photos": %(старые)s, "verified_photo": %(опорное)r}

async def update_profile(uid, **fields):
    вызовы.append(("update", fields["photos"]))
    return {}

async def clear_verification(uid):
    вызовы.append(("clear", uid))

db.get_or_create_user = get_or_create_user
db.get_profile = get_profile
db.update_profile = update_profile
db.clear_verification = clear_verification
sys.modules["database"] = db

from handlers.registration import _finish_registration

class Стейт:
    def __init__(self, данные): self.данные = данные
    async def get_data(self): return self.данные
    async def clear(self): pass

class Чат:
    id = 42

class Сообщение:
    chat = Чат()
    def __init__(self): self.ответы = []
    async def answer_photo(self, photo=None, caption="", reply_markup=None):
        self.ответы.append(caption)
    async def answer(self, text, reply_markup=None):
        self.ответы.append(text)

м = Сообщение()
asyncio.run(_finish_registration(
    м, Стейт({"reg_name": "Тест", "reg_photos": %(новые)s})
))
print(json.dumps({"вызовы": вызовы, "ответ": м.ответы[-1]}, ensure_ascii=False))
"""


def _прогон(старые, опорное, новые, verified=True) -> dict:
    return _в_боте(_СЦЕНАРИЙ % {
        "старые": json.dumps(старые),
        "опорное": опорное,
        "новые": json.dumps(новые),
        "verified": "True" if verified else "False",
    })


def test_бот_снимает_галочку_до_записи_нового_фото():
    """Порядок обязателен: сначала снять галочку, потом записать фото —
    если снятие упало, непроверенный снимок не попадёт в анкету с галочкой."""
    итог = _прогон(["a", "b"], "a", ["a", "b", "новое"])
    assert [в[0] for в in итог["вызовы"]] == ["clear", "update"]
    assert "галочка «проверено» снята" in итог["ответ"]


def test_бот_снимает_галочку_за_убранное_опорное():
    итог = _прогон(["a", "b"], "a", ["b"])
    assert [в[0] for в in итог["вызовы"]] == ["clear", "update"]


def test_бот_не_трогает_галочку_за_перестановку_старых():
    итог = _прогон(["a", "b"], "a", ["b", "a"])
    assert [в[0] for в in итог["вызовы"]] == ["update"]
    assert "галочка" not in итог["ответ"]


def test_бот_не_трогает_галочку_неверифицированного() -> None:
    итог = _прогон(["a"], "a", ["a", "новое"], verified=False)
    assert [в[0] for в in итог["вызовы"]] == ["update"]


def test_бот_снимает_галочку_без_опорного_при_новом_фото():
    """Легаси-аномалия: галочка есть, опорного нет — новое фото сверить
    нечем, галочка снимается (та же ветка, что в API)."""
    итог = _прогон(["a"], "", ["a", "новое"])
    assert [в[0] for в in итог["вызовы"]] == ["clear", "update"]
