"""Суточные лимиты В API — по-настоящему, через HTTP и WebSocket.

Бот проверяется отдельным сценарием (`test_daily_limits.py`, свой venv, свои
копии `services/quotas.py` и деки). Здесь — API, и он нуждается в своих
проверках не ради симметрии: у мини-аппа лимит живёт не в одной функции, а в
пяти точках входа в беседу (история сообщений, отправка, айсбрейкеры,
восстановление стрика, сокет) плюс список чатов, который обязан НЕ тратить
квоту. Проверка одной `open_match` в изоляции ничего из этого не покрывает: она
может быть безупречной, а роутер — читать отказ из `state.exhausted` и закрывать
последний разрешённый мэтч. Ровно так здесь и было.

Поэтому всё гоняется по-настоящему: живая БД (SQLite в файле), живой HTTP-клиент
поверх ASGI, живой сокет через `TestClient`. Утверждения — про то, что видит
клиент: код ответа, состав тела, число строк в базе.

Advisory-локи подменяются (`hashtextextended` есть только в Postgres), причём в
том же модуле, где их берут, — сам вызов из `open_match` при этом остаётся на
месте, и порядок захвата проверяется в `test_daily_limits.py`.
"""

from __future__ import annotations

import threading
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from services.plans import (
    LIKES_PER_DAY,
    MATCH_VIEWS_PER_DAY,
    TIER_AURORA,
    TIER_FREE,
)

ЛАЙКОВ = LIKES_PER_DAY[TIER_FREE]
МЭТЧЕЙ = MATCH_VIEWS_PER_DAY[TIER_FREE]

#: Целей для лайков заведомо больше лимита: иначе «отказали на 11-м» не
#: отличить от «анкеты кончились».
ЦЕЛЕЙ = ЛАЙКОВ + 3

#: Мэтчей больше квоты — нужен хотя бы один заведомо закрытый и один запасной.
МЭТЧЕЙ_ВСЕГО = МЭТЧЕЙ + 2


@pytest.fixture
async def живая_база(tmp_path):
    """Бесплатный Боря, платящая Аня, цели для лайков и мэтчи Бори.

    Уровень Ани — верхний из линейки, а не слово «plus»: фичи между уровнями
    уже переезжали, и захардкоженный тариф проверял бы вчерашнюю линейку.

    `created_at` мэтчей — возрастающий и наивный: SQLite отдаёт naive-время, а
    список чатов сортируется по свежести, и одинаковые метки сделали бы порядок
    открытий случайным от прогона к прогону.
    """
    from models.models import Base, Match, Profile, Subscription, User

    файл = tmp_path / "limits.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{файл}")
    async with engine.begin() as c:
        await c.run_sync(Base.metadata.create_all)

    Session = async_sessionmaker(engine, expire_on_commit=False)

    боря, аня = str(uuid.uuid4()), str(uuid.uuid4())
    цели: list[str] = []
    мэтчи: list[str] = []
    мэтчи_ани: list[str] = []
    tg = 1000

    def человек(s, uid: str, имя: str, пол: str = "female") -> None:
        nonlocal tg
        tg += 1
        s.add(User(
            id=uid, telegram_id=tg, role="user",
            last_seen_at=datetime.now(timezone.utc),
        ))
        s.add(Profile(
            user_id=uid, display_name=имя, gender=пол,
            birth_date=datetime(1997, 3, 3, tzinfo=timezone.utc),
            city="Москва", photos=[f"https://x/{uid}.jpg"],
            interests=["кино"], looking_for="any",
        ))

    async with Session() as s:
        человек(s, боря, "Боря", "male")
        человек(s, аня, "Аня")
        s.add(Subscription(
            user_id=аня, plan=TIER_AURORA,
            expires_at=datetime.now(timezone.utc) + timedelta(days=30),
        ))

        # Кому Боря будет ставить лайки
        for i in range(ЦЕЛЕЙ):
            цель = str(uuid.uuid4())
            человек(s, цель, f"Цель {i + 1}")
            цели.append(цель)

        # Мэтчи Бори и, теми же людьми, мэтчи Ани: платному уровню лимит
        # проверяется на том же объёме данных
        for i in range(МЭТЧЕЙ_ВСЕГО):
            собеседник = str(uuid.uuid4())
            человек(s, собеседник, f"Собеседник {i + 1}")
            когда = datetime(2026, 1, 1) + timedelta(minutes=i)
            борин = Match(
                id=str(uuid.uuid4()), user1_id=боря, user2_id=собеседник,
                is_active=True, created_at=когда,
            )
            анин = Match(
                id=str(uuid.uuid4()), user1_id=аня, user2_id=собеседник,
                is_active=True, created_at=когда,
            )
            s.add_all([борин, анин])
            мэтчи.append(борин.id)
            мэтчи_ани.append(анин.id)

        await s.commit()

    yield {
        "engine": engine, "Session": Session,
        "боря": боря, "аня": аня,
        "цели": цели, "мэтчи": мэтчи, "мэтчи_ани": мэтчи_ани,
    }
    await engine.dispose()


def _без_advisory(monkeypatch, *модули) -> None:
    """Убрать `pg_advisory_xact_lock` из SQL, оставив остальные запросы как есть.

    Подменяется `sa_text` в КАЖДОМ модуле, который берёт лок: имя импортировано
    внутрь модуля, и подмена в `sqlalchemy` до него не дошла бы.
    """
    for мод in модули:
        настоящий = мод.sa_text
        монк = (lambda н: lambda sql: н("SELECT 1") if "advisory" in sql else н(sql))(
            настоящий
        )
        monkeypatch.setattr(мод, "sa_text", монк)


@pytest.fixture
async def клиент(app, живая_база, monkeypatch):
    """HTTP-клиент на живой БД. `от_имени(uid)` переключает пользователя."""
    from database.connection import get_session
    from middleware.auth import get_current_user
    from models.models import User
    import routers.likes as likes_mod
    import services.quotas as quotas_mod

    Session = живая_база["Session"]
    _без_advisory(monkeypatch, likes_mod, quotas_mod)

    # Рассылка «вы понравились» и «мэтч» уходит в Redis и APNs, которых в
    # тестах нет, причём УЖЕ ПОСЛЕ коммита лайка. Незаглушённая, она превращает
    # успешный лайк в 500 — то есть ломает ровно те ответы, по которым здесь
    # считается расход квоты. Модерация текста ходит к внешней модели и
    # проверяется своими тестами.
    async def _ничего(*_a, **_kw):
        return None

    async def _пропустить(_текст):
        return {"blocked": False}

    for имя in (
        "publish_match", "publish_new_like", "publish_new_match_for_bot",
        "notify_new_match", "_push_match_notifications", "log_moderation",
    ):
        monkeypatch.setattr(likes_mod, имя, _ничего)
    monkeypatch.setattr(likes_mod, "moderate_text", _пропустить)

    текущий = {"id": живая_база["боря"]}

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

    было = {
        get_session: app.dependency_overrides.get(get_session),
        get_current_user: app.dependency_overrides.get(get_current_user),
    }
    app.dependency_overrides[get_session] = _sess
    app.dependency_overrides[get_current_user] = _user
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as c:
            c.от_имени = lambda uid: текущий.update(id=uid)  # type: ignore[attr-defined]
            yield c
    finally:
        # app — session-scoped: возвращаем ровно то, что было до нас
        for ключ, значение in было.items():
            if значение is None:
                app.dependency_overrides.pop(ключ, None)
            else:
                app.dependency_overrides[ключ] = значение


async def _просмотров(Session, user_id: str) -> int:
    """Сколько открытий записано в квоту — по базе, а не по ответу API."""
    from models.models import MatchView

    async with Session() as s:
        return (await s.execute(
            select(func.count(MatchView.id)).where(MatchView.user_id == user_id)
        )).scalar_one()


async def _вердикт() -> dict:
    """Модерация пропускает: она ходит к внешней модели и проверяется своими
    тестами, а здесь важен только расход квоты."""
    return {"blocked": False}


# ════════════════════════════════════════════════════════════════
#  Лайки: ровно норма, и ни один не украден у пропуска
# ════════════════════════════════════════════════════════════════

async def test_все_лайки_внутри_нормы_проходят(клиент, живая_база):
    """Десятый лайк из десяти — 200, а не 429.

    Ошибка на единицу (`>=` вместо `>`, лишний `+1`) отбирает у бесплатного
    уровня последнее действие, и тест «одиннадцатый отклонён» остаётся зелёным:
    отказ-то есть. Поэтому проверяется КАЖДЫЙ ответ внутри квоты.
    """
    for i in range(ЛАЙКОВ):
        r = await клиент.post(
            "/api/likes", json={"target_id": живая_база["цели"][i], "type": "like"}
        )
        assert r.status_code == 200, (
            f"лайк №{i + 1} из {ЛАЙКОВ} отклонён внутри квоты: "
            f"{r.status_code} {r.text}"
        )
        assert r.json()["liked"] is True, f"лайк №{i + 1} не записан: {r.text}"


async def test_лайк_сверх_нормы_даёт_429_и_не_попадает_в_базу(клиент, живая_база):
    """Отказ обязан быть настоящим: без строки в базе.

    Записанный «отклонённый» лайк — худший вариант: квота не тратится, но
    взаимность возникает, и человек получает мэтч, в котором ему отказали.
    Заодно исчезает возможность повторить действие завтра — цель уже лайкнута.
    """
    from models.models import Like

    for i in range(ЛАЙКОВ):
        await клиент.post(
            "/api/likes", json={"target_id": живая_база["цели"][i], "type": "like"}
        )

    сверх = живая_база["цели"][ЛАЙКОВ]
    r = await клиент.post("/api/likes", json={"target_id": сверх, "type": "like"})
    assert r.status_code == 429, f"лайк сверх квоты прошёл: {r.status_code} {r.text}"
    assert str(ЛАЙКОВ) in r.json()["detail"], (
        f"в отказе не назван лимит — шторке нечего показать: {r.text}"
    )

    async with живая_база["Session"]() as s:
        записан = (await s.execute(
            select(Like).where(Like.liked_id == сверх)
        )).scalar_one_or_none()
    assert записан is None, "отклонённый лайк всё равно записан в базу"


async def test_пропуск_бесплатен_до_и_после_исчерпания(клиент, живая_база):
    """Лимит на «👎» — это запрет ЛИСТАТЬ деку.

    Человек, потративший десять лайков, не смог бы даже пролистать анкеты
    дальше: продукт выглядел бы сломанным, а не ограниченным.
    """
    цели = живая_база["цели"]

    r = await клиент.post("/api/likes", json={"target_id": цели[-1], "type": "pass"})
    assert r.status_code == 200, f"пропуск упёрся в лимит: {r.text}"

    for i in range(ЛАЙКОВ):
        r = await клиент.post("/api/likes", json={"target_id": цели[i], "type": "like"})
        assert r.status_code == 200, f"лайк №{i + 1} внутри квоты отклонён: {r.text}"

    r = await клиент.post("/api/likes", json={"target_id": цели[-2], "type": "pass"})
    assert r.status_code == 200, (
        f"после исчерпания лайков пропуск запрещён — деку не пролистать: {r.text}"
    )


async def test_повторный_лайк_той_же_анкеты_бесплатен(клиент, живая_база):
    """Этот лайк уже лежит в подсчёте — отказ отбирал бы израсходованное.

    Так выглядит повторное нажатие после обрыва сети.
    """
    цели = живая_база["цели"]
    for i in range(ЛАЙКОВ):
        await клиент.post("/api/likes", json={"target_id": цели[i], "type": "like"})

    r = await клиент.post("/api/likes", json={"target_id": цели[0], "type": "like"})
    assert r.status_code == 200, (
        f"повторный лайк уже лайкнутой анкеты упёрся в лимит: {r.text}"
    )


async def test_пропуск_переделанный_в_лайк_тратит_квоту(клиент, живая_база):
    """Дырка, через которую лимит обходится целиком.

    Пропуск бесплатен, и если «лайк по уже размеченной анкете» считать
    бесплатным без разбора прежнего типа, стратегия «сначала 👎 всем, потом
    ❤️ всем» даёт неограниченные лайки. Смена `pass` → `like` — НОВЫЙ лайк.
    """
    цели = живая_база["цели"]

    r = await клиент.post("/api/likes", json={"target_id": цели[-1], "type": "pass"})
    assert r.status_code == 200, f"пропуск отклонён: {r.text}"

    for i in range(ЛАЙКОВ):
        await клиент.post("/api/likes", json={"target_id": цели[i], "type": "like"})

    r = await клиент.post("/api/likes", json={"target_id": цели[-1], "type": "like"})
    assert r.status_code == 429, (
        "пропуск, переделанный в лайк, прошёл сверх квоты — лимит обходится "
        f"через «сначала всем 👎»: {r.status_code} {r.text}"
    )


async def test_суперлайк_тратит_суточный_лимит_лайков(клиент, живая_база):
    """У суперлайка своя квота СВЕРХУ, а не вместо.

    Если суточный лимит его не считает, «10 лайков в сутки» обходится
    суперлайками ровно на число суперлайков — и обходится молча.
    """
    цели = живая_база["цели"]
    for i in range(ЛАЙКОВ):
        await клиент.post("/api/likes", json={"target_id": цели[i], "type": "like"})

    r = await клиент.post(
        "/api/likes", json={"target_id": цели[ЛАЙКОВ], "type": "superlike"}
    )
    assert r.status_code == 429, (
        f"суперлайк прошёл сверх суточного лимита лайков: {r.status_code} {r.text}"
    )


# ════════════════════════════════════════════════════════════════
#  Открытые мэтчи: норма открывается целиком, включая последний
# ════════════════════════════════════════════════════════════════

async def test_все_мэтчи_внутри_нормы_открываются(клиент, живая_база):
    """Третье открытие из трёх разрешено — здесь и жила ошибка.

    `open_match` возвращал состояние ПОСЛЕ записи, а вызывающий читал отказ из
    `state.exhausted`. Последнее открытие внутри квоты проходило, оставляло
    «осталось 0» — и тем самым выглядело как отказ: человеку обещали три мэтча,
    а показывали два. Ни один тест этого не видел, потому что все они проверяли
    `open_match` мимо роутера.
    """
    for i in range(МЭТЧЕЙ):
        r = await клиент.get(f"/api/matches/{живая_база['мэтчи'][i]}/messages")
        assert r.status_code == 200, (
            f"мэтч №{i + 1} из {МЭТЧЕЙ} закрыт внутри суточной нормы: "
            f"{r.status_code} {r.text}"
        )

    assert await _просмотров(живая_база["Session"], живая_база["боря"]) == МЭТЧЕЙ, (
        "открытий записано не столько, сколько разрешено"
    )


async def test_мэтч_сверх_нормы_даёт_429_и_не_тратит_слот(клиент, живая_база):
    """Отказ не имеет права списывать открытие.

    Иначе отказ съедал бы слот, который не выдал: человек упирается в лимит,
    ждёт сутки — и обнаруживает, что «вернувшийся» слот уже потрачен на тот
    самый отказ.
    """
    Session = живая_база["Session"]
    for i in range(МЭТЧЕЙ):
        await клиент.get(f"/api/matches/{живая_база['мэтчи'][i]}/messages")

    до = await _просмотров(Session, живая_база["боря"])
    r = await клиент.get(f"/api/matches/{живая_база['мэтчи'][МЭТЧЕЙ]}/messages")
    assert r.status_code == 429, (
        f"мэтч сверх суточной нормы открылся: {r.status_code} {r.text}"
    )
    assert str(МЭТЧЕЙ) in r.json()["detail"], (
        f"в отказе не назван лимит открытий: {r.text}"
    )
    assert await _просмотров(Session, живая_база["боря"]) == до, (
        "отклонённое открытие всё равно записалось в квоту"
    )


async def test_повторный_вход_в_открытый_чат_не_тратит_слот(клиент, живая_база):
    """Открытый мэтч остаётся открытым до конца окна.

    Иначе выход и повторный вход в тот же чат съедали бы квоту, и «три мэтча в
    сутки» означало бы «три нажатия в сутки». Проверка идёт при УЖЕ потраченной
    квоте — именно в этом состоянии идемпотентность и ломалась: слот не
    тратится, а состояние лимита при этом `exhausted`.
    """
    Session = живая_база["Session"]
    for i in range(МЭТЧЕЙ):
        await клиент.get(f"/api/matches/{живая_база['мэтчи'][i]}/messages")

    первый = живая_база["мэтчи"][0]
    r = await клиент.get(f"/api/matches/{первый}/messages")
    assert r.status_code == 200, (
        f"повторный вход в уже открытый чат закрыт лимитом: {r.status_code} {r.text}"
    )
    assert await _просмотров(Session, живая_база["боря"]) == МЭТЧЕЙ, (
        "повторный вход в уже открытый чат создал вторую запись в квоте"
    )


async def test_отправка_сообщения_не_тратит_второй_слот(
    клиент, живая_база, monkeypatch
):
    """К беседе ведут несколько путей, и слот у них один.

    История и отправка — два разных обработчика, каждый со своим
    `_открыть_мэтч`. Проверка идёт при ИСЧЕРПАННОЙ квоте и в уже открытом чате:
    только в этом состоянии видно разницу между «слот не тратится» и «слот
    тратится, но места ещё есть». На свободной квоте оба варианта дают 200, а
    строк в `MatchView` не прибавляется ни в одном — пара (человек, мэтч)
    уникальна, повторное открытие обновляет отметку на месте. То есть считать
    строки здесь бесполезно: мимо этого и прошла бы регрессия.
    """
    import routers.matches as matches_mod
    import services.chat_delivery as delivery

    Session = живая_база["Session"]
    monkeypatch.setattr(delivery, "async_session_factory", Session)
    _без_advisory(monkeypatch, delivery)

    async def _ничего(*_a, **_kw):
        return None

    monkeypatch.setattr(matches_mod, "fan_out", _ничего)
    monkeypatch.setattr(matches_mod, "log_moderation", _ничего)
    monkeypatch.setattr(matches_mod, "moderate_text", lambda _т: _вердикт())

    for i in range(МЭТЧЕЙ):
        r = await клиент.get(f"/api/matches/{живая_база['мэтчи'][i]}/messages")
        assert r.status_code == 200, f"мэтч №{i + 1} внутри квоты закрыт: {r.text}"

    мэтч = живая_база["мэтчи"][0]

    r = await клиент.get(f"/api/matches/{мэтч}/messages")
    assert r.status_code == 200, (
        f"история открытого чата закрыта на исчерпанной квоте: "
        f"{r.status_code} {r.text}"
    )
    r = await клиент.post(f"/api/matches/{мэтч}/messages", json={"text": "привет"})
    assert r.status_code in (200, 201), (
        f"ответить в открытый чат нельзя на исчерпанной квоте: "
        f"{r.status_code} {r.text}"
    )

    assert await _просмотров(Session, живая_база["боря"]) == МЭТЧЕЙ, (
        "чтение и отправка в уже открытом чате добавили открытий в квоту"
    )


async def test_список_чатов_не_тратит_квоту(клиент, живая_база):
    """Один заход в список не имеет права сжечь все суточные открытия.

    Список чатов — витрина подписки: он показывает, что мэтчи есть. Списывать
    за его показ значит отбирать квоту за то, чего человек не открывал.
    """
    Session = живая_база["Session"]

    r = await клиент.get("/api/matches")
    assert r.status_code == 200, f"список чатов не отдался: {r.text}"
    assert len(r.json()) == МЭТЧЕЙ_ВСЕГО, f"мэтчи потерялись из списка: {r.text}"
    assert not any(м["locked"] for м in r.json()), (
        f"мэтчи закрыты до первого открытия — квота тратится на список: {r.text}"
    )

    assert await _просмотров(Session, живая_база["боря"]) == 0, (
        "показ списка чатов записал открытия в квоту"
    )
    # И после исчерпания список всё равно ничего не списывает
    for i in range(МЭТЧЕЙ):
        await клиент.get(f"/api/matches/{живая_база['мэтчи'][i]}/messages")
    await клиент.get("/api/matches")
    assert await _просмотров(Session, живая_база["боря"]) == МЭТЧЕЙ, (
        "список чатов списал открытия после исчерпания квоты"
    )


async def test_закрытые_строки_списка_редактируются_на_сервере(клиент, живая_база):
    """Ни имени, ни фото, ни города — но счётчик непрочитанных остаётся.

    Скрывать на клиенте нельзя: данные уже пришли, и их видно во вкладке
    «сеть» за один клик. А непрочитанные — честная цифра и главный повод
    оформить подписку: «вам написали, но кто — не покажем».
    """
    from models.models import Match, Message

    Session = живая_база["Session"]
    закрытый = живая_база["мэтчи"][МЭТЧЕЙ]

    async with Session() as s:
        мэтч = (await s.execute(
            select(Match).where(Match.id == закрытый)
        )).scalar_one()
        s.add(Message(
            match_id=закрытый, sender_id=мэтч.user2_id, text="секрет",
            created_at=datetime.now(timezone.utc),
        ))
        await s.commit()

    for i in range(МЭТЧЕЙ):
        await клиент.get(f"/api/matches/{живая_база['мэтчи'][i]}/messages")

    r = await клиент.get("/api/matches")
    assert r.status_code == 200, r.text
    строки = {м["id"]: м for м in r.json()}

    строка = строки[закрытый]
    assert строка["locked"] is True, f"мэтч сверх нормы пришёл открытым: {строка}"
    assert not строка["partner"]["display_name"], (
        f"в закрытой строке осталось имя: {строка['partner']}"
    )
    assert not строка["partner"]["photos"], (
        f"в закрытой строке осталось фото: {строка['partner']}"
    )
    assert not строка["partner"]["city"], (
        f"в закрытой строке остался город: {строка['partner']}"
    )
    assert строка["partner"]["age"] is None, (
        f"в закрытой строке остался возраст: {строка['partner']}"
    )
    assert строка["last_message"] is None, (
        f"в закрытой строке осталось превью переписки: {строка}"
    )
    assert строка["unread_count"] == 1, (
        f"счётчик непрочитанных потерялся вместе с именем: {строка}"
    )

    # Открытые строки при этом полноценные — замок не должен зачистить всё
    открытая = строки[живая_база["мэтчи"][0]]
    assert открытая["locked"] is False, f"открытый мэтч под замком: {открытая}"
    assert открытая["partner"]["display_name"].startswith("Собеседник"), (
        f"открытый мэтч потерял имя собеседника: {открытая['partner']}"
    )


async def test_чужой_мэтч_остаётся_404_а_не_замком(клиент, живая_база):
    """Проверка участия идёт ДО лимита — иначе это IDOR, вернувшийся с фичей.

    Если бы `_открыть_мэтч` встал перед `_get_own_match`, подстановка чужого id
    отвечала бы 429 «оформите подписку» вместо 404: сам факт существования
    чужой беседы подтверждался бы ответом, а на исчерпанной квоте лимит ещё и
    списывал бы открытие на чужой мэтч.
    """
    Session = живая_база["Session"]
    чужой = живая_база["мэтчи_ани"][0]

    r = await клиент.get(f"/api/matches/{чужой}/messages")
    assert r.status_code == 404, (
        f"чужой мэтч ответил {r.status_code} вместо 404: {r.text}"
    )
    assert await _просмотров(Session, живая_база["боря"]) == 0, (
        "запрос чужого мэтча списал открытие"
    )

    # И на исчерпанной квоте — по-прежнему 404, а не 429
    for i in range(МЭТЧЕЙ):
        await клиент.get(f"/api/matches/{живая_база['мэтчи'][i]}/messages")
    r = await клиент.get(f"/api/matches/{чужой}/messages")
    assert r.status_code == 404, (
        f"на исчерпанной квоте чужой мэтч ответил {r.status_code} — лимит "
        f"подменил проверку участия: {r.text}"
    )


async def test_замок_держат_все_входы_в_беседу(клиент, живая_база, monkeypatch):
    """Одна незакрытая точка входа обнуляет лимит целиком.

    Читать чужой чат через айсбрейкеры ничем не хуже, чем через историю
    сообщений: у обоих на выходе анкета партнёра и повод остаться. Пути
    добавлялись в разное время, каждый со своим `_открыть_мэтч`, и проверка
    только `/messages` оставляла бы остальные без присмотра.

    Каждый путь проверяется на ЗАКРЫТОМ мэтче при исчерпанной квоте: 429 обязан
    прийти до всякой работы — до похода к модели за айсбрейкерами и до записи
    стрика, иначе отказ стоил бы денег за AI-запрос.
    """
    import routers.matches as matches_mod
    import services.chat_delivery as delivery

    Session = живая_база["Session"]
    monkeypatch.setattr(delivery, "async_session_factory", Session)
    _без_advisory(monkeypatch, delivery)

    async def _ничего(*_a, **_kw):
        return None

    monkeypatch.setattr(matches_mod, "fan_out", _ничего)
    monkeypatch.setattr(matches_mod, "log_moderation", _ничего)
    monkeypatch.setattr(matches_mod, "moderate_text", lambda _т: _вердикт())

    for i in range(МЭТЧЕЙ):
        await клиент.get(f"/api/matches/{живая_база['мэтчи'][i]}/messages")

    закрытый = живая_база["мэтчи"][МЭТЧЕЙ]
    пути = {
        "история": клиент.get(f"/api/matches/{закрытый}/messages"),
        "отправка": клиент.post(
            f"/api/matches/{закрытый}/messages", json={"text": "привет"}
        ),
        "айсбрейкеры": клиент.get(f"/api/matches/{закрытый}/icebreakers"),
        "стрик": клиент.post(f"/api/matches/{закрытый}/revive-streak"),
    }
    for имя, запрос in пути.items():
        r = await запрос
        assert r.status_code == 429, (
            f"путь «{имя}» открывает мэтч в обход суточного лимита: "
            f"{r.status_code} {r.text}"
        )
        # Отказ именно по лимиту открытий, а не любой другой 429 на этом
        # маршруте: у восстановления стрика свой 429 («уже восстанавливали»),
        # и он бы сделал проверку вечнозелёной
        assert "подписку" in r.json()["detail"], (
            f"путь «{имя}» ответил 429 не по лимиту открытий: {r.text}"
        )

    assert await _просмотров(Session, живая_база["боря"]) == МЭТЧЕЙ, (
        "отклонённые попытки записали открытия в квоту"
    )


# ════════════════════════════════════════════════════════════════
#  Кто платит — тому лимита нет
# ════════════════════════════════════════════════════════════════

async def test_подписчику_не_закрывают_ни_один_мэтч(клиент, живая_база):
    """Закрытый чат на платном уровне — это возврат денег.

    Мэтчей у Ани заведомо больше бесплатной квоты: безлимит обязан быть на
    самом лимите, а не только на счётчике в ответе.
    """
    Session = живая_база["Session"]
    клиент.от_имени(живая_база["аня"])

    for i, мэтч in enumerate(живая_база["мэтчи_ани"]):
        r = await клиент.get(f"/api/matches/{мэтч}/messages")
        assert r.status_code == 200, (
            f"подписчику закрыли мэтч №{i + 1} суточным лимитом: "
            f"{r.status_code} {r.text}"
        )

    r = await клиент.get("/api/matches")
    assert not any(м["locked"] for м in r.json()), (
        f"в списке подписчика есть закрытые чаты: {r.text}"
    )
    # Безлимиту нечего записывать: строки в квоте — это расход, которого нет
    assert await _просмотров(Session, живая_база["аня"]) == 0, (
        "подписчику пишутся открытия в квоту — при отмене подписки они "
        "мгновенно превратятся в исчерпанный лимит"
    )


async def test_подписчику_не_отказывают_в_лайках(клиент, живая_база):
    """Лайков заведомо больше бесплатной нормы, и все обязаны пройти."""
    клиент.от_имени(живая_база["аня"])

    for i in range(ЦЕЛЕЙ):
        r = await клиент.post(
            "/api/likes", json={"target_id": живая_база["цели"][i], "type": "like"}
        )
        assert r.status_code == 200, (
            f"подписчику отказали в лайке №{i + 1} из {ЦЕЛЕЙ}: "
            f"{r.status_code} {r.text}"
        )


# ════════════════════════════════════════════════════════════════
#  Счётчик для шторки: /api/likes/limits
# ════════════════════════════════════════════════════════════════

async def test_счётчик_лимитов_убывает_и_называет_время_возврата(клиент, живая_база):
    """Дека рисует «осталось N» до первого свайпа, шторка — «вернётся в HH:MM».

    Без `reset_at` остаётся «попробуйте позже» без ответа на «когда»: окно
    скользящее, календарная полночь тут ничего не значит.
    """
    r = await клиент.get("/api/likes/limits")
    assert r.status_code == 200, r.text
    свежий = r.json()
    assert свежий["likes_left"] == ЛАЙКОВ, f"счётчик лайков не полон: {свежий}"
    assert свежий["likes_total"] == ЛАЙКОВ, f"назван не тот лимит лайков: {свежий}"
    assert свежий["matches_left"] == МЭТЧЕЙ, f"счётчик мэтчей не полон: {свежий}"
    assert свежий["matches_total"] == МЭТЧЕЙ, f"назван не тот лимит мэтчей: {свежий}"
    assert свежий["is_premium"] is False, f"бесплатный уровень как платный: {свежий}"
    # Ничего не потрачено — возвращать нечего, и время возврата не выдумывается
    assert свежий["likes_reset_at"] is None, f"время возврата без расхода: {свежий}"
    assert свежий["matches_reset_at"] is None, f"время возврата без расхода: {свежий}"

    await клиент.post(
        "/api/likes", json={"target_id": живая_база["цели"][0], "type": "like"}
    )
    await клиент.get(f"/api/matches/{живая_база['мэтчи'][0]}/messages")

    r = await клиент.get("/api/likes/limits")
    после = r.json()
    assert после["likes_left"] == ЛАЙКОВ - 1, f"лайк не списался в счётчике: {после}"
    assert после["matches_left"] == МЭТЧЕЙ - 1, f"мэтч не списался в счётчике: {после}"
    assert после["likes_reset_at"] is not None, (
        f"нет времени возврата лайка — шторке нечего показать: {после}"
    )
    assert после["matches_reset_at"] is not None, (
        f"нет времени возврата открытия: {после}"
    )


async def test_счётчик_не_показывает_подписчику_осталось_ноль(клиент, живая_база):
    """`-1`, а не `0`: нулём безлимит обозначать нельзя.

    Клиент рисует «осталось 0» и шторку подписки тому, кто её уже оплатил.
    """
    клиент.от_имени(живая_база["аня"])

    r = await клиент.get("/api/likes/limits")
    assert r.status_code == 200, r.text
    лимиты = r.json()
    assert лимиты["is_premium"] is True, f"подписчик прочитан как бесплатный: {лимиты}"
    assert лимиты["likes_left"] == -1, f"подписчику показан остаток лайков: {лимиты}"
    assert лимиты["matches_left"] == -1, f"подписчику показан остаток мэтчей: {лимиты}"
    assert лимиты["likes_total"] == -1, f"подписчику показан лимит лайков: {лимиты}"
    assert лимиты["matches_total"] == -1, f"подписчику показан лимит мэтчей: {лимиты}"


# ════════════════════════════════════════════════════════════════
#  Сокет: вход в беседу минуя HTTP
# ════════════════════════════════════════════════════════════════

@pytest.fixture
def сокет_окружение(живая_база, monkeypatch):
    """Направить WebSocket-чат на тестовую БД.

    Сокет ходит в базу не через зависимость FastAPI, а через
    `async_session_factory` — подменять надо саму фабрику, причём в модуле
    чата: имя импортировано внутрь. Advisory-лок из `open_match` убираем там же,
    где он берётся, — в `services/quotas.py`.

    Это второй вход в беседу, и он самый опасный: клиент открывает сокет сразу
    при входе в чат, до всякого HTTP-запроса за историей. Незакрытый здесь
    лимит не «протекал бы» — его бы просто не было.
    """
    import routers.chat as chat_mod
    import services.quotas as quotas_mod

    monkeypatch.setattr(chat_mod, "async_session_factory", живая_база["Session"])
    _без_advisory(monkeypatch, quotas_mod)

    async def _ничего(*_a, **_kw):
        return None

    monkeypatch.setattr(chat_mod, "fan_out", _ничего)
    return живая_база


def _токен(живая_база, uid: str) -> str:
    from middleware.auth import create_access_token

    return create_access_token(uid, 1)


def _событие_сокета(ws, секунд: float = 5.0) -> dict:
    """Следующее событие сокета — с потолком по времени.

    `ws.receive()` блокирует поток до конца времён, и это делает тест ХУЖЕ
    отсутствующего: снятая проверка лимита в `routers/chat.py` не роняет прогон,
    а вешает его. Локально `pytest` перестаёт возвращать управление, в CI
    прогон умирает по общему таймауту — без имени теста и без строки, то есть
    ровно та регрессия, которую этот файл обязан назвать, остаётся неназванной.
    Проверено: без потолка мутация «пустить всех в сокет» вешала весь модуль.

    Ждём в потоке-демоне, а не в приватном `_send_rx` сессии: публичного приёма
    с таймаутом у starlette нет, а лезть в её внутренности значит ломаться на
    следующем обновлении. Поток остаётся висеть в `portal.call` — выход из
    `websocket_connect` отменяет задачу приложения и освобождает его.
    """
    ящик: list[dict] = []

    def читать() -> None:
        try:
            ящик.append(ws.receive())
        except Exception as ошибка:  # noqa: BLE001 — это диагностика, не обработка
            ящик.append({"type": "чтение сорвалось", "detail": repr(ошибка)})

    поток = threading.Thread(target=читать, daemon=True)
    поток.start()
    поток.join(секунд)
    if not ящик:
        pytest.fail(
            f"сервер не прислал ни одного события за {секунд} с — сокет остался "
            f"живым. Суточный лимит на этом пути не проверяется: клиент "
            f"открывает сокет при входе в чат, и закрытый мэтч читается через "
            f"него в обход HTTP."
        )
    return ящик[0]


async def test_сокет_закрывается_на_мэтче_сверх_нормы(app, сокет_окружение):
    """Код закрытия 4029, и открытие не записано.

    Отдельный код, а не 4004 «мэтч не найден»: клиент по нему показывает шторку
    подписки. Одинаковый код на «нет такого чата» и «оформите подписку» оставил
    бы человека с сообщением «чат не найден» — он бы решил, что беседа пропала.

    Квоту тратим через `open_match` напрямую, а не по HTTP: важно проверить сам
    сокет, а не связку двух путей, и на исчерпанной квоте они всё равно смотрят
    в одну таблицу.
    """
    from fastapi.testclient import TestClient
    from services.quotas import open_match

    Session = сокет_окружение["Session"]
    боря = сокет_окружение["боря"]

    async with Session() as s:
        for i in range(МЭТЧЕЙ):
            итог = await open_match(s, боря, сокет_окружение["мэтчи"][i])
            assert итог.granted, f"открытие №{i + 1} внутри квоты не выдано"
        await s.commit()

    закрытый = сокет_окружение["мэтчи"][МЭТЧЕЙ]
    токен = _токен(сокет_окружение, боря)

    with TestClient(app) as client:
        with client.websocket_connect(
            f"/ws/chat/{закрытый}?token={токен}"
        ) as ws:
            # Сервер закрывает соединение сам — читаем причину закрытия
            событие = _событие_сокета(ws)

    assert событие["type"] == "websocket.close", (
        f"сокет на закрытом мэтче не закрылся: {событие}"
    )
    assert событие["code"] == 4029, (
        f"сокет закрыт кодом {событие.get('code')} вместо 4029 — клиент покажет "
        f"«чат не найден» вместо шторки подписки: {событие}"
    )

    assert await _просмотров(Session, боря) == МЭТЧЕЙ, (
        "отклонённый сокет всё равно записал открытие в квоту"
    )


async def test_сокет_на_открытом_мэтче_не_тратит_второй_слот(app, сокет_окружение):
    """Уже открытый чат подключается и на исчерпанной квоте.

    Клиент открывает сокет при каждом входе в чат и переподключается после
    любого обрыва сети. Если сокет тратит слот, «три мэтча в сутки» кончаются
    на трёх поездках в метро — при том что человек не открыл ни одного нового
    чата.
    """
    from fastapi.testclient import TestClient
    from services.quotas import open_match

    Session = сокет_окружение["Session"]
    боря = сокет_окружение["боря"]

    async with Session() as s:
        for i in range(МЭТЧЕЙ):
            await open_match(s, боря, сокет_окружение["мэтчи"][i])
        await s.commit()

    открытый = сокет_окружение["мэтчи"][0]
    токен = _токен(сокет_окружение, боря)

    with TestClient(app) as client:
        with client.websocket_connect(
            f"/ws/chat/{открытый}?token={токен}"
        ) as ws:
            # Сокет живой: пинг не закрывает соединение, а закрытие пришло бы
            # немедленно и следующей же операцией
            ws.send_json({"type": "ping"})
            ws.send_json({"type": "typing"})

    assert await _просмотров(Session, боря) == МЭТЧЕЙ, (
        "переподключение к уже открытому чату списало ещё одно открытие"
    )
