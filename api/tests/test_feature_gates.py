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

    Session = живая_база["Session"]

    # pg_advisory_xact_lock есть только в Postgres, а тест идёт на SQLite
    настоящий = profiles_mod.sa_text
    monkeypatch.setattr(
        profiles_mod, "sa_text",
        lambda sql: настоящий("SELECT 1") if "advisory" in sql else настоящий(sql),
    )

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
