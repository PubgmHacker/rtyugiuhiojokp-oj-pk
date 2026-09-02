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
    import services.chat_delivery as delivery
    import services.quotas as quotas_mod

    Session = живая_база["Session"]

    # pg_advisory_xact_lock есть только в Postgres. Подменяем ровно его, а не
    # всю работу с БД: сами блокировки проверяются в test_http_behavior.py
    for мод in (likes_mod, cases_mod, delivery, quotas_mod):
        настоящий = мод.sa_text
        монк = (lambda н: lambda sql: н("SELECT 1") if "advisory" in sql else н(sql))(настоящий)
        monkeypatch.setattr(мод, "sa_text", монк)

    текущий = {"id": живая_база["аня"]}

    async def _sess():
        # Повторяем настоящую зависимость (database/connection.py): она
        # коммитит после успешного обработчика. Без этого тест «ловит» баги,
        # которых в проде нет
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

    app.dependency_overrides[get_session] = _sess
    app.dependency_overrides[get_current_user] = _user

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        c.от_имени = lambda uid: текущий.update(id=uid)  # type: ignore[attr-defined]
        yield c

    # Подмены снимаем: без этого они утекали в следующие файлы прогона —
    # оценка фото ловила 404 «Анкета не найдена» из чужой базы.
    app.dependency_overrides.pop(get_session, None)
    app.dependency_overrides.pop(get_current_user, None)


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
    """Механика кейса на живой базе: обе коллекции пополняются, дублей нет.

    Каждое открытие обязано дать ровно одну коллекционную вещь — наклейку или
    обложку, и всегда новую, пока есть недостающие: месячных попыток мало, и
    попытка, сгоревшая на дубликат, ощущалась бы как отобранная.
    """
    import routers.cases as cases_mod
    from models.models import DecorOwned, Profile, StickerOwned
    from services.cases import CASES
    from services.decor import ОФОРМЛЕНИЯ
    from services.stickers import набор, по_коду

    # Лимит попыток проверяется отдельно; здесь интересна механика наград.
    # Через monkeypatch, а не присваиванием: прямая замена утекала в соседние
    # тесты и ломала проверку «бесплатному кейс не открыть»
    monkeypatch.setattr(cases_mod, "openings_per_month", lambda tier: 99)

    # Кейсы открываем по кругу: каждый обязан отдавать только свой набор
    кейсы = [к.code for к in CASES]
    наклеек = 0
    обложек = 0
    for i in range(25):
        кейс = кейсы[i % len(кейсы)]
        r = await клиент.post("/api/cases/open", json={"case": кейс})
        assert r.status_code == 200, r.text
        тело = r.json()
        assert тело["case"] == кейс
        награда = тело["reward"]
        if награда.get("sticker"):
            наклеек += 1
            assert награда["sticker"]["set"] == кейс, "наклейка чужого набора"
        if награда.get("decor"):
            обложек += 1

    assert наклеек + обложек == 25, "открытие без коллекционной награды"

    Session = живая_база["Session"]
    async with Session() as s:
        мои = (
            await s.execute(
                select(StickerOwned).where(StickerOwned.user_id == живая_база["аня"])
            )
        ).scalars().all()
        мои_обложки = (
            await s.execute(
                select(DecorOwned).where(DecorOwned.user_id == живая_база["аня"])
            )
        ).scalars().all()

    assert наклеек > 0, "за 25 открытий не выпало ни одной наклейки"
    assert sum(x.count for x in мои) == наклеек, "счётчик коллекции разошёлся"
    assert len(мои_обложки) == обложек, "обложки не легли во владение"
    assert len(мои_обложки) <= len(ОФОРМЛЕНИЯ)
    # Обложка не выпадает дважды: выбор идёт только среди недостающих
    assert len({о.code for о in мои_обложки}) == len(мои_обложки)

    # Дубликат наклейки допустим только когда собран её набор и все обложки:
    # пока есть недостающее, кейс выбирает среди него
    свои_коды = {x.code for x in мои}
    for x in мои:
        if x.count > 1:
            н = по_коду(x.code)
            assert н is not None
            assert {s.code for s in набор(н.set)} <= свои_коды, (
                f"дубликат {x.code} при несобранном наборе {н.set}"
            )
            assert len(мои_обложки) == len(ОФОРМЛЕНИЯ), "дубликат при недостающих обложках"


@pytest.fixture
def ws_окружение(живая_база, monkeypatch):
    """WebSocket-чат ходит в БД напрямую через `async_session_factory`, а не
    через зависимость FastAPI, поэтому подменять надо саму фабрику.

    Заодно глушим фан-аут: Redis и APNs в тестах нет, а проверяем мы сам чат.
    Возвращает список разосланных событий — по нему видно, что сообщение не
    просто легло в базу, а ушло собеседнику.
    """
    import database.connection as dbc
    import routers.chat as chat_mod
    import services.chat_delivery as delivery

    Session = живая_база["Session"]
    monkeypatch.setattr(dbc, "async_session_factory", Session)
    monkeypatch.setattr(chat_mod, "async_session_factory", Session)
    # raising=True намеренно: если имя в модуле переименуют, подмена молча
    # перестанет работать и тест начнёт проверять пустоту
    monkeypatch.setattr(delivery, "async_session_factory", Session)

    # Запись сообщения берёт advisory-lock на беседу, а `hashtextextended`
    # есть только в Postgres
    настоящий = delivery.sa_text
    monkeypatch.setattr(
        delivery, "sa_text",
        lambda sql: настоящий("SELECT 1") if "advisory" in sql else настоящий(sql),
    )

    разослано: list[dict] = []
    доставлено = __import__("threading").Event()

    async def _fan_out(payload, *a, **kw):
        разослано.append(payload)
        # Сигналим тесту: сообщение записано и разослано. Без этого тест
        # закрывает сокет раньше, чем обработчик дописал в базу, и проверяет
        # пустоту — гонка в тесте, а не в продукте
        доставлено.set()

    monkeypatch.setattr(chat_mod, "fan_out", _fan_out)
    # Модерацию проверяем отдельно; здесь важен транспорт сообщения
    monkeypatch.setattr(chat_mod, "moderate_text", _пропустить)
    monkeypatch.setattr(chat_mod, "log_moderation", _ничего)
    return {"разослано": разослано, "доставлено": доставлено}


async def _пропустить(_текст):
    return {"blocked": False}


async def _ничего(*_a, **_kw):
    return None


async def test_сообщение_в_чате_доходит_и_сохраняется(app, живая_база, ws_окружение):
    """Самый горячий путь продукта — и единственный, который до сих пор не
    проверялся живьём: WebSocket-тестов не было вовсе.

    Проверяем и запись в базу, и рассылку: сообщение, которое легло в БД, но
    не ушло собеседнику, выглядит как «не доставлено», и наоборот.
    """
    from datetime import datetime, timezone

    from fastapi.testclient import TestClient
    from middleware.auth import create_access_token
    from models.models import Match, Message

    аня, боря = живая_база["аня"], живая_база["боря"]
    Session = живая_база["Session"]

    async with Session() as s:
        мэтч = Match(user1_id=аня, user2_id=боря, is_active=True)
        s.add(мэтч)
        await s.commit()
        match_id = мэтч.id

    токен = create_access_token(аня, 1)

    # TestClient синхронный — он и нужен: у httpx нет клиента WebSocket
    # Рассылку делает fan_out, и он подменён — своего эха сокет не шлёт.
    # Поэтому не ждём ответа, а закрываем соединение: выход из контекста
    # дожидается завершения обработчика, и к проверке база уже записана.
    with TestClient(app) as client:
        with client.websocket_connect(
            f"/ws/chat/{match_id}?token={токен}"
        ) as ws:
            ws.send_json({"type": "message", "text": "привет из теста"})
            # Ждём сигнала от подменённого fan_out: он срабатывает после
            # записи в базу, и только тогда закрывать сокет безопасно
            assert ws_окружение["доставлено"].wait(timeout=10), (
                "сообщение не дошло до рассылки за 10 секунд"
            )

    async with Session() as s:
        сообщения = (
            await s.execute(select(Message).where(Message.match_id == match_id))
        ).scalars().all()

    assert len(сообщения) == 1, "сообщение не сохранилось в базе"
    assert сообщения[0].sender_id == аня
    assert ws_окружение["разослано"], "сообщение не разослано собеседнику"


async def test_чужой_чат_не_открывается(app, живая_база, ws_окружение):
    """Защита от IDOR: подставив чужой match_id, читать переписку нельзя."""
    from fastapi.testclient import TestClient
    from middleware.auth import create_access_token
    from models.models import Match

    Session = живая_база["Session"]
    # Мэтч двух других людей — я в нём не участвую
    async with Session() as s:
        чужой = Match(user1_id="кто-то", user2_id="ещё-кто-то", is_active=True)
        s.add(чужой)
        await s.commit()
        match_id = чужой.id

    токен = create_access_token(живая_база["аня"], 1)

    # `pytest.raises(Exception)` тут не годится: он ловит и падение самого
    # теста, поэтому проходил даже со снятой защитой. Проверяем ровно то, что
    # нужно, — сервер закрыл сокет и сообщение в чужой чат не записалось
    from starlette.websockets import WebSocketDisconnect

    закрыт = False
    with TestClient(app) as client:
        try:
            with client.websocket_connect(
                f"/ws/chat/{match_id}?token={токен}"
            ) as ws:
                ws.send_json({"type": "message", "text": "я тут не участвую"})
                ws.receive_json()
        except WebSocketDisconnect:
            закрыт = True

    assert закрыт, "сокет чужого чата остался открытым"
    assert not ws_окружение["разослано"], "сообщение ушло в чужой чат"


async def test_без_токена_сокет_не_открывается(app, живая_база, ws_окружение):
    """Иначе переписку читал бы кто угодно, зная только match_id."""
    from fastapi.testclient import TestClient

    # Так же, как в тесте чужого чата: широкий `raises(Exception)` проходил
    # даже со снятой проверкой токена, потому что ловил любое падение
    from starlette.websockets import WebSocketDisconnect

    закрыт = False
    with TestClient(app) as client:
        try:
            with client.websocket_connect("/ws/chat/любой") as ws:
                ws.send_json({"type": "message", "text": "без токена"})
                ws.receive_json()
        except WebSocketDisconnect:
            закрыт = True

    assert закрыт, "сокет открылся без токена"
    assert not ws_окружение["разослано"], "сообщение прошло без токена"
