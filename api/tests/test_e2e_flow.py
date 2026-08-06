"""Сквозной путь на настоящей базе данных.

Зачем отдельно от `test_http_behavior.py`: там сессия подменена заготовками, и
это правильно для проверки ответов — быстро и без Postgres. Но такая сессия не
ловит того, что видно только на живой базе. Двумя живыми прогонами нашлось:

* `UnboundLocalError` на пустой деке — переменная объявлялась внутри `if`, а
  читалась снаружи. Падал главный экран, причём именно у нового пользователя,
  которому ещё некого показать;
* `TypeError` при сравнении времени — Postgres отдаёт aware, SQLite и старые
  записи naive, и начисление буста роняло обработчик.

Ни один из двух дефектов не был виден ни тестам с подменённой сессией, ни
линтеру, ни проверке типов.

БД здесь SQLite в файле: настоящие таблицы, внешние ключи и типы, но без
Postgres на машине. Из-за этого недоступны `pg_advisory_xact_lock` (блокировки
проверяются отдельно в `test_http_behavior.py`) — только его и подменяем.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


@pytest.fixture
async def живая_база(tmp_path, monkeypatch):
    """Настоящая БД со схемой по моделям и двумя людьми в ней."""
    from models.models import Base, Profile, Subscription, User

    файл = tmp_path / "e2e.db"
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
        # Аня платит: на ней проверяем платные гейты с той стороны, где видно
        s.add(Subscription(
            user_id=аня, plan="ultra",
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
    import routers.cases as cases_mod
    import routers.likes as likes_mod

    Session = живая_база["Session"]

    # pg_advisory_xact_lock есть только в Postgres. Подменяем ровно его, а не
    # всю работу с БД: сами блокировки проверяются в test_http_behavior.py
    for мод in (likes_mod, cases_mod):
        настоящий = мод.sa_text
        монк = (lambda н: lambda sql: н("SELECT 1") if "advisory" in sql else н(sql))(настоящий)
        monkeypatch.setattr(мод, "sa_text", монк)

    текущий = {"id": живая_база["аня"]}

    async def _sess():
        async with Session() as s:
            yield s

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


async def test_путь_от_деки_до_мэтча(клиент, живая_база):
    """Главный путь продукта целиком, на настоящей базе."""
    аня, боря = живая_база["аня"], живая_база["боря"]

    # Дека. Именно здесь падал UnboundLocalError, когда показывать некого
    r = await клиент.get("/api/profiles/deck")
    assert r.status_code == 200, r.text
    дека = r.json()
    assert len(дека) == 1 and дека[0]["id"] == боря
    assert дека[0]["is_online"] is True, "человек только что был в сети"

    # Лайк без взаимности мэтча не даёт
    r = await клиент.post(
        "/api/likes", json={"target_id": боря, "type": "like", "message": "привет!"}
    )
    assert r.status_code == 200, r.text
    assert r.json()["matched"] is False

    # Бесплатному карточка лайкнувшего закрыта — это главный платный гейт
    клиент.от_имени(боря)
    r = await клиент.get("/api/likes/received")
    (входящий,) = r.json()
    assert входящий["is_locked"] is True
    assert входящий["display_name"] == ""

    # Взаимность даёт мэтч
    r = await клиент.post("/api/likes", json={"target_id": аня, "type": "like"})
    assert r.json()["matched"] is True
    match_id = r.json()["match"]["id"]

    # И он открывается как чат
    r = await клиент.get("/api/matches")
    assert len(r.json()) == 1
    r = await клиент.get(f"/api/matches/{match_id}/messages")
    assert r.status_code == 200


async def test_пустая_дека_не_роняет_главный_экран(клиент, живая_база):
    """Ровно тот случай, что падал: новому человеку показывать некого.

    Отдельным тестом, потому что это состояние у КАЖДОГО нового пользователя,
    и падение здесь означает, что продукт не открывается вовсе.
    """
    боря = живая_база["боря"]

    # Оценили единственного кандидата — дека пуста
    r = await клиент.post("/api/likes", json={"target_id": боря, "type": "pass"})
    assert r.status_code == 200

    r = await клиент.get("/api/profiles/deck")
    assert r.status_code == 200, r.text
    assert r.json() == []


async def test_кейс_выдаёт_наклейки_и_копит_коллекцию(клиент, живая_база, monkeypatch):
    """Механика кейса на живой базе: и запись в коллекцию, и счётчик повторов.

    Заодно проверяется начисление буста — на нём падало сравнение времени.
    """
    import routers.cases as cases_mod
    from models.models import Profile, StickerOwned

    # Лимит попыток проверяется отдельно; здесь интересна механика наград.
    # Через monkeypatch, а не присваиванием: прямая замена утекала в соседние
    # тесты и ломала проверку «бесплатному кейс не открыть»
    monkeypatch.setattr(cases_mod, "openings_per_day", lambda tier: 99)

    наклеек = 0
    for _ in range(25):
        r = await клиент.post("/api/cases/open")
        assert r.status_code == 200, r.text
        if r.json()["reward"].get("sticker"):
            наклеек += 1

    Session = живая_база["Session"]
    async with Session() as s:
        мои = (
            await s.execute(
                select(StickerOwned).where(StickerOwned.user_id == живая_база["аня"])
            )
        ).scalars().all()
        анкета = (
            await s.execute(
                select(Profile).where(Profile.user_id == живая_база["аня"])
            )
        ).scalar_one()

    assert наклеек > 0, "за 25 открытий не выпало ни одной наклейки"
    assert sum(x.count for x in мои) == наклеек, "счётчик коллекции разошёлся"
    # Дубликат не пустой: за него начисляется суперлайк
    дублей = sum(x.count - 1 for x in мои)
    if дублей:
        assert анкета.bonus_superlikes > 0, "за дубликаты ничего не начислили"
