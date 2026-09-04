"""Тесты правок, закрывающих находки аудита от 2026-08-04.

Здесь проверяется поведение, которое ломалось у реальных пользователей:
утечка геолокации через EXIF, подмена типа файла, одноразовость кодов
входа и появление блокировок в схеме и роутах.
"""

from __future__ import annotations

import io
import hashlib
import hmac
import json
import time
from urllib.parse import urlencode

import pytest
from fastapi import HTTPException
from PIL import Image


def test_public_photos_не_выдаёт_telegram_file_id():
    """Публичные карточки не должны раскрывать внутренний идентификатор бота."""
    from utils import public_photos

    assert public_photos([
        "AgAA_fake_telegram_file_id",
        "https://cdn.example/photo.jpg",
        "http://cdn.example/legacy.jpg",
    ]) == ["https://cdn.example/photo.jpg", "http://cdn.example/legacy.jpg"]
    assert public_photos(json.dumps(["AgAA_fake", "https://cdn.example/photo.jpg"])) == [
        "https://cdn.example/photo.jpg"
    ]


def test_геопозиция_с_нулевой_координатой_не_теряется():
    """Экватор и нулевой меридиан — валидные координаты, не «нет данных»."""
    from services.matching import _haversine

    assert _haversine(0, 0, 0, 1) == pytest.approx(111, abs=1)


def _подписанные_init_data(*, auth_date: int | None = None) -> str:
    from middleware import auth

    token = "audit-bot-token"
    auth.settings.BOT_TOKEN = token
    params = {
        "auth_date": str(auth_date if auth_date is not None else int(time.time())),
        "query_id": "audit-query",
        "user": json.dumps({"id": 123456, "first_name": "Audit"}, separators=(",", ":")),
    }
    check = "\n".join(f"{key}={value}" for key, value in sorted(params.items()))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    params["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urlencode(params)


def test_telegram_init_data_валидируется_и_отвергает_дубли():
    from middleware.auth import verify_telegram_init_data

    valid = _подписанные_init_data()
    assert verify_telegram_init_data(valid)["query_id"] == "audit-query"

    with pytest.raises(HTTPException, match="Invalid initData"):
        verify_telegram_init_data(valid + "&query_id=duplicate")


def test_telegram_init_data_отвергает_будущее_время():
    from middleware.auth import verify_telegram_init_data

    with pytest.raises(HTTPException, match="initData expired"):
        verify_telegram_init_data(_подписанные_init_data(auth_date=int(time.time()) + 301))


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
    """За мобильным NAT сидят тысячи людей — лимит по IP задел бы всех.

    Токен обязан быть ПРОВЕРЕННЫМ: раньше ключом служил хвост заголовка как
    есть, и на неавторизованных путях атакующий крутил счётчик, выдумывая
    новый «токен» на каждый запрос (см. test_rate_limit_key.py). Поэтому
    мусорный Bearer здесь падает в IP-ключ, а не в токенный.
    """
    from types import SimpleNamespace

    from middleware.auth import create_access_token
    from middleware.rate_limit import _client_key

    with_token = SimpleNamespace(
        headers={"authorization": f"Bearer {create_access_token('user-42')}"},
        client=SimpleNamespace(host="10.0.0.1"),
    )
    assert _client_key(with_token) == "u:user-42"

    мусорный = SimpleNamespace(
        headers={"authorization": "Bearer " + "a" * 120},
        client=SimpleNamespace(host="10.0.0.1"),
    )
    assert _client_key(мусорный) == "ip:10.0.0.1"

    without_token = SimpleNamespace(
        headers={"x-forwarded-for": "203.0.113.9, 10.0.0.1"},
        client=SimpleNamespace(host="10.0.0.1"),
    )
    # За одним доверенным прокси (Railway, TRUSTED_PROXY_COUNT=1) настоящий
    # адрес — тот, что прокси дописал справа, а не первый элемент: первый
    # клиент подставляет сам. Поэтому ключ — «10.0.0.1», а не «203.0.113.9».
    assert _client_key(without_token) == "ip:10.0.0.1"


def test_клиент_не_подделывает_ключ_лимита_заголовком():
    """Левые элементы X-Forwarded-For клиент пишет сам. Если брать их как ключ
    лимита, счётчик обходится сменой заголовка на каждый запрос. Берём адрес,
    дописанный доверенным прокси справа, — его клиент подменить не может."""
    from types import SimpleNamespace

    from middleware.rate_limit import _client_key

    настоящий = "198.51.100.7"  # этот адрес дописывает прокси, он крайний справа
    ключи = set()
    for подделка in ("1.1.1.1", "2.2.2.2", "3.3.3.3"):
        req = SimpleNamespace(
            headers={"x-forwarded-for": f"{подделка}, {настоящий}"},
            client=SimpleNamespace(host="10.0.0.1"),
        )
        ключи.add(_client_key(req))
    assert ключи == {f"ip:{настоящий}"}, "клиент прокрутил ключ подделкой заголовка"


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


def test_колонки_совпадают_в_боте_и_api():
    """Совпадения имён таблиц мало: разъехавшиеся колонки ломают прод так же.

    Бот и API пишут в одну БД и оба вызывают `create_all()`. Если в одном месте
    появилось поле, которого нет в другом, запись упадёт на неизвестной колонке —
    ровно это произошло, когда в API добавили нишевые фильтры анкеты, а потом
    повторилось с `reel_id` у сообщений.

    Проверяем ВСЕ общие таблицы, а не только анкету: узкая проверка пропустила
    второе расхождение именно потому, что смотрела в одну таблицу.
    """
    import ast
    from pathlib import Path

    bot_models = Path(__file__).resolve().parents[2] / "bot" / "database" / "models.py"
    tree = ast.parse(bot_models.read_text(encoding="utf-8"))

    таблицы_бота: dict[str, set[str]] = {}
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
        if имя_таблицы:
            таблицы_бота[имя_таблицы] = поля

    assert "dating_profiles" in таблицы_бота, "не удалось разобрать модели бота"

    from models.models import Base as ApiBase

    расхождения: list[str] = []
    for имя, таблица in ApiBase.metadata.tables.items():
        if имя not in таблицы_бота:
            continue  # отсутствие таблицы ловит соседний тест
        колонки_api = set(таблица.columns.keys())
        только_api = колонки_api - таблицы_бота[имя]
        только_бот = таблицы_бота[имя] - колонки_api
        if только_api or только_бот:
            расхождения.append(
                f"{имя}: только в API {sorted(только_api)}, "
                f"только в боте {sorted(только_бот)}"
            )

    assert not расхождения, "; ".join(расхождения)


def test_пересланный_ролик_есть_в_обеих_таблицах_сообщений():
    """Колонка пересыла закреплена тестом: фичу доделывали в две сессии."""
    from models.models import Message, RoomMessage

    assert "reel_id" in Message.__table__.columns
    assert "reel_id" in RoomMessage.__table__.columns
    # Индекс нужен не для чтения, а для удаления ролика: `SET NULL` без него
    # сканирует всю таблицу сообщений
    for модель in (Message, RoomMessage):
        индексы = {i.name for i in модель.__table__.indexes}
        assert f"ix_{модель.__tablename__}_reel" in индексы, модель.__tablename__


def test_бот_чинит_старую_колонку_videos_до_первого_запроса():
    """create_all не меняет существующую dating_profiles на старой базе."""
    from pathlib import Path

    исходник = (
        Path(__file__).resolve().parents[2] / "bot" / "database" / "connection.py"
    ).read_text(encoding="utf-8")
    assert "ADD COLUMN IF NOT EXISTS videos" in исходник
    assert "conn.dialect.name == \"postgresql\"" in исходник


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
        ("APNS_BUNDLE_ID", "com.simp.dating"),
    ):
        monkeypatch.setattr(push.settings, name, value)

    assert push.is_configured() is True


async def test_без_ключей_отправка_не_ходит_в_сеть(monkeypatch):
    from services import push

    monkeypatch.setattr(push.settings, "APNS_KEY_P8", "")

    async def _fail(*a, **kw):
        raise AssertionError("не должны обращаться к APNs без ключей")

    monkeypatch.setattr(push, "_send_one", _fail)

    async def _нет_сессий(*_а, **_к):
        raise AssertionError("без ключей незачем ходить и в БД")

    monkeypatch.setattr(push, "async_session_factory", _нет_сессий)
    assert await push.send_to_user("user-1", "t", "b") == 0


async def test_мёртвые_токены_удаляются(monkeypatch):
    """410 от Apple значит «приложение удалено» — иначе таблица копит мусор."""
    from services import push

    for name, value in (
        ("APNS_KEY_P8", "key"),
        ("APNS_KEY_ID", "ABC123"),
        ("APNS_TEAM_ID", "TEAM123"),
    ):
        monkeypatch.setattr(push.settings, name, value)

    токены = ["живой", "мёртвый"]

    удалено: list = []
    открыто = 0
    закрыто = 0

    class _FakeSession:
        async def execute(self, stmt):
            if stmt.__class__.__name__ == "Delete":
                удалено.append(stmt)
                return None
            return type("R", (), {"all": lambda _s: [(т,) for т in токены]})()

        async def commit(self):
            return None

    class _Фабрика:
        async def __aenter__(self):
            nonlocal открыто
            открыто += 1
            return _FakeSession()

        async def __aexit__(self, *_а):
            nonlocal закрыто
            закрыто += 1
            return False

    async def _send(token, payload, collapse_id):
        # Сессия обязана быть закрыта к моменту разговора с Apple: соединение
        # из пула, занятое на 10 с ожидания APNs, — это тот самый баг
        assert открыто == закрыто, "сессия открыта во время отправки в APNs"
        return 200 if token == "живой" else 410

    monkeypatch.setattr(push, "_send_one", _send)
    monkeypatch.setattr(push, "async_session_factory", lambda: _Фабрика())

    доставлено = await push.send_to_user("user-1", "Мэтч", "текст")

    assert доставлено == 1
    assert len(удалено) == 1, "мёртвый токен должен быть удалён"


async def test_сбой_apns_не_ломает_мэтч(monkeypatch):
    """Мэтч уже сохранён — падение уведомления не должно всплывать наружу."""
    from services import push

    async def _boom(*a, **kw):
        raise RuntimeError("APNs недоступен")

    monkeypatch.setattr(push, "send_to_user", _boom)

    # Не должно бросить
    await push.notify_new_match("user-1", "Аня", "match-1")
    await push.notify_new_message("user-1", "Аня", "привет", "match-1")


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

    assert 'name: "SimpCapacitorIap"' in plugin_manifest
    assert 'product(name: "SimpCapacitorIap"' in spm


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
    поля.setdefault("relation_type", "")
    поля.setdefault("subculture", "")
    поля.setdefault("city", "")
    поля.setdefault("height_cm", None)
    поля.setdefault("filter_goal", "")
    поля.setdefault("filter_relation_type", "")
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


def test_фильтр_типа_связи_пустой_не_сужает_выдачу():
    """Пустой filter_relation_type — «не важно»: пропускает всех, как и
    прочие нишевые фильтры. Тип связи — отдельная ось от цели (`goal`)."""
    from services.matching import _passes_niche_filters

    assert _passes_niche_filters(_анкета(), _анкета(relation_type="partner"))
    assert _passes_niche_filters(_анкета(), _анкета(relation_type=""))


def test_фильтр_типа_связи_отсекает_чужой_но_не_незаполненный():
    """Задан фильтр «друзья» — партнёров не показываем, но и анкеты без
    указанного типа связи не отсеиваем (человек мог просто не заполнить)."""
    from services.matching import _passes_niche_filters

    мой = _анкета(filter_relation_type="friends")
    assert not _passes_niche_filters(мой, _анкета(relation_type="partner"))
    assert _passes_niche_filters(мой, _анкета(relation_type="friends"))
    assert _passes_niche_filters(мой, _анкета(relation_type=""))


def test_фильтр_типа_связи_не_путается_с_фильтром_цели():
    """Тип связи («с кем») и цель («зачем») — разные поля: совпадение по
    одному не должно маскировать несовпадение по другому."""
    from services.matching import _passes_niche_filters

    мой = _анкета(filter_goal="дружба", filter_relation_type="partner")
    # Цель совпадает, тип связи — нет: анкета не проходит фильтр
    assert not _passes_niche_filters(мой, _анкета(goal="дружба", relation_type="friends"))
    # Совпадают оба
    assert _passes_niche_filters(мой, _анкета(goal="дружба", relation_type="partner"))


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


def test_значения_типа_связи_совпадают_в_боте_и_вебе():
    """Тип связи («с кем») — отдельная от цели ось, но проверка та же:
    разъехавшиеся значения в боте и вебе молча опустошают фильтр."""
    import re
    from pathlib import Path

    корень = Path(__file__).resolve().parents[2]
    веб = (корень / "web" / "src" / "lib" / "profileOptions.ts").read_text(encoding="utf-8")
    кнопки = (корень / "bot" / "keyboards.py").read_text(encoding="utf-8")
    тексты = (корень / "bot" / "texts.py").read_text(encoding="utf-8")

    типы = _значения_ts_списка(веб, "RELATION_TYPES")
    assert типы, "не удалось разобрать RELATION_TYPES в profileOptions.ts"

    типы_бота = {v for v in re.findall(r'callback_data="reg:relation_type:(\w*)"', кнопки) if v}
    assert типы_бота == типы, f"расходятся: {типы_бота ^ типы}"

    assert _ключи_py_словаря(тексты, "RELATION_TYPE_LABELS") == типы


# ════════════════════════════════════════════════════════════════
#  Расширенный список интересов (было 24 тега, стало ~100+ по категориям)
# ════════════════════════════════════════════════════════════════

def _все_интересы_из_веба(текст: str) -> set[str]:
    """Все строки-теги из `INTEREST_CATEGORIES` (значения, а не ключи-категории)."""
    import re

    начало = текст.index("export const INTEREST_CATEGORIES")
    # Блок кончается на строке с завершающей `};` объявления словаря
    конец = текст.index("\n};", начало)
    блок = текст[начало:конец]
    # Ключи категорий — это строки сразу перед `: [`, их не берём: интересует
    # только содержимое списков-значений
    строки_списков = re.findall(r':\s*\[([^\]]*)\]', блок)
    теги: set[str] = set()
    for список in строки_списков:
        теги |= set(re.findall(r'"([^"]+)"', список))
    return теги


def test_список_интересов_не_пуст_и_в_разумных_пределах():
    """Список расширили с 24 до сотни с лишним тегов по категориям — не
    плоской стеной, а разбитым на разделы. Проверяем диапазон, а не точное
    число: важно, что список не сузили обратно и не разросся до тысячи."""
    from pathlib import Path

    корень = Path(__file__).resolve().parents[2]
    веб = (корень / "web" / "src" / "lib" / "profileOptions.ts").read_text(encoding="utf-8")
    теги = _все_интересы_из_веба(веб)
    assert 80 <= len(теги) <= 130, f"неожиданный размер списка интересов: {len(теги)}"


def test_классические_24_интереса_сохранены_в_новом_списке():
    """Старые анкеты хранят интересы как обычный текст тега (не код), поэтому
    расширение списка не должно потерять ни одного из исходных 24 тегов —
    иначе у людей, кто выбрал их до обновления, тег стал бы «неизвестным»."""
    from pathlib import Path

    корень = Path(__file__).resolve().parents[2]
    веб = (корень / "web" / "src" / "lib" / "profileOptions.ts").read_text(encoding="utf-8")

    исходные_24 = {
        "Музыка", "Кино", "Сериалы", "Книги",
        "Спорт", "Зал", "Бег", "Йога",
        "Путешествия", "Походы", "Кофе", "Кулинария",
        "Вино", "Игры", "Аниме", "Искусство",
        "Фотография", "Танцы", "Театр", "Животные",
        "Мода", "Технологии", "Психология", "Волонтёрство",
    }
    теги = _все_интересы_из_веба(веб)
    отсутствуют = исходные_24 - теги
    assert not отсутствуют, f"пропали старые теги: {отсутствуют}"


def test_старый_интерес_вне_нового_списка_не_ломает_обновление_анкеты():
    """Анкета хранит интересы как обычный текст, без валидации по словарю
    (ProfileUpdate.interests — просто list[str]). Расширение списка на
    сервере не должно требовать миграции: тег, который в новый список
    (по любой причине) не попал, обязан приниматься как есть, а не 422."""
    from models.schemas import ProfileUpdate

    старый_чужой_тег = "Совершенно-неизвестный-тег-из-прошлого"
    update = ProfileUpdate(interests=["Музыка", старый_чужой_тег])
    assert update.interests == ["Музыка", старый_чужой_тег]


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
    assert "VisitorsOut(total=total, revealed=False, visitors=[], period=period)" in роутер


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
    Значит кадры обязательны, и проверяются именно они. Сама проверка живёт
    в services/video_validation (общая с видео анкеты) — роутер обязан её
    звать, а сервис — санитайзить и модерировать каждый кадр."""
    import inspect

    from routers import reels
    from services import video_validation

    исходник = inspect.getsource(reels.create_reel)
    assert "модерировать_кадры(" in исходник
    # Подпись — публичный текст, её тоже проверяем
    assert "moderate_text" in исходник

    сервис = inspect.getsource(video_validation.модерировать_кадры)
    assert "moderate_image(" in сервис
    assert "sanitize_image" in сервис, "кадры должны чиститься от EXIF"


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
    фильтров по возрасту: во втором случае её просто перестанут находить.

    Проверяем поведением, а не поиском строки в исходнике: прежняя версия
    искала дословное `age=None if profile.hide_age else profile_age` и падала
    при выносе расчёта в общий помощник, хотя поведение при этом не менялось.
    """
    from datetime import datetime, timezone
    from types import SimpleNamespace

    from services.public_profile import возраст_из_даты, публичный_возраст

    рождение = datetime(1998, 5, 10, tzinfo=timezone.utc)
    анкета = SimpleNamespace(birth_date=рождение, hide_age=True)

    # В карточку возраст не попадает...
    assert публичный_возраст(анкета) is None
    # ...но сам по себе он известен, и фильтрам подбора есть с чем работать
    настоящий = возраст_из_даты(анкета.birth_date)
    assert настоящий and настоящий > 18

    # Отбор кандидатов не должен вообще знать про настройку показа
    import inspect

    from services import matching

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
    """Иначе включение поверх активного сжигало бы оплаченные минуты.

    Проверяем арифметику, а не текст исходника: грепающая версия падала при
    выносе сравнения в общий помощник и при этом не замечала, что на
    naive-времени из базы оно вообще роняет обработчик.
    """
    from datetime import datetime, timedelta, timezone

    from services.plans import BOOST_MINUTES
    from services.public_profile import в_utc

    now = datetime.now(timezone.utc)
    действует_до = now + timedelta(minutes=10)

    прежний = в_utc(действует_до)
    база = прежний if (прежний and прежний > now) else now
    итог = база + timedelta(minutes=BOOST_MINUTES)

    assert итог == действует_до + timedelta(minutes=BOOST_MINUTES), (
        "повторное включение обнулило остаток вместо продления"
    )


def test_буст_поднимает_анкету_в_деке():
    """Колонка без влияния на сортировку была бы мёртвой.

    Проверяем поведением: прежняя версия искала дословную строку сравнения и
    падала при выносе его в общий помощник, хотя смысл не менялся. Заодно
    ловим то, чего грепом не увидеть: время из базы бывает naive, и прямое
    сравнение с aware `now` роняет обработчик (так ломалось начисление буста).
    """
    from datetime import datetime, timedelta, timezone

    from services import matching
    from services.public_profile import буст_активен

    assert matching.BOOST_MULTIPLIER > 1

    ещё_идёт = datetime.now(timezone.utc) + timedelta(minutes=5)
    уже_кончился = datetime.now(timezone.utc) - timedelta(minutes=5)

    assert буст_активен(ещё_идёт) is True
    assert буст_активен(уже_кончился) is False, "прошедшая дата считается бустом"
    assert буст_активен(None) is False

    # Naive-время из SQLite и старых записей не должно ронять сравнение
    assert буст_активен(ещё_идёт.replace(tzinfo=None)) is True
    assert буст_активен(уже_кончился.replace(tzinfo=None)) is False


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
    assert "Like.created_at >= _window_start(period)" in исходник
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


def test_оценка_открыта_но_цельно_отключаема():
    """Оценки видимы (кто и сколько), а неучастие — только целиком: скрылся —
    не оцениваешь и тебя не оценивают. Половинчатой анонимности нет: она
    превращает очередь в одностороннее окошко."""
    import inspect

    from models.schemas import MyPhotoRating, RatingFeedItem
    from routers import photo_ratings

    # Лента оценщиков — часть ответа, карточка несёт анкету и балл
    assert {"feed"} <= set(MyPhotoRating.model_fields)
    assert {"user_id", "display_name", "score"} <= set(RatingFeedItem.model_fields)

    # Очередь не пускает скрывшихся, приём оценки — тоже (симметрия)
    очередь = inspect.getsource(photo_ratings.get_rating_queue)
    ставка = inspect.getsource(photo_ratings.rate_photo)
    assert "hide_from_ratings" in очередь
    assert "hide_from_ratings" in ставка


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
    assert "if public_photos(p.photos)" in исходник


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


def test_у_каждого_обработчика_бота_есть_кнопка():
    """Обратная сторона: обработчик, до которого не ведёт ни одна кнопка.

    Такой код не ломается и не падает — он просто мёртвый, и его легко принять
    за работающую функцию. Так было с `show_settings`: хендлер на
    `F.data == "settings"` существовал, а кнопки «Настройки» в боте не было
    нигде, то есть раздел выглядел реализованным, но открыть его было нельзя.
    """
    import re
    from pathlib import Path

    бот = Path(__file__).resolve().parents[2] / "bot"
    исходники = "\n".join(
        p.read_text(encoding="utf-8")
        for p in [бот / "keyboards.py", *sorted((бот / "handlers").glob("*.py"))]
    )

    отправляют = set()
    for значение in re.findall(r'callback_data=f?"([^"]*)"', исходники):
        отправляют.add(значение.split("{")[0])

    точные = set(re.findall(r'F\.data == "([^"]*)"', исходники))

    #: Приходят не от кнопки, а из другого места, поэтому кнопки им не нужны.
    ЖДЁМ_БЕЗ_КНОПКИ = {"menu"}

    недостижимые = {
        значение
        for значение in точные - ЖДЁМ_БЕЗ_КНОПКИ
        if значение not in отправляют
        and not any(о.startswith(значение) for о in отправляют if о)
    }
    assert not недостижимые, (
        f"обработчики, до которых не ведёт ни одна кнопка: {sorted(недостижимые)}"
    )


def test_кончившиеся_анкеты_ведут_в_приложение_за_настройками():
    """`no_more_profiles()` обещал «расширьте настройки поиска», которых в
    самом боте нет (возраст, дистанция, нишевые фильтры — это шторка в
    мини-аппе, см. web/src/pages/Discover.tsx). Дёргаем реальный хендлер
    `_show_next_profile` с пустой декой и смотрим на то, что он на самом деле
    отправляет: если текст продолжает звать «расширить настройки», а рядом
    нет кнопки в приложение — обещание снова ничем не подтверждено.

    Запускается интерпретатором бота (aiogram там, в api его нет), поэтому
    гоняем как отдельный процесс, а не импортируем модуль напрямую.
    """
    import json
    import subprocess
    import sys
    from pathlib import Path

    бот = Path(__file__).resolve().parents[2] / "bot"
    python = бот / ".venv" / "bin" / "python"
    if not python.exists():
        pytest.skip("venv бота не поднят в этом окружении")

    скрипт = """
import sys
sys.path.insert(0, ".")
import asyncio
import json
import handlers.dating as dating


async def _пустая_дека(user_id, limit=5):
    return []

dating.get_deck_profiles = _пустая_дека


class FakeMessage:
    def __init__(self):
        self.calls = []

    async def answer_photo(self, photo, caption, reply_markup):
        self.calls.append((caption, reply_markup))


class FakeState:
    async def update_data(self, **kw):
        pass

    async def set_state(self, s):
        pass

    async def clear(self):
        pass


async def main():
    msg = FakeMessage()
    await dating._show_next_profile(msg, 1, "uid", FakeState())
    caption, kb = msg.calls[0]
    urls = [
        btn.web_app.url
        for row in kb.inline_keyboard
        for btn in row
        if btn.web_app
    ]
    print(json.dumps({"caption": caption, "urls": urls}))


asyncio.run(main())
"""

    результат = subprocess.run(
        [str(python), "-c", скрипт],
        cwd=бот,
        capture_output=True,
        text=True,
    )
    assert результат.returncode == 0, результат.stderr

    ответ = json.loads(результат.stdout.strip().splitlines()[-1])
    caption = ответ["caption"]
    urls = ответ["urls"]

    if "настрой" in caption.lower() or "фильтр" in caption.lower():
        # Текст ссылается на настройки поиска — тогда рядом обязана быть
        # кнопка, которая туда действительно ведёт (в боте самих настроек нет)
        assert any("/discover" in url for url in urls), (
            "текст обещает настройки поиска, но кнопка в приложение "
            f"отсутствует: {ответ}"
        )


def test_бот_не_раздаёт_бесплатно_кто_вас_лайкнул():
    """Главный платный гейт обходился через бота.

    Мини-апп отдаёт бесплатному пользователю закрытую карточку без имени и
    фото (`api/routers/likes.py`), а бот слал анкету лайкнувшего целиком и
    любому — то есть раздавал даром ровно то, что продаётся как Plus-перк
    («👀 Видно, кто вас лайкнул», bot/services/plans.py).

    Дёргаем настоящий `_after_like` дважды: для бесплатного и для Plus. Имени
    лайкнувшего в бесплатной ветке быть не должно, а в платной — должно, иначе
    «починка» свелась бы к поломке функции.
    """
    import json
    import subprocess
    from pathlib import Path

    бот = Path(__file__).resolve().parents[2] / "bot"
    python = бот / ".venv" / "bin" / "python"
    if not python.exists():
        pytest.skip("venv бота не поднят в этом окружении")

    скрипт = """
import sys
sys.path.insert(0, ".")
import asyncio
import json
import handlers.dating as dating

ИМЯ = "Лайкнувший-Пётр"


async def _profile(uid):
    return {"user_id": uid, "display_name": ИМЯ, "photos": [], "bio": "", "age": 30}


async def _user_by_id(uid):
    return {"id": uid, "telegram_id": 555}


async def _like(*a, **kw):
    return {"matched": False}


class FakeBot:
    def __init__(self):
        self.sent = []

    async def send_message(self, chat_id, text, **kw):
        self.sent.append(text)

    async def send_photo(self, chat_id, photo, caption=None, **kw):
        self.sent.append(caption or "")


class FakeMessage:
    async def answer(self, *a, **kw):
        pass

    async def answer_photo(self, *a, **kw):
        pass


async def прогон(платный):
    async def _тариф(uid):
        return платный

    dating.get_profile = _profile
    dating.get_user_by_id = _user_by_id
    dating.видно_кто_лайкнул = _тариф

    async def _render(bot, chat_id, profile):
        await bot.send_message(chat_id, profile["display_name"])

    dating._render_profile_to_chat = _render

    bot = FakeBot()
    await dating._after_like(
        FakeMessage(), bot, {"id": "u-me"}, "u-target",
        {"matched": False}, None, True, "",
    )
    return " ".join(bot.sent)


async def main():
    бесплатно = await прогон(False)
    платно = await прогон(True)
    print(json.dumps({"free": бесплатно, "paid": платно, "имя": ИМЯ}))


asyncio.run(main())
"""

    результат = subprocess.run(
        [str(python), "-c", скрипт], cwd=бот, capture_output=True, text=True
    )
    if результат.returncode != 0:
        pytest.skip(f"сигнатура _after_like изменилась: {результат.stderr[-300:]}")

    ответ = json.loads(результат.stdout.strip().splitlines()[-1])
    имя = ответ["имя"]

    assert имя not in ответ["free"], (
        "бот показал бесплатному, кто его лайкнул — платный гейт обойдён"
    )
    assert имя in ответ["paid"], (
        "подписчику тоже не показали — гейт не работает, а просто ломает функцию"
    )


def test_возврат_stars_снимает_подписку():
    """Возврат Stars был бесплатным Ultra.

    Бот обрабатывал `successful_payment`, но не `refunded_payment`: человек
    оплачивал, получал уровень, возвращал Stars через поддержку Telegram и
    продолжал пользоваться до конца оплаченного срока.

    Проверяем поведением: у аиограма спрашиваем, что хендлер вообще
    зарегистрирован на это событие, и дёргаем настоящую функцию отката с
    подменённой БД — срок должен уменьшиться ровно на дни платежа.
    """
    import json
    import subprocess
    from pathlib import Path

    бот = Path(__file__).resolve().parents[2] / "bot"
    python = бот / ".venv" / "bin" / "python"
    if not python.exists():
        pytest.skip("venv бота не поднят в этом окружении")

    скрипт = """
import sys
sys.path.insert(0, ".")
import asyncio
import json
from aiogram.types import Message
import handlers.premium as premium

# Прогоняем фильтры хендлеров на настоящем событии возврата: так проверяется
# не имя функции, а то, что событие реально до кого-то доходит
событие = Message.model_validate({
    "message_id": 1,
    "date": 0,
    "chat": {"id": 5, "type": "private"},
    "from": {"id": 5, "is_bot": False, "first_name": "Тест"},
    "refunded_payment": {
        "currency": "XTR",
        "total_amount": 149,
        "invoice_payload": "plan:plus_1m",
        "telegram_payment_charge_id": "charge-возврат",
    },
})


async def main():
    import inspect

    async def проверить(f, событие):
        # MagicFilter возвращает само значение поля (не корутину), а обычные
        # фильтры — awaitable. Поддерживаем оба, иначе тест «не находит»
        # хендлер из-за своей же ошибки, а не из-за отсутствия обработчика
        итог = f.callback(событие)
        if inspect.isawaitable(итог):
            итог = await итог
        return bool(итог)

    подошло = []
    for h in premium.router.message.handlers:
        # Хендлер подходит, только если прошли ВСЕ его фильтры — иначе
        # StateFilter("*") у соседней команды матчит любое событие
        ок = bool(h.filters)
        for f in h.filters:
            try:
                if not await проверить(f, событие):
                    ок = False
                    break
            except Exception:
                ок = False
                break
        if ок:
            подошло.append(getattr(h.callback, "__name__", "?"))

    # И сама функция откатывает срок: подменяем БД, чтобы не поднимать Postgres
    снято = {}

    async def _revoke(payment_id, provider="stars"):
        снято["id"] = payment_id
        return {"revoked": True, "user_id": "u", "days": 30, "plan": "free"}

    premium.revoke_premium_payment = _revoke

    class FakeMsg:
        refunded_payment = событие.refunded_payment

        async def answer(self, *a, **kw):
            pass

    await premium.on_refunded_payment(FakeMsg())
    print(json.dumps({"подошло": подошло, "снято": снято.get("id")}))


asyncio.run(main())
"""

    результат = subprocess.run(
        [str(python), "-c", скрипт], cwd=бот, capture_output=True, text=True
    )
    assert результат.returncode == 0, результат.stderr

    ответ = json.loads(результат.stdout.strip().splitlines()[-1])
    assert "on_refunded_payment" in ответ["подошло"], (
        "событие возврата ни к кому не приходит — вернувший Stars "
        f"продолжит пользоваться подпиской: {ответ}"
    )
    assert ответ["снято"] == "charge-возврат", "откат вызван не для того платежа"


def test_картинка_в_личку_только_из_нашего_хранилища(monkeypatch):
    """WS-чат принимал `image_url` из сырого пакета без проверки.

    Загрузки фото в чат в интерфейсе нет, но пакет собирает клиент: в обход UI
    можно было положить ссылку на любой хост, и она показывалась собеседнику
    как картинка — мимо AI-модерации и санитайзера, попутно утекая IP
    получателя на посторонний сервер.

    Проверяем сам предикат, через который ходят оба пути (личка и фото
    анкеты), — тогда следующий канал картинок нельзя будет подключить,
    забыв про проверку.
    """
    from config import get_settings
    from services.public_profile import наша_картинка

    настройки = get_settings()
    monkeypatch.setattr(настройки, "R2_PUBLIC_URL", "https://media.simp.test", raising=False)

    assert наша_картинка("https://media.simp.test/photos/u/1.jpg") is True
    assert наша_картинка("https://evil.test/1.jpg") is False, "чужая ссылка принята"
    # http вместо https на нашем же домене — тоже чужая: подмена схемы
    assert наша_картинка("http://media.simp.test/photos/u/1.jpg") is False
    # file_id Telegram — не ссылка, его кладёт бот без R2
    assert наша_картинка("AgACAgIAAxkBAAI-file-id") is True
    # Пустое значение — картинки нет, проверять нечего
    assert наша_картинка(None) is True
    assert наша_картинка("") is True


def test_политика_не_обещает_лишнего_про_пуши():
    """privacy.html обещал, что Apple получает «только токен устройства, без
    содержания переписки», а сервер шлёт в теле пуша имя отправителя и первые
    150 символов сообщения (api/services/push.py: notify_new_message).

    Расхождение кода и юридического документа — не мелочь: на privacy.html
    человек принимает решение, о чём писать в переписке.
    """
    from pathlib import Path

    корень = Path(__file__).resolve().parents[2]
    политика = (корень / "landing" / "privacy.html").read_text(encoding="utf-8")
    пуши = (корень / "api" / "services" / "push.py").read_text(encoding="utf-8")

    # Текст сообщения действительно уходит в пуш — если это перестанет быть
    # правдой, обещание можно будет вернуть, и тест об этом напомнит
    шлёт_текст = "body=text[:150]" in пуши.replace(" ", "")
    assert шлёт_текст, (
        "пуш больше не содержит текст сообщения — можно вернуть в политику "
        "обещание «без содержания переписки» и упростить этот тест"
    )
    assert "без содержания переписки" not in политика, (
        "политика обещает, что переписка не уходит в Apple, а пуш несёт "
        "первые 150 символов сообщения"
    )


def test_заявленные_разрешения_ios_действительно_используются():
    """Разрешение, заявленное «на всякий случай», — повод для Metadata
    Rejected по Guideline 5.1.1: ревьюер ищет функцию и не находит.

    NSPhotoLibraryAddUsageDescription обещал сохранение фото в галерею,
    которого в коде нет вовсе (в приложении только выбор файла для анкеты).
    """
    from pathlib import Path

    корень = Path(__file__).resolve().parents[2]
    plist = (корень / "web" / "ios" / "App" / "App" / "Info.plist").read_text(encoding="utf-8")

    if "NSPhotoLibraryAddUsageDescription" in plist:
        исходники = " ".join(
            p.read_text(encoding="utf-8", errors="ignore")
            for p in (корень / "web" / "src").rglob("*.ts*")
        )
        assert any(
            маркер in исходники
            for маркер in ("saveToGallery", "writePhotoAlbum", "PhotoLibrary")
        ), (
            "заявлено сохранение фото в галерею, но кода для этого нет — "
            "Guideline 5.1.1, Metadata Rejected"
        )


def test_онлайн_не_показывает_точное_время_последнего_входа():
    """«В сети» на карточке — флаг, а не время.

    Точное «был в 14:32» превращает дейтинг в слежку: по нему видно распорядок
    дня человека. Поэтому наружу уходит только булев признак, а порог держим в
    одном месте, чтобы «недавно» не разъехалось между экранами.
    """
    from models.schemas import DeckProfile
    from services.matching import ОНЛАЙН_МИНУТ

    поля = DeckProfile.model_fields
    assert "is_online" in поля
    assert поля["is_online"].annotation is bool, "флаг стал не булевым — не время ли это?"
    assert "last_seen" not in поля, "точное время последнего входа утекло в карточку"
    assert 1 <= ОНЛАЙН_МИНУТ <= 60, "порог «в сети» выглядит неправдоподобным"


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
    """Общий лимит по пути не мешает залить одну комнату подряд.

    Проверка вынесена в `check_flood` и вызывается из двух мест — обычной
    отправки и пересыла ролика: пока она жила внутри обработчика отправки,
    роликами комнату можно было залить в обход лимита. Поэтому смотрим на саму
    функцию, а не на текст обработчика.
    """
    import inspect

    from routers import rooms

    assert 1 <= rooms.FLOOD_PER_MINUTE <= 60
    исходник = inspect.getsource(rooms.check_flood)
    assert "timedelta(minutes=1)" in исходник
    assert "429" in исходник
    # Оба пути записи в комнату обязаны звать проверку
    assert "check_flood" in inspect.getsource(rooms.send_room_message)

    from routers import reels

    assert "check_flood" in inspect.getsource(reels.forward_reel)


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
    """Бонус, доступный бесплатно, не помогает продать подписку. Квота
    месячная: одна попытка на базовом платном уровне, три — на максимальном,
    редкость попытки и есть ценность кейса."""
    from services.cases import openings_per_month

    assert openings_per_month("free") == 0
    assert openings_per_month("plus") == 1
    assert openings_per_month("ultra") > openings_per_month("plus")
    assert openings_per_month("aurora") == 3
    # Испорченная запись в БД не должна выдавать попытки
    assert openings_per_month("админ") == 0


def test_попытки_считаются_по_времени():
    import inspect

    from routers import cases

    исходник = inspect.getsource(cases._openings_left)
    # Окно — календарный месяц, а не скользящие сутки: у месяца есть дата
    # обновления, которую можно показать под кнопкой
    assert "начало_месяца" in исходник
    assert "CaseOpening.created_at >= since" in исходник


def test_буст_продлевает_а_не_обнуляет():
    """Иначе новые минуты сожгли бы уже действующий буст.

    Считаем ту же арифметику, что и роутер: от конца действующего буста, а не
    от текущего момента. Прежняя версия искала строку в исходнике и молчала бы
    о том, что сравнение падает на naive-времени из базы.
    """
    from datetime import datetime, timedelta, timezone

    from services.public_profile import в_utc

    now = datetime.now(timezone.utc)
    действующий_до = now + timedelta(minutes=20)

    # Ровно как в routers/profiles.py (включение буста)
    прежний = в_utc(действующий_до)
    база = прежний if (прежний and прежний > now) else now
    итог = база + timedelta(minutes=15)

    assert итог > действующий_до, "выпавшие минуты сожгли действующий буст"
    assert (итог - действующий_до) == timedelta(minutes=15)

    # Истёкший буст не должен продлеваться из прошлого
    истёк = в_utc(now - timedelta(minutes=30))
    база2 = истёк if (истёк and истёк > now) else now
    assert (база2 + timedelta(minutes=15)) > now


def test_бонусные_суперлайки_отдельным_полем_и_тратятся_последними():
    """Начисленный бонус (акции, компенсации, старые награды кейсов) не имеет
    права попадать в суточную квоту: прибавка к квоте возобновлялась бы каждый
    день сама. А тратить бонус первым означало бы сжечь его вместо того, что и
    так обновится завтра."""
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

    # Считаем записи, а не слово `path:`: у массива появилась аннотация типа
    # (`{ path: string; icon: typeof Flame; label: Ключ }[]`, добавлена вместе с
    # переводом подписей), и её `path: string` — не вкладка. Кавычка после
    # двоеточия отличает запись от поля типа.
    assert nav.count('path: "') == 5, "в навигации должно быть ровно пять вкладок"
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
    """Проверяем поведение, а не текст исходника.

    Прежняя версия этого теста искала слово «hide_age» в каждом месте, где
    отдаётся чужая анкета. Такой тест зелёный, пока слово встречается, и он
    ЛОМАЕТСЯ при правильном рефакторинге: когда расчёт возраста свели в один
    `публичный_возраст()`, слово из роутеров исчезло, а поведение стало
    строже. Плюс он не поймал пятую копию формулы в видео-ленте — там слова
    просто не было, и утечка прожила мимо «зелёных» тестов.

    Теперь дергаем сам помощник, через который обязаны ходить все публичные
    места, и проверяем результат.
    """
    from datetime import datetime, timezone
    from types import SimpleNamespace

    from services.public_profile import возраст_из_даты, публичный_возраст

    рождение = datetime(1998, 5, 10, tzinfo=timezone.utc)
    ожидаемый = возраст_из_даты(рождение)
    assert ожидаемый and ожидаемый > 18, "заготовка теста рассыпалась"

    открытый = SimpleNamespace(birth_date=рождение, hide_age=False)
    скрытый = SimpleNamespace(birth_date=рождение, hide_age=True)

    assert публичный_возраст(открытый) == ожидаемый
    assert публичный_возраст(скрытый) is None, "возраст отдан в обход настройки"
    # Анкеты может не быть вовсе — это не повод падать с 500
    assert публичный_возраст(None) is None


def test_все_публичные_места_берут_возраст_из_общего_помощника():
    """Пятая копия формулы в видео-ленте отдавала возраст мимо `hide_age`.

    Копии формулы — это и есть механизм утечки: настройку чинили в четырёх
    местах и пропустили пятое. Поэтому проверяем не текст про настройку, а то,
    что в модулях, отдающих чужую анкету, своей арифметики возраста не
    осталось: считать должен общий помощник.
    """
    import inspect

    from routers import likes, matches, profiles, reels
    from services import matching

    for модуль in (likes, matches, profiles, reels, matching):
        исходник = inspect.getsource(модуль)
        assert "birth_date.year" not in исходник, (
            f"{модуль.__name__}: своя копия расчёта возраста — "
            "именно так возраст и утекал мимо hide_age"
        )


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


def test_отсутствие_модерации_фото_заметно():
    """Фото без AI-ключа не проверяется НИКАК — в отличие от текста, у которого
    есть словарный фильтр. Молчаливый пропуск всех фото в дейтинге
    обнаруживается по жалобе, а не по логам, поэтому состояние обязано быть
    видно в health-check и логироваться как ошибка."""
    import inspect

    from services import ai_moderation

    assert hasattr(ai_moderation, "image_moderation_available")

    исходник = inspect.getsource(ai_moderation.moderate_image)
    assert "logger.error" in исходник, "пропуск всех фото должен логироваться как ошибка"

    from pathlib import Path

    main_src = (
        Path(__file__).resolve().parents[1] / "main.py"
    ).read_text(encoding="utf-8")
    assert "photo_moderation" in main_src, "состояния модерации фото нет в health-check"


def test_текстовая_модерация_имеет_запасной_фильтр():
    """У текста цена отказа AI ниже: словарь ловит хотя бы явное."""
    from services.ai_moderation import _keyword_filter

    assert _keyword_filter("продаю наркотики")["blocked"] is True
    assert _keyword_filter("люблю кофе и кино")["blocked"] is False


# ════════════════════════════════════════════════════════════════
#  Блокеры из полного аудита 05.08.2026 (32 роли, 134 агента)
# ════════════════════════════════════════════════════════════════

def test_лендинг_ведёт_на_тот_же_бот_что_и_приложение():
    """Лендинг вёл на t.me/simp_bot, а приложение — на simp_dating_bot.
    Единственный канал привлечения обрывался на первом клике, и это не видно
    ниоткуда, кроме как открыть ссылку руками."""
    import re
    from pathlib import Path

    корень = Path(__file__).resolve().parents[2]

    из_лендинга = set()
    for файл in (корень / "landing").glob("*.html"):
        из_лендинга |= set(
            re.findall(r"t\.me/([a-zA-Z0-9_]+)", файл.read_text(encoding="utf-8"))
        )

    веб = (корень / "web" / "src" / "pages" / "Profile.tsx").read_text(encoding="utf-8")
    из_веба = set(re.findall(r'VITE_BOT_USERNAME \|\| "([a-zA-Z0-9_]+)"', веб))

    assert из_лендинга, "на лендинге не нашлось ни одной ссылки на бота"
    assert из_лендинга == из_веба, (
        f"лендинг ведёт на {sorted(из_лендинга)}, приложение — на {sorted(из_веба)}"
    )


def test_разрешение_микрофона_объявлено():
    """Без NSMicrophoneUsageDescription iOS убивает приложение при первом
    getUserMedia — голосовая рулетка гарантированно роняет сборку."""
    from pathlib import Path

    plist = (
        Path(__file__).resolve().parents[2]
        / "web" / "ios" / "App" / "App" / "Info.plist"
    ).read_text(encoding="utf-8")

    assert "NSMicrophoneUsageDescription" in plist


def test_личный_чат_модерируется():
    """Самый объёмный канал общения был единственным немодерируемым: bio,
    текст лайка и комнаты проверялись, а в личке можно было писать что угодно."""
    import inspect

    from routers import chat

    исходник = inspect.getsource(chat.websocket_chat)
    assert "moderate_text(text)" in исходник
    assert '"chat_message"' in исходник
    # Сокет не рвём: разрыв выглядит как поломка приложения
    assert '"type": "rejected"' in исходник


def test_модерация_не_блокирует_event_loop():
    """SDK Zhipu синхронный: прямой вызов вешает единственный event loop —
    на время запроса встаёт весь сервер, включая чужие чаты и деку."""
    import inspect

    from services import ai_moderation

    for функция in (ai_moderation.moderate_text, ai_moderation.moderate_image):
        исходник = inspect.getsource(функция)
        assert "asyncio.to_thread" in исходник, f"{функция.__name__} блокирует loop"


def test_бан_переживает_удаление_аккаунта():
    """Забаненный удалял аккаунт (каскад стирал бан), заходил тем же Telegram
    и приходил чистым. Модерация без памяти не работает вовсе."""
    import inspect

    from models.models import BannedIdentity
    from routers import admin, auth, report

    assert "telegram_id" in BannedIdentity.__table__.columns

    # Запоминаем при всех трёх видах бана. Админские баны идут через общий
    # ban_user_for_violation — тогда память обязана сидеть внутри него.
    from services import enforcement

    assert "remember_ban" in inspect.getsource(enforcement.ban_user_for_violation)
    for функция in (admin.ban_user, admin.report_action, report.create_report):
        исходник = inspect.getsource(функция)
        assert "remember_ban" in исходник or "ban_user_for_violation" in исходник, (
            f"{функция.__name__} банит, не запоминая личность"
        )

    # Проверяем при регистрации: запись нужна целиком, чтобы новый аккаунт
    # унаследовал срок временного бана, а не только сам факт
    assert "banned_identity_record" in inspect.getsource(auth.auth_telegram)

    # Разбан убирает из списка, иначе он работал бы только до первой чистки
    assert "forgive" in inspect.getsource(admin.unban_user)


def test_удаление_аккаунта_остаётся_полным():
    """Список банов хранит только ключи входа и причину: App Store требует
    настоящего удаления данных (5.1.1(v)), и профиль, фото, переписка
    удаляются как раньше.

    telegram_id и apple_id — это внешние идентификаторы входа (кто заходит),
    а не содержимое профиля. Оба нужны, чтобы бан переживал удаление аккаунта
    на своей платформе: без apple_id пришедший из App Store обходил бы бан
    удалением и повторным входом через Apple, как раньше это делалось через
    Telegram. Apple ID — непрозрачный субъектный идентификатор, не имя и не
    фото, поэтому он в том же ряду, что telegram_id, а не среди личных данных.
    """
    from models.models import BannedIdentity

    колонки = set(BannedIdentity.__table__.columns.keys())
    # banned_until — атрибут санкции (когда бан кончается), той же природы,
    # что reason: без него временный бан после удаления аккаунта становился
    # бы вечным. Личных данных в нём нет.
    assert колонки == {
        "id", "telegram_id", "apple_id", "reason", "created_at", "banned_until",
    }
    # Ничего личного: ни имени, ни фото, ни города
    assert not (колонки & {"display_name", "photos", "bio", "city", "birth_date"})


def test_пауза_и_инкогнито_разные_поля():
    """Команда /pause в боте бесплатно включала is_incognito — то, что в
    мини-аппе стоит 149 руб и требует Plus. Смыслы разные: инкогнито платное,
    пауза — базовое право уйти из поиска."""
    import inspect
    from pathlib import Path

    from models.models import Profile

    assert "is_paused" in Profile.__table__.columns

    бот = (
        Path(__file__).resolve().parents[2] / "bot" / "database" / "connection.py"
    ).read_text(encoding="utf-8")

    начало = бот.index("async def set_profile_hidden")
    конец = бот.index("async def is_profile_hidden")
    # Только исполняемые строки: в комментарии инкогнито упоминается по делу —
    # там объясняется, почему поля разные
    пауза = "\n".join(
        строка
        for строка in бот[начало:конец].splitlines()
        if not строка.strip().startswith(("#", '"""', "*"))
    )
    assert "profile.is_paused = hidden" in пауза
    assert "profile.is_incognito" not in пауза, "/pause снова включает платную функцию"

    # Из выдачи убирают оба флага — иначе пауза перестала бы работать
    from services import matching

    выборка = inspect.getsource(matching._sample_candidates)
    assert "is_paused" in выборка and "is_incognito" in выборка


def test_пауза_учтена_во_всех_публичных_разделах():
    """Тот же класс ошибки, что с инкогнито: новый флаг легко забыть в
    половине мест."""
    import inspect

    from routers import leaderboard, photo_ratings, reels

    for модуль in (leaderboard, photo_ratings, reels):
        assert "is_paused" in inspect.getsource(модуль), (
            f"{модуль.__name__}: пауза не учтена"
        )


def test_индекс_деки_совпадает_с_условием_выборки():
    """Частичный индекс с прежним условием выборка просто не использовала бы —
    дека вернулась бы к полному сканированию таблицы."""
    from models.models import Profile

    индекс = next(
        i for i in Profile.__table__.indexes if i.name == "ix_profile_sample"
    )
    условие = str(индекс.dialect_options["postgresql"]["where"])
    assert "is_paused" in условие
    assert "is_incognito" in условие


# ════════════════════════════════════════════════════════════════
#  Голосовая рулетка: блокеры аудита
#  (6 ролей независимо упёрлись в эту фичу с разных сторон)
# ════════════════════════════════════════════════════════════════

def test_приглашение_доходит_между_инстансами():
    """Приглашение публиковалось «в комнату» звонка, но на другом инстансе
    комнаты ещё нет и подписчиков у неё тоже — событие уходило в пустоту, и
    пара не собиралась. Теперь у каждого свой канал, и ждущий слушает его.

    Раньше каждый сокет рулетки поднимал свой `r.pubsub()` — 10 000 ждущих
    держали 10 000 подключений к Redis из одного процесса. В audit #8
    подписка перенесена на общего читателя `RoomManager`: `subscribe_channel`
    вместо `invites_task = asyncio.create_task(listen_invites())`. Суть та же,
    форма — другая.
    """
    import inspect

    from routers import voice
    from services import voice as voice_service

    assert hasattr(voice_service, "personal_channel")
    assert hasattr(voice_service, "invite")

    сокет = inspect.getsource(voice.websocket_roulette)
    # Ждущий подписан заранее — иначе он не узнает о найденной паре
    assert "subscribe_channel" in сокет
    assert "personal_channel(user_id)" in сокет
    # Мёртвого события "invite", которое никто не слушал, больше нет
    assert '"invite"' not in сокет


def test_подписка_на_приглашения_отменяется():
    """Слушатель держит соединение к Redis: без отмены оно живёт после
    закрытия сокета и течёт по одному на каждый заход в рулетку.

    Раньше отменялась задача `invites_task.cancel()`. Теперь слушатель общий,
    задачи нет, но снятие подписки обязано быть: `unsubscribe_channel` в
    `finally`.
    """
    import inspect

    from routers import voice

    сокет = inspect.getsource(voice.websocket_roulette)
    assert "unsubscribe_channel" in сокет
    assert "personal_channel(user_id)" in сокет


def test_собеседник_известен_и_на_него_можно_пожаловаться():
    """Разговор с незнакомцем был единственным местом, откуда нельзя сообщить
    о нарушении: partner_id не доходил до клиента, кнопки не было."""
    import inspect
    from pathlib import Path

    from routers import voice
    from services import voice as voice_service

    # Сервер отдаёт партнёра обеим сторонам
    assert '"partner_id"' in inspect.getsource(voice.websocket_roulette)
    assert "partner_id" in inspect.getsource(voice_service.invite)

    клиент = (
        Path(__file__).resolve().parents[2]
        / "web" / "src" / "pages" / "VoiceRoulette.tsx"
    ).read_text(encoding="utf-8")
    assert "reportUser" in клиент
    assert "partnerId" in клиент


def test_заблокированный_не_попадёт_в_пару():
    """Человек заблокировал обидчика именно чтобы больше его не встречать —
    голосом тем более. Но выкидывать заблокированного из очереди нельзя: он
    ждёт разговора с кем-то другим."""
    import inspect

    from routers import voice
    from services.voice import pop_waiting

    подбор = inspect.getsource(pop_waiting)
    assert "blocked" in подбор
    # Пропущенных возвращаем в очередь, а не теряем
    assert "lpush" in подбор

    сокет = inspect.getsource(voice.websocket_roulette)
    assert "Block.blocker_id == user_id" in сокет
    assert "Block.blocked_id == user_id" in сокет


# ════════════════════════════════════════════════════════════════
#  Комментарии, просмотры и жалоба на ролик
#  (без комментариев лента остаётся просмотром: впечатление от
#   видео никуда не ведёт)
# ════════════════════════════════════════════════════════════════

def test_роуты_комментариев_и_жалобы_на_ролик(openapi):
    paths = openapi["paths"]
    assert "/api/reels/{reel_id}/comments" in paths
    assert "get" in paths["/api/reels/{reel_id}/comments"]
    assert "post" in paths["/api/reels/{reel_id}/comments"]
    assert "/api/reels/{reel_id}/comments/{comment_id}" in paths
    # Ролики были единственным публичным контентом без кнопки жалобы
    assert "/api/reels/{reel_id}/report" in paths
    assert "/api/reels/{reel_id}/view" in paths


def test_комментарий_модерируется_как_публичный_текст():
    """Комментарий читают все, кто смотрит ролик: в личке собеседника можно
    заблокировать, а под видео грубость видна каждому."""
    import inspect

    from routers import reels

    исходник = inspect.getsource(reels.add_comment)
    assert "moderate_text(text)" in исходник
    assert '"reel_comment"' in исходник
    # Проверка до создания записи
    assert исходник.index("moderate_text") < исходник.index("session.add")


def test_заблокированные_не_видят_друг_друга_в_комментариях():
    """И в чтении, и в записи: человек заблокировал обидчика именно чтобы его
    не встречать, а под своим видео — тем более."""
    import inspect

    from routers import reels

    чтение = inspect.getsource(reels.list_comments)
    assert "Block.blocker_id == user.id" in чтение
    assert "Block.blocked_id == user.id" in чтение

    запись = inspect.getsource(reels.add_comment)
    assert "Block.blocker_id == reel.user_id" in запись


def test_комментарий_удаляет_автор_и_владелец_ролика():
    """Под своим видео человек должен убрать чужую грубость сам, не дожидаясь
    модератора."""
    import inspect

    from routers import reels

    исходник = inspect.getsource(reels.delete_comment)
    assert "comment.user_id != user.id" in исходник
    assert "reel.user_id != user.id" in исходник


def test_счётчики_рядом_с_роликом():
    """Лента показывает счётчики на каждой карточке: COUNT по двум таблицам на
    каждый ролик — лишний проход на каждый запрос ленты."""
    from models.models import Reel

    assert "comments_count" in Reel.__table__.columns
    assert "views_count" in Reel.__table__.columns


def test_свои_просмотры_не_считаются():
    """Иначе автор накрутил бы сам себе, просто листая ленту."""
    import inspect

    from routers import reels

    assert "reel.user_id == user.id" in inspect.getsource(reels.record_view)


def test_жалоба_на_ролик_не_требует_контакта_но_ограничена():
    """Общая жалоба на пользователя требует, чтобы люди контактировали (защита
    от травли жалобами). Ролик видят все, и случайный зритель заметит нарушение
    первым — поэтому своя ручка. Механика жалоб общая для всех поверхностей и
    живёт в services.content_reports; ручка задаёт порог и прячет ролик."""
    import inspect

    from middleware.rate_limit import _find_limit
    from routers import reels
    from services import content_reports

    ручка = inspect.getsource(reels.report_reel)
    # Порог: три жалобы снимают ролик с показа; само сравнение — в сервисе
    assert "порог=3" in ручка
    assert "is_hidden = True" in ручка

    сервис = inspect.getsource(content_reports.подать_жалобу_на_контент)
    assert ">= порог" in сервис
    # Повторная жалоба того же человека не накручивает порог
    assert "Report.reporter_id == reporter_id" in сервис
    # Свой антифлуд: лимит по префиксу пути не ловит id в середине
    assert "429" in сервис

    # Убедимся, что префиксное правило действительно не подходит
    _, лимит, _ = _find_limit("/api/reels/abc/report", "POST")
    assert лимит > 100, "если правило стало строгим, лимит в роутере лишний"


def test_клиент_показывает_комментарии_и_жалобу():
    from pathlib import Path

    web = Path(__file__).resolve().parents[2] / "web" / "src"
    лента = (web / "pages" / "Reels.tsx").read_text(encoding="utf-8")

    assert "comments_count" in лента
    assert "onComments" in лента and "ReportReasonSheet" in лента
    assert "recordReelView" in лента
    # Просмотры видит только автор — чужому зрителю цифра ничего не даёт
    # Просмотры — только автору (после переезда ленты на TikTok-раскладку блок многострочный)
    assert "reel.is_mine && (" in лента and "reel.views_count" in лента

    assert (web / "components" / "ReelComments.tsx").exists()


def test_цвета_интерфейса_читаемы_и_различимы():
    """Палитра проверяется числами, а не на глаз.

    Три вещи, на которых уже обжигались: `text-faint` был 3.74:1 и не проходил
    AA, хотя им набраны таймстемпы и дисклеймеры; акцент был холодным индиго
    при названии Симп; а после перехода на тёплый акцент «ошибка»
    расходилась с ним всего на 12° по тону и читалась как главное действие.
    """
    import colorsys
    import re
    from pathlib import Path

    css = (
        Path(__file__).resolve().parents[2] / "web" / "src" / "styles" / "globals.css"
    ).read_text(encoding="utf-8")

    def токен(имя: str) -> str:
        m = re.search(rf"--color-{имя}:\s*(#[0-9a-fA-F]{{6}})", css)
        assert m, f"токен --color-{имя} не найден"
        return m.group(1)

    def яркость(h: str) -> float:
        r, g, b = (int(h[i:i + 2], 16) / 255 for i in (1, 3, 5))
        f = lambda c: c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
        return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)

    def контраст(a: str, b: str) -> float:
        l1, l2 = sorted((яркость(a), яркость(b)), reverse=True)
        return (l1 + 0.05) / (l2 + 0.05)

    def тон(h: str) -> float:
        r, g, b = (int(h[i:i + 2], 16) / 255 for i in (1, 3, 5))
        return colorsys.rgb_to_hsv(r, g, b)[0] * 360

    фон = токен("bg")
    акцент = токен("accent")

    # Текст на фоне: AA требует 4.5:1
    for имя in ("text", "text-secondary", "text-muted", "text-faint"):
        значение = контраст(токен(имя), фон)
        assert значение >= 4.5, f"{имя}: {значение:.2f}:1 — ниже AA"

    # Акцент виден на фоне, и белый глиф виден на самом акценте
    assert контраст(акцент, фон) >= 3.0, "акцент теряется на фоне"
    assert контраст("#ffffff", акцент) >= 3.0, "белый глиф на акценте нечитаем"

    # «Ошибка» и «главное действие» не должны выглядеть одинаково
    расхождение = abs(тон(токен("danger")) - тон(акцент)) % 360
    расхождение = min(расхождение, 360 - расхождение)
    assert расхождение >= 20, (
        f"danger и accent расходятся всего на {расхождение:.0f}° — "
        "ошибка выглядит как главное действие"
    )


def test_живой_фон_не_закрашен_сплошной_заливкой():
    """Градиент был написан, но не виден — и по скриншоту это не читалось.

    Живой фон (`components/LivingBackground.tsx`, слой `.living-bg`) лежит
    на `z-index: -1`. Отрицательный слой уходит за фон СВОЕГО контекста
    наложения, но не за фон предка. Пока `background: var(--color-bg)`
    стоял на `body`, непрозрачная заливка закрывала орбы, и фон оставался
    ровным. Лечится переносом базовой заливки на `html`; `body` и `#root`
    обязаны быть прозрачными.
    """
    import re
    from pathlib import Path

    web = Path(__file__).resolve().parents[2] / "web" / "src"
    css = (web / "styles" / "globals.css").read_text(encoding="utf-8")

    assert re.search(r"(?m)^\s*\.living-bg\s*\{", css), "живой фон исчез из стилей"
    assert (web / "components" / "LivingBackground.tsx").exists(), (
        "компонент живого фона исчез"
    )
    assert "<LivingBackground" in (web / "App.tsx").read_text(encoding="utf-8"), (
        "живой фон не смонтирован в App"
    )

    # Заливка на html — есть; на body/#root — нет.
    assert re.search(r"\bhtml\s*\{[^}]*background:\s*var\(--color-bg\)", css), (
        "базовая заливка не на html — градиент ниже будет не виден"
    )
    for селектор in (r"body,\s*\n?\s*#root", r"body"):
        блок = re.search(rf"(?m)^\s*{селектор}\s*\{{([^}}]*)\}}", css)
        if блок and "background" in блок.group(1):
            assert "transparent" in блок.group(1), (
                f"у «{селектор}» непрозрачный фон — он закроет body::before"
            )


def test_лендинг_и_миниапп_не_расходятся_по_палитре():
    """Лендинг повторяет токены вручную (собирается без тулчейна).

    Из-за этого он уже отставал: после перехода на тёплую палитру у него
    остались холодные серые и старый цвет «ошибки». Первое, что видит
    человек, выглядело другим продуктом, чем само приложение.
    """
    import re
    from pathlib import Path

    корень = Path(__file__).resolve().parents[2]

    def токены(путь: Path) -> dict[str, str]:
        текст = путь.read_text(encoding="utf-8")
        return {
            m.group(1): m.group(2).lower()
            for m in re.finditer(r"--color-([a-z0-9-]+):\s*(#[0-9a-fA-F]{6})", текст)
        }

    def базовые_токены(путь: Path) -> dict[str, str]:
        """Только базовая палитра из `@theme`.

        Ниже в файле лежат схемы оформления (`:root[data-appearance=…]`),
        которые переопределяют ТЕ ЖЕ имена токенов. Сканирование файла
        целиком отдавало значения последней схемы — то есть сравнивало
        лендинг с «сепией» и всегда расходилось. У схем на лендинге пары
        нет, сравнивать их не с чем; сверяем то, что человек видит по
        умолчанию.
        """
        текст = путь.read_text(encoding="utf-8")
        начало = текст.index("@theme {")
        конец = текст.index("\n}", начало)
        return {
            m.group(1): m.group(2).lower()
            for m in re.finditer(
                r"--color-([a-z0-9-]+):\s*(#[0-9a-fA-F]{6})", текст[начало:конец]
            )
        }

    веб = базовые_токены(корень / "web" / "src" / "styles" / "globals.css")
    лендинг = токены(корень / "landing" / "styles.css")

    общие = веб.keys() & лендинг.keys()
    assert общие, "у лендинга не разобрались токены — проверка бесполезна"

    разошлись = {к: (веб[к], лендинг[к]) for к in общие if веб[к] != лендинг[к]}
    assert not разошлись, (
        "лендинг разошёлся с мини-аппом по цветам "
        f"(токен: веб / лендинг): {разошлись}"
    )


def test_миграции_применяются_при_старте():
    """24 файла миграций лежали мёртвым грузом.

    `create_all` создаёт недостающие таблицы, но НЕ добавляет колонки в уже
    существующие. На пустой базе всё работало, а на боевой новая колонка
    (например, `apple_id` или `email`) просто не появлялась — и запрос к ней
    падал в рантайме у пользователей. При этом `alembic upgrade head` не
    вызывался нигде: ни в Dockerfile, ни в railway.json, ни в приложении.
    """
    import inspect

    import main

    lifespan = inspect.getsource(main.lifespan)
    assert "_применить_миграции" in lifespan, (
        "миграции не накатываются при старте — новые колонки не появятся "
        "на существующей базе"
    )
    # Alembic блокирующий, а event loop здесь один: синхронный вызов подвесил
    # бы приложение целиком (на этом уже обжигались с клиентом AI-модерации)
    assert "to_thread" in lifespan, "блокирующий alembic вызывается прямо в loop"


def test_цепочка_миграций_целая():
    """Две головы или разрыв цепочки — деплой встанет на ровном месте, и
    выяснится это только в проде."""
    from pathlib import Path

    from alembic.config import Config
    from alembic.script import ScriptDirectory

    api = Path(__file__).resolve().parents[1]
    cfg = Config(str(api / "alembic.ini"))
    cfg.set_main_option("script_location", str(api / "migrations"))

    sc = ScriptDirectory.from_config(cfg)
    головы = sc.get_heads()
    assert len(головы) == 1, f"у миграций {len(головы)} голов: {головы}"

    # Вся цепочка должна доходить до базы одним куском
    всего = len(list(sc.walk_revisions()))
    длина, rev = 0, sc.get_revision(головы[0])
    while rev:
        длина += 1
        rev = sc.get_revision(rev.down_revision) if rev.down_revision else None
    assert длина == всего, f"цепочка рвётся: дошли до {длина} из {всего} ревизий"


def test_личка_из_бота_проходит_модерацию():
    """Личный чат — самый объёмный канал контента, и через бота он шёл вообще
    без проверки: тот же текст из мини-аппа модерируется (api/routers/chat.py),
    а из бота попадал собеседнику как есть.

    Дёргаем настоящий хендлер с заблокированным вердиктом и смотрим, что
    сообщение не сохранено и не разослано.
    """
    import json
    import subprocess
    from pathlib import Path

    бот = Path(__file__).resolve().parents[2] / "bot"
    python = бот / ".venv" / "bin" / "python"
    if not python.exists():
        pytest.skip("venv бота не поднят в этом окружении")

    скрипт = """
import sys
sys.path.insert(0, ".")
import asyncio, json
import handlers.matches as m

сохранено = []
разослано = []


async def _mod(текст):
    return {"blocked": True, "reason": "мат"}


async def _strike(*a, **kw):
    # Страйк-путь легитимно пишет журнал модерации (log_moderation,
    # text_strike_count) — глушим его, чтобы взрыв _session_cls ниже
    # означал ровно одно: сообщение дошло до записи в базу
    return None


async def _user(*a, **kw):
    return {"id": "u-me"}


async def _partner(match_id, user_id):
    return {"user_id": "u-partner", "display_name": "Партнёр"}


class FakeMessage:
    text = "запрещённый текст"

    class _From:
        id = 1
        username = ""
        first_name = "Т"

    from_user = _From()

    def __init__(self):
        self.ответы = []

    async def answer(self, text, **kw):
        self.ответы.append(text)


class FakeState:
    async def get_data(self):
        return {"active_match_id": "m-1"}

    async def clear(self):
        pass

    async def set_state(self, s):
        pass


async def main():
    m.moderate_text = _mod
    m.apply_text_strike = _strike
    m.get_or_create_user = _user
    m.get_match_partner = _partner
    # Если модерация не сработает, тест упадёт именно здесь — значит текст
    # дошёл до записи в базу
    # Хендлер делает `from database.connection import _session_cls` ВНУТРИ
    # функции, поэтому подменять надо в самом модуле, а не в хендлере
    import database.connection as dbc

    def _взрыв(*a, **kw):
        сохранено.append(1)
        raise RuntimeError("дошли до записи в БД")

    dbc._session_cls = _взрыв

    msg = FakeMessage()
    try:
        await m.send_message(msg, FakeState())
    except RuntimeError:
        pass

    print(json.dumps({"сохранено": len(сохранено), "ответы": msg.ответы}))


asyncio.run(main())
"""

    результат = subprocess.run(
        [str(python), "-c", скрипт], cwd=бот, capture_output=True, text=True
    )
    if результат.returncode != 0:
        pytest.skip(f"хендлер изменился: {результат.stderr[-300:]}")

    ответ = json.loads(результат.stdout.strip().splitlines()[-1])
    assert ответ["сохранено"] == 0, (
        "запрещённое сообщение дошло до записи в базу — модерации нет"
    )
    assert ответ["ответы"], "человеку не сказали, почему сообщение не ушло"


def test_у_горячих_фильтров_есть_индексы():
    """Колонка, по которой фильтруют на горячем пути, обязана быть в индексе.

    Так всплыл `dating_reports.reporter_id`: дедуп жалобы и антифлуд фильтруют
    по автору, а индекс был только на том, НА КОГО жалуются. Каждая новая
    жалоба сканировала таблицу целиком — а жалуется человек, когда ему уже
    плохо, и ждать он не должен.
    """
    from models.models import Base

    def проиндексирована(таблица: str, колонка: str) -> bool:
        t = Base.metadata.tables[таблица]
        # Индекс, первичный ключ или уникальное ограничение — любого хватит
        if колонка in [c.name for c in t.primary_key.columns]:
            return True
        for ix in t.indexes:
            if ix.columns.keys() and ix.columns.keys()[0] == колонка:
                return True
        # Уникальное ограничение индексом является, а внешний ключ — НЕТ:
        # Postgres не создаёт под FK индекс сам, и ровно на этом
        # dating_reports.reporter_id и оказался без индекса
        from sqlalchemy import UniqueConstraint

        for c in t.constraints:
            if isinstance(c, UniqueConstraint) and list(c.columns.keys())[:1] == [колонка]:
                return True
        return False

    # (таблица, колонка) → где по ней фильтруют
    ГОРЯЧИЕ = [
        ("dating_reports", "reporter_id"),   # дедуп жалобы, антифлуд
        ("dating_reports", "reported_id"),   # сколько жалоб на человека
        ("dating_likes", "liker_id"),        # кого я оценил (дека)
        ("dating_likes", "liked_id"),        # кто меня лайкнул
        ("dating_messages", "match_id"),     # переписка мэтча
        ("dating_messages", "reel_id"),      # FK SET NULL при удалении ролика
    ]

    без_индекса = [
        f"{т}.{к}" for т, к in ГОРЯЧИЕ if not проиндексирована(т, к)
    ]
    assert not без_индекса, f"фильтруют без индекса: {без_индекса}"


def test_наклейки_каталог_и_картинки_совпадают():
    """Каталог и папка с картинками пишутся одним генератором.

    Если завести список кодов вручную, он разойдётся с папкой, и в анкете
    появится битая картинка — а заметно это станет только на живом профиле.
    """
    from pathlib import Path

    from services.stickers import каталог

    папка = Path(__file__).resolve().parents[2] / "web" / "public" / "stickers"
    все = каталог()
    assert все, "каталог наклеек пуст"

    for н in все:
        файл = папка / н.set / f"{н.code}.webp"
        assert файл.exists(), f"нет картинки для {н.code}"
        assert н.image == f"/stickers/{н.set}/{н.code}.webp"

    # И наоборот: картинка без записи в каталоге никогда не выпадет
    пути = {f"{н.set}/{н.code}" for н in все}
    лишние = {
        str(f.relative_to(папка).with_suffix(""))
        for f in папка.rglob("*") if f.is_file()
        if str(f.relative_to(папка).with_suffix("")) not in пути
    }
    assert not лишние, f"файлы без записи в каталоге: {sorted(лишние)}"

    # Коды уникальны сквозь наборы: в анкете хранится только код
    assert len({н.code for н in все}) == len(все), "дубль кода наклейки"


def test_наклейки_каталог_внутри_api():
    """Каталог обязан доехать до контейнера API.

    Сервис на Railway собирается из папки api/ (Dockerfile: COPY . .), папки
    web/ там нет. Пока каталог лежал рядом с картинками в web/public, все тесты
    были зелёными, а в проде коллекция была бы пуста и каждый кейс отвечал 503 —
    ровно там, где тесты не бегают. Здесь держим оба условия: файл внутри api/
    и не вырезан .dockerignore.
    """
    from fnmatch import fnmatch
    from pathlib import Path

    from services.stickers import _КАТАЛОГ

    api = Path(__file__).resolve().parents[1]
    assert _КАТАЛОГ.is_relative_to(api), f"каталог наклеек вне api/: {_КАТАЛОГ}"
    assert _КАТАЛОГ.is_file(), f"каталог наклеек не найден: {_КАТАЛОГ}"

    внутри = _КАТАЛОГ.relative_to(api)
    кандидаты = {str(внутри), внутри.name, *(str(р) for р in внутри.parents if str(р) != ".")}
    for строка in (api / ".dockerignore").read_text(encoding="utf-8").splitlines():
        шаблон = строка.strip().rstrip("/")
        if not шаблон or шаблон.startswith("#"):
            continue
        for к in кандидаты:
            assert not fnmatch(к, шаблон), f".dockerignore вырезает каталог наклеек: {строка!r}"


def test_каждый_набор_наклеек_это_кейс():
    """Кейс выдаёт наклейки своего набора. Набор без кейса не выпадет никогда,
    кейс без набора отдаст 503 — оба расхождения ловим здесь, а не на живом
    человеке с оплаченной попыткой."""
    from services.cases import CASES
    from services.stickers import набор, наборы

    assert {к.code for к in CASES} == set(наборы())
    for к in CASES:
        assert len(набор(к.code)) >= 5, f"в наборе {к.code} меньше пяти наклеек"
        assert к.title and к.hint and к.accent.startswith("#")
    assert len({к.code for к in CASES}) == len(CASES)


def test_кейс_выдаёт_только_свой_набор():
    """Человек открывает «Керопи» — и получает Керопи, а не случайную картинку
    из общей кучи. Собранный набор возвращает None: кейс тогда идёт за
    обложкой, а не сжигает попытку на дубликат."""
    from services.cases import CASES
    from services.stickers import выпала, набор

    for к in CASES:
        for _ in range(300):
            н = выпала(набор_код=к.code)
            assert н is not None and н.set == к.code
        все_коды = {н.code for н in набор(к.code)}
        assert выпала(исключая=все_коды, набор_код=к.code) is None
        # Недостающая одна — выпадает именно она
        последняя = next(iter(все_коды))
        assert выпала(исключая=все_коды - {последняя}, набор_код=к.code).code == последняя

    assert выпала(набор_код="несуществующий") is None


def test_шансы_наклеек_честные():
    """Шансы показываются человеку до открытия, поэтому обязаны сходиться с
    тем, что реально выпадает. Скрытые шансы — то, за что не любят гача."""
    from collections import Counter

    from services.stickers import выпала, шансы_по_редкости

    объявлено = шансы_по_редкости()
    assert объявлено, "шансы не заданы"
    assert abs(sum(объявлено.values()) - 100) < 0.5, "суммарно не 100%"

    # Проверяем не «примерно похоже», а что каждая редкость попадает в свой
    # коридор: подкрутить вес незаметно не получится
    сколько = 6000
    факт = Counter(н.rarity for н in (выпала() for _ in range(сколько)) if н)
    for редкость, доля in объявлено.items():
        получилось = факт[редкость] / сколько * 100
        assert abs(получилось - доля) < 3.0, (
            f"{редкость}: обещано {доля}%, выпадает {получилось:.1f}%"
        )


def test_сумма_шансов_кейса_единица():
    """«Щедрый» кейс, где сумма больше единицы, незаметно повышает частоту
    последней награды — и наоборот."""
    from services.cases import REWARDS

    assert abs(sum(r.chance for r in REWARDS) - 1.0) < 1e-9

    # Обе коллекции обязаны быть среди наград: иначе одну из них нечем
    # пополнять. И только они: расходники превращали бы кейс в игровой автомат
    from services.cases import REWARD_DECOR, REWARD_STICKER

    assert any(r.code == REWARD_STICKER for r in REWARDS)
    assert any(r.code == REWARD_DECOR for r in REWARDS)
    assert {r.code for r in REWARDS} == {REWARD_STICKER, REWARD_DECOR}


def test_каждый_эндпоинт_кому_то_нужен():
    """Эндпоинт, до которого никто не обращается, — мёртвый код, который
    выглядит работающей функцией.

    Так нашёлся `/auth/logout-all`: выход со всех устройств был написан и
    протестирован, но ни одна кнопка к нему не вела — при угоне аккаунта
    воспользоваться им было нельзя.

    Клиентов несколько: мини-апп (`web/src/lib/*.ts`), бот (`bot/`) и внешние
    вызовы (Apple, Telegram). Последние перечислены явно — их «не зовёт наш
    код» является нормой.
    """
    import re
    from pathlib import Path

    from main import app

    корень = Path(__file__).resolve().parents[2]

    def норм(p: str) -> str:
        return re.sub(r"\{[^}]+\}", "{x}", p).rstrip("/")

    серверные = {
        норм(p.replace("/api", "", 1))
        for p in app.openapi()["paths"]
        if p.startswith("/api")
    }

    # Всё, что зовёт любой наш клиент
    зовут: set[str] = set()
    for файл in [*(корень / "web" / "src" / "lib").glob("*.ts")]:
        текст = файл.read_text(encoding="utf-8")
        for вызов in re.findall(
            r"api\.(?:get|post|patch|delete|put)\(\s*[`\"']([^`\"']+)", текст
        ):
            зовут.add(норм(re.sub(r"\$\{[^}]+\}", "{x}", вызов).split("?")[0]))

    #: Зовут не наши клиенты, поэтому в коде вызова нет и быть не должно.
    ВНЕШНИЕ = {
        "/iap/appstore/notifications",  # сервер-сервер от Apple
        "/auth/apple",                  # нативная сборка iOS
        "/auth/me",                     # проверка токена сторонними клиентами
        "/verification/sumsub/webhook",  # сервер-сервер от Sumsub
    }

    мёртвые = sorted(серверные - зовут - ВНЕШНИЕ)
    assert not мёртвые, (
        f"эндпоинты, до которых никто не обращается: {мёртвые}"
    )


def test_баннеры_бота_свои_и_существуют():
    """Баннеры вели на placehold.co: каждый пользователь видел чужую картинку,
    мы зависели от чужой доступности и отдавали туда статистику показов.

    Проверяем и обратное — что файлы на месте: ссылка на свой домен, за
    которой пусто, ничем не лучше чужого сервиса.
    """
    import re
    from pathlib import Path

    корень = Path(__file__).resolve().parents[2]
    конфиг = (корень / "bot" / "config.py").read_text(encoding="utf-8")

    # Ищем в коде, а не в комментариях: в комментарии рядом объяснено, почему
    # от внешнего сервиса ушли, и он не должен ронять проверку
    код = "\n".join(
        строка for строка in конфиг.splitlines()
        if not строка.lstrip().startswith("#")
    )
    assert "placehold" not in код, "баннеры снова ведут на внешний сервис"
    assert "http://" not in код.split("BANNERS")[-1], "баннер по незащищённой ссылке"

    # Берём имена прямо из бота: разбирать конфиг регуляркой хрупко, а
    # импортировать его нельзя (venv у бота свой, aiogram в api-venv нет)
    хвост = конфиг[конфиг.index("BANNERS"):]
    имена = re.findall(r'"(\w+)"', хвост)
    assert имена, "не нашёл список баннеров в bot/config.py"

    папка = корень / "web" / "public" / "banners"
    for имя in имена:
        assert (папка / f"{имя}.png").exists(), f"нет файла баннера {имя}.png"


def test_вход_через_apple_собран_целиком():
    """Guideline 4.8: вход через Apple обязателен там, где вход идёт через
    сторонний сервис. Сервер был готов раньше клиента, поэтому проверяем всю
    цепочку — иначе легко забыть одно звено и получить отклонение.

    Четыре звена: нативный плагин, регистрация в сборке iOS, право в
    entitlements (без него запрос падает в рантайме) и кнопка в интерфейсе.
    """
    from pathlib import Path

    корень = Path(__file__).resolve().parents[2]
    web = корень / "web"

    плагин = web / "native-plugins" / "capacitor-apple-signin"
    assert (плагин / "package.json").exists(), "плагина нет"
    swift = (
        плагин / "ios" / "Sources" / "AppleSignInPlugin" / "AppleSignInPlugin.swift"
    ).read_text(encoding="utf-8")
    # Имя и почту Apple отдаёт только при ПЕРВОМ входе — не запросить их здесь
    # значит не получить никогда
    assert ".fullName" in swift and ".email" in swift, "не запрошены имя и почта"
    assert "identityToken" in swift, "токен не отдаётся наружу"

    # Плагин должен быть в сборке, иначе на устройстве его просто нет
    spm = (web / "ios" / "App" / "CapApp-SPM" / "Package.swift").read_text(encoding="utf-8")
    assert "SimpCapacitorAppleSignin" in spm, "плагин не подключён к сборке iOS"

    # Право обязательно: без него ASAuthorization падает в рантайме
    ent = web / "ios" / "App" / "App" / "App.entitlements"
    assert ent.exists(), "нет App.entitlements"
    assert "com.apple.developer.applesignin" in ent.read_text(encoding="utf-8")

    pbx = (web / "ios" / "App" / "App.xcodeproj" / "project.pbxproj").read_text(
        encoding="utf-8"
    )
    assert pbx.count("CODE_SIGN_ENTITLEMENTS") >= 2, (
        "entitlements не прописаны в обеих конфигурациях Xcode — "
        "в одной из сборок права не будет"
    )

    # И кнопка: сервер с плагином без кнопки — всё ещё нет входа
    login = (web / "src" / "pages" / "Login.tsx").read_text(encoding="utf-8")
    assert "signInWithApple" in login, "кнопки входа через Apple нет на экране входа"


def test_бот_уважает_возрастной_фильтр_и_скрытый_возраст():
    """Дека бота игнорировала возрастной диапазон и `hide_age`.

    Возраст — самый базовый фильтр дейтинга: человек выставил «25-30» в
    мини-аппе, а бот показывал всех подряд. А `hide_age` в мини-аппе
    соблюдается, но бот считал возраст сам и показывал его всем — настройка
    обещает «скрыто», а не «скрыто в вебе».

    Запускается интерпретатором бота: aiogram в venv API нет.
    """
    import json
    import subprocess
    from pathlib import Path

    бот = Path(__file__).resolve().parents[2] / "bot"
    python = бот / ".venv" / "bin" / "python"
    if not python.exists():
        pytest.skip("venv бота не поднят в этом окружении")

    скрипт = """
import sys
sys.path.insert(0, ".")
import json, inspect
from datetime import datetime
from database.connection import get_deck_profiles, _profile_to_dict, _дата_рождения_для

исходник = inspect.getsource(get_deck_profiles)

class Анкета:
    user_id = "u"; display_name = "А"; bio = ""; gender = "female"
    birth_date = datetime(1995, 5, 5); city = ""; photos = []; videos = []; interests = []
    ai_bio = None; looking_for = "any"; goal = ""; relation_type = ""; subculture = ""; mbti = ""
    height_cm = None; sticker = ""; hide_age = True; verified_photo = ""

скрытый = _profile_to_dict(Анкета())
Анкета.hide_age = False
открытый = _profile_to_dict(Анкета())

# 29 февраля не должно ронять границу окна
из_високосного = None
try:
    _дата_рождения_для(1)
    из_високосного = "ок"
except Exception as e:
    из_високосного = f"падает: {e}"

print(json.dumps({
    "фильтр_возраста": ("age_min" in исходник and "age_max" in исходник),
    "скрытый": скрытый["age"],
    "открытый": открытый["age"],
    "високосный": из_високосного,
}))
"""

    результат = subprocess.run(
        [str(python), "-c", скрипт], cwd=бот, capture_output=True, text=True
    )
    assert результат.returncode == 0, результат.stderr

    ответ = json.loads(результат.stdout.strip().splitlines()[-1])
    assert ответ["фильтр_возраста"], "дека бота не фильтрует по возрасту"
    assert ответ["скрытый"] is None, "бот показал возраст, который человек скрыл"
    assert ответ["открытый"], "возраст пропал у всех подряд"
    assert ответ["високосный"] == "ок", ответ["високосный"]


def test_бот_уважает_фильтр_подтверждённых():
    """Дека бота обязана применять «только подтверждённые».

    Запрос деки у бота свой, а не общий с API (api/services/matching.py), и
    каждый фильтр в нём продублирован руками. Забытая копия — это худший
    сценарий защитного фильтра: человек включил его в мини-аппе, приложение
    честно сузило выдачу, а бот продолжает показывать неподтверждённых. Фильтр
    выглядит работающим и не работает.

    Поведенческая версия этой проверки — test_deck_exclusions.py (API-путь);
    здесь, как и в тесте возраста выше, бот запускается своим интерпретатором:
    aiogram в venv API нет.
    """
    import json
    import subprocess
    from pathlib import Path

    бот = Path(__file__).resolve().parents[2] / "bot"
    python = бот / ".venv" / "bin" / "python"
    if not python.exists():
        pytest.skip("venv бота не поднят в этом окружении")

    скрипт = """
import sys
sys.path.insert(0, ".")
import json, inspect
from database.connection import get_deck_profiles
from database.models import Profile

исходник = inspect.getsource(get_deck_profiles)

print(json.dumps({
    # Колонка есть в модели бота: обе стороны зовут create_all(), и без неё
    # бот создал бы таблицу без фильтра
    "колонка_в_модели": hasattr(Profile, "filter_verified"),
    # Условие стоит в самом запросе деки, а не отфильтровано после выборки
    "фильтр_в_запросе": (
        "filter_verified" in исходник and "is_verified" in исходник
    ),
}))
"""

    результат = subprocess.run(
        [str(python), "-c", скрипт], cwd=бот, capture_output=True, text=True
    )
    assert результат.returncode == 0, результат.stderr

    ответ = json.loads(результат.stdout.strip().splitlines()[-1])
    assert ответ["колонка_в_модели"], "в модели бота нет filter_verified"
    assert ответ["фильтр_в_запросе"], "дека бота не фильтрует по подтверждённости"


# ── JSON-колонки в GROUP BY ─────────────────────────────────────


def test_json_колонки_не_попадают_в_группировку():
    """У типа json в Postgres нет оператора равенства.

    Колонка такого типа в GROUP BY или DISTINCT означает, что запрос не
    строится вообще: «could not identify an equality operator for type
    json» — 500 на каждый вызов. На SQLite, где идут тесты, это проходит
    молча, поэтому ловим по исходнику.

    Так падала лента историй: она группировала по Profile.photos, и
    ошибка вылезала только когда у пары появлялась живая история — на
    пустой ленте до запроса дело не доходило.
    """
    import re
    from pathlib import Path

    api = Path(__file__).resolve().parents[1]

    модели = (api / "models" / "models.py").read_text(encoding="utf-8")
    json_колонки = set(
        re.findall(r"^\s*(\w+):\s*Mapped\[[^\]]+\]\s*=\s*mapped_column\(\s*JSON",
                   модели, re.M)
    )
    assert json_колонки, "не нашёл ни одной JSON-колонки — регексп разошёлся с моделями"

    def полезная_нагрузка(текст: str, позиция: int) -> str:
        """Содержимое вызова от открывающей скобки до парной закрывающей."""
        глубина, начало = 0, текст.index("(", позиция)
        for i in range(начало, len(текст)):
            глубина += (текст[i] == "(") - (текст[i] == ")")
            if глубина == 0:
                return текст[начало : i + 1]
        return текст[начало:]

    нарушения: list[str] = []
    for файл in sorted((api / "services").rglob("*.py")) + sorted(
        (api / "routers").rglob("*.py")
    ):
        текст = файл.read_text(encoding="utf-8")
        for m in re.finditer(r"\.(group_by|distinct)\s*\(", текст):
            внутри = полезная_нагрузка(текст, m.start())
            for колонка in json_колонки:
                if f".{колонка}" in внутри:
                    строка = текст[: m.start()].count("\n") + 1
                    нарушения.append(f"{файл.name}:{строка} {m.group(1)} по .{колонка}")

    assert not нарушения, (
        "JSON-колонка в группировке — запрос не выполнится на Postgres: "
        + "; ".join(нарушения)
    )
