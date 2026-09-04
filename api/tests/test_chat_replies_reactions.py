"""Ответы цитатой и реакции в личке.

На живой SQLite-базе тем же приёмом, что `test_direct_messages.py`: настоящие
таблицы и внешние ключи, `pg_advisory_xact_lock` подменяется (в SQLite его
нет). Проверяется именно то, что нельзя увидеть глазами в интерфейсе:

* цитата на сообщение ИЗ ДРУГОГО чата молча обнуляется, а не цитируется;
* реакция на чужое сообщение из другой переписки — 404, а не запись в базу;
* повтор того же кода снимает реакцию, другой код заменяет её;
* реакции страницы набираются одним запросом, а не по запросу на сообщение.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


async def _пропустить(_текст):
    return {"blocked": False}


async def _ничего(*_a, **_kw):
    return None


class _ЖурналЗапросов:
    """Сессия, считающая SELECT'ы к таблице реакций.

    Нужна ровно для одного утверждения: страница сообщений обязана брать
    реакции ОДНИМ запросом. Запрос на сообщение — это N+1, который на живой
    переписке в тысячу реплик виден задержкой открытия чата.
    """

    def __init__(self, session, журнал: list[str]):
        self._s = session
        self._журнал = журнал

    async def execute(self, statement=None, *a, **kw):
        текст = str(statement)
        if "dating_message_reactions" in текст:
            self._журнал.append(текст.split("\n")[0][:60])
        return await self._s.execute(statement, *a, **kw)

    def __getattr__(self, name):
        return getattr(self._s, name)


class _ФейкРедис:
    def __init__(self) -> None:
        self.counts: dict[str, int] = {}

    async def incr(self, key: str) -> int:
        self.counts[key] = self.counts.get(key, 0) + 1
        return self.counts[key]

    async def expire(self, *_a, **_kw) -> None:
        """Окно не переживает тест — чистить нечего."""


@pytest.fixture
async def чат(tmp_path):
    """Аня↔Боря (основной чат) и Аня↔Вера (чужой, для проверок границы)."""
    from models.models import Base, Match, Profile, User

    файл = tmp_path / "reactions.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{файл}")

    # SQLite по умолчанию внешние ключи НЕ соблюдает, и без прагмы проверка
    # `ON DELETE SET NULL` у цитаты ничего бы не проверяла: строка ответа
    # осталась бы со ссылкой на удалённое сообщение и тест зеленел бы зря
    @event.listens_for(engine.sync_engine, "connect")
    def _включить_внешние_ключи(соединение, _запись):   # noqa: ANN001
        курсор = соединение.cursor()
        курсор.execute("PRAGMA foreign_keys=ON")
        курсор.close()

    async with engine.begin() as c:
        await c.run_sync(Base.metadata.create_all)

    Session = async_sessionmaker(engine, expire_on_commit=False)
    аня, боря, вера = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
    ab, av = str(uuid.uuid4()), str(uuid.uuid4())

    async with Session() as s:
        for uid, имя, пол, tg in (
            (аня, "Аня", "female", 1), (боря, "Боря", "male", 2), (вера, "Вера", "female", 3),
        ):
            s.add(User(id=uid, telegram_id=tg, role="user"))
            s.add(Profile(
                user_id=uid, display_name=имя, gender=пол,
                birth_date=datetime(1997, 3, 3, tzinfo=timezone.utc),
                city="Москва", photos=["https://x/1.jpg"], looking_for="any",
            ))
        for mid, a, b in ((ab, аня, боря), (av, аня, вера)):
            первый, второй = sorted((a, b))
            s.add(Match(id=mid, user1_id=первый, user2_id=второй, is_active=True, kind="match"))
        await s.commit()

    yield {"engine": engine, "Session": Session,
           "аня": аня, "боря": боря, "вера": вера, "ab": ab, "av": av}
    await engine.dispose()


@pytest.fixture
async def клиент(app, чат, monkeypatch):
    from database.connection import get_session
    from middleware.auth import get_current_user
    from models.models import User
    import database.connection as dbc
    import routers.matches as matches_mod
    import services.chat_delivery as delivery
    import services.direct_messages as dm_mod
    import services.quotas as quotas_mod

    Session = чат["Session"]
    monkeypatch.setattr(dbc, "async_session_factory", Session)
    monkeypatch.setattr(delivery, "async_session_factory", Session)

    for мод in (dm_mod, delivery, quotas_mod):
        настоящий = мод.sa_text
        монк = (lambda н: lambda sql: н("SELECT 1") if "advisory" in sql else н(sql))(настоящий)
        monkeypatch.setattr(мод, "sa_text", монк)

    monkeypatch.setattr(matches_mod, "moderate_text", _пропустить)
    monkeypatch.setattr(matches_mod, "log_moderation", _ничего)
    monkeypatch.setattr(matches_mod, "fan_out", _ничего)

    редис = _ФейкРедис()

    async def _get_redis():
        return редис

    monkeypatch.setattr(delivery, "get_redis", _get_redis)

    # Реакция уходит в сокет тем же кадром, что и по HTTP: подменяем менеджер
    # и складываем кадры — это половина контракта, и она не видна в ответе
    эфир: list[tuple[str, dict]] = []

    class _Эфир:
        async def publish(self, match_id, payload, exclude=None):
            эфир.append((match_id, payload))

    monkeypatch.setattr(matches_mod, "manager", _Эфир())

    текущий = {"id": чат["аня"]}
    журнал: list[str] = []

    async def _sess():
        async with Session() as s:
            обёртка = _ЖурналЗапросов(s, журнал)
            try:
                yield обёртка
                await s.commit()
            except Exception:
                await s.rollback()
                raise

    async def _user():
        async with Session() as s:
            return (await s.execute(select(User).where(User.id == текущий["id"]))).scalar_one()

    app.dependency_overrides[get_session] = _sess
    app.dependency_overrides[get_current_user] = _user

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        c.от_имени = lambda uid: текущий.update(id=uid)   # type: ignore[attr-defined]
        c.эфир = эфир                                     # type: ignore[attr-defined]
        c.журнал = журнал                                 # type: ignore[attr-defined]
        c.редис = редис                                   # type: ignore[attr-defined]
        yield c

    # Подмены снимаем: утечка dependency_overrides между файлами уже ломала
    # прогон целиком (см. историю test_open_photo_ratings)
    app.dependency_overrides.pop(get_session, None)
    app.dependency_overrides.pop(get_current_user, None)


async def _написать(клиент, match_id: str, текст: str, **поля) -> dict:
    r = await клиент.post(f"/api/matches/{match_id}/messages", json={"text": текст, **поля})
    assert r.status_code == 200, r.text
    return r.json()


# ── словарь реакций ──────────────────────────────────────────────


def test_словарь_реакций_закрытый_и_без_эмодзи():
    """Ключи — коды, а не символы: рисует их интерфейс, иначе один и тот же
    «огонь» выглядит на трёх платформах тремя разными картинками."""
    from services.reactions import REACTION_KEYS, нормализовать_реакцию

    assert нормализовать_реакцию("heart") == "heart"
    assert нормализовать_реакцию("  fire  ") == "fire"
    for мусор in ("", "  ", "banana", "❤️", None, 7, ["heart"]):
        assert нормализовать_реакцию(мусор) is None, мусор
    assert all(k.isascii() and k.isalpha() for k in REACTION_KEYS)
    assert len(set(REACTION_KEYS)) == len(REACTION_KEYS)


def test_свод_реакций_идёт_порядком_словаря():
    """Порядок ряда под сообщением не должен зависеть от порядка нажатий."""
    from services.chat_delivery import свод_реакций
    from services.reactions import REACTION_KEYS

    class Р:
        def __init__(self, key, user_id):
            self.key, self.user_id = key, user_id

    свод = свод_реакций([Р("wow", "u2"), Р("heart", "u1"), Р("heart", "u3")])
    assert [x["key"] for x in свод] == [k for k in REACTION_KEYS if k in {"heart", "wow"}]
    assert свод[0] == {"key": "heart", "users": ["u1", "u3"]}


# ── цитаты ───────────────────────────────────────────────────────


async def test_ответ_цитатой_возвращается_и_в_отправке_и_в_истории(клиент, чат):
    исходное = await _написать(клиент, чат["ab"], "Пойдём в «Пионер» в пятницу?")
    клиент.от_имени(чат["боря"])
    ответ = await _написать(клиент, чат["ab"], "Да!", reply_to_id=исходное["id"])

    assert ответ["reply_to"] == {
        "id": исходное["id"], "sender_id": чат["аня"],
        "text": "Пойдём в «Пионер» в пятницу?", "kind": "text",
        "shape": None, "poster": None, "image_url": None, "duration": 0,
    }

    r = await клиент.get(f"/api/matches/{чат['ab']}/messages")
    assert r.status_code == 200, r.text
    страница = r.json()
    assert страница[0]["reply_to"] is None
    assert страница[1]["reply_to"]["id"] == исходное["id"]
    assert страница[1]["reactions"] == []


async def test_цитата_из_чужого_чата_молча_обнуляется(клиент, чат):
    """Подставить id из своей другой переписки — можно; процитировать — нет."""
    чужое = await _написать(клиент, чат["av"], "Привет, Вера")
    ответ = await _написать(клиент, чат["ab"], "Смотри", reply_to_id=чужое["id"])
    assert ответ["reply_to"] is None, "цитата утекла между чатами"

    # И мусор вместо id тоже не ошибка запроса, а просто отсутствие цитаты
    assert (await _написать(клиент, чат["ab"], "х", reply_to_id="нет-такого"))["reply_to"] is None
    assert (await _написать(клиент, чат["ab"], "у", reply_to_id=""))["reply_to"] is None


async def test_цитата_на_кружок_несёт_форму_и_кадр(клиент, чат, monkeypatch):
    """Ответ кружком на кружок — крючок продукта: цитата на видеосообщение
    без кадра и формы выглядит как ответ на пустоту, текста-то там нет."""
    from config import get_settings

    monkeypatch.setattr(get_settings(), "R2_PUBLIC_URL", "https://cdn.example.test")
    аня = чат["аня"]
    кружок = await _написать(клиент, чат["ab"], "", media={
        "url": f"https://cdn.example.test/chat-media/{аня}/note-1.mp4",
        "kind": "video_note", "duration": 9, "shape": "star",
        "poster": f"https://cdn.example.test/chat-media/{аня}/note-1.jpg",
    })
    клиент.от_имени(чат["боря"])
    ответ = await _написать(клиент, чат["ab"], "ого", reply_to_id=кружок["id"])
    assert ответ["reply_to"]["kind"] == "video_note"
    assert ответ["reply_to"]["shape"] == "star"
    assert ответ["reply_to"]["poster"].endswith("note-1.jpg")
    assert ответ["reply_to"]["duration"] == 9
    assert ответ["reply_to"]["text"] == ""


async def test_цитата_старше_страницы_догружается(клиент, чат):
    """Ответ на реплику месячной давности обязан показать цитату, даже если
    сама реплика на страницу не попала."""
    старое = await _написать(клиент, чат["ab"], "самое первое")
    for i in range(4):
        await _написать(клиент, чат["ab"], f"шум {i}")
    ответ = await _написать(клиент, чат["ab"], "вот про что я", reply_to_id=старое["id"])

    r = await клиент.get(f"/api/matches/{чат['ab']}/messages?limit=2")
    страница = r.json()
    assert [m["id"] for m in страница][-1] == ответ["id"]
    assert старое["id"] not in {m["id"] for m in страница}, "цитируемое не должно быть на странице"
    assert страница[-1]["reply_to"]["text"] == "самое первое"


async def test_удаление_цитируемого_не_уносит_ответ(чат):
    """`SET NULL`, а не `CASCADE`: ответ остаётся в истории без цитаты."""
    from models.models import Message

    Session = чат["Session"]
    async with Session() as s:
        первое = Message(match_id=чат["ab"], sender_id=чат["аня"], text="раз")
        s.add(первое)
        await s.flush()
        второе = Message(match_id=чат["ab"], sender_id=чат["боря"], text="два",
                         reply_to_id=первое.id)
        s.add(второе)
        await s.commit()
        ид = второе.id

        await s.execute(Message.__table__.delete().where(Message.id == первое.id))
        await s.commit()

    async with Session() as s:
        остался = (await s.execute(select(Message).where(Message.id == ид))).scalar_one()
        assert остался.text == "два" and остался.reply_to_id is None


# ── реакции ──────────────────────────────────────────────────────


async def test_реакция_ставится_снимается_и_заменяется(клиент, чат):
    сообщение = await _написать(клиент, чат["ab"], "смешно же")
    путь = f"/api/matches/{чат['ab']}/messages/{сообщение['id']}/reaction"
    клиент.от_имени(чат["боря"])

    r = await клиент.put(путь, json={"key": "haha"})
    assert r.status_code == 200, r.text
    assert r.json()["reactions"] == [{"key": "haha", "users": [чат["боря"]]}]

    # Другой код заменяет: реакция одна на человека
    assert (await клиент.put(путь, json={"key": "fire"})).json()["reactions"] == [
        {"key": "fire", "users": [чат["боря"]]}
    ]
    # Повтор того же кода снимает — иначе передумать можно только крестиком
    assert (await клиент.put(путь, json={"key": "fire"})).json()["reactions"] == []
    # Неизвестный код — тоже снятие, а не 400: клиент старой версии не должен
    # ронять запрос, а «ничего» — единственное безопасное толкование
    await клиент.put(путь, json={"key": "heart"})
    assert (await клиент.put(путь, json={"key": "инопланетное"})).json()["reactions"] == []


async def test_реакции_двоих_складываются_в_один_ключ(клиент, чат):
    """«Моя» не считается на сервере: кадр один на двоих, и у них она разная."""
    сообщение = await _написать(клиент, чат["ab"], "вместе")
    путь = f"/api/matches/{чат['ab']}/messages/{сообщение['id']}/reaction"

    await клиент.put(путь, json={"key": "heart"})       # Аня
    клиент.от_имени(чат["боря"])
    свод = (await клиент.put(путь, json={"key": "heart"})).json()["reactions"]
    assert свод == [{"key": "heart", "users": [чат["аня"], чат["боря"]]}] or свод == [
        {"key": "heart", "users": [чат["боря"], чат["аня"]]}
    ]
    assert len(свод[0]["users"]) == 2

    # И то же самое приезжает в истории чата
    r = await клиент.get(f"/api/matches/{чат['ab']}/messages")
    assert sorted(r.json()[0]["reactions"][0]["users"]) == sorted([чат["аня"], чат["боря"]])


async def test_реакция_уходит_в_сокет_тем_же_кадром(клиент, чат):
    сообщение = await _написать(клиент, чат["ab"], "эхо")
    r = await клиент.put(
        f"/api/matches/{чат['ab']}/messages/{сообщение['id']}/reaction", json={"key": "spark"}
    )
    match_id, кадр = клиент.эфир[-1]
    assert match_id == чат["ab"]
    assert кадр == r.json()
    assert кадр["type"] == "reaction" and кадр["message_id"] == сообщение["id"]


async def test_реакция_на_сообщение_чужого_чата_это_404(клиент, чат):
    чужое = await _написать(клиент, чат["av"], "письмо Вере")
    r = await клиент.put(
        f"/api/matches/{чат['ab']}/messages/{чужое['id']}/reaction", json={"key": "heart"}
    )
    assert r.status_code == 404, r.text

    # И в чужую переписку целиком — тоже не пустят
    клиент.от_имени(чат["боря"])
    r = await клиент.put(
        f"/api/matches/{чат['av']}/messages/{чужое['id']}/reaction", json={"key": "heart"}
    )
    assert r.status_code in (403, 404), r.text


async def test_реакции_страницы_одним_запросом(клиент, чат):
    """N+1 на открытии чата не виден в ответе — только в задержке."""
    ид = []
    for i in range(5):
        ид.append((await _написать(клиент, чат["ab"], f"реплика {i}"))["id"])
    for m in ид:
        await клиент.put(f"/api/matches/{чат['ab']}/messages/{m}/reaction", json={"key": "wow"})

    клиент.журнал.clear()
    r = await клиент.get(f"/api/matches/{чат['ab']}/messages")
    assert r.status_code == 200
    assert all(m["reactions"] == [{"key": "wow", "users": [чат["аня"]]}] for m in r.json())
    assert len(клиент.журнал) == 1, f"реакции набраны {len(клиент.журнал)} запросами"


async def test_пустая_страница_не_ходит_за_реакциями(чат):
    from services.chat_delivery import реакции_страницы

    class _НеЗвать:
        async def execute(self, *_a, **_kw):
            raise AssertionError("на пустой список запрос не нужен")

    assert await реакции_страницы(_НеЗвать(), []) == {}


async def test_шторм_реакций_упирается_в_потолок(клиент, чат):
    """Своё окно, вдвое шире сообщений: перебор реакций дешевле сообщений —
    ни модерации, ни пуша, — но и бесконечным быть не должен."""
    from services.chat_delivery import REACTION_FLOOD_PER_MINUTE

    сообщение = await _написать(клиент, чат["ab"], "по кругу")
    путь = f"/api/matches/{чат['ab']}/messages/{сообщение['id']}/reaction"
    for _ in range(REACTION_FLOOD_PER_MINUTE - 1):
        assert (await клиент.put(путь, json={"key": "heart"})).status_code == 200
    r = await клиент.put(путь, json={"key": "heart"})
    assert r.status_code == 200
    r = await клиент.put(путь, json={"key": "heart"})
    assert r.status_code == 429, r.text
    assert "реакц" in r.json()["detail"].lower()
