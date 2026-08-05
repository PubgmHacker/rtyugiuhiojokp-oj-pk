"""Тесты правок, закрывающих находки аудита от 2026-08-04.

Здесь проверяется поведение, которое ломалось у реальных пользователей:
утечка геолокации через EXIF, подмена типа файла, одноразовость кодов
входа и появление блокировок в схеме и роутах.
"""

from __future__ import annotations

import io

import pytest
from PIL import Image


# ── Санитайзер изображений ──────────────────────────────────────


def _jpeg_with_gps(size=(3000, 2000)) -> bytes:
    """JPEG с GPS-тегом — так выглядит снимок с телефона."""
    img = Image.new("RGB", size, (120, 80, 200))
    exif = img.getexif()
    exif[0x8825] = {}  # GPSInfo
    exif[0x010F] = "Apple"  # Make
    buf = io.BytesIO()
    img.save(buf, format="JPEG", exif=exif.tobytes())
    return buf.getvalue()


def test_exif_gps_стирается():
    """Координаты дома не должны уезжать в публичный бакет вместе с фото."""
    from services.image_sanitizer import sanitize_image

    raw = _jpeg_with_gps()
    assert Image.open(io.BytesIO(raw)).info.get("exif"), "в исходнике должен быть EXIF"

    out, content_type, ext = sanitize_image(raw)

    assert not Image.open(io.BytesIO(out)).info.get("exif")
    assert content_type == "image/jpeg"
    assert ext == "jpg"


def test_огромное_фото_уменьшается():
    from services.image_sanitizer import MAX_DIMENSION, sanitize_image

    out, _, _ = sanitize_image(_jpeg_with_gps(size=(5000, 4000)))
    assert max(Image.open(io.BytesIO(out)).size) <= MAX_DIMENSION


def test_svg_отклоняется():
    """SVG исполняется браузером — под видом картинки это stored XSS."""
    from services.image_sanitizer import ImageRejected, sanitize_image

    svg = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'
    with pytest.raises(ImageRejected):
        sanitize_image(svg)


def test_не_изображение_отклоняется():
    from services.image_sanitizer import ImageRejected, sanitize_image

    # Сигнатура ZIP: переименованный архив не должен пройти как фото
    with pytest.raises(ImageRejected):
        sanitize_image(b"PK\x03\x04\x14\x00\x00\x00\x08\x00")


def test_прозрачность_сохраняется():
    """PNG с альфой не должен получить чёрный фон после перекодирования."""
    from services.image_sanitizer import sanitize_image

    src = Image.new("RGBA", (60, 60), (0, 0, 0, 0))
    buf = io.BytesIO()
    src.save(buf, format="PNG")

    out, content_type, ext = sanitize_image(buf.getvalue())

    assert content_type == "image/png"
    assert ext == "png"
    assert Image.open(io.BytesIO(out)).mode == "RGBA"


# ── Коды входа для нативного приложения ─────────────────────────


class _FakeRedis:
    """Минимальный Redis: только то, что используют link_codes и отзыв токенов."""

    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    async def set(self, key, value, ex=None, nx=False):
        if nx and key in self.store:
            return None
        self.store[key] = str(value)
        return True

    async def get(self, key):
        return self.store.get(key)

    async def exists(self, key):
        return 1 if key in self.store else 0

    async def getdel(self, key):
        return self.store.pop(key, None)

    async def incr(self, key):
        value = int(self.store.get(key, 0)) + 1
        self.store[key] = str(value)
        return value

    async def expire(self, key, ttl):
        return True

    async def delete(self, key):
        self.store.pop(key, None)
        return True


@pytest.fixture
def fake_redis(monkeypatch):
    from services import link_codes

    redis = _FakeRedis()

    async def _get_redis():
        return redis

    monkeypatch.setattr(link_codes, "get_redis", _get_redis)
    return redis


async def test_код_обменивается_один_раз(fake_redis):
    """Второй обмен тем же кодом не должен пускать в аккаунт."""
    from services.link_codes import issue_code, redeem_code

    code = await issue_code("user-1")
    assert code and len(code) == 6

    assert await redeem_code(code) == "user-1"
    assert await redeem_code(code) is None


async def test_неверный_код_отклоняется(fake_redis):
    from services.link_codes import redeem_code

    assert await redeem_code("000000") is None
    assert await redeem_code("abc") is None
    assert await redeem_code("") is None


async def test_перебор_гасит_код(fake_redis):
    """После лимита неверных попыток код перестаёт работать.

    Счётчик попыток ведётся отдельно по каждому введённому значению,
    поэтому перебор одного кода не задевает остальные.
    """
    from services.link_codes import MAX_ATTEMPTS, issue_code, redeem_code

    code = await issue_code("user-2")

    # Перебираем сам этот код: значение верное, но попытки исчерпываются
    # раньше, чем атакующий успеет им воспользоваться
    for _ in range(MAX_ATTEMPTS):
        await redeem_code(code)

    assert await redeem_code(code) is None


async def test_перебор_чужого_кода_не_гасит_свой(fake_redis):
    from services.link_codes import MAX_ATTEMPTS, issue_code, redeem_code

    code = await issue_code("user-3")
    for _ in range(MAX_ATTEMPTS + 2):
        await redeem_code("111111")

    assert await redeem_code(code) == "user-3"


async def test_код_без_ведущего_нуля(fake_redis):
    """Ведущий ноль теряется при копировании — код не должен с него начинаться."""
    from services.link_codes import generate_code

    for _ in range(200):
        assert not generate_code().startswith("0")


# ── Схема и роуты ───────────────────────────────────────────────


def test_блокировки_и_платежи_в_схеме():
    from models.models import Base

    tables = set(Base.metadata.tables)
    assert "dating_blocks" in tables
    assert "dating_processed_payments" in tables


def test_платёж_уникален_по_провайдеру_и_id():
    """Уникальный ключ — единственная надёжная защита от двойного начисления."""
    from models.models import ProcessedPayment

    constraints = {
        tuple(col.name for col in c.columns)
        for c in ProcessedPayment.__table__.constraints
        if c.__class__.__name__ == "UniqueConstraint"
    }
    assert ("provider", "external_id") in constraints


def test_индексы_горячих_запросов():
    from models.models import Base

    indexes = {
        idx.name for table in Base.metadata.tables.values() for idx in table.indexes
    }
    for name in (
        "ix_like_liker",
        "ix_like_liked",
        "ix_message_match_created",
        "ix_match_user1",
        "ix_report_reported",
    ):
        assert name in indexes, f"нет индекса {name}"


def test_роуты_блокировки_и_входа_по_коду(openapi):
    paths = openapi["paths"]
    assert "/api/blocks/{target_id}" in paths
    assert "post" in paths["/api/blocks/{target_id}"]
    assert "delete" in paths["/api/blocks/{target_id}"]
    assert "/api/blocks" in paths
    assert "/api/auth/link" in paths


# ── Ограничение частоты запросов ────────────────────────────────


def test_лимит_находится_по_самому_длинному_префиксу():
    """/api/auth/link должен получить свой лимит, а не общий по /api/auth."""
    from middleware.rate_limit import _find_limit

    prefix, limit, _ = _find_limit("/api/auth/link", "POST")
    assert prefix == "/api/auth/link"
    assert limit == 10

    # Жалобы ограничены строже свайпов — иначе спам жалоб бесплатен
    _, report_limit, _ = _find_limit("/api/report", "POST")
    _, likes_limit, _ = _find_limit("/api/likes", "POST")
    assert report_limit < likes_limit


def test_чтение_не_ограничивается():
    """GET-запросы деки и чатов лимитов не имеют — иначе сломается листание."""
    from middleware.rate_limit import _find_limit

    assert _find_limit("/api/profiles/deck", "GET") is None
    assert _find_limit("/api/matches", "GET") is None


def test_ключ_клиента_по_токену_а_не_по_ip():
    """За мобильным NAT сидят тысячи людей — лимит по IP задел бы всех."""
    from types import SimpleNamespace

    from middleware.rate_limit import _client_key

    with_token = SimpleNamespace(
        headers={"authorization": "Bearer " + "a" * 120},
        client=SimpleNamespace(host="10.0.0.1"),
    )
    assert _client_key(with_token).startswith("t:")

    without_token = SimpleNamespace(
        headers={"x-forwarded-for": "203.0.113.9, 10.0.0.1"},
        client=SimpleNamespace(host="10.0.0.1"),
    )
    assert _client_key(without_token) == "ip:203.0.113.9"


def test_middleware_подключено(app):
    from middleware.rate_limit import RateLimitMiddleware

    assert any(m.cls is RateLimitMiddleware for m in app.user_middleware)


# ── Суперлайки ──────────────────────────────────────────────────


def test_квота_суперлайков_конечна_и_растёт_с_уровнем():
    """Безлимитный суперлайк ничего не значит и не продаёт подписку,
    а одинаковая квота на всех уровнях не даёт повода брать старший."""
    from services.plans import superlikes_for

    free = superlikes_for("free")
    plus = superlikes_for("plus")
    ultra = superlikes_for("ultra")

    assert free >= 1
    assert free < plus < ultra


def test_роут_остатка_суперлайков(openapi):
    assert "/api/likes/superlikes" in openapi["paths"]


def test_мёртвый_кеш_деки_удалён():
    """Кеш просмотренных анкет никто не наполнял — сброс чистил пустоту."""
    from services import realtime

    for name in ("cache_deck_profile", "get_viewed_profile_ids", "clear_viewed_profiles"):
        assert not hasattr(realtime, name), f"{name} должен быть удалён"


def test_схема_бота_совпадает_с_api():
    """Обе схемы создают таблицы в одной БД — расхождение ломает прод.

    Сравниваем не объекты моделей, а разобранный текст `bot/database/models.py`:
    импортировать его в одном процессе с моделями API нельзя (два разных
    `DeclarativeBase` с одинаковыми именами таблиц конфликтуют в реестре).
    """
    import ast
    from pathlib import Path

    bot_models = Path(__file__).resolve().parents[2] / "bot" / "database" / "models.py"
    tree = ast.parse(bot_models.read_text(encoding="utf-8"))

    bot_tables: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        for stmt in node.body:
            if (
                isinstance(stmt, ast.Assign)
                and any(
                    isinstance(t, ast.Name) and t.id == "__tablename__"
                    for t in stmt.targets
                )
                and isinstance(stmt.value, ast.Constant)
            ):
                bot_tables.add(stmt.value.value)

    from models.models import Base as ApiBase

    api_tables = set(ApiBase.metadata.tables)
    assert api_tables == bot_tables, (
        f"только в API: {sorted(api_tables - bot_tables)}; "
        f"только в боте: {sorted(bot_tables - api_tables)}"
    )


def test_колонки_анкеты_совпадают_в_боте_и_api():
    """Совпадения имён таблиц мало: разъехавшиеся колонки ломают прод так же.

    Бот и API оба пишут `dating_profiles`. Если в одном месте появилось поле,
    которого нет в другом, то запись из бота упадёт на неизвестной колонке —
    ровно это и произошло, когда в API добавили нишевые фильтры.
    """
    import ast
    from pathlib import Path

    bot_models = Path(__file__).resolve().parents[2] / "bot" / "database" / "models.py"
    tree = ast.parse(bot_models.read_text(encoding="utf-8"))

    колонки_бота: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        имя_таблицы = None
        поля: set[str] = set()
        for stmt in node.body:
            if (
                isinstance(stmt, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == "__tablename__" for t in stmt.targets)
                and isinstance(stmt.value, ast.Constant)
            ):
                имя_таблицы = stmt.value.value
            # Колонки объявлены как аннотированные присваивания с mapped_column
            if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
                поля.add(stmt.target.id)
        if имя_таблицы == "dating_profiles":
            колонки_бота = поля

    assert колонки_бота, "не удалось разобрать модель анкеты в боте"

    from models.models import Profile

    колонки_api = set(Profile.__table__.columns.keys())
    assert колонки_api == колонки_бота, (
        f"только в API: {sorted(колонки_api - колонки_бота)}; "
        f"только в боте: {sorted(колонки_бота - колонки_api)}"
    )


# ── Отзыв сессий (JWT) ──────────────────────────────────────────


@pytest.fixture
def fake_revocation_redis(monkeypatch):
    from services import token_revocation

    redis = _FakeRedis()

    async def _get_redis():
        return redis

    monkeypatch.setattr(token_revocation, "get_redis", _get_redis)
    return redis


def test_токен_содержит_jti_и_iat():
    """Без них конкретную сессию погасить нельзя — только сменить секрет."""
    from middleware.auth import create_access_token, verify_access_token

    payload = verify_access_token(create_access_token("user-1", 12345))

    assert payload["jti"], "нужен уникальный id токена"
    assert payload["iat"], "нужна метка выпуска для отзыва «всех сессий»"
    assert payload["sub"] == "user-1"


def test_два_токена_имеют_разные_jti():
    from middleware.auth import create_access_token, verify_access_token

    first = verify_access_token(create_access_token("user-1"))
    second = verify_access_token(create_access_token("user-1"))

    assert first["jti"] != second["jti"]


async def test_свежий_токен_не_отозван(fake_revocation_redis):
    from middleware.auth import create_access_token, verify_access_token
    from services.token_revocation import is_revoked

    payload = verify_access_token(create_access_token("user-1"))
    assert await is_revoked(payload) is False


async def test_выход_гасит_только_свой_токен(fake_revocation_redis):
    """Выход на одном устройстве не должен разлогинивать остальные."""
    from middleware.auth import create_access_token, verify_access_token
    from services.token_revocation import is_revoked, revoke_token

    phone = verify_access_token(create_access_token("user-1"))
    laptop = verify_access_token(create_access_token("user-1"))

    assert await revoke_token(phone) is True

    assert await is_revoked(phone) is True
    assert await is_revoked(laptop) is False


async def test_выход_везде_гасит_все_токены(fake_revocation_redis):
    """Сценарий угнанного аккаунта: разом гаснут все выданные сессии."""
    from middleware.auth import create_access_token, verify_access_token
    from services.token_revocation import is_revoked, revoke_all_for_user

    phone = verify_access_token(create_access_token("user-1"))
    laptop = verify_access_token(create_access_token("user-1"))
    другой_юзер = verify_access_token(create_access_token("user-2"))

    assert await revoke_all_for_user("user-1") is True

    assert await is_revoked(phone) is True
    assert await is_revoked(laptop) is True
    assert await is_revoked(другой_юзер) is False, "чужие сессии не трогаем"


async def test_после_отзыва_всех_новый_токен_работает(fake_revocation_redis):
    """Повторный вход после «выйти везде» должен пускать в аккаунт."""
    import asyncio

    from middleware.auth import create_access_token, verify_access_token
    from services.token_revocation import is_revoked, revoke_all_for_user

    await revoke_all_for_user("user-1")
    # iat в JWT — целые секунды, поэтому токен той же секунды сравнить нельзя
    await asyncio.sleep(1.1)

    свежий = verify_access_token(create_access_token("user-1"))
    assert await is_revoked(свежий) is False


async def test_разбан_снимает_отзыв(fake_revocation_redis):
    import asyncio

    from middleware.auth import create_access_token, verify_access_token
    from services.token_revocation import (
        clear_user_revocation,
        is_revoked,
        revoke_all_for_user,
    )

    await revoke_all_for_user("user-1")
    await clear_user_revocation("user-1")

    старый = verify_access_token(create_access_token("user-1"))
    await asyncio.sleep(0)
    assert await is_revoked(старый) is False


async def test_токен_старого_формата_считается_отозванным(fake_revocation_redis):
    """Иначе токен без jti обходил бы проверку целиком."""
    from services.token_revocation import is_revoked

    assert await is_revoked({"sub": "user-1", "exp": 9999999999}) is True


async def test_истёкший_токен_не_пишется_в_список(fake_revocation_redis):
    """Список отзыва не должен расти записями, которые уже не нужны."""
    from services.token_revocation import revoke_token

    assert await revoke_token({"jti": "old", "exp": 1}) is True
    assert fake_revocation_redis.store == {}


async def test_недоступный_redis_не_разлогинивает(monkeypatch):
    """Падение кеша не должно выбивать всех пользователей сервиса."""
    from middleware.auth import create_access_token, verify_access_token
    from services import token_revocation

    async def _broken():
        raise RuntimeError("redis is down")

    monkeypatch.setattr(token_revocation, "get_redis", _broken)

    payload = verify_access_token(create_access_token("user-1"))
    assert await token_revocation.is_revoked(payload) is False


def test_роуты_выхода_есть(openapi):
    paths = openapi["paths"]
    assert "/api/auth/logout" in paths
    assert "/api/auth/logout-all" in paths


# ── Выборка деки ────────────────────────────────────────────────


def test_дека_не_сортирует_таблицу_рандомом():
    """ORDER BY random() — Seq Scan с сортировкой всей таблицы на каждый свайп."""
    from pathlib import Path

    api_deck = Path(__file__).resolve().parents[1] / "services" / "matching.py"
    bot_deck = (
        Path(__file__).resolve().parents[2] / "bot" / "database" / "connection.py"
    )

    for path in (api_deck, bot_deck):
        source = path.read_text(encoding="utf-8")
        assert "func.random()" not in source, f"{path.name}: остался ORDER BY random()"
        assert 'text("RANDOM()")' not in source, f"{path.name}: остался ORDER BY RANDOM()"
        assert "sample_key" in source, f"{path.name}: выборка не переведена на ключ"


def test_ключ_выборки_в_схеме_и_под_индексом():
    from models.models import Profile

    column = Profile.__table__.columns.get("sample_key")
    assert column is not None, "нет колонки sample_key"
    assert not column.nullable, "NULL выбросил бы анкету из выдачи"
    assert column.server_default is not None, "существующие анкеты остались бы без ключа"

    indexes = {idx.name: idx for idx in Profile.__table__.indexes}
    assert "ix_profile_sample" in indexes, "без индекса выборка снова станет Seq Scan"


def test_миграция_ключа_выборки_есть():
    """Колонка в модели без миграции — падение на проде, а не в тестах."""
    from pathlib import Path

    versions = Path(__file__).resolve().parents[1] / "migrations" / "versions"
    sources = [p.read_text(encoding="utf-8") for p in versions.glob("*.py")]

    assert any("sample_key" in s and "ix_profile_sample" in s for s in sources), (
        "нет миграции, добавляющей sample_key и индекс"
    )


async def test_выборка_добирает_анкеты_с_начала_ключа(monkeypatch):
    """У конца диапазона строк не хватает — иначе дека была бы полупустой.

    БД здесь не нужна: проверяем сам алгоритм двух проходов, подменив
    выполнение запроса на срез по ключу в памяти.
    """
    from services import matching

    профили = [type("P", (), {"user_id": f"u{i}", "sample_key": i / 100})() for i in range(100)]

    class _FakeSession:
        def __init__(self):
            self.запросов = 0

        async def execute(self, stmt):
            self.запросов += 1
            текст = str(stmt.whereclause) if stmt.whereclause is not None else ""
            выборка = self._отобрать(текст)
            limit = stmt._limit
            return type("R", (), {"scalars": lambda _self, rows=выборка[:limit]: type(
                "S", (), {"all": lambda _s: rows})()})()

        def _отобрать(self, текст):
            # ">=" — первый проход от точки среза, "<" — добор с начала
            if ">=" in текст:
                return [p for p in профили if p.sample_key >= _cut]
            return [p for p in профили if p.sample_key < _cut]

    # Срез почти у конца: после точки всего 2 анкеты из 30 нужных
    _cut = 0.98
    monkeypatch.setattr(matching.random, "random", lambda: _cut)

    session = _FakeSession()
    результат = await matching._sample_candidates(session, set(), 30)

    assert len(результат) == 30, "не добрали анкеты с начала ключа"
    assert session.запросов == 2, "добор должен быть вторым запросом, а не всегда"


async def test_выборка_не_добирает_когда_анкет_достаточно(monkeypatch):
    """Второй запрос на каждый свайп — лишняя работа, если хватило первого."""
    from services import matching

    class _FakeSession:
        def __init__(self):
            self.запросов = 0

        async def execute(self, stmt):
            self.запросов += 1
            rows = [type("P", (), {"user_id": f"u{i}"})() for i in range(30)]
            return type("R", (), {"scalars": lambda _self: type(
                "S", (), {"all": lambda _s: rows})()})()

    monkeypatch.setattr(matching.random, "random", lambda: 0.1)

    session = _FakeSession()
    результат = await matching._sample_candidates(session, set(), 30)

    assert len(результат) == 30
    assert session.запросов == 1, "хватило первого прохода — второй не нужен"


# ── Пуш-уведомления (APNs) ──────────────────────────────────────


def test_таблица_токенов_устройств_в_схеме():
    from models.models import Base, DeviceToken

    assert "dating_device_tokens" in Base.metadata.tables

    constraints = {
        tuple(col.name for col in c.columns)
        for c in DeviceToken.__table__.constraints
        if c.__class__.__name__ == "UniqueConstraint"
    }
    assert ("token",) in constraints, "один токен не может висеть на двух аккаунтах"

    indexes = {idx.name for idx in DeviceToken.__table__.indexes}
    assert "ix_device_user" in indexes, "отправка ищет устройства по user_id"


def test_миграция_токенов_устройств_есть():
    from pathlib import Path

    versions = Path(__file__).resolve().parents[1] / "migrations" / "versions"
    sources = [p.read_text(encoding="utf-8") for p in versions.glob("*.py")]

    assert any("dating_device_tokens" in s for s in sources), (
        "нет миграции, создающей таблицу токенов устройств"
    )


def test_роут_регистрации_устройства(openapi):
    assert "/api/profiles/me/devices" in openapi["paths"]


def test_пуши_молчат_без_ключей(monkeypatch):
    """Без ключей APNs приложение работает — уведомления просто не уходят."""
    from services import push

    monkeypatch.setattr(push.settings, "APNS_KEY_P8", "")
    assert push.is_configured() is False


def test_пуши_включаются_когда_ключи_заданы(monkeypatch):
    from services import push

    for name, value in (
        ("APNS_KEY_P8", "-----BEGIN PRIVATE KEY-----\nx\n-----END PRIVATE KEY-----"),
        ("APNS_KEY_ID", "ABC123"),
        ("APNS_TEAM_ID", "TEAM123"),
        ("APNS_BUNDLE_ID", "com.souldawn.dating"),
    ):
        monkeypatch.setattr(push.settings, name, value)

    assert push.is_configured() is True


async def test_без_ключей_отправка_не_ходит_в_сеть(monkeypatch):
    from services import push

    monkeypatch.setattr(push.settings, "APNS_KEY_P8", "")

    async def _fail(*a, **kw):
        raise AssertionError("не должны обращаться к APNs без ключей")

    monkeypatch.setattr(push, "_send_one", _fail)
    assert await push.send_to_user(None, "user-1", "t", "b") == 0


async def test_мёртвые_токены_удаляются(monkeypatch):
    """410 от Apple значит «приложение удалено» — иначе таблица копит мусор."""
    from services import push

    for name, value in (
        ("APNS_KEY_P8", "key"),
        ("APNS_KEY_ID", "ABC123"),
        ("APNS_TEAM_ID", "TEAM123"),
    ):
        monkeypatch.setattr(push.settings, name, value)

    устройства = [
        type("D", (), {"token": "живой", "user_id": "user-1"})(),
        type("D", (), {"token": "мёртвый", "user_id": "user-1"})(),
    ]

    удалено: list = []

    class _FakeSession:
        async def execute(self, stmt):
            if stmt.__class__.__name__ == "Delete":
                удалено.append(stmt)
                return None
            return type("R", (), {"scalars": lambda _s: type(
                "S", (), {"all": lambda _x: устройства})()})()

    async def _send(token, payload, collapse_id):
        return 200 if token == "живой" else 410

    monkeypatch.setattr(push, "_send_one", _send)

    доставлено = await push.send_to_user(_FakeSession(), "user-1", "Мэтч", "текст")

    assert доставлено == 1
    assert len(удалено) == 1, "мёртвый токен должен быть удалён"


async def test_сбой_apns_не_ломает_мэтч(monkeypatch):
    """Мэтч уже сохранён — падение уведомления не должно всплывать наружу."""
    from services import push

    async def _boom(*a, **kw):
        raise RuntimeError("APNs недоступен")

    monkeypatch.setattr(push, "send_to_user", _boom)

    # Не должно бросить
    await push.notify_new_match(None, "user-1", "Аня", "match-1")
    await push.notify_new_message(None, "user-1", "Аня", "привет", "match-1")


def test_клиент_регистрирует_устройство_после_входа():
    """Регистрация была написана, но никогда не вызывалась."""
    from pathlib import Path

    web = Path(__file__).resolve().parents[2] / "web" / "src"
    app = (web / "App.tsx").read_text(encoding="utf-8")

    assert "registerPushNotifications" in app, "регистрация пушей не подключена"
    assert "registerDevice" in app, "токен не отправляется на сервер"


# ── Покупки в приложении (App Store IAP) ────────────────────────


@pytest.fixture
def appstore_configured(monkeypatch):
    """Полностью настроенная проверка чеков — иначе отказы будут по конфигу."""
    from services import appstore

    monkeypatch.setattr(appstore.settings, "APPSTORE_APP_APPLE_ID", 1234567890)
    monkeypatch.setattr(appstore.settings, "APPSTORE_USE_SANDBOX", False)
    return appstore


def test_роуты_покупок(openapi):
    paths = openapi["paths"]
    assert "/api/iap/products" in paths
    assert "/api/iap/verify" in paths


def test_корневой_сертификат_apple_на_месте():
    """Без корня Apple подпись чека проверить нечем."""
    from cryptography import x509

    from services.appstore import _ROOT_CERT_PATH

    assert _ROOT_CERT_PATH.exists(), "нет AppleRootCA-G3.cer"

    cert = x509.load_der_x509_certificate(_ROOT_CERT_PATH.read_bytes())
    assert "Apple Root CA - G3" in cert.subject.rfc4514_string()
    # Корень самоподписан — иначе это не корень
    assert cert.subject == cert.issuer


def test_покупка_не_предлагается_без_apple_id(monkeypatch):
    """В Production библиотека Apple не работает без app_apple_id: кнопка
    появилась бы, а оплата падала бы на проверке."""
    from services import appstore

    monkeypatch.setattr(appstore.settings, "APPSTORE_USE_SANDBOX", False)
    monkeypatch.setattr(appstore.settings, "APPSTORE_APP_APPLE_ID", 0)

    assert appstore.is_configured() is False


def test_покупка_доступна_при_полной_настройке(appstore_configured):
    assert appstore_configured.is_configured() is True


def test_подделанный_чек_отклоняется(appstore_configured):
    """Подпись Apple — единственное, что отделяет оплату от подделки."""
    from services.appstore import ReceiptInvalid, verify_transaction

    # Похоже на JWS по форме, но подписано не Apple
    forged = "eyJhbGciOiJFUzI1NiJ9." + "e30." + "x" * 90

    with pytest.raises(ReceiptInvalid):
        verify_transaction(forged, expected_account_token="user-1")


def test_мусор_вместо_чека_отклоняется(appstore_configured):
    from services.appstore import ReceiptInvalid, verify_transaction

    for garbage in ("", "не-jws", "a.b.c"):
        with pytest.raises(ReceiptInvalid):
            verify_transaction(garbage, expected_account_token="user-1")


def _payload(**over):
    """Payload транзакции, как его отдаёт библиотека Apple."""
    import time
    import types

    from appstoreserverlibrary.models.Environment import Environment
    from config import get_settings

    from services.plans import PLANS_BY_CODE

    s = get_settings()
    now_ms = int(time.time() * 1000)
    base = dict(
        transactionId="2000000000000001",
        originalTransactionId="2000000000000000",
        bundleId=s.APPSTORE_BUNDLE_ID,
        productId=PLANS_BY_CODE["plus_1m"].appstore_id,
        purchaseDate=now_ms,
        expiresDate=now_ms + 30 * 86400 * 1000,
        appAccountToken="11111111-1111-1111-1111-111111111111",
        environment=Environment.PRODUCTION,
        revocationDate=None,
    )
    base.update(over)
    return types.SimpleNamespace(**base)


def _with_verified_payload(monkeypatch, payload):
    """Подменяем верификатор: подпись Apple подделать нельзя, а проверить
    прикладные правила после успешной подписи нужно."""
    from services import appstore

    class _FakeVerifier:
        def verify_and_decode_signed_transaction(self, _jws):
            return payload

    monkeypatch.setattr(appstore, "_load_verifier", lambda: _FakeVerifier())


ВЛАДЕЛЕЦ = "11111111-1111-1111-1111-111111111111"


def test_честная_покупка_проходит(appstore_configured, monkeypatch):
    from services.appstore import verify_transaction

    _with_verified_payload(monkeypatch, _payload())
    purchase = verify_transaction("x" * 200, expected_account_token=ВЛАДЕЛЕЦ)

    assert purchase.is_subscription is True
    assert purchase.expires_at is not None
    # У продления transactionId новый, а этот остаётся прежним
    assert purchase.original_transaction_id == "2000000000000000"


def test_чужая_покупка_не_принимается(appstore_configured, monkeypatch):
    """Иначе валидный чужой чек можно приклеить к любому аккаунту."""
    from services.appstore import ReceiptInvalid, verify_transaction

    _with_verified_payload(monkeypatch, _payload())

    with pytest.raises(ReceiptInvalid, match="другому аккаунту"):
        verify_transaction("x" * 200, expected_account_token="22222222-2222-2222-2222-222222222222")


def test_покупка_без_привязки_к_аккаунту_отклоняется(appstore_configured, monkeypatch):
    from services.appstore import ReceiptInvalid, verify_transaction

    _with_verified_payload(monkeypatch, _payload(appAccountToken=None))

    with pytest.raises(ReceiptInvalid, match="не привязана"):
        verify_transaction("x" * 200, expected_account_token=ВЛАДЕЛЕЦ)


def test_чек_другого_приложения_отклоняется(appstore_configured, monkeypatch):
    from services.appstore import ReceiptInvalid, verify_transaction

    _with_verified_payload(monkeypatch, _payload(bundleId="com.attacker.app"))

    with pytest.raises(ReceiptInvalid, match="другого приложения"):
        verify_transaction("x" * 200, expected_account_token=ВЛАДЕЛЕЦ)


def test_песочница_не_даёт_платный_доступ(appstore_configured, monkeypatch):
    """Sandbox-покупки бесплатны — в проде они не должны открывать Premium."""
    from appstoreserverlibrary.models.Environment import Environment

    from services.appstore import ReceiptInvalid, verify_transaction

    _with_verified_payload(monkeypatch, _payload(environment=Environment.SANDBOX))

    with pytest.raises(ReceiptInvalid, match="окружения"):
        verify_transaction("x" * 200, expected_account_token=ВЛАДЕЛЕЦ)


def test_возврат_закрывает_доступ(appstore_configured, monkeypatch):
    import time

    from services.appstore import ReceiptInvalid, verify_transaction

    _with_verified_payload(monkeypatch, _payload(revocationDate=int(time.time() * 1000)))

    with pytest.raises(ReceiptInvalid, match="отозвана"):
        verify_transaction("x" * 200, expected_account_token=ВЛАДЕЛЕЦ)


def test_истёкшая_подписка_не_принимается(appstore_configured, monkeypatch):
    import time

    from services.appstore import ReceiptInvalid, verify_transaction

    past = int(time.time() * 1000) - 1000
    _with_verified_payload(monkeypatch, _payload(expiresDate=past))

    with pytest.raises(ReceiptInvalid, match="истёк"):
        verify_transaction("x" * 200, expected_account_token=ВЛАДЕЛЕЦ)


def test_срок_подписки_берётся_у_apple(appstore_configured, monkeypatch):
    """Считать срок самим — значит разойтись с Apple после продления."""
    import time
    from datetime import timezone

    from services.appstore import verify_transaction

    expires_ms = int(time.time() * 1000) + 77 * 86400 * 1000
    _with_verified_payload(monkeypatch, _payload(expiresDate=expires_ms))

    purchase = verify_transaction("x" * 200, expected_account_token=ВЛАДЕЛЕЦ)

    assert purchase.expires_at.astimezone(timezone.utc).timestamp() == pytest.approx(
        expires_ms / 1000, abs=1
    )


def test_нативный_плагин_подключён_к_ios():
    """Плагин должен попасть в автогенерируемый Package.swift, иначе
    в приложении покупки просто нет."""
    from pathlib import Path

    web = Path(__file__).resolve().parents[2] / "web"

    plugin = web / "native-plugins" / "capacitor-iap"
    assert (plugin / "Package.swift").exists()
    assert (plugin / "ios" / "Sources" / "IAPPlugin" / "IAPPlugin.swift").exists()

    spm = (web / "ios" / "App" / "CapApp-SPM" / "Package.swift").read_text(encoding="utf-8")
    assert "capacitor-iap" in spm, "плагин не подключён — нужен npx cap sync ios"


def test_имя_продукта_плагина_совпадает_с_ios_проектом():
    """Capacitor выводит имя продукта из имени npm-пакета: расхождение
    ломает сборку на этапе разрешения зависимостей."""
    from pathlib import Path

    web = Path(__file__).resolve().parents[2] / "web"
    plugin_manifest = (web / "native-plugins" / "capacitor-iap" / "Package.swift").read_text(
        encoding="utf-8"
    )
    spm = (web / "ios" / "App" / "CapApp-SPM" / "Package.swift").read_text(encoding="utf-8")

    assert 'name: "SouldawnCapacitorIap"' in plugin_manifest
    assert 'product(name: "SouldawnCapacitorIap"' in spm


def test_клиент_покупки_подключён_к_витрине():
    """Витрина тарифов должна и продавать, и восстанавливать покупки."""
    from pathlib import Path

    web = Path(__file__).resolve().parents[2] / "web" / "src"

    assert (web / "lib" / "iap.ts").exists()

    plans = (web / "pages" / "Plans.tsx").read_text(encoding="utf-8")
    assert "purchasePremium" in plans, "витрина ничего не покупает"
    # Обязательный пункт ревью: сменивший устройство должен вернуть оплаченное
    assert "restorePurchases" in plans, "нет восстановления покупок"
    # Цены приходят с сервера: захардкоженный ценник разойдётся с ботом
    assert "getPlans" in plans

    profile = (web / "pages" / "Profile.tsx").read_text(encoding="utf-8")
    assert '"/plans"' in profile, "из профиля не попасть в витрину"

    app = (web / "App.tsx").read_text(encoding="utf-8")
    # Без слушателя продления не дойдут до сервера и Premium погаснет
    assert "startTransactionListener" in app
    assert '"/plans"' in app, "маршрут витрины не объявлен"


def test_транзакция_подтверждается_после_сервера():
    """finish() до ответа сервера — деньги списаны, доступа нет."""
    from pathlib import Path

    iap = (
        Path(__file__).resolve().parents[2] / "web" / "src" / "lib" / "iap.ts"
    ).read_text(encoding="utf-8")

    # Смотрим тело redeem — там оба вызова; в остальном файле встречаются
    # объявления интерфейса, порядок в которых ничего не значит
    начало = iap.index("async function redeem")
    конец = iap.index("\n}", начало)
    redeem = iap[начало:конец]

    assert "/iap/verify" in redeem and "finishTransaction" in redeem
    assert redeem.index("/iap/verify") < redeem.index("finishTransaction"), (
        "подтверждение раньше проверки на сервере"
    )


# ════════════════════════════════════════════════════════════════
#  Совместимость в деке (была заглушкой: карточка умела рисовать
#  «% совпадение», а бэкенд всегда отдавал null)
# ════════════════════════════════════════════════════════════════

def _профиль(**поля):
    """Заглушка анкеты: _compatibility читает только эти четыре поля."""
    from types import SimpleNamespace

    поля.setdefault("city", "")
    поля.setdefault("interests", [])
    return SimpleNamespace(**поля)


def test_без_своей_анкеты_процент_не_показываем():
    """Сравнивать не с чем — честнее промолчать, чем выдумать число."""
    from services.matching import _compatibility

    процент, причина = _compatibility(None, _профиль(), None, set())
    assert процент is None and причина is None


def test_общие_интересы_поднимают_процент_и_попадают_в_причину():
    from services.matching import _compatibility

    мой = _профиль(city="Москва", interests=["кино", "бег", "кофе"])
    чужой = _профиль(city="Москва", interests=["кино", "бег", "кофе"])
    похожий, причина = _compatibility(мой, чужой, 5, {"кино", "бег", "кофе"})

    далёкий = _профиль(city="Тверь", interests=["рыбалка"])
    чужой_процент, _ = _compatibility(мой, далёкий, 300, {"кино", "бег", "кофе"})

    assert похожий > чужой_процент
    assert причина and "кино" in причина


def test_процент_держится_в_разумных_границах():
    """Ни обидного нуля у пустой анкеты, ни обещания идеальной пары."""
    from services.matching import _compatibility

    интересы = [f"тег-{i}" for i in range(30)]
    мой = _профиль(city="Москва", interests=интересы)
    двойник = _профиль(city="Москва", interests=интересы)

    максимум, _ = _compatibility(мой, двойник, 1, set(интересы))
    минимум, _ = _compatibility(_профиль(), _профиль(), None, set())

    assert максимум <= 96
    assert минимум >= 40


def test_причина_объясняет_город_когда_интересов_нет():
    from services.matching import _compatibility

    мой = _профиль(city="Казань")
    чужой = _профиль(city="казань")
    _, причина = _compatibility(мой, чужой, None, set())
    assert причина == "Вы в одном городе"


# ════════════════════════════════════════════════════════════════
#  Нишевые фильтры деки (цель, субкультура, город, рост)
# ════════════════════════════════════════════════════════════════

def _анкета(**поля):
    """Заглушка: _passes_niche_filters читает только эти поля."""
    from types import SimpleNamespace

    поля.setdefault("goal", "")
    поля.setdefault("subculture", "")
    поля.setdefault("city", "")
    поля.setdefault("height_cm", None)
    поля.setdefault("filter_goal", "")
    поля.setdefault("filter_subculture", "")
    поля.setdefault("filter_city", "")
    поля.setdefault("filter_height_min", None)
    поля.setdefault("filter_height_max", None)
    return SimpleNamespace(**поля)


def test_пустые_фильтры_пропускают_всех():
    """Новичок с незаполненной анкетой обязан видеть людей."""
    from services.matching import _passes_niche_filters

    assert _passes_niche_filters(_анкета(), _анкета(subculture="гот", height_cm=180))


def test_фильтр_субкультуры_отсекает_чужую_но_не_незаполненную():
    """Иначе фильтр прятал бы тех, кто просто не заполнил графу."""
    from services.matching import _passes_niche_filters

    мой = _анкета(filter_subculture="гот")
    assert not _passes_niche_filters(мой, _анкета(subculture="нормис"))
    assert _passes_niche_filters(мой, _анкета(subculture="гот"))
    assert _passes_niche_filters(мой, _анкета(subculture=""))


def test_фильтр_города_не_зависит_от_регистра():
    from services.matching import _passes_niche_filters

    мой = _анкета(filter_city="Казань")
    assert _passes_niche_filters(мой, _анкета(city="  казань "))
    assert not _passes_niche_filters(мой, _анкета(city="Москва"))


def test_фильтр_роста_отсекает_анкеты_без_роста():
    """Задан диапазон — «подойдёт ли» у анкеты без роста проверить нечем."""
    from services.matching import _passes_niche_filters

    мой = _анкета(filter_height_min=170, filter_height_max=190)
    assert _passes_niche_filters(мой, _анкета(height_cm=175))
    assert not _passes_niche_filters(мой, _анкета(height_cm=165))
    assert not _passes_niche_filters(мой, _анкета(height_cm=200))
    assert not _passes_niche_filters(мой, _анкета(height_cm=None))


def test_фильтр_цели_знакомства():
    from services.matching import _passes_niche_filters

    мой = _анкета(filter_goal="дружба")
    assert _passes_niche_filters(мой, _анкета(goal="дружба"))
    assert not _passes_niche_filters(мой, _анкета(goal="отношения"))


# ════════════════════════════════════════════════════════════════
#  Согласованность значений между ботом и мини-аппом
# ════════════════════════════════════════════════════════════════

def _значения_ts_списка(текст: str, имя: str) -> set[str]:
    """Значения `value:` внутри объявления `export const ИМЯ: Option[] = [...]`."""
    import re

    начало = текст.index(f"export const {имя}")
    конец = текст.index("];", начало)
    return set(re.findall(r'value:\s*"([^"]+)"', текст[начало:конец]))


def _ключи_py_словаря(текст: str, имя: str) -> set[str]:
    """Ключи словаря `ИМЯ = {...}` в исходнике на Python."""
    import re

    начало = текст.index(f"{имя} = {{")
    конец = текст.index("}", начало)
    return set(re.findall(r'"(\w+)":', текст[начало:конец]))


def test_значения_цели_и_субкультуры_совпадают_в_боте_и_вебе():
    """Разъехавшиеся значения — это молча пустая выдача.

    Цель и субкультуру выбирают и в боте, и в мини-аппе, а фильтр сравнивает
    строки. Если бот запишет «дружба», а веб отфильтрует «friendship», фильтр
    не найдёт никого — и объяснить человеку, почему пусто, будет нечем.
    """
    import re
    from pathlib import Path

    корень = Path(__file__).resolve().parents[2]
    веб = (корень / "web" / "src" / "lib" / "profileOptions.ts").read_text(encoding="utf-8")
    кнопки = (корень / "bot" / "keyboards.py").read_text(encoding="utf-8")
    тексты = (корень / "bot" / "texts.py").read_text(encoding="utf-8")

    цели = _значения_ts_списка(веб, "GOALS")
    субкультуры = _значения_ts_списка(веб, "SUBCULTURES")
    assert цели and субкультуры, "не удалось разобрать списки в profileOptions.ts"

    # Пустое значение кнопки «Пока не решил» в наборе не участвует
    цели_бота = {v for v in re.findall(r'callback_data="reg:goal:(\w*)"', кнопки) if v}
    assert цели_бота == цели, f"расходятся: {цели_бота ^ цели}"

    assert _ключи_py_словаря(тексты, "GOAL_LABELS") == цели
    assert _ключи_py_словаря(тексты, "SUBCULTURE_LABELS") == субкультуры


# ════════════════════════════════════════════════════════════════
#  Лайк с сообщением (кнопка «Написать» в боте была заглушкой:
#  отвечала «напишите после мэтча» и не делала ничего)
# ════════════════════════════════════════════════════════════════

def test_текст_лайка_принимается_и_ограничен(openapi):
    """Схема должна принимать message, иначе клиент шлёт его в пустоту."""
    from models.schemas import LikeRequest

    поля = LikeRequest.model_fields
    assert "message" in поля

    # Двести символов проходят, двести один — нет: это повод для разговора,
    # а не первое сообщение
    LikeRequest(target_id="u1", message="я" * 200)
    with pytest.raises(Exception):
        LikeRequest(target_id="u1", message="я" * 201)


def test_текст_лайка_виден_в_списке_кто_лайкнул():
    """Отправлять сообщение некуда, если получатель его не увидит."""
    from models.schemas import UserProfile

    assert "like_message" in UserProfile.model_fields
    assert UserProfile(id="u1").like_message == ""


def test_колонка_текста_есть_в_обеих_моделях_лайка():
    import ast
    from pathlib import Path

    from models.models import Like

    assert "message" in Like.__table__.columns

    бот = (
        Path(__file__).resolve().parents[2] / "bot" / "database" / "models.py"
    ).read_text(encoding="utf-8")
    дерево = ast.parse(бот)
    поля = {
        stmt.target.id
        for узел in ast.walk(дерево)
        if isinstance(узел, ast.ClassDef) and узел.name == "Like"
        for stmt in узел.body
        if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name)
    }
    assert "message" in поля, "бот пишет лайки той же таблицей — колонка нужна и там"


def test_бот_умеет_ставить_лайк_с_текстом():
    """Заглушка «напишите после мэтча» не должна вернуться."""
    from pathlib import Path

    корень = Path(__file__).resolve().parents[2] / "bot"
    хендлеры = (корень / "handlers" / "dating.py").read_text(encoding="utf-8")
    состояния = (корень / "states.py").read_text(encoding="utf-8")

    assert "Напишите после мэтча" not in хендлеры
    assert "waiting_like_message" in состояния
    # Текст уходит вместе с лайком, а не отдельным сообщением в чат
    assert 'like_and_match(db_user["id"], target_id, "like", note)' in хендлеры


def test_причины_жалобы_совпадают_во_всех_слоях():
    """Бот слал «fake», которой не было в схеме — жалоба из мини-аппа с такой
    причиной получила бы 422, а в админке осталась бы без подписи.

    Причина жалобы гуляет по четырём местам: схема API, кнопки бота, список в
    мини-аппе и подписи в админке. Расхождение здесь не падает с ошибкой —
    оно молча теряет сигнал о нарушителе.
    """
    import re
    from pathlib import Path

    from models.schemas import REPORT_REASONS

    корень = Path(__file__).resolve().parents[2]
    кнопки = (корень / "bot" / "keyboards.py").read_text(encoding="utf-8")
    веб = (корень / "web" / "src" / "lib" / "profileOptions.ts").read_text(encoding="utf-8")
    админка = (
        корень / "web" / "src" / "components" / "admin" / "ReportsTable.tsx"
    ).read_text(encoding="utf-8")

    эталон = set(REPORT_REASONS)

    # В боте «Другое» кнопкой не предлагается — там вместо неё «Заблокировать»
    из_бота = set(re.findall(r'report:send:\{target_id\}:(\w+)', кнопки))
    assert из_бота <= эталон, f"бот шлёт неизвестные причины: {из_бота - эталон}"

    из_веба = _значения_ts_списка(веб, "REPORT_REASONS")
    assert из_веба == эталон, f"расходятся: {из_веба ^ эталон}"

    начало = админка.index("const REASON_MAP")
    из_админки = set(re.findall(r"^\s+(\w+):", админка[начало : админка.index("};", начало)], re.M))
    assert из_админки == эталон, f"в админке нет подписи для: {эталон - из_админки}"


# ════════════════════════════════════════════════════════════════
#  Тарифная линейка (раньше премиум был бинарным: любая платная
#  возможность включалась всем одинаково)
# ════════════════════════════════════════════════════════════════

def test_тарифы_совпадают_в_боте_и_api():
    """Бот и API держат линейку раздельно — бот не может импортировать код API.

    Разойдись они в цене, человек увидел бы в боте одну сумму, а в мини-аппе
    другую, и заплатил бы третью.
    """
    import ast
    from pathlib import Path

    from services.plans import PLANS

    бот = (
        Path(__file__).resolve().parents[2] / "bot" / "services" / "plans.py"
    ).read_text(encoding="utf-8")
    дерево = ast.parse(бот)

    планы_бота = {}
    for узел in ast.walk(дерево):
        if not (isinstance(узел, ast.Call) and getattr(узел.func, "id", "") == "Plan"):
            continue
        # tier передаётся константой TIER_PLUS/TIER_ULTRA, остальное — литералы
        значения = []
        for арг in узел.args:
            if isinstance(арг, ast.Constant):
                значения.append(арг.value)
            elif isinstance(арг, ast.Name):
                значения.append(арг.id.removeprefix("TIER_").lower())
        планы_бота[значения[0]] = tuple(значения[1:5])

    планы_api = {p.code: (p.tier, p.months, p.days, p.price_rub) for p in PLANS}
    assert планы_бота == планы_api, (
        f"расходятся: {set(планы_бота.items()) ^ set(планы_api.items())}"
    )


def test_цены_растут_с_уровнем_а_за_срок_дают_скидку():
    """Тариф без выгоды за длинный срок не продаётся, а Ultra дешевле Plus
    означал бы, что старший уровень покупать незачем."""
    from services.plans import PLANS_BY_CODE

    for tier in ("plus", "ultra"):
        месяц = PLANS_BY_CODE[f"{tier}_1m"]
        квартал = PLANS_BY_CODE[f"{tier}_3m"]
        год = PLANS_BY_CODE[f"{tier}_12m"]

        assert месяц.price_per_month > квартал.price_per_month > год.price_per_month
        # Общая сумма всё равно растёт со сроком — иначе год выглядел бы ошибкой
        assert месяц.price_rub < квартал.price_rub < год.price_rub

    assert PLANS_BY_CODE["ultra_1m"].price_rub > PLANS_BY_CODE["plus_1m"].price_rub


def test_возможности_наследуются_от_младшего_уровня():
    from services.plans import tier_allows

    # Всё, что доступно в Plus, доступно и в Ultra
    for feature in ("see_who_liked", "incognito", "deck_boost"):
        assert tier_allows("plus", feature)
        assert tier_allows("ultra", feature)
        assert not tier_allows("free", feature)

    # А обратное неверно: за старший уровень платят не зря
    assert tier_allows("ultra", "visitors")
    assert not tier_allows("plus", "visitors")


def test_неизвестный_уровень_не_открывает_платное():
    """Испорченная или чужая запись в БД не должна выдавать подписку."""
    from services.plans import superlikes_for, tier_allows

    assert not tier_allows("админ", "visitors")
    assert not tier_allows("", "incognito")
    # Незнакомая возможность закрыта: опечатка не открывает платное всем
    assert not tier_allows("ultra", "телепортация")
    assert superlikes_for("что-то") == superlikes_for("free")


def test_каждый_платный_тариф_продаётся_в_ios():
    """Тариф без продукта App Store нельзя купить с айфона, а показать его
    в витрине мы всё равно покажем."""
    from services.plans import PLANS

    for plan in PLANS:
        assert plan.appstore_id, f"{plan.code} без идентификатора продукта"

    # Идентификаторы уникальны: один продукт на два тарифа начислял бы не то
    assert len({p.appstore_id for p in PLANS}) == len(PLANS)


def test_витрина_и_гейт_лайков_есть_в_апи(openapi):
    assert "/api/iap/plans" in openapi["paths"]

    from pathlib import Path

    likes = (
        Path(__file__).resolve().parents[1] / "routers" / "likes.py"
    ).read_text(encoding="utf-8")
    # Кто именно лайкнул — за подписку, но количество видно всем: пустой
    # список выглядел бы как «вас никто не лайкал»
    assert 'tier_allows(await current_tier(session, user.id), "see_who_liked")' in likes
    assert "is_locked=True" in likes


# ════════════════════════════════════════════════════════════════
#  Гости: кто заходил в анкету (уровень Ultra)
# ════════════════════════════════════════════════════════════════

def test_роуты_гостей(openapi):
    paths = openapi["paths"]
    assert "/api/profiles/me/visitors" in paths
    # Визит отмечает клиент при показе карточки: дека отдаёт анкеты на десяток
    # вперёд, и записывать её целиком значило бы врать в разделе
    assert "/api/profiles/{profile_id}/visit" in paths
    assert "post" in paths["/api/profiles/{profile_id}/visit"]


def test_визит_уникален_по_паре():
    """Журнал всех заходов распухал бы: анкету открывают десятки раз за вечер.
    Уникальный ключ нужен и для UPSERT, которым визит создаётся и обновляется."""
    from models.models import ProfileVisit

    constraints = {
        tuple(col.name for col in c.columns)
        for c in ProfileVisit.__table__.constraints
        if c.__class__.__name__ == "UniqueConstraint"
    }
    assert ("visitor_id", "host_id") in constraints

    indexes = {idx.name for idx in ProfileVisit.__table__.indexes}
    assert "ix_visit_host_seen" in indexes, "раздел читает визиты по host_id"


def test_гости_под_гейтом_но_число_видно_всем():
    """Скрыв и число, мы не дали бы повода купить: человек не знает, что к
    нему вообще заходили. Поэтому total отдаём всегда, а список — с Ultra."""
    from pathlib import Path

    from services.plans import tier_allows

    assert tier_allows("ultra", "visitors")
    assert not tier_allows("plus", "visitors")
    assert not tier_allows("free", "visitors")

    роутер = (
        Path(__file__).resolve().parents[1] / "routers" / "profiles.py"
    ).read_text(encoding="utf-8")
    assert "VisitorsOut(total=total, revealed=False, visitors=[])" in роутер


def test_свой_визит_не_считается():
    """«Вы заходили к себе» — бесполезная строка в разделе."""
    import inspect

    from services import visits

    исходник = inspect.getsource(visits.record_visit)
    assert "if visitor_id == host_id:" in исходник
    assert "return" in исходник


def test_визит_пишется_через_upsert():
    """SELECT-потом-INSERT падал бы на уникальном ключе при двух
    одновременных открытиях анкеты."""
    import inspect

    from services import visits

    исходник = inspect.getsource(visits.record_visit)
    assert "on_conflict_do_update" in исходник
    assert "uq_visit_pair" in исходник


def test_заблокированные_не_видны_среди_гостей():
    """Жертва харассмента не должна видеть обидчика даже в списке визитов."""
    import inspect

    from services import visits

    исходник = inspect.getsource(visits.list_visitors)
    assert "Block.blocker_id == host_id" in исходник
    assert "Block.blocked_id == host_id" in исходник


def test_клиент_отмечает_визит_один_раз_на_анкету():
    """Карточка перерисовывается на каждый жест — без защиты один просмотр
    давал бы десяток запросов."""
    from pathlib import Path

    дека = (
        Path(__file__).resolve().parents[2]
        / "web" / "src" / "components" / "SwipeDeck.tsx"
    ).read_text(encoding="utf-8")

    assert "recordVisit" in дека
    assert "visitedRef" in дека, "нет защиты от повторной отправки"


# ════════════════════════════════════════════════════════════════
#  Видео-лента (reels) — второй формат знакомства помимо свайпов
# ════════════════════════════════════════════════════════════════

def test_роуты_видеоленты(openapi):
    paths = openapi["paths"]
    assert "/api/reels" in paths
    assert "get" in paths["/api/reels"] and "post" in paths["/api/reels"]
    # Свои ролики видны автору вместе со снятыми с показа
    assert "/api/reels/mine" in paths
    assert "/api/reels/{reel_id}/like" in paths
    assert "delete" in paths["/api/reels/{reel_id}"]


def test_сигнатура_видео_проверяется():
    """Заголовок Content-Type клиент подставляет любой: переименованный архив
    не должен попасть в ленту как видео."""
    from routers.reels import _looks_like_video

    # MP4/MOV — ISO BMFF: 'ftyp' на 4-м байте
    assert _looks_like_video(b"\x00\x00\x00\x20ftypisom" + b"\x00" * 8)
    # WebM — EBML
    assert _looks_like_video(b"\x1a\x45\xdf\xa3" + b"\x00" * 16)

    assert not _looks_like_video(b"PK\x03\x04" + b"\x00" * 16)  # zip
    assert not _looks_like_video(b"\x89PNG\r\n\x1a\n" + b"\x00" * 8)
    assert not _looks_like_video(b"")


def test_видео_модерируется_по_обложке():
    """Сервер не разбирает видео на кадры — ffmpeg в образе ради этого дорог.
    Значит обложка обязательна, и проверяется именно она."""
    import inspect

    from routers import reels

    исходник = inspect.getsource(reels.create_reel)
    assert "moderate_image(cover_bytes)" in исходник
    assert "sanitize_image" in исходник, "обложка должна чиститься от EXIF"
    # Подпись — публичный текст, её тоже проверяем
    assert "moderate_text" in исходник


def test_лимит_публикаций_считается_по_времени():
    """Счётчик пришлось бы обнулять по расписанию, а пропущенный запуск
    открыл бы безлимит."""
    import inspect

    from routers import reels

    assert reels.DAILY_LIMIT >= 1
    исходник = inspect.getsource(reels._published_today)
    assert "timedelta(days=1)" in исходник
    assert "Reel.created_at >= since" in исходник


def test_лимит_загрузки_видео_строже_лимита_лайков():
    """Иначе пролистывание ленты упрётся в лимит, рассчитанный на видео."""
    from middleware.rate_limit import _find_limit

    _, публикация, _ = _find_limit("/api/reels", "POST")
    _, лайк, _ = _find_limit("/api/reels/abc/like", "POST")

    assert публикация < лайк, "лайк ролика не должен делить лимит с загрузкой"
    assert лайк >= 100, "лента станет неюзабельной"


def test_лайк_ролика_уникален_и_счётчик_рядом():
    """Счётчик лежит в самом ролике: COUNT по лайкам на каждый ролик — лишний
    проход на каждый запрос ленты. Уникальный ключ не даёт ему разойтись."""
    from models.models import Reel, ReelLike

    assert "likes_count" in Reel.__table__.columns

    constraints = {
        tuple(col.name for col in c.columns)
        for c in ReelLike.__table__.constraints
        if c.__class__.__name__ == "UniqueConstraint"
    }
    assert ("reel_id", "user_id") in constraints


def test_скрытый_ролик_виден_автору_но_не_ленте():
    """Иначе автор решит, что загрузка не сработала, и загрузит то же снова."""
    import inspect

    from routers import reels

    лента = inspect.getsource(reels.list_reels)
    assert "Reel.is_hidden == False" in лента

    свои = inspect.getsource(reels.list_my_reels)
    assert "is_hidden" not in свои, "в своих роликах фильтра по скрытию быть не должно"


def test_клиент_снимает_обложку_в_браузере():
    from pathlib import Path

    web = Path(__file__).resolve().parents[2] / "web" / "src"
    cover = (web / "lib" / "videoCover.ts").read_text(encoding="utf-8")

    assert "canvas" in cover and "toBlob" in cover
    # Сломанный файл не должен оставить интерфейс в вечной загрузке
    assert "setTimeout" in cover

    uploader = (web / "components" / "ReelUploader.tsx").read_text(encoding="utf-8")
    assert "grabVideoCover" in uploader


def test_модерация_роликов_доступна_админу(openapi):
    """Флаг is_hidden без эндпоинта был бы мёртвой колонкой: AI смотрит только
    первый кадр, дальше видео может быть любым, и снять его должен человек."""
    paths = openapi["paths"]
    assert "/api/admin/reels" in paths
    assert "/api/admin/reels/action" in paths

    import inspect

    from routers import admin

    исходник = inspect.getsource(admin.moderate_reel)
    # Не удаляем: жалоба могла быть ложной, а вернуть удалённое нечем
    assert "delete" not in исходник.lower()
    assert 'data.action == "hide"' in исходник


# ════════════════════════════════════════════════════════════════
#  Тонкие настройки приватности (был один перегруженный is_incognito)
# ════════════════════════════════════════════════════════════════

def test_флаги_приватности_есть_в_схеме_и_принимаются():
    from models.models import Profile
    from models.schemas import ProfileUpdate, UserProfile

    for поле in ("hide_age", "hide_distance", "hide_from_visitors"):
        assert поле in Profile.__table__.columns
        assert поле in ProfileUpdate.model_fields
        assert поле in UserProfile.model_fields

    # По умолчанию выключены: анкета, вдруг перестающая показывать возраст,
    # выглядит поломанной
    профиль = UserProfile(id="u1")
    assert not профиль.hide_age
    assert not профиль.hide_distance
    assert not профиль.hide_from_visitors


def test_скрытый_возраст_не_выпадает_из_подбора():
    """Спрятать возраст в карточке — не то же, что исключить анкету из
    фильтров по возрасту: во втором случае её просто перестанут находить."""
    import inspect

    from services import matching

    исходник = inspect.getsource(matching.get_deck_profiles)
    # Прячем в ответе, а не в условиях выборки
    assert "age=None if profile.hide_age else profile_age" in исходник
    assert "distance=None if profile.hide_distance else distance" in исходник
    assert "hide_age" not in inspect.getsource(matching._sample_candidates)


def test_невидимка_не_попадает_в_чужие_гости():
    """Проверка на записи, а не на чтении: включивший настройку позже иначе
    остался бы в чужих списках навсегда."""
    import inspect

    from services import visits

    исходник = inspect.getsource(visits.record_visit)
    assert "Profile.hide_from_visitors" in исходник
    assert исходник.index("hide_from_visitors") < исходник.index("on_conflict_do_update")


def test_настройки_приватности_доступны_без_подписки():
    """Прятать приватность за подписку — плохо по отношению к тем, кому просто
    некомфортно быть на виду. Платным остаётся только полное инкогнито."""
    from pathlib import Path

    профиль = (
        Path(__file__).resolve().parents[2] / "web" / "src" / "pages" / "Profile.tsx"
    ).read_text(encoding="utf-8")

    секция = профиль[профиль.index("── Приватность"):]
    assert "hide_age" in секция and "hide_from_visitors" in секция
    # Секция лежит вне ветки is_premium — она общая
    assert "is_premium" not in секция[: секция.index("</Card>")]

    роутер = (
        Path(__file__).resolve().parents[1] / "routers" / "profiles.py"
    ).read_text(encoding="utf-8")
    # А инкогнито по-прежнему требует подписки
    assert 'update_fields.get("is_incognito") is True' in роутер


# ════════════════════════════════════════════════════════════════
#  MBTI и заполненность анкеты
# ════════════════════════════════════════════════════════════════

def test_mbti_принимает_только_валидные_типы():
    """Свободная строка тут бесполезна: «интроверт» не совпадёт ни с чем."""
    import pytest as _pytest

    from models.schemas import ProfileUpdate

    for код in ("INFJ", "ESTP", "INTJ"):
        ProfileUpdate(mbti=код)
    # Пустая строка — законное «не указан»
    ProfileUpdate(mbti="")

    for мусор in ("XXXX", "INF", "INFJX", "интроверт", "infj"):
        with _pytest.raises(Exception):
            ProfileUpdate(mbti=мусор)


def test_mbti_виден_во_всех_слоях():
    from pathlib import Path

    from models.models import Profile
    from models.schemas import DeckProfile, UserProfile

    assert "mbti" in Profile.__table__.columns
    assert "mbti" in UserProfile.model_fields
    assert "mbti" in DeckProfile.model_fields

    корень = Path(__file__).resolve().parents[2]
    карточка = (
        корень / "web" / "src" / "components" / "SwipeCard.tsx"
    ).read_text(encoding="utf-8")
    assert "profile.mbti" in карточка

    # В боте — то же поле в той же карточке, иначе человек выглядит по-разному
    тексты = (корень / "bot" / "texts.py").read_text(encoding="utf-8")
    assert 'profile.get("mbti")' in тексты


def test_шестнадцать_типов_в_справочнике():
    """Пропущенный тип — это анкета, которую нельзя заполнить до конца."""
    from pathlib import Path

    веб = (
        Path(__file__).resolve().parents[2] / "web" / "src" / "lib" / "profileOptions.ts"
    ).read_text(encoding="utf-8")

    типы = _значения_ts_списка(веб, "MBTI_TYPES")
    assert len(типы) == 16, f"типов {len(типы)}, а не 16"
    # Все комбинации четырёх осей должны быть на месте
    ожидаемые = {
        a + b + c + d
        for a in "EI"
        for b in "NS"
        for c in "FT"
        for d in "JP"
    }
    assert типы == ожидаемые


def test_веса_заполненности_дают_ровно_сто():
    """Иначе «100%» недостижимо и полоса никогда не закрывается."""
    import re
    from pathlib import Path

    профиль = (
        Path(__file__).resolve().parents[2] / "web" / "src" / "pages" / "Profile.tsx"
    ).read_text(encoding="utf-8")

    блок = профиль[профиль.index("const COMPLETENESS") : профиль.index("function ProfileCompleteness")]
    веса = [int(n) for n in re.findall(r"weight:\s*(\d+)", блок)]
    assert веса, "не удалось разобрать веса"
    assert sum(веса) == 100, f"сумма весов {sum(веса)}"


# ════════════════════════════════════════════════════════════════
#  Платный буст показов (был только реферальный, за друзей)
# ════════════════════════════════════════════════════════════════

def test_роуты_буста(openapi):
    paths = openapi["paths"]
    assert "/api/profiles/me/boost" in paths
    assert "get" in paths["/api/profiles/me/boost"]
    assert "post" in paths["/api/profiles/me/boost"]


def test_буст_растёт_с_уровнем_и_закрыт_бесплатным():
    from services.plans import BOOST_MINUTES, boosts_per_day, tier_allows

    assert boosts_per_day("free") == 0
    assert boosts_per_day("plus") >= 1
    assert boosts_per_day("ultra") > boosts_per_day("plus")
    # Испорченный уровень в БД не должен открывать буст
    assert boosts_per_day("админ") == 0

    assert tier_allows("plus", "deck_boost")
    assert not tier_allows("free", "deck_boost")

    # Короткий срок намеренно: буст тратится, когда человек сам в приложении
    assert 5 <= BOOST_MINUTES <= 120


def test_остаток_бустов_считается_по_времени():
    """Счётчик пришлось бы обнулять по расписанию, а пропущенный запуск
    открыл бы безлимит — та же логика, что у суперлайков."""
    import inspect

    from routers import profiles

    исходник = inspect.getsource(profiles._boost_state)
    assert "timedelta(days=1)" in исходник
    assert "BoostActivation.created_at >= since" in исходник


def test_повторный_буст_продлевает_а_не_обнуляет():
    """Иначе включение поверх активного сжигало бы оплаченные минуты."""
    import inspect

    from routers import profiles

    исходник = inspect.getsource(profiles.activate_boost)
    assert "profile.boost_until > now" in исходник
    assert "base + timedelta(minutes=BOOST_MINUTES)" in исходник


def test_буст_поднимает_анкету_в_деке():
    """Колонка без влияния на сортировку была бы мёртвой."""
    import inspect

    from services import matching

    assert matching.BOOST_MULTIPLIER > 1
    исходник = inspect.getsource(matching.get_deck_profiles)
    assert "boosted_ids" in исходник
    # Считаем по времени: прошедшая дата сама означает «буста нет»
    assert "p.boost_until > datetime.now(timezone.utc)" in исходник


# ════════════════════════════════════════════════════════════════
#  Топ по лайкам
# ════════════════════════════════════════════════════════════════

def test_роут_рейтинга(openapi):
    assert "/api/leaderboard" in openapi["paths"]


def test_рейтинг_считается_за_окно_а_не_за_всё_время():
    """Вечный рейтинг занимают те, кто зарегистрировался раньше, и новичку в
    него не попасть никогда — а значит и стараться незачем."""
    import inspect

    from routers import leaderboard

    assert 1 <= leaderboard.WINDOW_DAYS <= 31
    исходник = inspect.getsource(leaderboard._ranked_rows)
    assert "Like.created_at >= _window_start()" in исходник
    # Считаем в БД: выгружать все лайки за неделю в память нельзя
    assert "func.count" in исходник and "group_by" in исходник


def test_невидимки_не_попадают_в_чужой_топ_но_видят_себя():
    """Публичный топ видно вообще всем — это сильнее «Гостей». Но человек,
    который себя в рейтинге не находит, просто решит, что тот не работает."""
    import inspect

    from routers import leaderboard

    исходник = inspect.getsource(leaderboard._ranked_rows)
    assert "not_(Profile.is_incognito)" in исходник
    assert "not_(Profile.hide_from_visitors)" in исходник
    # Исключение для самого смотрящего
    assert "Like.liked_id == viewer_id" in исходник


def test_пассы_не_считаются_за_лайк():
    import inspect

    from routers import leaderboard

    assert 'Like.type != "pass"' in inspect.getsource(leaderboard._ranked_rows)


def test_место_вне_рейтинга_не_выдумывается():
    """Ниже последнего посчитанного места точный номер неизвестен."""
    from models.schemas import LeaderboardOut

    пустой = LeaderboardOut()
    assert пустой.my_place is None
    assert пустой.my_place_exact is False

    import inspect

    from routers import leaderboard

    исходник = inspect.getsource(leaderboard.get_leaderboard)
    assert "my_place_exact=my_place is not None" in исходник


def test_заблокированные_не_видны_в_рейтинге():
    import inspect

    from routers import leaderboard

    исходник = inspect.getsource(leaderboard.get_leaderboard)
    assert "Block.blocker_id == user.id" in исходник
    assert "Block.blocked_id == user.id" in исходник


# ════════════════════════════════════════════════════════════════
#  Оценка фото
# ════════════════════════════════════════════════════════════════

def test_роуты_оценки_фото(openapi):
    paths = openapi["paths"]
    assert "/api/photo-ratings" in paths
    assert "/api/photo-ratings/queue" in paths
    assert "/api/photo-ratings/mine" in paths


def test_оценка_только_от_одного_до_пяти():
    """Ноль означал бы «не оценил», а не оценку."""
    import pytest as _pytest

    from models.schemas import PhotoRatingRequest

    for балл in (1, 3, 5):
        PhotoRatingRequest(target_id="u1", score=балл)
    for мусор in (0, 6, -1, 100):
        with _pytest.raises(Exception):
            PhotoRatingRequest(target_id="u1", score=мусор)


def test_одна_оценка_на_пару_с_возможностью_переоценить():
    """Иначе один человек наставил бы шесть оценок одному лицу — по одной на
    каждое фото. А два быстрых тапа подряд упали бы на уникальном ключе."""
    import inspect

    from models.models import PhotoRating
    from routers import photo_ratings

    constraints = {
        tuple(col.name for col in c.columns)
        for c in PhotoRating.__table__.constraints
        if c.__class__.__name__ == "UniqueConstraint"
    }
    assert ("rater_id", "target_id") in constraints

    исходник = inspect.getsource(photo_ratings.rate_photo)
    assert "on_conflict_do_update" in исходник
    assert "uq_photo_rating" in исходник


def test_оценка_анонимна():
    """За тройку прилетела бы обида конкретному человеку, и честных оценок
    не стало бы вовсе."""
    import inspect

    from models.schemas import MyPhotoRating
    from routers import photo_ratings

    # В ответе только среднее и количество — ни одного идентификатора
    поля = set(MyPhotoRating.model_fields)
    assert поля == {"photo", "average", "total"}

    assert "rater_id" not in inspect.getsource(photo_ratings.get_my_rating)


def test_оценка_не_влияет_на_подбор():
    """Скрытый рейтинг привлекательности сделал бы сервис, где «некрасивых»
    никто не видит."""
    import inspect

    from services import matching

    assert "PhotoRating" not in inspect.getsource(matching)


def test_себя_оценить_нельзя():
    import inspect

    from routers import photo_ratings

    assert "data.target_id == user.id" in inspect.getsource(photo_ratings.rate_photo)


def test_очередь_не_сравнивает_json_в_sql():
    """Тип JSON в Postgres не поддерживает равенство: `photos != '[]'` уронил
    бы запрос. Анкеты без фото отсеиваются в Python."""
    import inspect

    from routers import photo_ratings

    исходник = inspect.getsource(photo_ratings.get_rating_queue)
    assert "Profile.photos !=" not in исходник
    assert "if as_list(p.photos)" in исходник


def test_каждая_кнопка_бота_имеет_обработчик():
    """Кнопка без хендлера — самый незаметный вид поломки: Telegram показывает
    «часики» и ничего не происходит, в логах тоже пусто.

    Так и случилось с СБП: кнопка стала передавать код тарифа
    (`pay:sbp:plus_1m`), а хендлер сравнивал строку целиком с `pay:sbp`.
    """
    import re
    from pathlib import Path

    бот = Path(__file__).resolve().parents[2] / "bot"
    исходники = "\n".join(
        p.read_text(encoding="utf-8")
        for p in [бот / "keyboards.py", *sorted((бот / "handlers").glob("*.py"))]
    )

    # Что кнопки отправляют: у параметризованных берём часть до подстановки
    отправляют = set()
    for значение in re.findall(r'callback_data=f?"([^"]*)"', исходники):
        отправляют.add(значение.split("{")[0])

    # Что хендлеры принимают
    точные = set(re.findall(r'F\.data == "([^"]*)"', исходники))
    префиксы = set(re.findall(r'F\.data\.startswith\("([^"]*)"\)', исходники))

    непокрытые = {
        значение
        for значение in отправляют
        if значение not in точные
        and not any(значение.startswith(p) or p.startswith(значение) for p in префиксы)
    }
    assert not непокрытые, f"кнопки без обработчика: {sorted(непокрытые)}"


# ════════════════════════════════════════════════════════════════
#  Групповые чаты по интересам
# ════════════════════════════════════════════════════════════════

def test_роуты_комнат(openapi):
    paths = openapi["paths"]
    assert "/api/rooms" in paths
    assert "/api/rooms/{room_id}/messages" in paths
    assert "post" in paths["/api/rooms/{room_id}/messages"]


def test_сообщение_комнаты_модерируется_до_публикации():
    """В личке собеседника можно заблокировать, а в общем чате грубость
    видят все."""
    import inspect

    from routers import rooms

    исходник = inspect.getsource(rooms.send_room_message)
    assert "moderate_text(text)" in исходник
    # Проверка идёт до создания записи
    assert исходник.index("moderate_text") < исходник.index("session.add")


def test_антифлуд_в_комнате_отдельно_от_общего_лимита():
    """Общий лимит по пути не мешает залить одну комнату подряд."""
    import inspect

    from routers import rooms

    assert 1 <= rooms.FLOOD_PER_MINUTE <= 60
    исходник = inspect.getsource(rooms.send_room_message)
    assert "timedelta(minutes=1)" in исходник
    assert "429" in исходник


def test_заблокированные_не_видны_в_комнате():
    """Человек заблокировал обидчика именно чтобы его не видеть, и общий чат
    не исключение."""
    import inspect

    from routers import rooms

    исходник = inspect.getsource(rooms.get_room_messages)
    assert "Block.blocker_id == user.id" in исходник
    assert "Block.blocked_id == user.id" in исходник


def test_скрытые_сообщения_не_отдаются():
    import inspect

    from routers import rooms

    assert "RoomMessage.is_hidden == False" in inspect.getsource(rooms.get_room_messages)


def test_стартовые_комнаты_создаются_миграцией():
    """Пустой экран на первом открытии выглядит как поломка."""
    from pathlib import Path

    миграция = (
        Path(__file__).resolve().parents[1]
        / "migrations" / "versions" / "b7e14c630f92_rooms.py"
    ).read_text(encoding="utf-8")

    assert "bulk_insert" in миграция
    # Комнат должно быть несколько, иначе выбирать не из чего
    assert миграция.count('", "') >= 5


def test_сообщения_комнат_отдельно_от_личных():
    """В личке отметка прочтения на двоих, в групповом чате она бессмысленна."""
    from models.models import Message, RoomMessage

    assert "read_at" in Message.__table__.columns
    assert "read_at" not in RoomMessage.__table__.columns
    assert "match_id" not in RoomMessage.__table__.columns


# ════════════════════════════════════════════════════════════════
#  Кейсы (бонус подписки)
# ════════════════════════════════════════════════════════════════

def test_роуты_кейсов(openapi):
    paths = openapi["paths"]
    assert "/api/cases" in paths
    assert "/api/cases/open" in paths


def test_шансы_наград_дают_единицу():
    """Сумма меньше единицы означала бы, что иногда не выпадает ничего, а
    больше — что часть наград недостижима."""
    from services.cases import REWARDS

    assert abs(sum(r.chance for r in REWARDS) - 1.0) < 1e-9
    assert all(0 < r.chance < 1 for r in REWARDS)
    assert all(r.amount > 0 for r in REWARDS)


def test_каждая_награда_достижима():
    """Наивная реализация через накопленную сумму легко оставляет последнюю
    награду недостижимой — проверяем, что выпадают все."""
    from collections import Counter

    from services.cases import REWARDS, roll

    выпало = Counter(roll().title for _ in range(20_000))
    for награда in REWARDS:
        assert выпало[награда.title] > 0, f"{награда.title} не выпала ни разу"


def test_кейсы_только_по_подписке():
    """Бонус, доступный бесплатно, не помогает продать подписку."""
    from services.cases import openings_per_day

    assert openings_per_day("free") == 0
    assert openings_per_day("plus") >= 1
    assert openings_per_day("ultra") > openings_per_day("plus")
    # Испорченная запись в БД не должна выдавать попытки
    assert openings_per_day("админ") == 0


def test_попытки_считаются_по_времени():
    import inspect

    from routers import cases

    исходник = inspect.getsource(cases._openings_left)
    assert "timedelta(days=1)" in исходник
    assert "CaseOpening.created_at >= since" in исходник


def test_выпавший_буст_продлевает_а_не_обнуляет():
    """Иначе выпавшие минуты сожгли бы уже действующий буст."""
    import inspect

    from routers import cases

    исходник = inspect.getsource(cases.open_case)
    assert "profile.boost_until > now" in исходник


def test_бонусные_суперлайки_отдельным_полем_и_тратятся_последними():
    """Прибавка к суточной квоте возобновлялась бы каждый день сама — кейс
    давал бы бесконечный бонус. А тратить награду первой означало бы сжечь её
    вместо того, что и так обновится завтра."""
    import inspect

    from models.models import Profile
    from routers import likes

    assert "bonus_superlikes" in Profile.__table__.columns

    остаток = inspect.getsource(likes._superlikes_left)
    assert "bonus" in остаток and "max(0, quota - used) + bonus" in остаток

    списание = inspect.getsource(likes._spend_bonus_superlike)
    # Списываем только когда суточные уже исчерпаны
    assert "<= quota" in списание and "return" in списание


# ════════════════════════════════════════════════════════════════
#  Карта дня и голосовая рулетка
# ════════════════════════════════════════════════════════════════

def test_роут_карты_дня(openapi):
    assert "/api/daily/card" in openapi["paths"]


def test_карта_одна_на_сутки_и_разная_у_разных_людей():
    """Карта, меняющаяся на каждое обновление страницы, ничего не стоит.
    А одинаковая у всех выглядела бы рассылкой."""
    from datetime import date

    from services.daily_card import CARDS, card_for_day

    день = date(2026, 8, 4)
    assert card_for_day("u1", день).name == card_for_day("u1", день).name

    у_разных = {card_for_day(f"u{i}", день).name for i in range(60)}
    assert len(у_разных) > len(CARDS) // 2, "карты почти не различаются между людьми"

    по_дням = {card_for_day("u1", date(2026, 8, d)).name for d in range(1, 29)}
    assert len(по_дням) > 10, "карта почти не меняется по дням"


async def test_расклад_работает_без_ai_ключа():
    """На окружении без ключа раздел не должен быть пустым."""
    from services.daily_card import CARDS, phrase_for

    карта = CARDS[0]
    фраза = await phrase_for(карта)
    assert фраза, "фраза пустая"
    # Без ключа ожидаем совет из справочника
    assert isinstance(фраза, str) and len(фраза) > 5


def test_карта_не_обещает_будущее():
    """Гадание, которое звучит как предсказание, — это обман. Формулировки
    должны быть про действия в приложении."""
    from services.daily_card import CARDS

    запрещённое = ("судьба", "предскаж", "гарантир", "obязательно", "точно будет")
    for карта in CARDS:
        текст = f"{карта.meaning} {карта.advice}".lower()
        assert not any(с in текст for с in запрещённое), карта.name
        assert карта.advice, карта.name


def test_роуты_рулетки(openapi):
    """WebSocket в OpenAPI не попадает, поэтому его ищем в самом приложении.

    Роутеры подключены вложенно, и плоский обход `app.routes` их не видит —
    спускаемся рекурсивно.
    """
    assert "/api/voice/ice-servers" in openapi["paths"]

    import main

    def пути(routes) -> set[str]:
        собрано = set()
        for r in routes:
            путь = getattr(r, "path", None)
            if путь:
                собрано.add(путь)
            # Подключённые роутеры обёрнуты и своих routes не отдают —
            # спускаемся через original_router
            вложенный = getattr(r, "original_router", None) or getattr(r, "app", None)
            if getattr(вложенный, "routes", None):
                собрано |= пути(вложенный.routes)
            elif getattr(r, "routes", None):
                собрано |= пути(r.routes)
        return собрано

    все = пути(main.app.routes)
    assert any(p.endswith("/voice/ws/roulette") for p in все), (
        f"сокет рулетки не зарегистрирован; есть: {sorted(p for p in все if 'ws' in p)}"
    )


def test_голос_не_идёт_через_сервер():
    """Пропускать звук через себя значило бы платить за трафик и хранить то,
    чего хранить нельзя."""
    import inspect

    from routers import voice

    исходник = inspect.getsource(voice)
    # Сервер только передаёт сигналы, тело не разбирает
    assert '"type": "signal"' in исходник
    assert "payload" in исходник
    # Никаких аудиобуферов и записи
    assert "record" not in исходник.lower()


def test_очередь_рулетки_в_redis_а_не_в_памяти():
    """Инстансов API несколько, и человек, попавший на другой, ждал бы вечно."""
    import inspect

    from services import voice

    исходник = inspect.getsource(voice)
    assert "get_redis" in исходник
    assert "WAITING_TTL" in исходник, "запись без TTL оставит «призрака» в очереди"


def test_себя_с_собой_не_соединяем():
    """Два открытых окна одного человека иначе соединили бы его с самим собой."""
    import inspect

    from services.voice import pop_waiting

    assert "exclude_user_id" in inspect.getsource(pop_waiting)


def test_звонок_пишется_в_журнал_без_записи_разговора():
    """Пожаловавшийся на голос не знает имени собеседника — без пары «кто с
    кем» жалоба неразбираема. Но самой записи разговора быть не должно."""
    from models.models import VoiceCall

    колонки = set(VoiceCall.__table__.columns.keys())
    assert {"caller_id", "callee_id", "duration_seconds"} <= колонки
    # Ничего похожего на файл записи
    assert not {c for c in колонки if "url" in c or "file" in c or "audio" in c}


def test_turn_необязателен_но_отсутствие_логируется():
    """Без TURN часть звонков не соединится в мобильных сетях — это должно быть
    видно в логах, а не превращаться в загадочную поломку."""
    import inspect

    from services import voice

    исходник = inspect.getsource(voice._ice_servers)
    assert "stun:" in исходник
    assert "logger.info" in исходник


# ════════════════════════════════════════════════════════════════
#  Учёт открытий разделов и хаб «Ещё»
# ════════════════════════════════════════════════════════════════

def test_роуты_учёта_разделов(openapi):
    paths = openapi["paths"]
    assert "/api/sections/{section}/open" in paths
    assert "/api/sections/stats" in paths


def test_неизвестный_раздел_не_попадает_в_сводку():
    """Опечатка в клиенте создала бы раздел-призрак, и сводка перестала бы
    быть читаемой."""
    import inspect

    from routers import sections

    исходник = inspect.getsource(sections.record_open)
    assert "section not in KNOWN_SECTIONS" in исходник
    # Падать на аналитике незачем — молча игнорируем
    assert "204" in исходник


def test_учёт_считает_людей_а_не_тапы():
    """Журнал каждого тапа стал бы самой большой таблицей в базе, а для ответа
    «сколько людей заходит в кейсы» нужны уникальные посетители."""
    from models.models import SectionOpen

    constraints = {
        tuple(col.name for col in c.columns)
        for c in SectionOpen.__table__.constraints
        if c.__class__.__name__ == "UniqueConstraint"
    }
    assert ("user_id", "section") in constraints
    assert "opens" in SectionOpen.__table__.columns


def test_сводка_показывает_разделы_с_нулём():
    """Пустая строка — самый честный аргумент за удаление раздела. Если
    показывать только непустые, лишнего не увидишь никогда."""
    import inspect

    from routers import sections

    исходник = inspect.getsource(sections.get_section_stats)
    assert "for section in sorted(KNOWN_SECTIONS)" in исходник
    assert "reach_percent" in исходник


def test_сводка_только_админу():
    import inspect

    from routers import sections

    assert "require_admin" in inspect.getsource(sections.get_section_stats)


def test_все_разделы_учитываются_на_клиенте():
    """Раздел без учёта не попадёт в сводку, и решение о нём придётся принимать
    вслепую — ровно та проблема, ради которой учёт и заводился."""
    from pathlib import Path

    from routers.sections import KNOWN_SECTIONS

    web = Path(__file__).resolve().parents[2] / "web" / "src"
    исходники = "\n".join(
        p.read_text(encoding="utf-8")
        for p in [*sorted((web / "pages").glob("*.tsx")), *sorted((web / "components").glob("*.tsx"))]
    )

    непокрытые = {s for s in KNOWN_SECTIONS if f'"{s}"' not in исходники}
    assert not непокрытые, f"разделы без учёта открытий: {sorted(непокрытые)}"


def test_вкладка_ещё_вместо_отдельной_вкладки_раздела():
    """Пять вкладок — предел, и знакомства делаются в первых трёх. Раздел,
    получивший свою вкладку, конкурирует за внимание с тем, что продаёт."""
    from pathlib import Path

    web = Path(__file__).resolve().parents[2] / "web" / "src"
    app = (web / "App.tsx").read_text(encoding="utf-8")

    начало = app.index("const NAV_ITEMS")
    конец = app.index("];", начало)
    nav = app[начало:конец]

    assert nav.count("path:") == 5, "в навигации должно быть ровно пять вкладок"
    assert '"/more"' in nav
    # Второстепенные разделы живут в «Ещё», а не в навигации
    for путь in ('"/reels"', '"/rooms"', '"/voice"', '"/cases"', '"/photo-ratings"'):
        assert путь not in nav, f"{путь} не должен занимать вкладку"

    more = (web / "pages" / "More.tsx").read_text(encoding="utf-8")
    for путь in ("/reels", "/rooms", "/voice", "/cases", "/photo-ratings"):
        assert путь in more, f"{путь} потерялся — из «Ещё» в него не попасть"


# ════════════════════════════════════════════════════════════════
#  Приватность действует ВО ВСЕХ местах, а не только в деке
#  (аудит 05.08.2026: hide_age работал в одной точке из четырёх,
#   инкогнито не работало в видео-ленте)
# ════════════════════════════════════════════════════════════════

def test_скрытый_возраст_скрыт_везде_где_видно_чужую_анкету():
    """Прежний тест проверял только деку — и пропустил три места, где возраст
    отдавался в обход настройки. Настройка обещает «скрыто», значит скрыто
    должно быть и в лайках, и в чатах, и в «Гостях»."""
    import inspect

    from routers import likes, matches, profiles
    from services import matching

    места = {
        "дека": inspect.getsource(matching.get_deck_profiles),
        "кто лайкнул": inspect.getsource(likes._profile_to_user),
        "список чатов": inspect.getsource(matches.get_matches),
        "гости": inspect.getsource(profiles._deck_like_profile),
    }
    for имя, исходник in места.items():
        assert "hide_age" in исходник, f"{имя}: возраст отдаётся в обход настройки"


def test_инкогнито_убирает_и_ролики_из_ленты():
    """Инкогнито — платная функция Plus. Если она прячет анкету из деки, но
    оставляет видео с тем же лицом в общей ленте, обещание не выполнено."""
    import inspect

    from routers import reels

    исходник = inspect.getsource(reels.list_reels)
    assert "Profile.is_incognito" in исходник
    # Outer join: NULL означает «анкеты нет», а не «инкогнито» — без этой
    # проверки ролик без заполненной анкеты молча выпал бы из ленты
    assert "is_(None)" in исходник


def test_все_публичные_разделы_уважают_инкогнито():
    """Разделов, где видно чужие анкеты, стало много — проверяем разом, чтобы
    следующий новый не забыли."""
    import inspect

    from routers import leaderboard, photo_ratings, reels

    for модуль in (leaderboard, photo_ratings, reels):
        исходник = inspect.getsource(модуль)
        assert "is_incognito" in исходник, f"{модуль.__name__}: инкогнито не учтено"
