"""P0-3 «Рост»: буст новичка и авторасширение тонкой деки.

Буст новичка (PRD §2.4.5) — довести свежую анкету до первого мэтча в первые
сутки: множитель считается на лету от User.created_at и угасает за 24 часа.
Здесь закреплены обещания механики: новичок с фото поднимается, пустышка без
фото — нет, через сутки буст исчезает, платный буст остаётся сильнее, а
жёсткие фильтры (пол, блокировки) буст не обходит — гейт PRD §2.6.

Авторасширение — лечение «пустой деки малого города»: кандидаты за радиусом
distance_max, но до ×3 от него («соседние города»), добирают деку только
когда своих меньше страницы, и всегда хвостом — свой радиус выше.

Шум ранжирования (random.uniform 0–8) в тестах порядка глушится в ноль:
проверяется детерминированная часть формулы, а не удача.
"""
import json
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

import services.matching as matching
from models.models import User, Profile
from services.matching import get_deck_profiles


@pytest.fixture
async def sqlite_session():
    """Изолированная БД в памяти для каждого теста."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(User.metadata.create_all)

    session_cls = async_sessionmaker(engine, expire_on_commit=False)
    async with session_cls() as session:
        yield session

    await engine.dispose()


@pytest.fixture
def без_шума(monkeypatch):
    """Глушит случайную добавку 0–8 в _rank: порядок решает только формула."""
    monkeypatch.setattr(matching.random, "uniform", lambda a, b: 0.0)


async def _анкета(
    session,
    user_id: str,
    имя: str,
    *,
    возраст_аккаунта_ч: float = 72.0,
    фото: bool = True,
    интересы: list | None = None,
    пол: str = "male",
    ищет: str = "any",
    широта: float | None = None,
    долгота: float | None = None,
    радиус: int = 100,
    буст_до: datetime | None = None,
    sample_key: float = 0.5,
):
    """Кандидат с управляемым возрастом аккаунта и геопозицией."""
    session.add(User(
        id=user_id,
        telegram_id=abs(hash(user_id)) % 10**9,
        created_at=datetime.now(timezone.utc) - timedelta(hours=возраст_аккаунта_ч),
    ))
    session.add(Profile(
        user_id=user_id,
        display_name=имя,
        gender=пол,
        looking_for=ищет,
        age_min=18,
        age_max=99,
        sample_key=sample_key,
        photos=[f"{user_id}.jpg"] if фото else [],
        interests=интересы or [],
        latitude=широта,
        longitude=долгота,
        distance_max=радиус,
        boost_until=буст_до,
    ))
    await session.commit()


# ── Буст новичка ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_новичок_с_фото_выше_ветерана(sqlite_session, без_шума):
    """Свежая анкета с фото поднимается над ветераном при прочих равных."""
    await _анкета(sqlite_session, "я", "Зритель")
    await _анкета(sqlite_session, "ветеран", "Ветеран", возраст_аккаунта_ч=72)
    await _анкета(sqlite_session, "новичок", "Новичок", возраст_аккаунта_ч=0)

    дека = await get_deck_profiles(sqlite_session, "я", limit=10)
    assert [p.id for p in дека] == ["новичок", "ветеран"]


@pytest.mark.asyncio
async def test_новичок_без_фото_не_разгоняется(sqlite_session, без_шума):
    """Гард PRD «механика не разгоняет мусор»: пустышке буст не даётся."""
    await _анкета(sqlite_session, "я", "Зритель", интересы=["кино"])
    await _анкета(
        sqlite_session, "ветеран", "Ветеран",
        возраст_аккаунта_ч=72, интересы=["кино"],
    )
    await _анкета(
        sqlite_session, "голый", "Без фото",
        возраст_аккаунта_ч=0, фото=False,
    )

    дека = await get_deck_profiles(sqlite_session, "я", limit=10)
    # Один общий интерес (+10) обязан обгонять новичка без фото (0):
    # был бы буст — новичок набрал бы 15 и вышел вперёд
    assert [p.id for p in дека] == ["ветеран", "голый"]


@pytest.mark.asyncio
async def test_свежесть_угасает_за_сутки(sqlite_session, без_шума):
    """Аккаунту старше 24 часов буст не положен — иначе он вечный."""
    await _анкета(sqlite_session, "я", "Зритель", интересы=["кино"])
    await _анкета(
        sqlite_session, "ветеран", "Ветеран",
        возраст_аккаунта_ч=72, интересы=["кино"],
    )
    await _анкета(sqlite_session, "вчерашний", "Вчерашний", возраст_аккаунта_ч=25)

    дека = await get_deck_profiles(sqlite_session, "я", limit=10)
    assert [p.id for p in дека] == ["ветеран", "вчерашний"]


@pytest.mark.asyncio
async def test_платный_буст_сильнее_новичкового(sqlite_session, без_шума):
    """Купленный буст (×3 + 40) обязан бить бесплатный сигнал (×1.8 + 15)."""
    await _анкета(sqlite_session, "я", "Зритель")
    await _анкета(
        sqlite_session, "платник", "Платник", возраст_аккаунта_ч=72,
        буст_до=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    await _анкета(sqlite_session, "новичок", "Новичок", возраст_аккаунта_ч=0)

    дека = await get_deck_profiles(sqlite_session, "я", limit=10)
    assert [p.id for p in дека] == ["платник", "новичок"]


@pytest.mark.asyncio
async def test_буст_новичка_не_обходит_жёсткие_фильтры(sqlite_session, без_шума):
    """Гейт PRD §2.6: ни один множитель не протаскивает отфильтрованное.

    Зрительница ищет женщин — свежайший новичок-мужчина в деку не попадает,
    какой бы высокий буст ему ни полагался.
    """
    await _анкета(sqlite_session, "я", "Зрительница", пол="female", ищет="female")
    await _анкета(
        sqlite_session, "новичок", "Новичок", возраст_аккаунта_ч=0, пол="male",
    )
    await _анкета(
        sqlite_session, "кандидатка", "Кандидатка",
        возраст_аккаунта_ч=72, пол="female",
    )

    дека = await get_deck_profiles(sqlite_session, "я", limit=10)
    assert [p.id for p in дека] == ["кандидатка"]


# ── Авторасширение тонкой деки ───────────────────────────────────
#
# Координаты вдоль одного меридиана: градус широты ≈ 111 км, дистанции
# управляются смещением широты. Радиус зрителя 10 км, порог соседа ×3 = 30.

МОСКВА = (55.75, 37.62)


@pytest.mark.asyncio
async def test_тонкая_дека_добирается_соседями(sqlite_session, без_шума):
    """Своих меньше страницы — добор из соседних городов, хвостом и честно."""
    await _анкета(
        sqlite_session, "я", "Зритель",
        широта=МОСКВА[0], долгота=МОСКВА[1], радиус=10,
    )
    # ~4.4 км — свой; ~24 км — сосед (>10, ≤30); ~205 км — не сосед
    await _анкета(
        sqlite_session, "свой", "Свой",
        широта=МОСКВА[0] + 0.04, долгота=МОСКВА[1],
    )
    await _анкета(
        sqlite_session, "сосед", "Сосед",
        широта=МОСКВА[0] + 0.22, долгота=МОСКВА[1],
    )
    await _анкета(
        sqlite_session, "дальний", "Дальний",
        широта=МОСКВА[0] + 1.85, долгота=МОСКВА[1],
    )

    дека = await get_deck_profiles(sqlite_session, "я", limit=10)
    assert [p.id for p in дека] == ["свой", "сосед"], (
        "свой радиус всегда выше добора, дальний не сосед"
    )
    # Дистанция на карточке соседа честная — человек видит, что это не рядом
    сосед = next(p for p in дека if p.id == "сосед")
    assert сосед.distance and сосед.distance > 10


@pytest.mark.asyncio
async def test_полной_деке_соседи_не_нужны(sqlite_session, без_шума):
    """Пока своих хватает на страницу, за радиус дека не выходит."""
    await _анкета(
        sqlite_session, "я", "Зритель",
        широта=МОСКВА[0], долгота=МОСКВА[1], радиус=10,
    )
    for i in range(3):
        await _анкета(
            sqlite_session, f"свой{i}", f"Свой {i}",
            широта=МОСКВА[0] + 0.04, долгота=МОСКВА[1],
            sample_key=0.1 * (i + 1),
        )
    await _анкета(
        sqlite_session, "сосед", "Сосед",
        широта=МОСКВА[0] + 0.22, долгота=МОСКВА[1],
    )

    дека = await get_deck_profiles(sqlite_session, "я", limit=2)
    assert len(дека) == 2
    assert all(p.id.startswith("свой") for p in дека)


# ── Бот: та же механика на своей поверхности ─────────────────────

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


def test_бот_дека_поднимает_новичка():
    """Дека бота ранжируется общими интересами; у всех кандидатов их ноль —
    решать обязана свежесть: новичок с фото первым, пустышке буст не даётся.
    Настоящая бот-SQLite через подмену глобальной фабрики, как в
    test_analytics."""
    итог = _в_боте("""
import asyncio, json
from datetime import datetime, timedelta, timezone

async def main():
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
    from sqlalchemy.pool import StaticPool
    import database.connection as conn
    from database.models import Base, User, Profile

    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as c:
        await c.run_sync(Base.metadata.create_all)
    conn.async_session_factory = async_sessionmaker(engine, expire_on_commit=False)

    now = datetime.now(timezone.utc)
    анкеты = [
        ("я", now - timedelta(days=3), ["me.jpg"]),
        ("ветеран", now - timedelta(days=3), ["v.jpg"]),
        ("новичок", now, ["n.jpg"]),
        ("голый", now, []),
    ]
    async with conn.async_session_factory() as s:
        for i, (uid, создан, фото) in enumerate(анкеты):
            s.add(User(id=uid, telegram_id=i + 1, created_at=создан))
            s.add(Profile(
                user_id=uid, display_name=uid.title(), gender="other",
                looking_for="any", age_min=18, age_max=99,
                sample_key=0.2 * (i + 1), photos=фото, interests=[],
            ))
        await s.commit()

    дека = await conn.get_deck_profiles("я", limit=5)
    print(json.dumps({"порядок": [p["user_id"] for p in дека]}, ensure_ascii=False))

asyncio.run(main())
""")
    порядок = итог["порядок"]
    assert set(порядок) == {"ветеран", "новичок", "голый"}
    assert порядок[0] == "новичок", "свежий с фото обязан идти первым"
