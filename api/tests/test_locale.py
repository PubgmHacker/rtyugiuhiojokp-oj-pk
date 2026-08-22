"""Язык интерфейса: выбор на онбординге доезжает до мини-аппа.

Бот спрашивал язык первым же экраном и выбрасывал ответ: он жил в FSM-состоянии
и не переживал ни рестарт бота, ни истечение ключа, а мини-апп о нём не узнавал
вообще никогда — доступа к FSM у него нет. Человек выбирал узбекский и получал
русский интерфейс. Колонка `dating_users.locale` (миграция a1e6f30c74d2) это
закрывает, и здесь проверяется весь её путь на стороне API.

Четыре места, каждое из которых ломается по-своему:

1. `PATCH /api/profiles/me` пишет язык на АККАУНТ. `update_my_profile`
   заканчивается циклом `setattr(profile, key, value)` по всем присланным
   полям — и колонка аккаунта, забытая перед этим циклом, тихо ложится
   атрибутом на объект анкеты: ошибки нет, ответ успешный, в базе ничего.
2. Ответ на PATCH отдаёт сохранённое значение. Без этого клиент, доверяющий
   ответу, откатывал бы выбор на русский сразу после сохранения.
3. Ответ на вход (`_user_to_profile`) несёт язык: мини-апп выбирает его до
   первой отрисовки, и отдельный запрос анкеты успел бы мигнуть русским.
4. Неизвестный код — 422, а не тихая подстановка русского. Клиент с опечаткой
   обязан узнать об этом сразу, иначе он покажет «язык сохранён» и соврёт.

Плюс контракт со списком языков бота: копии в двух деплоях обязаны совпадать.
"""

from __future__ import annotations

import ast
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient

from services import locales as локали

КОРЕНЬ = Path(__file__).resolve().parents[2]
БОТ = КОРЕНЬ / "bot"


# ── Заготовки ───────────────────────────────────────────────────


def _user(язык: str = "ru"):
    """Строка аккаунта. Язык — параметр: он и есть предмет проверки."""
    return SimpleNamespace(
        id="u-me",
        telegram_id=555,
        apple_id=None,
        email=None,
        role="user",
        is_banned=False,
        is_verified=False,
        created_at=datetime.now(timezone.utc),
        phone=None,
        last_seen_at=None,
        locale=язык,
    )


def _profile():
    """Анкета с полями, которые читает `update_my_profile`."""
    return SimpleNamespace(
        user_id="u-me",
        display_name="Боря",
        bio="о себе",
        gender="male",
        birth_date=datetime(1996, 3, 3, tzinfo=timezone.utc),
        city="Казань",
        latitude=None,
        longitude=None,
        photos=[],
        interests=[],
        ai_bio=None,
        goal="",
        relation_type="",
        subculture="",
        mbti="",
        height_cm=None,
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
        filter_height_min=None,
        filter_height_max=None,
        filter_verified=False,
        sample_key=0.5,
        tg_channel="",
    )


class _Result:
    def __init__(self, scalar=None):
        self._scalar = scalar

    def scalar_one_or_none(self):
        return self._scalar

    def scalar(self):
        return self._scalar

    def scalars(self):
        return SimpleNamespace(all=lambda: [])

    def all(self):
        return []

    def one(self):
        return (None, 0)


class _Session:
    """Сессия, отдающая анкету на первый запрос и пустоту на остальные."""

    def __init__(self, профиль):
        self.профиль = профиль
        self.первый = True

    async def execute(self, *_a, **_kw):
        if self.первый:
            self.первый = False
            return _Result(scalar=self.профиль)
        return _Result()

    def add(self, _obj):
        pass

    async def flush(self):
        pass

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


# ── Запись языка ────────────────────────────────────────────────


async def test_язык_ложится_на_аккаунт_а_не_на_анкету(app):
    """Главная ловушка этого обработчика.

    `update_my_profile` заканчивается циклом `setattr(profile, key, value)` по
    всему присланному. Колонка аккаунта, не изъятая перед циклом, ложится
    атрибутом на объект анкеты — Python это позволяет молча, SQLAlchemy такой
    атрибут не сохраняет, и запрос выглядит успешным при пустой базе.
    """
    user, профиль = _user("ru"), _profile()
    async with await _client(app, _Session(профиль), user) as client:
        r = await client.patch("/api/profiles/me", json={"locale": "uz"})

    assert r.status_code == 200, r.text
    assert user.locale == "uz", (
        f"язык не записан на аккаунт (там {user.locale!r}) — выбор человека "
        f"не доедет до базы"
    )
    assert getattr(профиль, "locale", None) is None, (
        "язык лёг атрибутом на анкету: SQLAlchemy его не сохранит, а ответ "
        "будет выглядеть успешным"
    )


async def test_ответ_на_смену_языка_несёт_новый_язык(app):
    """Клиент верит ответу. Отдадим старое значение — он откатит выбор."""
    async with await _client(app, _Session(_profile()), _user("ru")) as client:
        r = await client.patch("/api/profiles/me", json={"locale": "tr"})

    assert r.status_code == 200, r.text
    assert r.json()["locale"] == "tr", (
        f"ответ вернул {r.json().get('locale')!r} вместо сохранённого 'tr' — "
        f"клиент мгновенно откатит язык"
    )


async def test_язык_отдаётся_в_своей_анкете(app):
    """GET /me: по нему мини-апп переключается при обычной загрузке."""
    async with await _client(app, _Session(_profile()), _user("es")) as client:
        r = await client.get("/api/profiles/me")

    assert r.status_code == 200, r.text
    assert r.json()["locale"] == "es"


async def test_анкета_без_профиля_всё_равно_знает_язык(app):
    """Язык живёт на аккаунте — он есть и до создания анкеты.

    Ровно этот случай и есть онбординг: язык выбран на первом экране, анкеты
    ещё нет. Держи мы колонку на `Profile`, здесь бы её и не было.
    """
    async with await _client(app, _Session(None), _user("zh")) as client:
        r = await client.get("/api/profiles/me")

    assert r.status_code == 200, r.text
    assert r.json()["locale"] == "zh", (
        "у человека без анкеты язык потерялся — а это ровно состояние "
        "онбординга, когда язык только что выбран"
    )


async def test_чужой_язык_не_трогается_правкой_анкеты(app):
    """PATCH без поля `locale` язык не сбрасывает.

    `exclude_unset=True` это обеспечивает, но проверка нужна именно здесь:
    любая правка анкеты, обнуляющая язык, вернула бы всех на русский.
    """
    user = _user("id")
    async with await _client(app, _Session(_profile()), user) as client:
        r = await client.patch("/api/profiles/me", json={"city": "Уфа"})

    assert r.status_code == 200, r.text
    assert user.locale == "id", f"язык сбросился на {user.locale!r} правкой города"
    assert r.json()["locale"] == "id"


@pytest.mark.parametrize("мусор", ["klingon", "RU-ru", "", "ru;drop", "russian"])
async def test_неизвестный_язык_отклоняется(app, мусор):
    """422, а не тихая подстановка русского.

    Тихий фолбэк здесь — худший вариант: клиент получает 200, показывает «язык
    сохранён» и врёт человеку. Ошибка обязана быть видна тому, кто её сделал.
    """
    user = _user("ru")
    async with await _client(app, _Session(_profile()), user) as client:
        r = await client.patch("/api/profiles/me", json={"locale": мусор})

    assert r.status_code == 422, (
        f"код {мусор!r} принят с ответом {r.status_code} — клиент решит, что "
        f"язык сменился"
    )
    assert user.locale == "ru", f"мусорный код всё же долетел до аккаунта: {user.locale!r}"


async def test_язык_есть_в_ответе_на_вход():
    """Ответ на вход — единственное место, где язык нужен ДО отрисовки.

    Мини-апп выбирает язык на старте; жди он отдельного запроса анкеты, у всех
    неруссских интерфейс успевал бы мигнуть русским.
    """
    from routers.auth import _user_to_profile

    анкета = _user_to_profile(_user("uz"), None)
    assert анкета.locale == "uz", (
        "ответ на вход не несёт язык — мини-апп откроется на русском и "
        "переключится только вторым запросом"
    )


# ── Контракт со списком языков бота ─────────────────────────────


def _список_из_бота() -> tuple[str, ...]:
    """`ONBOARDING_LOCALES` из bot/texts.py, прочитанный разбором AST.

    Импортировать модуль бота нельзя: у него свой venv (3.12 против 3.14 здесь)
    и свои зависимости. Разбор AST не исполняет код и не требует ничего.
    """
    дерево = ast.parse((БОТ / "texts.py").read_text(encoding="utf-8"))
    for узел in ast.walk(дерево):
        if isinstance(узел, ast.Assign):
            for цель in узел.targets:
                if isinstance(цель, ast.Name) and цель.id == "ONBOARDING_LOCALES":
                    return tuple(ast.literal_eval(узел.value))
    pytest.fail("в bot/texts.py не нашлось ONBOARDING_LOCALES")


def test_списки_языков_api_и_бота_совпадают():
    """Два деплоя, два списка, один продукт.

    API и бот разъезжаются молча: бот нарисует кнопку языка, которого API не
    знает, и человек, нажав её, получит 422 при первой же правке анкеты. Общего
    модуля быть не может — деплои и venv раздельные, — поэтому копии сверяет
    тест.
    """
    из_бота = _список_из_бота()
    assert локали.ЯЗЫКИ == из_бота, (
        f"списки языков разъехались: у API {локали.ЯЗЫКИ}, у бота {из_бота} — "
        f"кнопка лишнего языка вернёт 422 при первой правке анкеты"
    )


def test_язык_по_умолчанию_есть_в_списке():
    """Иначе значение из базы не прошло бы собственную же валидацию."""
    assert локали.ПО_УМОЛЧАНИЮ in локали.ЯЗЫКИ


def test_шаблон_собран_из_списка():
    """Шаблон — производная списка, а не вторая его копия.

    Ручной шаблон разъехался бы с `ЯЗЫКИ` при первом добавленном языке, и
    валидный код получал бы 422.
    """
    import re

    for язык in локали.ЯЗЫКИ:
        assert re.match(локали.ШАБЛОН, язык), f"валидный {язык} не проходит шаблон"
    for мусор in ("klingon", "ru-RU", "", "r", "ruu"):
        assert not re.match(локали.ШАБЛОН, мусор), f"мусор {мусор!r} проходит шаблон"


def test_миграция_совпадает_с_языком_по_умолчанию():
    """`server_default` в миграции и `ПО_УМОЛЧАНИЮ` — одно и то же значение.

    Разъедутся — и у аккаунтов, созданных до колонки, язык окажется не тем,
    который API считает значением по умолчанию.
    """
    миграции = КОРЕНЬ / "api" / "migrations" / "versions"
    (файл,) = list(миграции.glob("a1e6f30c74d2_*.py"))
    текст = файл.read_text(encoding="utf-8")
    assert f"'{локали.ПО_УМОЛЧАНИЮ}'" in текст, (
        f"в миграции нет server_default '{локали.ПО_УМОЛЧАНИЮ}'"
    )
    assert '"locale"' in текст


def test_нормализация_не_пропускает_мусор():
    """Чтение уже сохранённого значения: падать поздно, подставляем умолчание."""
    assert локали.нормализовать("uz") == "uz"
    assert локали.нормализовать("UZ") == "uz"
    assert локали.нормализовать("  tr  ") == "tr"
    assert локали.нормализовать(None) == локали.ПО_УМОЛЧАНИЮ
    assert локали.нормализовать("") == локали.ПО_УМОЛЧАНИЮ
    assert локали.нормализовать("klingon") == локали.ПО_УМОЛЧАНИЮ


# ── Схема базы ──────────────────────────────────────────────────


def test_колонка_есть_в_обеих_моделях():
    """Бот тоже вызывает `create_all()` — схемы обязаны совпадать.

    Стартуй бот первым на пустой базе с моделью без этой колонки, он создал бы
    таблицу без неё, и API падал бы на каждом запросе анкеты.
    """
    from models.models import User as ЮзерAPI

    assert "locale" in ЮзерAPI.__table__.columns, "нет колонки в модели API"

    модель_бота = (БОТ / "database" / "models.py").read_text(encoding="utf-8")
    дерево = ast.parse(модель_бота)
    классы = {
        узел.name: узел for узел in ast.walk(дерево) if isinstance(узел, ast.ClassDef)
    }
    assert "User" in классы, "в моделях бота нет класса User"
    поля = {
        цель.id
        for узел in классы["User"].body
        if isinstance(узел, ast.AnnAssign) and isinstance(цель := узел.target, ast.Name)
    }
    assert "locale" in поля, (
        "в модели бота нет колонки locale — бот, стартовав первым на пустой "
        "базе, создаст таблицу без неё"
    )
