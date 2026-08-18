"""Каждая платная возможность из `FEATURE_MIN_TIER` действительно закрыта.

Дыра в Таро появилась не из-за сложной логики, а из-за того, что таблицу
возможностей никто не сверял с кодом целиком: строка `"tarot_spreads": PLUS`
в линейке была, перк в витрине был, а роутер отдавал расклады всем. Здесь
таблица проверяется списком, а не по одной фиче: добавил строку в
`FEATURE_MIN_TIER` — обязан добавить и место, которое её спрашивает.

Фикстуры повторяют `живая_база`/`клиент` из `test_mimolet_features.py`: буст
пишет в БД и берёт суточную блокировку, поэтому подменённой сессией здесь не
обойтись. Имена уровней в проверках берём из линейки, а не словом — фичи
между уровнями уже переезжали.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


@pytest.fixture
async def живая_база(tmp_path):
    """Настоящая БД: платящая Аня и бесплатный Боря."""
    from models.models import Base, Profile, Subscription, User

    файл = tmp_path / "gates.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{файл}")
    async with engine.begin() as c:
        await c.run_sync(Base.metadata.create_all)

    Session = async_sessionmaker(engine, expire_on_commit=False)

    аня, боря = str(uuid.uuid4()), str(uuid.uuid4())
    async with Session() as s:
        for uid, имя, пол, tg in ((аня, "Аня", "female", 1), (боря, "Боря", "male", 2)):
            s.add(User(
                id=uid, telegram_id=tg, role="user",
                last_seen_at=datetime.now(timezone.utc),
            ))
            s.add(Profile(
                user_id=uid, display_name=имя, gender=пол,
                birth_date=datetime(1997, 3, 3, tzinfo=timezone.utc),
                city="Москва", photos=["https://x/1.jpg"],
                interests=["кино"], looking_for="any",
            ))
        # Верхний уровень: на Ане проверяем, что гейт не сломал саму функцию
        s.add(Subscription(
            user_id=аня, plan="aurora",
            expires_at=datetime.now(timezone.utc) + timedelta(days=30),
        ))
        await s.commit()

    yield {"engine": engine, "Session": Session, "аня": аня, "боря": боря}
    await engine.dispose()


@pytest.fixture
async def клиент(app, живая_база, monkeypatch):
    """Клиент с живой БД. `от_имени` переключает текущего пользователя."""
    from database.connection import get_session
    from middleware.auth import get_current_user
    from models.models import User
    import routers.profiles as profiles_mod
    import services.quotas as quotas_mod

    Session = живая_база["Session"]

    # pg_advisory_xact_lock есть только в Postgres, а тест идёт на SQLite
    for мод in (profiles_mod, quotas_mod):
        настоящий = мод.sa_text
        монк = (lambda н: lambda sql: н("SELECT 1") if "advisory" in sql else н(sql))(настоящий)
        monkeypatch.setattr(мод, "sa_text", монк)

    текущий = {"id": живая_база["боря"]}

    async def _sess():
        async with Session() as s:
            try:
                yield s
                await s.commit()
            except Exception:
                await s.rollback()
                raise

    async def _user():
        async with Session() as s:
            return (
                await s.execute(select(User).where(User.id == текущий["id"]))
            ).scalar_one()

    было = {
        get_session: app.dependency_overrides.get(get_session),
        get_current_user: app.dependency_overrides.get(get_current_user),
    }
    app.dependency_overrides[get_session] = _sess
    app.dependency_overrides[get_current_user] = _user
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as c:
            c.от_имени = lambda uid: текущий.update(id=uid)  # type: ignore[attr-defined]
            yield c
    finally:
        # app — session-scoped: возвращаем ровно то, что было до нас
        for ключ, значение in было.items():
            if значение is None:
                app.dependency_overrides.pop(ключ, None)
            else:
                app.dependency_overrides[ключ] = значение


# ════════════════════════════════════════════════════════════════
#  Буст: право проверялось по числу включений, а не по таблице
# ════════════════════════════════════════════════════════════════

async def test_бесплатному_буст_закрыт(клиент, живая_база):
    """403 с именем уровня из линейки, а не «доступен в Plus» словом."""
    from services.plans import FEATURE_MIN_TIER, TIERS

    клиент.от_имени(живая_база["боря"])
    r = await клиент.post("/api/profiles/me/boost")
    assert r.status_code == 403, r.text
    assert TIERS[FEATURE_MIN_TIER["deck_boost"]].name in r.json()["detail"]


async def test_подписчику_буст_работает(клиент, живая_база):
    """Гейт не должен ломать саму функцию: на платном уровне буст включается."""
    клиент.от_имени(живая_база["аня"])
    r = await клиент.post("/api/profiles/me/boost")
    assert r.status_code == 200, r.text
    assert r.json()["active"] is True


async def test_буст_сообщает_нужный_уровень_бесплатному(клиент, живая_база):
    """Состояние буста открыто всем — это крючок, как карта дня в Таро.

    Имя уровня приходит с сервера: без него клиент писал бы «доступен в Plus»
    словом и соврал бы после переноса фичи (web/src/components/SwipeDeck.tsx).
    """
    from services.plans import FEATURE_MIN_TIER, TIERS

    клиент.от_имени(живая_база["боря"])
    r = await клиент.get("/api/profiles/me/boost")
    assert r.status_code == 200, r.text
    тело = r.json()
    assert тело["per_day"] == 0
    assert тело["required_tier_name"] == TIERS[FEATURE_MIN_TIER["deck_boost"]].name


async def test_право_на_буст_не_выводится_из_числа_включений(клиент, живая_база, monkeypatch):
    """Гейт спрашивает таблицу возможностей, а не `BOOSTS_PER_DAY`.

    Раньше «нельзя» означало `per_day == 0`, то есть право выводилось из
    квоты. Дай бесплатному один пробный буст — и платная фича открылась бы
    всем, хотя в `FEATURE_MIN_TIER` она осталась платной.
    """
    import routers.profiles as profiles_mod

    monkeypatch.setattr(profiles_mod, "boosts_per_day", lambda tier: 3)

    клиент.от_имени(живая_база["боря"])
    r = await клиент.post("/api/profiles/me/boost")
    assert r.status_code == 403, (
        f"квота открыла платную фичу бесплатному: {r.status_code} {r.text}"
    )


# ════════════════════════════════════════════════════════════════
#  Инкогнито: гейт спрашивал «есть ли подписка вообще»
# ════════════════════════════════════════════════════════════════

async def test_бесплатному_инкогнито_закрыто(клиент, живая_база):
    from services.plans import FEATURE_MIN_TIER, TIERS

    клиент.от_имени(живая_база["боря"])
    r = await клиент.patch("/api/profiles/me", json={"is_incognito": True})
    assert r.status_code == 403, r.text
    assert TIERS[FEATURE_MIN_TIER["incognito"]].name in r.json()["detail"]


async def test_выключить_инкогнито_может_любой(клиент, живая_база):
    """Приватность обратно не запирается: выключение — не платное действие."""
    клиент.от_имени(живая_база["боря"])
    r = await клиент.patch("/api/profiles/me", json={"is_incognito": False})
    assert r.status_code == 200, r.text
    assert r.json()["is_incognito"] is False


async def test_подписчику_инкогнито_включается(клиент, живая_база):
    клиент.от_имени(живая_база["аня"])
    r = await клиент.patch("/api/profiles/me", json={"is_incognito": True})
    assert r.status_code == 200, r.text
    assert r.json()["is_incognito"] is True


async def test_испорченный_уровень_не_открывает_инкогнито(клиент, живая_база):
    """Гейт шёл через `is_premium` — это `plan != "free"`, а не уровень.

    Запись с чужим или испорченным значением уровня проходила проверку
    (`is_premium` — да), хотя `current_tier` считает такой уровень
    бесплатным. Ровно этот разъезд и открывал платное задаром.
    """
    from models.models import Subscription

    боря = живая_база["боря"]
    async with живая_база["Session"]() as s:
        s.add(Subscription(
            user_id=боря, plan="премиум-вип",
            expires_at=datetime.now(timezone.utc) + timedelta(days=30),
        ))
        await s.commit()

    клиент.от_имени(боря)
    r = await клиент.patch("/api/profiles/me", json={"is_incognito": True})
    assert r.status_code == 403, (
        f"мусор в plan открыл платную фичу: {r.status_code} {r.text}"
    )


# ════════════════════════════════════════════════════════════════
#  Сама таблица: строка без места, которое её спрашивает
# ════════════════════════════════════════════════════════════════

def test_каждая_фича_из_таблицы_где_то_проверяется():
    """Строка в `FEATURE_MIN_TIER` без кода, который её спрашивает, — это и
    есть дыра Таро: возможность объявлена платной и отдаётся даром.

    Проверяем по исходникам, а не запросами: эндпоинтов у фичи может быть
    несколько (`tg_channel` — и чтение, и запись), и перечислять их руками
    значило бы вести второй такой же список.
    """
    from pathlib import Path

    from services.plans import FEATURE_MIN_TIER

    корень = Path(__file__).resolve().parents[1]
    исходники = {
        путь: путь.read_text(encoding="utf-8")
        for каталог in ("routers", "services", "middleware")
        for путь in (корень / каталог).rglob("*.py")
        if путь.name != "plans.py"
    }

    for фича in FEATURE_MIN_TIER:
        места = [п.name for п, текст in исходники.items() if f'"{фича}"' in текст]
        assert места, (
            f'"{фича}" объявлена платной в FEATURE_MIN_TIER, но её никто не '
            "спрашивает — значит, она отдаётся бесплатно"
        )


def test_гейты_фич_совпадают_в_боте_и_api():
    """Бот держит копию таблицы — импортировать код API он не может.

    Разойдись они, бот показывал бы замок там, где мини-апп открывает (или
    наоборот), и человек покупал бы уровень за то, что уже получил.
    """
    import ast
    from pathlib import Path

    from services.plans import FEATURE_MIN_TIER

    бот = (
        Path(__file__).resolve().parents[2] / "bot" / "services" / "plans.py"
    ).read_text(encoding="utf-8")
    дерево = ast.parse(бот)

    таблица_бота = {}
    for узел in ast.walk(дерево):
        if not isinstance(узел, ast.AnnAssign):
            continue
        if getattr(узел.target, "id", "") != "FEATURE_MIN_TIER":
            continue
        assert isinstance(узел.value, ast.Dict)
        for ключ, значение in zip(узел.value.keys, узел.value.values):
            # Уровни передаются константами TIER_PLUS/TIER_ULTRA/TIER_AURORA
            таблица_бота[ключ.value] = значение.id.removeprefix("TIER_").lower()

    assert таблица_бота, "в боте нет FEATURE_MIN_TIER — гейты снова разъедутся"
    assert таблица_бота == FEATURE_MIN_TIER, (
        f"расходятся: {set(таблица_бота.items()) ^ set(FEATURE_MIN_TIER.items())}"
    )


def test_бот_не_пишет_имена_уровней_словом():
    """Имя тарифа в тексте бота — из линейки, а не литералом.

    Пока «Plus» стоял словом в `texts.py` и `keyboards.py`, перенос фичи на
    другой уровень оставлял бота продавать старый: человек платил за Plus то,
    что уже отдали Ultra.
    """
    from pathlib import Path

    бот = Path(__file__).resolve().parents[2] / "bot"
    for файл in ("texts.py", "keyboards.py", "handlers/dating.py"):
        текст = (бот / файл).read_text(encoding="utf-8")
        # Строки кода без комментариев: в комментариях имя уровня уместно
        код = "\n".join(
            с for с in текст.splitlines() if not с.lstrip().startswith("#")
        )
        for уровень in ("Plus", "Ultra", "Aurora"):
            assert f"в {уровень}" not in код and f"на {уровень}" not in код, (
                f"{файл}: имя уровня {уровень} вписано словом — возьмите его "
                "из TIER_NAMES через имя_уровня_для()"
            )


def test_в_боте_есть_кнопка_покупки_каждого_платного_уровня():
    """Витрина бота собирается по линейке, а не перечислением.

    Aurora появилась в линейке, но `tiers_kb()` перечисляла два уровня
    руками — верхний тариф нельзя было купить нигде, кроме нативной сборки
    iOS, хотя веб и мини-апп за оплатой уходят именно в бота.
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
import json
from handlers.premium import tiers_kb
from services.plans import TIER_ORDER

kb = tiers_kb()
print(json.dumps({
    "callbacks": [b.callback_data for row in kb.inline_keyboard for b in row],
    "тексты": [b.text for row in kb.inline_keyboard for b in row],
    "уровни": list(TIER_ORDER),
}))
"""
    результат = subprocess.run(
        [str(python), "-c", скрипт], cwd=бот, capture_output=True, text=True
    )
    assert результат.returncode == 0, результат.stderr[-500:]

    ответ = json.loads(результат.stdout.strip().splitlines()[-1])
    for уровень in ответ["уровни"][1:]:
        assert f"tier:{уровень}" in ответ["callbacks"], (
            f"{уровень} нельзя купить из бота: кнопки нет"
        )
    # Бесплатный уровень не продаётся — покупать в нём нечего
    assert f"tier:{ответ['уровни'][0]}" not in ответ["callbacks"]


def test_описание_счёта_без_значков_перков():
    """В описание счёта Stars значки не уезжают.

    Значки срезались перечислением (`lstrip("👀🥷⭐🚀✨🚪 ")`), и каждый новый
    перк надо было дописывать в набор. Перки Aurora (✉️ 📣 📈) в него не
    попали и уходили в счёт вместе со значком.
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
import json
from handlers.premium import _без_значка
from services.plans import TIER_PERKS

print(json.dumps({
    t: [_без_значка(p) for p in perks] for t, perks in TIER_PERKS.items()
}))
"""
    результат = subprocess.run(
        [str(python), "-c", скрипт], cwd=бот, capture_output=True, text=True
    )
    assert результат.returncode == 0, результат.stderr[-500:]

    по_уровням = json.loads(результат.stdout.strip().splitlines()[-1])
    assert по_уровням, "перков не оказалось вовсе"
    for уровень, перки in по_уровням.items():
        for перк in перки:
            assert перк, f"{уровень}: перк срезан целиком"
            assert перк[0].isalnum(), f"{уровень}: значок уехал в счёт — {перк!r}"


# ════════════════════════════════════════════════════════════════
#  Приоритет в выдаче: словам в витрине должны отвечать числа
# ════════════════════════════════════════════════════════════════

async def test_приоритет_в_деке_растёт_с_уровнем(tmp_path, monkeypatch):
    """«Приоритет в выдаче» (Ultra) и «Максимальный» (Aurora) — разные числа.

    Раньше дека спрашивала `Subscription.plan != "free"` и давала всем платным
    одинаковые +25: Plus получал приоритет, которого в его перках нет, а
    Aurora — ровно столько же, сколько вдвое более дешёвый Ultra, хотя
    продаётся именно «максимальным».

    Проверяем через настоящую сортировку, а не через таблицу констант: таблицу
    можно завести и не подключить — так и было.
    """
    import services.matching as m
    from models.models import Base, Profile, Subscription, User

    файл = tmp_path / "prio.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{файл}")
    async with engine.begin() as c:
        await c.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False)

    # Шум сортировки убираем: он существует, чтобы дека не была
    # детерминированной, но здесь проверяется именно вклад уровня
    monkeypatch.setattr(m.random, "uniform", lambda a, b: 0.0)

    смотрящий = str(uuid.uuid4())
    уровни = {"free": None, "plus": "plus", "ultra": "ultra", "aurora": "aurora"}
    ids: dict[str, str] = {}

    async with Session() as s:
        s.add(User(id=смотрящий, telegram_id=100, role="user"))
        s.add(Profile(
            user_id=смотрящий, display_name="Смотрящий", gender="male",
            birth_date=datetime(1995, 1, 1, tzinfo=timezone.utc),
            city="Москва", photos=["https://x/0.jpg"], interests=[],
            looking_for="any",
        ))
        for i, (метка, plan) in enumerate(уровни.items(), start=1):
            uid = str(uuid.uuid4())
            ids[метка] = uid
            s.add(User(id=uid, telegram_id=200 + i, role="user"))
            # Анкеты одинаковые во всём, кроме подписки: иначе разницу в
            # порядке могли бы дать интересы, город или расстояние
            s.add(Profile(
                user_id=uid, display_name=f"Кандидат {метка}", gender="female",
                birth_date=datetime(1996, 1, 1, tzinfo=timezone.utc),
                city="Тверь", photos=[f"https://x/{i}.jpg"], interests=[],
                looking_for="any",
            ))
            if plan:
                s.add(Subscription(
                    user_id=uid, plan=plan,
                    expires_at=datetime.now(timezone.utc) + timedelta(days=30),
                ))
        await s.commit()

    async with Session() as s:
        дека = await m.get_deck_profiles(s, смотрящий, limit=10)

    порядок = [p.id for p in дека]
    место = {метка: порядок.index(uid) for метка, uid in ids.items()}

    assert место["aurora"] < место["ultra"], (
        "Aurora продаёт «максимальный приоритет», а стоит не выше Ultra"
    )
    assert место["ultra"] < место["plus"], (
        "«Приоритет в выдаче» продаётся с Ultra — Plus не должен его обгонять"
    )
    # У Plus приоритета в перках нет: с бесплатным его равенство и ожидается,
    # поэтому сравниваем не порядок (он при равных очках произволен), а вклад
    assert m.deck_priority("plus") == m.deck_priority("free") == 0, (
        "Plus получает приоритет, которого нет в его перках"
    )

    await engine.dispose()


def test_старая_запись_premium_считается_plus_и_в_деке():
    """Записи до линейки (`plan="premium"`) разбираются одинаково везде.

    Дека читала уровни своим запросом и про `"premium"` не знала вовсе, а
    гейты фич знали: один и тот же человек считался платным для одних мест и
    бесплатным для других.
    """
    from services.plans import TIER_PLUS, deck_priority, tier_from_plan

    assert tier_from_plan("premium") == TIER_PLUS
    assert tier_from_plan("совсем не уровень") == "free"
    assert tier_from_plan(None) == "free"
    # Испорченное значение не должно давать приоритет
    assert deck_priority(tier_from_plan("мусор")) == 0


# ════════════════════════════════════════════════════════════════
#  Витрина и лимиты: число в тексте — это обещание, за него платят
# ════════════════════════════════════════════════════════════════

def _таблица_бота(имя: str) -> dict[str, object]:
    """Словарь-константу из `bot/services/plans.py` — разбором, а не импортом.

    Бот живёт в отдельном venv и не может импортировать код API (и наоборот),
    поэтому таблицы у него — копии, набитые руками. Читаем их AST-разбором:
    так копия сверяется с оригиналом, не поднимая процесс бота.
    """
    import ast
    from pathlib import Path

    файл = Path(__file__).resolve().parents[2] / "bot" / "services" / "plans.py"
    дерево = ast.parse(файл.read_text(encoding="utf-8"))

    #: Значение в таблице может быть не литералом, а ссылкой на константу того
    #: же файла (`UNLIMITED`), — на имени `literal_eval` падает. Собираем
    #: простые константы модуля и подставляем их: сверять надо настоящее число
    #: бота, а не факт, что оно записано цифрой.
    константы: dict[str, object] = {}
    for узел in дерево.body:
        цели: list[ast.expr] = []
        if isinstance(узел, ast.Assign):
            цели = list(узел.targets)
        elif isinstance(узел, ast.AnnAssign) and узел.value is not None:
            цели = [узел.target]
        for цель in цели:
            if isinstance(цель, ast.Name):
                try:
                    константы[цель.id] = ast.literal_eval(узел.value)
                except (ValueError, TypeError):
                    pass

    def значение(узел_значения: ast.expr) -> object:
        if isinstance(узел_значения, ast.Name):
            assert узел_значения.id in константы, (
                f"{имя}: значение ссылается на {узел_значения.id}, а такой "
                "константы в bot/services/plans.py нет"
            )
            return константы[узел_значения.id]
        return ast.literal_eval(узел_значения)

    for узел in ast.walk(дерево):
        if not isinstance(узел, ast.AnnAssign):
            continue
        if getattr(узел.target, "id", "") != имя:
            continue
        assert isinstance(узел.value, ast.Dict), f"{имя} в боте — не словарь"
        # Ключи — константы уровней (TIER_PLUS), значения — числа или кортежи
        return {
            ключ.id.removeprefix("TIER_").lower(): значение(знач)
            for ключ, знач in zip(узел.value.keys, узел.value.values)
        }
    raise AssertionError(f"в bot/services/plans.py нет {имя}")


def test_суточный_лимит_писем_совпадает_в_боте_и_api():
    """Копия `DIRECT_MESSAGES_PER_DAY` в боте равна оригиналу.

    Цены и гейты фич уже сверяются (`test_тарифы_совпадают_в_боте_и_api`,
    `test_гейты_фич_совпадают_в_боте_и_api`), а этот лимит — нет, хотя он
    ровно того же сорта: число, за которое заплачено. Разойдись копии, бот
    обещал бы одно количество писем, а API отдавал другое — и отказ пришёл бы
    уже после оплаты.
    """
    from services.plans import DIRECT_MESSAGES_PER_DAY

    у_бота = _таблица_бота("DIRECT_MESSAGES_PER_DAY")
    assert у_бота == DIRECT_MESSAGES_PER_DAY, (
        f"расходятся: {set(у_бота.items()) ^ set(DIRECT_MESSAGES_PER_DAY.items())}"
    )


def test_перки_в_витрине_бота_дословно_равны_перкам_api():
    """Список возможностей уровня в боте — тот же, что в мини-аппе.

    Человек сравнивает уровни в боте, а покупает в мини-аппе: расхождение
    читается как обман, даже если это просто забытая строка. Значок в начале
    перка — единственное допустимое отличие, его бот рисует сам.
    """
    import re

    from services.plans import TIERS

    у_бота = _таблица_бота("TIER_PERKS")
    assert у_бота, "в боте нет TIER_PERKS — витрина разъедется"

    for уровень, перки in у_бота.items():
        assert уровень in TIERS, f"уровня {уровень} нет в линейке API"
        без_значков = tuple(re.sub(r"^\W+", "", п) for п in перки)
        assert без_значков == TIERS[уровень].perks, (
            f"{уровень}: витрина бота разошлась с API\n"
            f"  бот: {без_значков}\n"
            f"  api: {TIERS[уровень].perks}"
        )


def test_суточные_лимиты_лайков_и_мэтчей_совпадают_в_боте_и_api():
    """Копии `LIKES_PER_DAY` и `MATCH_VIEWS_PER_DAY` в боте равны оригиналам.

    Это два самых чувствительных числа в продукте: ими продаётся подписка. Бот
    пишет лайки и открывает чаты напрямую через `database/connection.py`, минуя
    API, поэтому у него своя копия лимита. Разойдись копии — бесплатный аккаунт
    получил бы в боте больше, чем в мини-аппе, то есть купленное отдавалось бы
    бесплатно тому, кто просто свайпает в другом клиенте.
    """
    from pathlib import Path

    from services.plans import LIKES_PER_DAY, MATCH_VIEWS_PER_DAY, UNLIMITED

    for имя, оригинал in (
        ("LIKES_PER_DAY", LIKES_PER_DAY),
        ("MATCH_VIEWS_PER_DAY", MATCH_VIEWS_PER_DAY),
    ):
        у_бота = _таблица_бота(имя)
        assert у_бота == оригинал, (
            f"{имя} расходится: {set(у_бота.items()) ^ set(оригинал.items())}"
        )

    # Сентинел безлимита обязан быть отрицательным в обоих сервисах: ноль в
    # этих таблицах читался бы как «нельзя совсем» (так его понимает
    # DIRECT_MESSAGES_PER_DAY), и платный уровень остался бы без лайков
    assert UNLIMITED < 0, "безлимит перестал быть отрицательным"
    текст_бота = (
        Path(__file__).resolve().parents[2] / "bot" / "services" / "plans.py"
    ).read_text(encoding="utf-8")
    assert f"UNLIMITED = {UNLIMITED}" in текст_бота, (
        "в боте другой сентинел безлимита — таблицы совпадут числами, "
        "а смысл разойдётся"
    )


def test_числа_в_витрине_отвечают_настоящим_лимитам():
    """«5 суперлайков в день» в тексте — это ровно то, что отдаёт код.

    Числа живут в двух местах: в таблицах (`TIERS[...].superlikes`,
    `BOOSTS_PER_DAY`, `DIRECT_MESSAGES_PER_DAY`) и словами в перках, которые
    человек читает перед оплатой. Правка таблицы текст не трогает — и наоборот.
    Молчаливое расхождение здесь дороже любого падения: обещание в витрине
    остаётся, а купленного количества уже нет.

    Проверяются перки API; бот привязан к ним `test_перки_в_витрине_бота_...`.
    """
    import re

    from services.plans import (
        TIER_ORDER,
        TIERS,
        boosts_per_day,
        direct_messages_per_day,
        is_unlimited,
        likes_per_day,
        match_views_per_day,
        superlikes_for,
        tier_allows,
        tier_rank,
    )

    неразобранные: list[tuple[str, str]] = []

    for уровень, инфо in TIERS.items():
        for перк in инфо.perks:
            числа = [int(н) for н in re.findall(r"\d+", перк)]

            if "суперлайк" in перк:
                assert числа, f"{уровень}: перк про суперлайки без числа — {перк!r}"
                assert числа[0] == superlikes_for(уровень), (
                    f"{уровень}: витрина обещает {числа[0]} суперлайков, "
                    f"код даёт {superlikes_for(уровень)} — {перк!r}"
                )
                if len(числа) > 1:
                    # «…вместо N» — сравнение с предыдущим уровнем линейки
                    предыдущий = TIER_ORDER[tier_rank(уровень) - 1]
                    assert числа[1] == superlikes_for(предыдущий), (
                        f"{уровень}: «вместо {числа[1]}» — но у {предыдущий} "
                        f"их {superlikes_for(предыдущий)}"
                    )

            elif "буст" in перк.lower():
                # «Буст анкеты раз в день» — цифры нет, «раз» значит один
                обещано = числа[0] if числа else 1
                assert обещано == boosts_per_day(уровень), (
                    f"{уровень}: витрина обещает {обещано} бустов, "
                    f"код даёт {boosts_per_day(уровень)} — {перк!r}"
                )

            elif "исьма без взаимного" in перк:
                assert tier_allows(уровень, "direct_messages"), (
                    f"{уровень}: письма в витрине есть, а гейт их не пускает"
                )
                assert числа, f"{уровень}: перк про письма без числа — {перк!r}"
                assert числа[0] == direct_messages_per_day(уровень), (
                    f"{уровень}: витрина обещает {числа[0]} писем, "
                    f"код даёт {direct_messages_per_day(уровень)} — {перк!r}"
                )

            elif "лайк" in перк.lower() and ("в день" in перк or "ограничени" in перк):
                # Ветка про суперлайки стоит выше, поэтому здесь остаются
                # только перки про обычный суточный лимит лайков
                лимит = likes_per_day(уровень)
                if числа:
                    assert not is_unlimited(лимит), (
                        f"{уровень}: витрина обещает ровно {числа[0]} лайков, "
                        f"а в коде лимита нет вовсе — {перк!r}"
                    )
                    assert числа[0] == лимит, (
                        f"{уровень}: витрина обещает {числа[0]} лайков в сутки, "
                        f"код даёт {лимит} — {перк!r}"
                    )
                else:
                    assert is_unlimited(лимит), (
                        f"{уровень}: витрина обещает лайки без ограничений, "
                        f"а код даёт {лимит} в сутки — {перк!r}"
                    )

            elif "мэтч" in перк.lower():
                лимит = match_views_per_day(уровень)
                if числа:
                    assert not is_unlimited(лимит), (
                        f"{уровень}: витрина обещает ровно {числа[0]} мэтчей, "
                        f"а в коде лимита нет вовсе — {перк!r}"
                    )
                    assert числа[0] == лимит, (
                        f"{уровень}: витрина обещает {числа[0]} мэтчей в сутки, "
                        f"код даёт {лимит} — {перк!r}"
                    )
                else:
                    assert is_unlimited(лимит), (
                        f"{уровень}: витрина обещает все мэтчи, а код даёт "
                        f"{лимит} в сутки — {перк!r}"
                    )

            elif числа:
                неразобранные.append((уровень, перк))

    assert not неразобранные, (
        "в витрине появилось число, которое ни с чем не сверяется — допишите "
        f"правило рядом с остальными: {неразобранные}"
    )


def test_письма_не_обещаны_там_где_их_не_дают():
    """Уровень без права на письма про них и не пишет.

    Обратная сторона предыдущей проверки: там сверялось число у того, кто
    письма продаёт, здесь — молчание у тех, кто не продаёт. Фича уже
    переезжала между уровнями (Plus → Aurora), и перк легко остался бы у
    старого — тот продавал бы отказ.
    """
    from services.plans import TIERS, direct_messages_per_day, tier_allows

    for уровень, инфо in TIERS.items():
        обещаны = any("исьма без взаимного" in п for п in инфо.perks)
        разрешены = tier_allows(уровень, "direct_messages")
        assert обещаны == разрешены, (
            f"{уровень}: в витрине письма {'есть' if обещаны else 'нет'}, "
            f"а гейт их {'пускает' if разрешены else 'не пускает'}"
        )
        if not разрешены:
            assert direct_messages_per_day(уровень) == 0, (
                f"{уровень}: фича закрыта гейтом, но суточный лимит не ноль — "
                "он вернёт письма тому, кому их не продавали"
            )
