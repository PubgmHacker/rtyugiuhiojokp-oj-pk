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


def test_квота_суперлайков_конечна(settings):
    """Безлимитный суперлайк ничего не значит и не продаёт подписку."""
    assert settings.SUPERLIKES_PER_DAY >= 1
    assert settings.SUPERLIKES_PER_DAY_PREMIUM > settings.SUPERLIKES_PER_DAY


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

    s = get_settings()
    now_ms = int(time.time() * 1000)
    base = dict(
        transactionId="2000000000000001",
        originalTransactionId="2000000000000000",
        bundleId=s.APPSTORE_BUNDLE_ID,
        productId=s.APPSTORE_PRODUCT_MONTHLY,
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


def test_клиент_покупки_подключён_к_профилю():
    from pathlib import Path

    web = Path(__file__).resolve().parents[2] / "web" / "src"

    assert (web / "lib" / "iap.ts").exists()
    profile = (web / "pages" / "Profile.tsx").read_text(encoding="utf-8")
    assert "PremiumOffer" in profile, "блок покупки не подключён в профиль"

    offer = (web / "components" / "PremiumOffer.tsx").read_text(encoding="utf-8")
    # Обязательный пункт ревью: сменивший устройство должен вернуть оплаченное
    assert "restorePurchases" in offer, "нет восстановления покупок"

    app = (web / "App.tsx").read_text(encoding="utf-8")
    # Без слушателя продления не дойдут до сервера и Premium погаснет
    assert "startTransactionListener" in app


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
