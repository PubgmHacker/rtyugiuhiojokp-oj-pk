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


class _СессияСЖурналомЛоков:
    """Настоящая сессия, запоминающая захваты advisory-локов и подсчёты.

    Ключ лока приходит не в тексте запроса, а в параметрах (`:k`), поэтому
    журнал пишет и то, и другое. Порядок захвата двух локов — инвариант, а не
    деталь: письмо и встречный лайк берут одни и те же два ключа, и разный
    порядок между этими путями — дедлок. Проверить его можно только по ключам.
    """

    def __init__(self, session, журнал: list[str]):
        self._s = session
        self._журнал = журнал

    async def execute(self, statement=None, *a, **kw):
        текст = str(statement)
        параметры = a[0] if a and isinstance(a[0], dict) else kw.get("parameters") or {}
        if "advisory" in текст:
            self._журнал.append(f"lock:{параметры.get('k', '?')}")
        elif "count(" in текст.lower():
            self._журнал.append("count")
        return await self._s.execute(statement, *a, **kw)

    def __getattr__(self, name):
        return getattr(self._s, name)


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
    import services.quotas as quotas_mod

    Session = три_человека["Session"]

    # save_message/fan_out живут в services/chat_delivery.py и открывают свою
    # сессию через async_session_factory, а не через FastAPI Depends — их
    # тоже нужно перенаправить на тестовую живую базу (см. test_e2e_flow.py)
    monkeypatch.setattr(dbc, "async_session_factory", Session)
    monkeypatch.setattr(chat_mod, "async_session_factory", Session)
    monkeypatch.setattr(delivery, "async_session_factory", Session)

    # pg_advisory_xact_lock есть только в Postgres — подменяем ровно его.
    # Слово «advisory» в тексте оставляем: по нему `_СессияСЖурналомЛоков`
    # отличает захват лока от обычного запроса, а без него журнал видел бы
    # безобидный «SELECT 1» и проверка порядка локов молча ничего не проверяла.
    for мод in (likes_mod, dm_mod, delivery, quotas_mod):
        настоящий = мод.sa_text
        монк = (
            lambda н: lambda sql: н("SELECT 1 -- advisory") if "advisory" in sql else н(sql)
        )(настоящий)
        monkeypatch.setattr(мод, "sa_text", монк)

    # Модерация и рассылка — не то, что здесь проверяется
    monkeypatch.setattr(matches_mod, "moderate_text", _пропустить)
    monkeypatch.setattr(matches_mod, "log_moderation", _ничего)
    monkeypatch.setattr(matches_mod, "fan_out", _ничего)

    текущий = {"id": три_человека["аня"]}
    журнал_локов: list[str] = []

    async def _sess():
        async with Session() as s:
            обёртка = _СессияСЖурналомЛоков(s, журнал_локов)
            try:
                yield обёртка
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
        c.журнал_локов = журнал_локов  # type: ignore[attr-defined]
        yield c

    # Подмены снимаем: без этого они утекали в следующие файлы прогона —
    # оценка фото ловила 404 «Анкета не найдена» из чужой базы.
    app.dependency_overrides.pop(get_session, None)
    app.dependency_overrides.pop(get_current_user, None)


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


async def test_второе_письмо_не_проходит_и_через_создание_беседы(клиент, три_человека):
    """`POST /matches/direct` — не «завести чат», а «отправить письмо», и правило
    «одно до ответа» действует и на нём.

    Дыра была настоящая и незаметная: `start_direct_message` для уже
    существующей беседы возвращает её же и лимит НЕ списывает (это верно —
    второе письмо не должно стоить второй квоты), а роутер писал в неё через
    `save_message` вообще без проверок. Отказ приходил только на
    `POST /matches/{id}/messages`, то есть на пути, по которому идёт открытый
    чат, — а клиент, дёргающий `/direct` повторно, получал безлимитный канал к
    человеку, который ни разу не ответил. Ровно то, от чего лимит и защищает.
    """
    боря = три_человека["боря"]

    r = await клиент.post("/api/matches/direct", json={"target_id": боря, "text": "письмо один"})
    assert r.status_code == 200, r.text
    match_id = r.json()["match"]["id"]

    r = await клиент.post("/api/matches/direct", json={"target_id": боря, "text": "письмо два"})
    assert r.status_code == 403, (
        f"второе письмо молчащему человеку прошло через /direct: {r.text}"
    )
    assert "ответа" in r.json()["detail"]

    # И в базе ровно одно сообщение: отказ должен быть ДО записи, а не после
    r = await клиент.get(f"/api/matches/{match_id}/messages")
    assert len(r.json()) == 1, "второе письмо всё-таки легло в базу"


async def test_пересылка_ролика_не_обходит_правило_одного_письма(
    клиент, три_человека, monkeypatch
):
    """Ролик в чат — такое же сообщение, и лимит на него распространяется.

    Пересыл идёт мимо `routers/matches.py` (свой обработчик в `routers/reels.py`)
    и звал `save_message` напрямую. Пока правило жило в роутере, письмо
    запрещалось, а пересланный ролик с подписью — нет: тот же канал к молчащему
    человеку, только другим путём.
    """
    import routers.reels as reels_mod
    from models.models import Reel

    monkeypatch.setattr(reels_mod, "moderate_text", _пропустить)
    monkeypatch.setattr(reels_mod, "log_moderation", _ничего)

    аня, боря = три_человека["аня"], три_человека["боря"]
    Session = три_человека["Session"]

    r = await клиент.post("/api/matches/direct", json={"target_id": боря, "text": "письмо один"})
    assert r.status_code == 200, r.text
    match_id = r.json()["match"]["id"]

    async with Session() as s:
        ролик = Reel(user_id=аня, video_url="https://x/v.mp4", caption="мой ролик")
        s.add(ролик)
        await s.commit()
        reel_id = ролик.id

    r = await клиент.post(
        f"/api/reels/{reel_id}/forward",
        json={"match_id": match_id, "text": "а ещё вот"},
    )
    assert r.status_code == 403, (
        f"пересылка ролика обошла правило «одно письмо до ответа»: {r.status_code} {r.text}"
    )

    r = await клиент.get(f"/api/matches/{match_id}/messages")
    assert len(r.json()) == 1, "ролик всё-таки лёг в чат сверх лимита"


async def test_чужая_картинка_не_принимается_и_по_http(клиент, три_человека, monkeypatch):
    """Ссылка на посторонний хост в `image_url` отклоняется на всех путях.

    Проверка стояла только в WebSocket-обработчике. HTTP-отправка принимала
    любой URL: он показывался собеседнику как <img> — минуя и AI-модерацию, и
    срезание EXIF, и раскрывая IP получателя постороннему серверу в момент
    показа. Клиент собирает пакет сам, так что «в интерфейсе такой кнопки нет»
    защитой не является.
    """
    from config import get_settings
    from models.models import Match

    настройки = get_settings()
    monkeypatch.setattr(настройки, "R2_PUBLIC_URL", "https://media.simp.test", raising=False)

    аня, боря = три_человека["аня"], три_человека["боря"]
    Session = три_человека["Session"]
    async with Session() as s:
        мэтч = Match(user1_id=аня, user2_id=боря, is_active=True)
        s.add(мэтч)
        await s.commit()
        match_id = мэтч.id

    r = await клиент.post(
        f"/api/matches/{match_id}/messages",
        json={"text": "смотри", "image_url": "https://evil.test/1.jpg"},
    )
    assert r.status_code == 400, f"чужая ссылка принята по HTTP: {r.status_code} {r.text}"

    r = await клиент.post(
        f"/api/matches/{match_id}/messages",
        json={"text": "а вот наша", "image_url": "https://media.simp.test/photos/a/1.jpg"},
    )
    assert r.status_code == 200, f"своя картинка не прошла: {r.text}"

    r = await клиент.get(f"/api/matches/{match_id}/messages")
    ссылки = [m["image_url"] for m in r.json()]
    assert ссылки == ["https://media.simp.test/photos/a/1.jpg"], ссылки


async def test_размэтч_не_даёт_написать_письмо_заново(клиент, три_человека):
    """Правило «одно письмо до ответа» обходилось в два запроса.

    `unmatch` доступен обеим сторонам, а `start_direct_message` переиспользовал
    ту же строку `Match` и обнулял `direct_answered` — то есть закрытая беседа
    превращалась в чистый лист, и отправитель писал молчащему человеку сколько
    угодно раз. Причём именно тот, кто закрыл переписку от него, получал письма
    снова: обход бил ровно по тому, кого правило защищает.
    """
    боря = три_человека["боря"]

    r = await клиент.post(
        "/api/matches/direct", json={"target_id": боря, "text": "письмо один"}
    )
    assert r.status_code == 200, r.text
    match_id = r.json()["match"]["id"]

    # Боря закрывает переписку, не ответив
    клиент.от_имени(боря)
    r = await клиент.post(f"/api/matches/{match_id}/unmatch")
    assert r.status_code == 200, r.text

    # Аня заходит второй раз тем же путём
    клиент.от_имени(три_человека["аня"])
    r = await клиент.post(
        "/api/matches/direct", json={"target_id": боря, "text": "письмо два"}
    )
    assert r.status_code == 403, f"письмо прошло после размэтча: {r.status_code} {r.text}"
    assert "закрыли" in r.json()["detail"]

    # И в базе не появилось второго сообщения
    Session = три_человека["Session"]
    from models.models import Message
    async with Session() as s:
        сообщения = (
            await s.execute(select(Message).where(Message.match_id == match_id))
        ).scalars().all()
    assert len(сообщения) == 1, "второе письмо всё-таки записалось"


async def test_письмо_в_закрытую_отвеченную_беседу_тратит_суточную_квоту(
    клиент, три_человека, monkeypatch
):
    """Реактивированная беседа — новое письмо, и оно должно списать лимит.

    `_direct_sent_today` считает письма по `Match.created_at`. Переиспользуемая
    строка сохраняла дату первого знакомства, поэтому реактивация выпадала из
    суточного окна: лимит списывался нулём, и верхний тариф получал лишнее
    письмо в день на каждую старую беседу.
    """
    import services.direct_messages as dm
    import services.premium as premium_mod
    from models.models import Match, Profile, User
    from services.plans import FEATURE_MIN_TIER

    monkeypatch.setattr(
        premium_mod, "current_tier",
        _async_return(FEATURE_MIN_TIER["direct_messages"]),
    )
    monkeypatch.setattr(dm, "direct_messages_per_day", lambda tier: 1)

    аня, боря = три_человека["аня"], три_человека["боря"]
    Session = три_человека["Session"]

    r = await клиент.post(
        "/api/matches/direct", json={"target_id": боря, "text": "первое"}
    )
    assert r.status_code == 200, r.text
    match_id = r.json()["match"]["id"]

    # Боря ответил — значит закрытую беседу можно будет завести заново
    клиент.от_имени(боря)
    r = await клиент.post(f"/api/matches/{match_id}/messages", json={"text": "привет"})
    assert r.status_code == 200, r.text
    r = await клиент.post(f"/api/matches/{match_id}/unmatch")
    assert r.status_code == 200, r.text

    # Состарим беседу: письмо было не сегодня, суточная квота Ани свободна
    async with Session() as s:
        мэтч = (
            await s.execute(select(Match).where(Match.id == match_id))
        ).scalar_one()
        мэтч.created_at = datetime.now(timezone.utc) - timedelta(days=2)
        await s.commit()

    клиент.от_имени(аня)
    r = await клиент.post(
        "/api/matches/direct", json={"target_id": боря, "text": "снова привет"}
    )
    assert r.status_code == 200, f"письмо в старую беседу должно проходить: {r.text}"

    # Квота на сегодня (per_day=1) этим письмом исчерпана — третьему отказ
    третий = str(uuid.uuid4())
    async with Session() as s:
        s.add(User(id=третий, telegram_id=98))
        s.add(Profile(user_id=третий, display_name="Гриша", gender="male", city="Питер"))
        await s.commit()

    r = await клиент.post(
        "/api/matches/direct", json={"target_id": третий, "text": "третьему"}
    )
    assert r.status_code == 429, (
        f"реактивация не списала суточное письмо: {r.status_code} {r.text}"
    )


def _заглушить_лайки(monkeypatch) -> list[str]:
    """Отключить рассылку в роутере лайков и вернуть журнал объявлений о мэтче.

    Журнал нужен не для галочки: «мэтч состоялся» — это ещё и пуш, событие боту
    и всплывашка в интерфейсе. Реактивация уже закрытой беседы обязана их
    поднять (пара сошлась заново), а конверсия активного письма — нет, там чат
    и так открыт у обоих. Без этой проверки обе ветки `is_new_match`
    неразличимы.
    """
    import routers.likes as likes_mod

    объявления: list[str] = []

    async def _объявить(*a, **_kw):
        объявления.append(str(a[0]) if a else "")

    monkeypatch.setattr(likes_mod, "publish_match", _объявить)
    monkeypatch.setattr(likes_mod, "publish_new_like", _ничего)
    monkeypatch.setattr(likes_mod, "publish_new_match_for_bot", _ничего)
    monkeypatch.setattr(likes_mod, "notify_new_match", _ничего)
    monkeypatch.setattr(likes_mod, "_push_match_notifications", _ничего)
    monkeypatch.setattr(likes_mod, "moderate_text", _пропустить)
    monkeypatch.setattr(likes_mod, "log_moderation", _ничего)
    return объявления


async def test_взаимный_лайк_превращает_письмо_в_обычный_мэтч(
    клиент, три_человека, monkeypatch
):
    """Пара лайкнула друг друга поверх беседы-письма — это обычный чат.

    `kind` оставался "direct" навсегда: ветка мэтча в `routers/likes.py`
    трогала только неактивную строку, а беседа-письмо активна. Из-за этого
    правило «одно письмо до ответа» продолжало действовать на пару, которая
    уже сказала друг другу «да» лайками: отправитель молчал до тех пор, пока
    получатель не напишет первым, — при том что интерфейс показывал им обычный
    мэтч. Платное ограничение переживало причину, по которой оно вводилось.
    """
    объявления = _заглушить_лайки(monkeypatch)

    аня, боря = три_человека["аня"], три_человека["боря"]

    r = await клиент.post(
        "/api/matches/direct", json={"target_id": боря, "text": "письмо один"}
    )
    assert r.status_code == 200, r.text
    match_id = r.json()["match"]["id"]

    # Аня лайкает Борю, Боря — Аню: взаимность есть, ответа в чате ещё нет
    r = await клиент.post("/api/likes", json={"target_id": боря, "type": "like"})
    assert r.status_code == 200, r.text
    клиент.от_имени(боря)
    r = await клиент.post("/api/likes", json={"target_id": аня, "type": "like"})
    assert r.status_code == 200, r.text
    assert r.json()["matched"] is True, "взаимный лайк не дал мэтча"

    # Беседа стала обычной — и вторым письмом Аня уже не упирается в правило
    клиент.от_имени(аня)
    r = await клиент.get("/api/matches")
    (чат,) = r.json()
    assert чат["kind"] == "match", (
        f"после взаимного лайка беседа осталась платным письмом: {чат['kind']}"
    )

    r = await клиент.post(
        f"/api/matches/{match_id}/messages", json={"text": "письмо два"}
    )
    assert r.status_code == 200, (
        f"взаимно лайкнувшая пара упёрлась в «одно письмо до ответа»: {r.text}"
    )

    assert объявления == [], (
        "чат у пары уже был открыт — второй раз объявлять «у вас мэтч» "
        f"нечего: {объявления}"
    )


async def test_взаимный_лайк_после_размэтча_письма_открывает_чат_заново(
    клиент, три_человека, monkeypatch
):
    """Письмо закрыли, потом пара сошлась лайками — чат обязан ожить.

    Ветка конверсии перехватывает беседу-письмо раньше общей ветки
    «неактивную реактивируем», и если она меняет только `kind`, закрытая
    переписка остаётся закрытой: лайки взаимные, в списке чатов пусто.
    А объявить мэтч тут, наоборот, нужно — для обоих это новое событие, чата
    перед ним не было.
    """
    объявления = _заглушить_лайки(monkeypatch)

    аня, боря = три_человека["аня"], три_человека["боря"]

    r = await клиент.post(
        "/api/matches/direct", json={"target_id": боря, "text": "письмо один"}
    )
    assert r.status_code == 200, r.text
    match_id = r.json()["match"]["id"]

    клиент.от_имени(боря)
    r = await клиент.post(f"/api/matches/{match_id}/unmatch")
    assert r.status_code == 200, r.text

    # Разошлись — и сошлись заново, уже взаимно
    r = await клиент.post("/api/likes", json={"target_id": аня, "type": "like"})
    assert r.status_code == 200, r.text
    клиент.от_имени(аня)
    r = await клиент.post("/api/likes", json={"target_id": боря, "type": "like"})
    assert r.status_code == 200, r.text
    assert r.json()["matched"] is True, "взаимный лайк не дал мэтча"

    r = await клиент.get("/api/matches")
    чаты = r.json()
    assert len(чаты) == 1, f"чат не ожил после взаимного лайка: {чаты}"
    assert чаты[0]["kind"] == "match", чаты[0]["kind"]

    assert объявления, (
        "чата перед этим не было — о мэтче обязаны узнать оба, иначе он "
        "появляется в списке молча"
    )

    r = await клиент.post(
        f"/api/matches/{match_id}/messages", json={"text": "снова привет"}
    )
    assert r.status_code == 200, f"в ожившем чате не пишется: {r.text}"


async def test_конверсия_во_взаимный_мэтч_не_возвращает_суточное_письмо(
    клиент, три_человека, monkeypatch
):
    """Удачное письмо не должно обнулять суточную квоту.

    Расход считался по строкам с `kind="direct"`, а взаимный лайк переводит
    беседу в `kind="match"` — то есть письмо, которое сработало, исчезало из
    подсчёта и возвращалось отправителю. Сговор двух аккаунтов (написал —
    лайкнули друг друга) снимал лимит ровно тем действием, за которое человек
    и платит.
    """
    import services.direct_messages as dm
    import services.premium as premium_mod
    from models.models import Profile, User
    from services.plans import FEATURE_MIN_TIER

    monkeypatch.setattr(
        premium_mod, "current_tier",
        _async_return(FEATURE_MIN_TIER["direct_messages"]),
    )
    monkeypatch.setattr(dm, "direct_messages_per_day", lambda tier: 1)
    _заглушить_лайки(monkeypatch)

    аня, боря = три_человека["аня"], три_человека["боря"]
    Session = три_человека["Session"]

    r = await клиент.post(
        "/api/matches/direct", json={"target_id": боря, "text": "письмо"}
    )
    assert r.status_code == 200, r.text

    r = await клиент.post("/api/likes", json={"target_id": боря, "type": "like"})
    assert r.status_code == 200, r.text
    клиент.от_имени(боря)
    r = await клиент.post("/api/likes", json={"target_id": аня, "type": "like"})
    assert r.json()["matched"] is True, r.text

    третий = str(uuid.uuid4())
    async with Session() as s:
        s.add(User(id=третий, telegram_id=96))
        s.add(Profile(user_id=третий, display_name="Гриша", gender="male", city="Питер"))
        await s.commit()

    клиент.от_имени(аня)
    r = await клиент.post(
        "/api/matches/direct", json={"target_id": третий, "text": "ещё одно"}
    )
    assert r.status_code == 429, (
        f"мэтч вернул потраченное письмо в квоту: {r.status_code} {r.text}"
    )

    # И витрина показывает то же самое, что и сам гейт
    r = await клиент.get("/api/matches/direct/quota")
    assert r.json()["left"] == 0, r.json()


def _локи(журнал: list[str]) -> list[str]:
    """Только захваты локов, в порядке обращения."""
    return [с for с in журнал if с.startswith("lock:")]


async def test_суперлайк_берёт_личный_лок_до_подсчёта_квоты(
    клиент, три_человека, monkeypatch
):
    """Квота суперлайков — личная и суточная, значит и лок должен быть личным.

    Раньше `create_like` брал только парный лок, да ещё и после подсчёта. Оба
    промаха бьют в одно место: два одновременных суперлайка РАЗНЫМ людям берут
    разные парные ключи, не видят друг друга, оба читают «использовано 0 из 1»
    и оба проходят. Платная вещь выдавалась вдвое, и чем больше целей, тем
    больше лишних суперлайков.

    Гонку в один поток не воспроизвести, поэтому проверяем то, что её
    исключает: личный ключ захвачен и захвачен ДО подсчёта.
    """
    import routers.likes as likes_mod

    _заглушить_лайки(monkeypatch)
    monkeypatch.setattr(likes_mod, "superlikes_for", lambda tier: 1)

    аня, боря = три_человека["аня"], три_человека["боря"]
    клиент.журнал_локов.clear()

    r = await клиент.post("/api/likes", json={"target_id": боря, "type": "superlike"})
    assert r.status_code == 200, r.text

    журнал = клиент.журнал_локов
    личный = f"lock:dating:likes:{аня}"
    assert личный in журнал, (
        f"личный лок не взят — суперлайки раздаются гонкой: {журнал}"
    )
    assert "count" in журнал, "квота суперлайков вообще не считается"
    assert журнал.index(личный) < журнал.index("count"), (
        f"лок взят после подсчёта — гонка осталась: {журнал}"
    )


async def test_суперлайк_второму_человеку_не_проходит_сверх_суточной_квоты(
    клиент, три_человека, monkeypatch
):
    """Квота считается по всем целям сразу, а не по каждой отдельно."""
    import routers.likes as likes_mod

    _заглушить_лайки(monkeypatch)
    monkeypatch.setattr(likes_mod, "superlikes_for", lambda tier: 1)

    from models.models import Profile, User
    Session = три_человека["Session"]
    третий = str(uuid.uuid4())
    async with Session() as s:
        s.add(User(id=третий, telegram_id=98))
        s.add(Profile(user_id=третий, display_name="Дима", gender="male", city="Уфа"))
        await s.commit()

    r = await клиент.post(
        "/api/likes", json={"target_id": три_человека["боря"], "type": "superlike"}
    )
    assert r.status_code == 200, r.text

    r = await клиент.post("/api/likes", json={"target_id": третий, "type": "superlike"})
    assert r.status_code == 429, (
        f"второй суперлайк при квоте 1 прошёл: {r.status_code} {r.text}"
    )


async def test_повторный_суперлайк_тому_же_человеку_не_упирается_в_квоту(
    клиент, три_человека, monkeypatch
):
    """Повтор того же суперлайка ничего не тратит — и отказывать в нём нельзя.

    Проверка квоты стоит до записи лайка, а суперлайк этой же паре УЖЕ лежит в
    подсчёте: без оговорки «только для нового» человек, потративший последний
    суперлайк, получал 429 на повторный запрос к тому же человеку — то есть
    отказ в том, что он уже купил и получил. Клиент повторяет запрос при
    потере сети, так что это не теоретический случай.
    """
    import routers.likes as likes_mod

    _заглушить_лайки(monkeypatch)
    monkeypatch.setattr(likes_mod, "superlikes_for", lambda tier: 1)

    боря = три_человека["боря"]
    r = await клиент.post("/api/likes", json={"target_id": боря, "type": "superlike"})
    assert r.status_code == 200, r.text

    r = await клиент.post("/api/likes", json={"target_id": боря, "type": "superlike"})
    assert r.status_code == 200, (
        f"повтор того же суперлайка отклонён по квоте: {r.status_code} {r.text}"
    )

    # И второй раз он не списался: бонусных не было, суточный один и тот же
    from models.models import Like
    Session = три_человека["Session"]
    async with Session() as s:
        лайки = (await s.execute(select(Like))).scalars().all()
    assert len(лайки) == 1, f"повтор завёл второй лайк: {len(лайки)}"


async def test_письмо_и_лайк_берут_одни_локи_в_одном_порядке(
    клиент, три_человека, monkeypatch
):
    """Порядок захвата обязан совпадать у письма и у встречного лайка.

    Оба пути заводят одну и ту же строку `Match` для пары и обоим нужны оба
    ключа: личный (суточная квота — писем и суперлайков) и парный (строка пары
    и взаимность). Пока письмо брало только личный, а лайк только парный, они
    не видели друг друга: письмо и встречный лайк создавали строку пары
    одновременно, и проигравший падал на `uq_match_pair` пятисоткой — ровно в
    тот момент, когда пара сошлась.

    Взять оба ключа мало: захватывать их в РАЗНОМ порядке — классический
    дедлок, два запроса упираются друг в друга насмерть. Поэтому сравниваются
    не сами ключи (пары разные), а форма: сначала личный, потом парный.
    """
    from models.models import Profile, User

    _заглушить_лайки(monkeypatch)

    аня, боря = три_человека["аня"], три_человека["боря"]
    Session = три_человека["Session"]
    третий = str(uuid.uuid4())
    async with Session() as s:
        s.add(User(id=третий, telegram_id=99))
        s.add(Profile(user_id=третий, display_name="Женя", gender="male", city="Тверь"))
        await s.commit()

    клиент.журнал_локов.clear()
    r = await клиент.post(
        "/api/matches/direct", json={"target_id": боря, "text": "письмо"}
    )
    assert r.status_code == 200, r.text
    письмо = _локи(клиент.журнал_локов)

    клиент.журнал_локов.clear()
    r = await клиент.post("/api/likes", json={"target_id": третий, "type": "like"})
    assert r.status_code == 200, r.text
    лайк = _локи(клиент.журнал_локов)

    for имя, взятые, партнёр in (("письмо", письмо, боря), ("лайк", лайк, третий)):
        u1, u2 = (аня, партнёр) if аня < партнёр else (партнёр, аня)
        assert взятые[:2] == [
            f"lock:dating:likes:{аня}",
            f"lock:dating:pair:{u1}:{u2}",
        ], f"{имя}: не тот набор или не тот порядок локов — {взятые}"
