"""Поведенческие проверки: кого дека исключает и почему.

Мутации формы (списком id вместо анти-джойна) умирают на test_query_scale.
Мутации смысла (неправильная колонка, одностороння проверка, пропущенное
условие) здесь. Каждая — это реальный баг: видеть заблокировавшего тебя,
видеть того, кому ты лайкнул, видеть самого себя.
"""
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from models.models import User, Profile, Like, Block
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


async def _создать_пользователя(session, user_id: str, display_name: str):
    """Минимальная анкета: видна в деке, не заблокирована."""
    session.add(User(id=user_id, telegram_id=int(user_id.replace("U", ""))))
    session.add(Profile(
        user_id=user_id,
        display_name=display_name,
        gender="male",
        looking_for="any",
        age_min=18,
        age_max=99,
        sample_key=0.5,
    ))
    await session.commit()


@pytest.mark.asyncio
async def test_дека_не_показывает_кому_я_лайкнул(sqlite_session):
    """Если я лайкнул человека — он выпадает из деки (не трачу свайпы зря)."""
    await _создать_пользователя(sqlite_session, "U1", "Я")
    await _создать_пользователя(sqlite_session, "U2", "Лайкнутый")
    await _создать_пользователя(sqlite_session, "U3", "Нетронутый")

    sqlite_session.add(Like(
        id="L1", liker_id="U1", liked_id="U2", type="like",
    ))
    await sqlite_session.commit()

    дека = await get_deck_profiles(sqlite_session, "U1", limit=10)
    ids = {a.id for a in дека}

    assert "U2" not in ids, "лайкнутый остался в деке"
    assert "U3" in ids, "чистый кандидат выпал"


@pytest.mark.asyncio
async def test_дека_не_показывает_кому_я_поставил_пропустить(sqlite_session):
    """«Пропустить» == взаимности не будет, показывать повторно бессмысленно."""
    await _создать_пользователя(sqlite_session, "U1", "Я")
    await _создать_пользователя(sqlite_session, "U2", "Пропущенный")
    await _создать_пользователя(sqlite_session, "U3", "Чистый")

    sqlite_session.add(Like(
        id="L1", liker_id="U1", liked_id="U2", type="pass",
    ))
    await sqlite_session.commit()

    дека = await get_deck_profiles(sqlite_session, "U1", limit=10)
    ids = {a.id for a in дека}

    assert "U2" not in ids
    assert "U3" in ids


@pytest.mark.asyncio
async def test_дека_не_показывает_кто_пропустил_меня(sqlite_session):
    """Тот, кто пропустил меня, взаимности не даст — трачу на него свайп зря."""
    await _создать_пользователя(sqlite_session, "U1", "Я")
    await _создать_пользователя(sqlite_session, "U2", "Пропустивший меня")
    await _создать_пользователя(sqlite_session, "U3", "Чистый")

    sqlite_session.add(Like(
        id="L1", liker_id="U2", liked_id="U1", type="pass",
    ))
    await sqlite_session.commit()

    дека = await get_deck_profiles(sqlite_session, "U1", limit=10)
    ids = {a.id for a in дека}

    assert "U2" not in ids, "тот, кто пропустил меня, попал в деку"
    assert "U3" in ids


@pytest.mark.asyncio
async def test_дека_не_показывает_кого_я_заблокировал(sqlite_session):
    """Я заблокировал → не хочу видеть."""
    await _создать_пользователя(sqlite_session, "U1", "Я")
    await _создать_пользователя(sqlite_session, "U2", "Заблокированный")
    await _создать_пользователя(sqlite_session, "U3", "Чистый")

    sqlite_session.add(Block(
        id="B1", blocker_id="U1", blocked_id="U2",
    ))
    await sqlite_session.commit()

    дека = await get_deck_profiles(sqlite_session, "U1", limit=10)
    ids = {a.id for a in дека}

    assert "U2" not in ids
    assert "U3" in ids


@pytest.mark.asyncio
async def test_дека_не_показывает_кто_заблокировал_меня(sqlite_session):
    """Меня заблокировали → жертва не должна снова видеть обидчика."""
    await _создать_пользователя(sqlite_session, "U1", "Я")
    await _создать_пользователя(sqlite_session, "U2", "Заблокировавший меня")
    await _создать_пользователя(sqlite_session, "U3", "Чистый")

    sqlite_session.add(Block(
        id="B1", blocker_id="U2", blocked_id="U1",
    ))
    await sqlite_session.commit()

    дека = await get_deck_profiles(sqlite_session, "U1", limit=10)
    ids = {a.id for a in дека}

    assert "U2" not in ids, "заблокировавший меня попал в деку"
    assert "U3" in ids


@pytest.mark.asyncio
async def test_дека_не_показывает_самого_себя(sqlite_session):
    """Даже если все остальные фильтры пустые — сам себя не вижу."""
    await _создать_пользователя(sqlite_session, "U1", "Я")
    await _создать_пользователя(sqlite_session, "U2", "Другой")

    дека = await get_deck_profiles(sqlite_session, "U1", limit=10)
    ids = {a.id for a in дека}

    assert "U1" not in ids, "сам себя вижу в деке"
    assert "U2" in ids
