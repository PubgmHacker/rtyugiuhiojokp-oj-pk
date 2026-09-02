"""Открытые оценки фото: владелец видит, кто и сколько поставил.

Раньше оценка была анонимной (ради «честности»), теперь открыта, как у
конкурента, но с цельным отказом от участия: hide_from_ratings прячет
человека и из чужой очереди, и из его права оценивать. Асимметрия «сам
сужу, а меня не судят» не допускается — она превращает очередь в
одностороннее окошко.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


@pytest.fixture
async def база(tmp_path, monkeypatch):
    from models.models import Base, Profile, User

    файл = tmp_path / "ratings.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{файл}")
    async with engine.begin() as c:
        await c.run_sync(Base.metadata.create_all)

    Session = async_sessionmaker(engine, expire_on_commit=False)

    люди = {}
    async with Session() as s:
        for tg, имя, пол in ((1, "Аня", "female"), (2, "Боря", "male"), (3, "Вера", "female"), (4, "Глеб", "male")):
            uid = str(uuid.uuid4())
            s.add(User(id=uid, telegram_id=tg, role="user"))
            s.add(Profile(
                user_id=uid, display_name=имя, gender=пол,
                city="Москва", photos=[f"https://x/{tg}.jpg"],
            ))
            люди[tg] = uid
        await s.commit()

    async def _сессия():
        return Session()

    monkeypatch.setattr("database.connection.async_session_factory", Session)
    # Модули импортируют фабрику напрямую — подменяем и у них
    import database.connection as dc
    monkeypatch.setattr(dc, "async_session_factory", Session)
    from routers import photo_ratings as pr
    monkeypatch.setattr(pr, "get_session", _сессия)

    yield Session, люди

    await engine.dispose()


@pytest.fixture
async def клиент(база):
    from main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        yield c


def _заголовок(uid: str) -> dict:
    from middleware.auth import create_access_token

    return {"Authorization": f"Bearer {create_access_token(uid)}"}


@pytest.mark.anyio
async def test_оценка_видна_владельцу_с_анкетой_оценщика(база, клиент):
    Session, люди = база
    аня, боря, вера = люди[1], люди[2], люди[3]

    r = await клиент.post("/api/photo-ratings", json={"target_id": аня, "score": 4}, headers=_заголовок(боря))
    assert r.status_code == 204
    r = await клиент.post("/api/photo-ratings", json={"target_id": аня, "score": 2}, headers=_заголовок(вера))
    assert r.status_code == 204

    # updated_at хранится с точностью до секунды: разносим, чтобы «свежие
    # первыми» проверялось детерминированно, а не гонкой двух INSERT
    from datetime import timedelta, timezone as tz

    from models.models import PhotoRating
    from sqlalchemy import select

    async with Session() as s:
        боря_оценка = (
            await s.execute(
                select(PhotoRating).where(
                    PhotoRating.rater_id == боря, PhotoRating.target_id == аня
                )
            )
        ).scalar_one()
        боря_оценка.updated_at = datetime.now(tz.utc) - timedelta(seconds=10)
        await s.commit()

    r = await клиент.get("/api/photo-ratings/mine", headers=_заголовок(аня))
    assert r.status_code == 200
    data = r.json()
    assert data["average"] == 3.0
    assert data["total"] == 2
    # Свежие первыми: Вера оцен позже
    assert [i["user_id"] for i in data["feed"]][0] == вера
    боря_карточка = next(i for i in data["feed"] if i["user_id"] == боря)
    assert боря_карточка["score"] == 4
    assert боря_карточка["display_name"] == "Боря"
    assert боря_карточка["photo"] == "https://x/2.jpg"


@pytest.mark.anyio
async def test_скрывшийся_не_оценивает_и_не_оцениваем(база, клиент):
    Session, люди = база
    аня, боря = люди[1], люди[2]

    async with Session() as s:
        from sqlalchemy import select

        from models.models import Profile

        анкета = (await s.execute(select(Profile).where(Profile.user_id == боря))).scalar_one()
        анкета.hide_from_ratings = True
        await s.commit()

    # Скрывшийся сам ставить оценку не может
    r = await клиент.post("/api/photo-ratings", json={"target_id": аня, "score": 5}, headers=_заголовок(боря))
    assert r.status_code == 403

    # …и его нет в чужой очереди
    r = await клиент.get("/api/photo-ratings/queue", headers=_заголовок(аня))
    assert all(t["user_id"] != боря for t in r.json()["targets"])


@pytest.mark.anyio
async def test_заблокированный_оценщик_исчезает_из_ленты(база, клиент):
    Session, люди = база
    аня, боря = люди[1], люди[2]

    await клиент.post("/api/photo-ratings", json={"target_id": аня, "score": 3}, headers=_заголовок(боря))

    async with Session() as s:
        from models.models import Block

        s.add(Block(blocker_id=аня, blocked_id=боря))
        await s.commit()

    r = await клиент.get("/api/photo-ratings/mine", headers=_заголовок(аня))
    data = r.json()
    # Оценка в средней осталась — история честная
    assert data["total"] == 1
    # …но карточки заблокированного в ленте нет
    assert all(i["user_id"] != боря for i in data["feed"])
