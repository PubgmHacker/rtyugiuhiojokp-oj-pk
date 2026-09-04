"""Листание истории переписки и витрина вложений.

На живой SQLite-базе тем же приёмом, что `test_chat_replies_reactions.py`:
настоящие таблицы, `pg_advisory_xact_lock` подменяется. Проверяется то, чего
не увидеть глазами в интерфейсе:

* курсор `before` отдаёт строго предыдущую страницу и не сбивается, когда
  снизу пришло новое сообщение — а `offset` в этот момент отдаёт дубль;
* `around` даёт непрерывное окно ВОКРУГ сообщения (сама опора внутри), и
  чужое сообщение через него не подсмотреть;
* счётчики витрины считаются по всей переписке, а списки — одной страницей,
  и подпись «показаны последние N» опирается на эту разницу.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

НАЧАЛО = datetime(2026, 3, 1, 12, 0, tzinfo=timezone.utc)


async def _ничего(*_a, **_kw):
    return None


@pytest.fixture
async def переписка(tmp_path):
    """Аня↔Боря: шестьдесят реплик по минуте, и чужой чат Аня↔Вера."""
    from models.models import Base, Match, Message, Profile, User

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'paging.db'}")
    async with engine.begin() as c:
        await c.run_sync(Base.metadata.create_all)

    Session = async_sessionmaker(engine, expire_on_commit=False)
    аня, боря, вера = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
    ab, av = str(uuid.uuid4()), str(uuid.uuid4())
    свои: list[str] = []

    async with Session() as s:
        for uid, имя, пол, tg in (
            (аня, "Аня", "female", 1),
            (боря, "Боря", "male", 2),
            (вера, "Вера", "female", 3),
        ):
            s.add(User(id=uid, telegram_id=tg, role="user"))
            s.add(Profile(
                user_id=uid, display_name=имя, gender=пол,
                birth_date=datetime(1997, 3, 3, tzinfo=timezone.utc),
                city="Москва", photos=["https://x/1.jpg"], looking_for="any",
            ))
        for mid, a, b in ((ab, аня, боря), (av, аня, вера)):
            первый, второй = sorted((a, b))
            s.add(Match(id=mid, user1_id=первый, user2_id=второй,
                        is_active=True, kind="match"))
        # Ровная минутная сетка: страницы по времени должны стыковаться
        # встык, и любой пропуск виден по номеру в тексте
        for n in range(60):
            mid = str(uuid.uuid4())
            свои.append(mid)
            s.add(Message(
                id=mid, match_id=ab, sender_id=аня if n % 2 else боря,
                text=f"реплика {n:02d}", created_at=НАЧАЛО + timedelta(minutes=n),
            ))
        чужое = str(uuid.uuid4())
        s.add(Message(id=чужое, match_id=av, sender_id=вера,
                      text="секрет", created_at=НАЧАЛО))
        await s.commit()

    yield {"Session": Session, "аня": аня, "боря": боря, "вера": вера,
           "ab": ab, "av": av, "свои": свои, "чужое": чужое}
    await engine.dispose()


@pytest.fixture
async def клиент(app, переписка, monkeypatch):
    from database.connection import get_session
    from middleware.auth import get_current_user
    from models.models import User
    import database.connection as dbc
    import routers.matches as matches_mod
    import services.quotas as quotas_mod

    Session = переписка["Session"]
    monkeypatch.setattr(dbc, "async_session_factory", Session)

    # advisory-локов в SQLite нет; всё остальное в квотах работает как в бою
    настоящий = quotas_mod.sa_text
    monkeypatch.setattr(
        quotas_mod, "sa_text",
        lambda sql: настоящий("SELECT 1") if "advisory" in sql else настоящий(sql),
    )
    monkeypatch.setattr(matches_mod, "fan_out", _ничего)

    текущий = {"id": переписка["аня"]}

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

    app.dependency_overrides[get_session] = _sess
    app.dependency_overrides[get_current_user] = _user

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        c.от_имени = lambda uid: текущий.update(id=uid)   # type: ignore[attr-defined]
        yield c

    # Подмены снимаем: утечка dependency_overrides между файлами уже ломала
    # прогон целиком (см. историю test_open_photo_ratings)
    app.dependency_overrides.pop(get_session, None)
    app.dependency_overrides.pop(get_current_user, None)


async def _страница(клиент, match_id: str, **параметры) -> list[dict]:
    r = await клиент.get(f"/api/matches/{match_id}/messages", params=параметры)
    assert r.status_code == 200, r.text
    return r.json()


def _номера(страница: list[dict]) -> list[int]:
    return [int(m["text"].split()[1]) for m in страница]


# ── курсор назад ─────────────────────────────────────────────────


async def test_страница_идёт_снизу_и_по_возрастанию(клиент, переписка):
    """Первая страница — последние реплики, но отданы по порядку чтения."""
    стр = await _страница(клиент, переписка["ab"], limit=20)

    assert _номера(стр) == list(range(40, 60))


async def test_курсор_before_отдаёт_предыдущую_страницу(клиент, переписка):
    """Ровно предыдущие двадцать, без нахлёста и без пропуска."""
    первая = await _страница(клиент, переписка["ab"], limit=20)
    вторая = await _страница(
        клиент, переписка["ab"], limit=20, before=первая[0]["created_at"],
    )

    assert _номера(вторая) == list(range(20, 40))
    третья = await _страница(
        клиент, переписка["ab"], limit=20, before=вторая[0]["created_at"],
    )
    assert _номера(третья) == list(range(0, 20))
    # Начало переписки: короткая страница — это сигнал клиенту «больше нет»
    дальше = await _страница(
        клиент, переписка["ab"], limit=20, before=третья[0]["created_at"],
    )
    assert дальше == []


async def test_новое_сообщение_не_сдвигает_курсор(клиент, переписка):
    """Смысл `before` вместо `offset`: пока человек листает верх, снизу
    приходят реплики. Окно по offset съезжает и отдаёт ту же строку второй
    раз — курсор по времени привязан к прочитанному краю и не съезжает."""
    from models.models import Message

    первая = await _страница(клиент, переписка["ab"], limit=20)

    async with переписка["Session"]() as s:
        s.add(Message(
            id=str(uuid.uuid4()), match_id=переписка["ab"],
            sender_id=переписка["боря"], text="реплика 60",
            created_at=НАЧАЛО + timedelta(minutes=60),
        ))
        await s.commit()

    по_курсору = await _страница(
        клиент, переписка["ab"], limit=20, before=первая[0]["created_at"],
    )
    assert _номера(по_курсору) == list(range(20, 40))
    assert not set(_номера(по_курсору)) & set(_номера(первая))

    по_смещению = await _страница(клиент, переписка["ab"], limit=20, offset=20)
    assert set(_номера(по_смещению)) & set(_номера(первая)), (
        "offset перестал давать дубль — значит смысл курсора пропал, "
        "и этот тест больше ничего не охраняет"
    )


async def test_битый_курсор_before_это_400(клиент, переписка):
    """«вчера» вместо времени — ошибка запроса, а не пятисотка и не пустота."""
    r = await клиент.get(
        f"/api/matches/{переписка['ab']}/messages", params={"before": "вчера"},
    )

    assert r.status_code == 400


# ── окно вокруг сообщения ────────────────────────────────────────


async def test_around_даёт_окно_вокруг_сообщения(клиент, переписка):
    """Прыжок к вложению из середины: опора внутри, вокруг — соседи.

    Без этой ручки клиент листал бы к трёхнедельной фотографии восемь
    страниц подряд, по запросу на каждую.
    """
    опора = переписка["свои"][10]

    окно = await _страница(клиент, переписка["ab"], limit=20, around=опора)

    номера = _номера(окно)
    assert 10 in номера
    assert номера == sorted(номера), "окно отдано не по порядку чтения"
    assert номера == list(range(номера[0], номера[-1] + 1)), "в окне дыра"
    assert min(номера) < 10 < max(номера), "опора на краю — прыжок упрётся"
    assert any(m["id"] == опора for m in окно)


async def test_around_у_начала_переписки_не_ломается(клиент, переписка):
    """Опора — самая первая реплика: старше ничего нет, окно короче половины."""
    окно = await _страница(клиент, переписка["ab"], limit=20, around=переписка["свои"][0])

    assert _номера(окно) == list(range(0, 10))


async def test_around_из_чужого_чата_это_404(клиент, переписка):
    """Чужой id в параметре — не окно на чужую переписку, а отказ."""
    r = await клиент.get(
        f"/api/matches/{переписка['ab']}/messages",
        params={"around": переписка["чужое"]},
    )

    assert r.status_code == 404


async def test_around_с_выдуманным_id_это_404(клиент, переписка):
    r = await клиент.get(
        f"/api/matches/{переписка['ab']}/messages",
        params={"around": str(uuid.uuid4())},
    )

    assert r.status_code == 404


# ── витрина вложений ─────────────────────────────────────────────


@pytest.fixture
async def вложения(переписка):
    """Фото, кружок, три голосовых и две ссылки в одном сообщении."""
    from models.models import Message

    async with переписка["Session"]() as s:
        добавить = lambda **поля: s.add(Message(  # noqa: E731
            id=str(uuid.uuid4()), match_id=переписка["ab"],
            sender_id=переписка["аня"], text="", **поля,
        ))
        for n in range(4):
            добавить(image_url=f"https://r2/фото{n}.jpg",
                     created_at=НАЧАЛО + timedelta(hours=1, minutes=n))
        добавить(media_kind="video_note", media_url="https://r2/кружок.mp4",
                 media_poster_url="https://r2/кружок.jpg", media_shape="heart",
                 media_duration=7, created_at=НАЧАЛО + timedelta(hours=2))
        for n, секунды in enumerate((3, 11, 25)):
            добавить(media_kind="voice", media_url=f"https://r2/голос{n}.ogg",
                     media_duration=секунды, media_waveform="1357975313",
                     created_at=НАЧАЛО + timedelta(hours=3, minutes=n))
        s.add(Message(
            id=str(uuid.uuid4()), match_id=переписка["ab"],
            sender_id=переписка["боря"],
            text="глянь https://vk.com/wall1 и t.me/simpmatchbot, ага",
            created_at=НАЧАЛО + timedelta(hours=4),
        ))
        await s.commit()
    return переписка


async def test_витрина_считает_и_раскладывает_вложения(клиент, вложения):
    """Счётчики, виды и метаданные — то, из чего собраны вкладки витрины."""
    r = await клиент.get(f"/api/matches/{вложения['ab']}/attachments")
    assert r.status_code == 200, r.text
    d = r.json()

    assert (d["photos"], d["video_notes"], d["voices"]) == (4, 1, 3)
    assert d["voice_seconds"] == 39, "общее время голосовых считается суммой"
    assert d["links"] == 2, "две ссылки в одной фразе — это две строки"

    виды = [m["kind"] for m in d["media"]]
    assert виды == ["video_note", "photo", "photo", "photo", "photo"], (
        "медиа идёт одной лентой от свежего к старому"
    )
    кружок = d["media"][0]
    assert (кружок["shape"], кружок["duration"]) == ("heart", 7)
    assert кружок["poster"], "без кадра плитка кружка была бы пустым пятном"

    assert [v["duration"] for v in d["voice"]] == [25, 11, 3]
    assert all(v["waveform"] for v in d["voice"]), (
        "волна не дошла — строка витрины не совпадёт с пузырём в переписке"
    )

    ссылки = {s["host"]: s["url"] for s in d["link"]}
    assert ссылки == {
        "vk.com": "https://vk.com/wall1",
        "t.me": "https://t.me/simpmatchbot",
    }, "запятая после ссылки уехала в адрес или домен потерялся"
    assert all(s["message_id"] for s in d["link"]), (
        "без message_id строка витрины никуда не прыгает"
    )


async def test_счётчики_витрины_не_зависят_от_длины_страницы(
    клиент, вложения, monkeypatch,
):
    """Счётчик считает всю переписку, список — одну страницу.

    На этой разнице держится подпись «показаны последние N»: заголовок
    обязан говорить правду о переписке, даже когда список короче.
    """
    import routers.matches as matches_mod

    monkeypatch.setattr(matches_mod, "ВЛОЖЕНИЙ_НА_ВКЛАДКУ", 2)

    d = (await клиент.get(f"/api/matches/{вложения['ab']}/attachments")).json()

    assert d["photos"] == 4 and d["voices"] == 3
    assert len(d["media"]) == 2 and len(d["voice"]) == 2


async def test_витрина_чужого_чата_закрыта(клиент, вложения):
    """Мэтч не свой — ни счётчиков, ни ссылок."""
    from models.models import Match

    async with вложения["Session"]() as s:
        s.add(Match(id="m-чужой", user1_id=вложения["боря"],
                    user2_id=вложения["вера"], is_active=True, kind="match"))
        await s.commit()

    r = await клиент.get("/api/matches/m-чужой/attachments")

    assert r.status_code == 404


async def test_from_me_считается_от_смотрящего(клиент, вложения):
    """Одна и та же ссылка своя для отправителя и чужая для получателя —
    иначе витрина красит все строки одинаково."""
    моя = (await клиент.get(f"/api/matches/{вложения['ab']}/attachments")).json()
    assert моя["link"][0]["from_me"] is False, "ссылку прислал Боря"

    клиент.от_имени(вложения["боря"])
    его = (await клиент.get(f"/api/matches/{вложения['ab']}/attachments")).json()

    assert его["link"][0]["from_me"] is True
    assert его["media"][0]["from_me"] is False, "кружок записывала Аня"
