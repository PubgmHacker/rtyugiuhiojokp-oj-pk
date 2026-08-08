"""Личка без взаимного мэтча — платный крючок (аналог «Мимолёта»).

На живой SQLite-базе, тем же приёмом, что и `test_e2e_flow.py`: настоящие
таблицы и внешние ключи, `pg_advisory_xact_lock` подменяем — его нет в SQLite,
и сама блокировка (порядок «сначала lock, потом подсчёт») проверяется здесь
через `_SessionСЖурналом`-подобный журнал, как в `test_http_behavior.py` для
кейсов и буста.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


async def _пропустить(_текст):
    return {"blocked": False}


async def _ничего(*_a, **_kw):
    return None


@pytest.fixture
async def три_человека(tmp_path):
    """Аня (Ultra), Боря (free) и Вера (free, на паузе) — для разных сценариев."""
    from models.models import Base, Profile, Subscription, User

    файл = tmp_path / "direct.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{файл}")
    async with engine.begin() as c:
        await c.run_sync(Base.metadata.create_all)

    Session = async_sessionmaker(engine, expire_on_commit=False)

    аня, боря, вера = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
    async with Session() as s:
        for uid, имя, пол, tg, пауза in (
            (аня, "Аня", "female", 1, False),
            (боря, "Боря", "male", 2, False),
            (вера, "Вера", "female", 3, True),
        ):
            s.add(User(id=uid, telegram_id=tg, role="user"))
            s.add(Profile(
                user_id=uid, display_name=имя, gender=пол,
                birth_date=datetime(1997, 3, 3, tzinfo=timezone.utc),
                city="Москва", photos=["https://x/1.jpg"],
                looking_for="any", is_paused=пауза,
            ))
        # Аня на верхнем уровне: личка без взаимного лайка продаётся именно
        # там. Уровень берём из тарифной линейки, а не пишем словом, — фича
        # уже переезжала с Plus на Aurora, и зашитое имя пришлось бы искать
        # по всем тестам заново.
        from services.plans import FEATURE_MIN_TIER
        s.add(Subscription(
            user_id=аня, plan=FEATURE_MIN_TIER["direct_messages"],
            expires_at=datetime.now(timezone.utc) + timedelta(days=30),
        ))
        await s.commit()

    yield {"engine": engine, "Session": Session, "аня": аня, "боря": боря, "вера": вера}
    await engine.dispose()


@pytest.fixture
async def клиент(app, три_человека, monkeypatch):
    from database.connection import get_session
    from middleware.auth import get_current_user
    from models.models import User
    import database.connection as dbc
    import routers.chat as chat_mod
    import routers.likes as likes_mod
    import routers.matches as matches_mod
    import services.chat_delivery as delivery
    import services.direct_messages as dm_mod

    Session = три_человека["Session"]

    # save_message/fan_out живут в services/chat_delivery.py и открывают свою
    # сессию через async_session_factory, а не через FastAPI Depends — их
    # тоже нужно перенаправить на тестовую живую базу (см. test_e2e_flow.py)
    monkeypatch.setattr(dbc, "async_session_factory", Session)
    monkeypatch.setattr(chat_mod, "async_session_factory", Session)
    monkeypatch.setattr(delivery, "async_session_factory", Session)

    # pg_advisory_xact_lock есть только в Postgres — подменяем ровно его
    for мод in (likes_mod, dm_mod):
        настоящий = мод.sa_text
        монк = (lambda н: lambda sql: н("SELECT 1") if "advisory" in sql else н(sql))(настоящий)
        monkeypatch.setattr(мод, "sa_text", монк)

    # Модерация и рассылка — не то, что здесь проверяется
    monkeypatch.setattr(matches_mod, "moderate_text", _пропустить)
    monkeypatch.setattr(matches_mod, "log_moderation", _ничего)
    monkeypatch.setattr(matches_mod, "fan_out", _ничего)

    текущий = {"id": три_человека["аня"]}

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

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        c.от_имени = lambda uid: текущий.update(id=uid)  # type: ignore[attr-defined]
        yield c


async def test_бесплатному_личка_без_лайка_закрыта(клиент, три_человека):
    """Free — тариф не позволяет вовсе, а не «лимит на сегодня 0»."""
    from services.plans import FEATURE_MIN_TIER, TIERS

    аня, боря = три_человека["аня"], три_человека["боря"]
    клиент.от_имени(боря)  # Боря на free

    нужный = TIERS[FEATURE_MIN_TIER["direct_messages"]].name

    r = await клиент.get("/api/matches/direct/quota")
    assert r.status_code == 200
    # Проверяем смысл, а не форму целиком: сравнение со словарём дословно
    # ломается от любого нового поля в ответе, хотя поведение не менялось
    тело = r.json()
    assert тело["allowed"] is False, "на free личка обязана быть закрыта"
    assert тело["left"] == 0 and тело["total"] == 0
    assert тело["required_tier_name"] == нужный, (
        "клиент показывает название тарифа из этого поля — оно должно "
        "совпадать с реальным гейтом"
    )

    r = await клиент.post("/api/matches/direct", json={"target_id": аня, "text": "привет"})
    assert r.status_code == 403, r.text
    assert нужный in r.json()["detail"]


async def test_верхний_тариф_может_написать_без_лайка_и_чат_появляется_в_списке(
    клиент, три_человека
):
    """Основной путь: с верхним тарифом человек пишет тому, кто его не
    лайкал, — появляется чат."""
    боря = три_человека["боря"]

    r = await клиент.post("/api/matches/direct", json={"target_id": боря, "text": "Привет! Заметил, что мы оба любим кино"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["match"]["kind"] == "direct"
    assert body["match"]["direct_answered"] is False

    r = await клиент.get("/api/matches")
    (чат,) = r.json()
    assert чат["kind"] == "direct"
    assert чат["partner"]["id"] == боря

    # И сообщение реально сохранилось
    match_id = body["match"]["id"]
    r = await клиент.get(f"/api/matches/{match_id}/messages")
    (сообщение,) = r.json()
    assert "кино" in сообщение["text"]


async def test_одно_письмо_до_ответа(клиент, три_человека):
    """До ответа получателя — ровно одно письмо. Второе от того же инициатора
    запрещено даже в пределах суточного лимита."""
    боря = три_человека["боря"]

    r = await клиент.post("/api/matches/direct", json={"target_id": боря, "text": "письмо один"})
    assert r.status_code == 200, r.text
    match_id = r.json()["match"]["id"]

    # Повторное письмо тому же человеку — тем же путём (start_direct_message
    # переиспользует беседу), второе сообщение через HTTP-отправку запрещено
    r = await клиент.post(f"/api/matches/{match_id}/messages", json={"text": "письмо два"})
    assert r.status_code == 403, r.text
    assert "ответа" in r.json()["detail"]

    # Ответ получателя снимает ограничение
    клиент.от_имени(боря)
    r = await клиент.post(f"/api/matches/{match_id}/messages", json={"text": "привет, взаимно!"})
    assert r.status_code == 200, r.text

    # После ответа инициатор снова может писать
    клиент.от_имени(три_человека["аня"])
    r = await клиент.post(f"/api/matches/{match_id}/messages", json={"text": "рада, что ответили"})
    assert r.status_code == 200, r.text


async def test_суточный_лимит_писем(клиент, три_человека, monkeypatch):
    """Plus — 3 письма в сутки (см. services/plans.py). Четвёртому разным
    людям — отказ 429, а не тихое молчание.

    Лимит подменяем в `services.direct_messages`, а НЕ только в
    `services.plans`: сервис импортирует функцию себе по имени
    (`from services.plans import direct_messages_per_day`), поэтому патч
    исходного модуля до него не доходит — первая версия теста патчила именно
    его и падала на исправном коде.
    """
    import services.direct_messages as dm
    import services.premium as premium_mod
    from services.plans import FEATURE_MIN_TIER

    monkeypatch.setattr(
        premium_mod, "current_tier",
        _async_return(FEATURE_MIN_TIER["direct_messages"]),
    )
    monkeypatch.setattr(dm, "direct_messages_per_day", lambda tier: 1)

    боря = три_человека["боря"]

    r = await клиент.post("/api/matches/direct", json={"target_id": боря, "text": "первое"})
    assert r.status_code == 200, r.text

    # Второму человеку в тот же день — лимит уже исчерпан (per_day=1)
    третий = str(uuid.uuid4())
    from models.models import Profile, User
    Session = три_человека["Session"]
    async with Session() as s:
        s.add(User(id=третий, telegram_id=99))
        s.add(Profile(user_id=третий, display_name="Гриша", gender="male", city="Питер"))
        await s.commit()

    r = await клиент.post("/api/matches/direct", json={"target_id": третий, "text": "второе"})
    assert r.status_code == 429, r.text
    assert "закончились" in r.json()["detail"]


def _async_return(value):
    async def _f(*_a, **_kw):
        return value
    return _f


async def test_блок_запрещает_личку_без_лайка(клиент, три_человека):
    """Блок в любую сторону закрывает direct-письмо, как и обычный лайк."""
    from models.models import Block

    боря = три_человека["боря"]
    Session = три_человека["Session"]
    async with Session() as s:
        s.add(Block(blocker_id=боря, blocked_id=три_человека["аня"]))
        await s.commit()

    r = await клиент.post("/api/matches/direct", json={"target_id": боря, "text": "привет"})
    assert r.status_code == 403, r.text
    assert r.json()["detail"] == "Написать нельзя"


async def test_пауза_запрещает_личку_без_лайка(клиент, три_человека):
    """Анкета на паузе не должна получать письма, как и не показывается в деке."""
    вера = три_человека["вера"]  # is_paused=True

    r = await клиент.post("/api/matches/direct", json={"target_id": вера, "text": "привет"})
    assert r.status_code == 403, r.text
    assert "принимает" in r.json()["detail"]


async def test_если_уже_есть_match_direct_запрещён(клиент, три_человека):
    """Взаимный мэтч — это уже обычный чат, второй путь для той же пары не нужен."""
    from models.models import Match

    аня, боря = три_человека["аня"], три_человека["боря"]
    Session = три_человека["Session"]
    async with Session() as s:
        u1, u2 = (аня, боря) if аня < боря else (боря, аня)
        s.add(Match(user1_id=u1, user2_id=u2, is_active=True, kind="match"))
        await s.commit()

    r = await клиент.post("/api/matches/direct", json={"target_id": боря, "text": "привет"})
    assert r.status_code == 403, r.text
    assert "чат" in r.json()["detail"]


async def test_текст_письма_проходит_модерацию(клиент, три_человека, monkeypatch):
    """Заблокированный вердиктом текст не создаёт ни письма, ни беседы."""
    import routers.matches as matches_mod

    async def _блокирующая_модерация(_текст):
        return {"blocked": True, "reason": "spam"}

    monkeypatch.setattr(matches_mod, "moderate_text", _блокирующая_модерация)

    боря = три_человека["боря"]
    r = await клиент.post("/api/matches/direct", json={"target_id": боря, "text": "спам-спам"})
    assert r.status_code == 422, r.text

    # И беседа не создалась
    Session = три_человека["Session"]
    from models.models import Match
    async with Session() as s:
        матчи = (await s.execute(select(Match))).scalars().all()
    assert not матчи, "письмо заблокировано модерацией, но Match всё равно создан"


class _ЖурналСессия:
    """Оборачивает настоящую AsyncSession и запоминает порядок execute() —
    тот же приём, что `_SessionСЖурналом` в test_http_behavior.py, только тут
    сессия настоящая (живая база), а не заготовленная."""

    def __init__(self, session):
        self._s = session
        self.запросы: list[str] = []

    async def execute(self, statement=None, *a, **kw):
        self.запросы.append(str(statement))
        return await self._s.execute(statement, *a, **kw)

    def __getattr__(self, name):
        return getattr(self._s, name)


async def test_лимит_писем_берёт_блокировку_до_подсчёта(три_человека, monkeypatch):
    """Гонка параллельных запросов: блокировка обязана быть взята ДО подсчёта
    отправленных за сутки — иначе два быстрых запроса оба читают «отправлено
    0 из 1» и оба проходят. Ровно так уже обходились лимиты кейсов и бустов.

    Фикстура работает на sqlite, где `pg_advisory_xact_lock` не существует,
    поэтому саму блокировку приходится подменять. Подменяем НЕ `sa_text`
    целиком (первая версия теста так и делала — превращала запрос в `SELECT 1`
    и потом искала в журнале слово «advisory», которого после подмены там уже
    быть не могло: тест падал на исправном коде), а перехватываем текст SQL до
    подмены и записываем факт вызова в отдельный журнал. Так проверяется
    настоящий порядок «лок → подсчёт», а не формулировка запроса.
    """
    import services.direct_messages as dm
    import services.plans as plans_mod

    monkeypatch.setattr(plans_mod, "direct_messages_per_day", lambda tier: 1)
    monkeypatch.setattr(dm, "direct_messages_per_day", lambda tier: 1)

    #: Сюда попадает порядковый номер запроса, которым брали блокировку.
    события: list[str] = []
    настоящий_sa_text = dm.sa_text

    def _подменить(sql: str):
        # sqlite не знает advisory-локов: подменяем на безобидный запрос, но
        # факт обращения фиксируем — именно он и проверяется
        if "advisory" in sql:
            событие = "lock"
            события.append(событие)
            return настоящий_sa_text("SELECT 1")
        return настоящий_sa_text(sql)

    monkeypatch.setattr(dm, "sa_text", _подменить)

    #: Подсчёт отправленных за сутки — оборачиваем, чтобы отметить его в том же
    #: журнале и сравнить порядок с блокировкой
    настоящий_подсчёт = dm._direct_sent_today

    async def _подсчёт(*a, **kw):
        события.append("count")
        return await настоящий_подсчёт(*a, **kw)

    monkeypatch.setattr(dm, "_direct_sent_today", _подсчёт)

    Session = три_человека["Session"]
    аня, боря = три_человека["аня"], три_человека["боря"]

    третий = str(uuid.uuid4())
    from models.models import Profile, User
    async with Session() as s:
        s.add(User(id=третий, telegram_id=77))
        s.add(Profile(user_id=третий, display_name="Игорь", gender="male", city="Казань"))
        await s.commit()

    async with Session() as session:
        первый = await dm.start_direct_message(session, аня, боря)
        assert not isinstance(первый, dm.DirectDenied), первый

        # Второе письмо ДРУГОМУ человеку в те же сутки: лимит 1/сутки личный,
        # значит должно быть отказано
        второй = await dm.start_direct_message(session, аня, третий)
        assert isinstance(второй, dm.DirectDenied) and второй.code == "limit", (
            "лимит 1/сутки обойдён — второе письмо того же отправителя прошло"
        )

    assert "lock" in события, (
        "start_direct_message не берёт advisory-lock — лимит обходится гонкой"
    )
    assert "count" in события, "суточный расход вообще не считается"
    assert события.index("lock") < события.index("count"), (
        f"блокировка взята после подсчёта — гонка осталась: {события}"
    )
