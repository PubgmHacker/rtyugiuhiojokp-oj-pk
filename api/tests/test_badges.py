"""Счётчики таббара (`GET /api/badges`) — два числа при входе.

Проверяется главное свойство эндпоинта: он считает ТО ЖЕ, что показывают
экраны. Непрочитанные — как красятся строки в списке чатов, лайки — как
строится «кто меня лайкнул». Разошедшиеся формулы дают бейдж-обманку:
цифра на вкладке есть, а внутри пусто.

Живая SQLite-база, тот же приём, что в test_direct_messages.py.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


@pytest.fixture
async def мир(tmp_path):
    """Аня и трое вокруг неё: Боря (мэтч с перепиской), Вера и Гоша (лайкнули)."""
    from models.models import Base, Like, Match, Message, Profile, User

    файл = tmp_path / "badges.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{файл}")
    async with engine.begin() as c:
        await c.run_sync(Base.metadata.create_all)

    Session = async_sessionmaker(engine, expire_on_commit=False)

    аня, боря, вера, гоша = (str(uuid.uuid4()) for _ in range(4))
    async with Session() as s:
        for uid, имя, tg in ((аня, "Аня", 1), (боря, "Боря", 2), (вера, "Вера", 3), (гоша, "Гоша", 4)):
            s.add(User(id=uid, telegram_id=tg, role="user"))
            s.add(Profile(
                user_id=uid, display_name=имя, gender="female",
                birth_date=datetime(1997, 3, 3, tzinfo=timezone.utc),
                city="Москва", photos=["https://x/1.jpg"], looking_for="any",
            ))

        # Мэтч Аня-Боря: два непрочитанных от Бори и одно прочитанное
        u1, u2 = (аня, боря) if аня < боря else (боря, аня)
        мэтч = Match(user1_id=u1, user2_id=u2, is_active=True)
        s.add(мэтч)
        await s.flush()
        s.add(Message(match_id=мэтч.id, sender_id=боря, text="раз"))
        s.add(Message(match_id=мэтч.id, sender_id=боря, text="два"))
        s.add(Message(
            match_id=мэтч.id, sender_id=боря, text="старое",
            read_at=datetime.now(timezone.utc),
        ))
        # Свои отправленные не считаются
        s.add(Message(match_id=мэтч.id, sender_id=аня, text="моё"))

        # Входящие лайки: Вера и Гоша. Пасс Веры не в счёт — это исходящее.
        s.add(Like(liker_id=вера, liked_id=аня, type="like"))
        s.add(Like(liker_id=гоша, liked_id=аня, type="superlike"))
        await s.commit()

    yield {"Session": Session, "аня": аня, "боря": боря, "вера": вера, "гоша": гоша}
    await engine.dispose()


@pytest.fixture
async def клиент(app, мир):
    from sqlalchemy import select

    from database.connection import get_session
    from middleware.auth import get_current_user
    from models.models import User

    Session = мир["Session"]
    текущий = {"id": мир["аня"]}

    async def _sess():
        async with Session() as s:
            yield s
            await s.commit()

    async def _user():
        async with Session() as s:
            return (
                await s.execute(select(User).where(User.id == текущий["id"]))
            ).scalar_one()

    app.dependency_overrides[get_session] = _sess
    app.dependency_overrides[get_current_user] = _user

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        c.от_имени = lambda uid: текущий.update(id=uid)  # type: ignore[attr-defined]
        yield c

    app.dependency_overrides.pop(get_session, None)
    app.dependency_overrides.pop(get_current_user, None)


async def test_считает_непрочитанные_и_лайки(клиент):
    # Полное равенство, а не подмножество: появление нового счётчика должно
    # осознанно дойти и сюда, и до BadgeCounts на клиенте
    r = await клиент.get("/api/badges")
    assert r.status_code == 200, r.text
    assert r.json() == {"messages": 2, "likes": 2, "notifications": 0}


async def test_оценённые_лайки_выпадают_из_бейджа(клиент, мир):
    """Ответный лайк или пасс убирает карточку с экрана «кто меня лайкнул» —
    и из бейджа она обязана уйти тем же движением."""
    from models.models import Like

    Session = мир["Session"]
    async with Session() as s:
        s.add(Like(liker_id=мир["аня"], liked_id=мир["вера"], type="pass"))
        await s.commit()

    r = await клиент.get("/api/badges")
    assert r.json()["likes"] == 1, r.json()


async def test_неактивный_мэтч_не_считается(клиент, мир):
    """Размэтч прячет переписку из списка чатов — непрочитанные из неё
    не должны продолжать светиться на вкладке."""
    from sqlalchemy import update

    from models.models import Match

    Session = мир["Session"]
    async with Session() as s:
        await s.execute(update(Match).values(is_active=False))
        await s.commit()

    r = await клиент.get("/api/badges")
    assert r.json()["messages"] == 0, r.json()


async def test_лайк_забаненного_не_светится(клиент, мир):
    """Экран лайков забаненных не показывает — бейджу обещать их нельзя."""
    from sqlalchemy import update

    from models.models import User

    Session = мир["Session"]
    async with Session() as s:
        await s.execute(
            update(User).where(User.id == мир["гоша"]).values(is_banned=True)
        )
        await s.commit()

    r = await клиент.get("/api/badges")
    assert r.json()["likes"] == 1, r.json()
