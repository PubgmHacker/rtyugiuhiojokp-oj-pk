"""Центр уведомлений (Блок В5): лента событий без собственного экрана.

Мэтчи, лайки и сообщения сюда не пишутся — у них есть вкладки с бейджами
(routers/badges.py). В ленту попадает то, чему больше некуда деться: итог
жалобы и галочка верификации, пришедшая вебхуком при закрытой шторке.

Три обещания, которые здесь закреплены:

* уведомление пишется В СЕССИИ события, а не best-effort после — откат
  события откатывает и уведомление, полуправда в ленте невозможна;
* дозировка та же, что у рассылки: итог жалобы — на переходе порога,
  галочка — один раз (ретрай вебхука отсекается ранним выходом по
  is_verified), в ленте нет дублей;
* тексты собирает КЛИЕНТ из kind+payload — API не знает языка интерфейса.
  Поэтому каждый kind и каждый outcome обязаны иметь ветку в
  web/src/pages/Notifications.tsx, иначе событие молча спрячется.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

КОРЕНЬ = Path(__file__).resolve().parents[2]


# ════════════════════════════════════════════════════════════════
#  Сервис: единственная дверь в ленту
# ════════════════════════════════════════════════════════════════

class _Сессия:
    """Стаб: копит add, считает flush. Для сервиса execute не нужен."""

    def __init__(self):
        self.добавлено: list = []
        self.флашей = 0

    def add(self, объект):
        self.добавлено.append(объект)

    async def flush(self):
        self.флашей += 1


async def test_неизвестный_вид_не_пишется():
    """Опечатка в kind — ошибка кода, а не невидимая строка в базе: клиент
    молча прячет незнакомые виды, и такие записи копились бы вечно."""
    from services.notifications import записать_уведомление

    сессия = _Сессия()
    with pytest.raises(ValueError):
        await записать_уведомление(сессия, "у1", "report_outcom", {})
    assert сессия.добавлено == [], "проверка вида обязана стоять до add"


async def test_сервис_пишет_и_флашит_но_не_коммитит():
    """Транзакцией владеет событие: сервис даёт строке id через flush,
    а фиксирует её тот, кто фиксирует само событие."""
    from services.notifications import ВИДЫ, записать_уведомление

    сессия = _Сессия()
    строка = await записать_уведомление(
        сессия, "у1", "report_outcome", {"outcome": "hidden"}
    )
    assert сессия.добавлено == [строка]
    assert сессия.флашей == 1
    assert (строка.user_id, строка.kind) == ("у1", "report_outcome")
    assert строка.payload == {"outcome": "hidden"}
    assert строка.read_at is None, "новое событие рождается непрочитанным"
    assert not hasattr(сессия, "commit"), (
        "стаб без commit: попытка коммита в сервисе уронила бы этот тест"
    )
    assert set(ВИДЫ) == {"report_outcome", "verification_approved"}


async def test_пустой_payload_не_обязателен():
    from services.notifications import записать_уведомление

    строка = await записать_уведомление(_Сессия(), "у1", "verification_approved")
    assert строка.payload == {}


# ════════════════════════════════════════════════════════════════
#  Write-point: эскалация жалоб (routers/report.py)
# ════════════════════════════════════════════════════════════════

class _Результат:
    def __init__(self, значение=None, список=None):
        self._значение = значение
        self._список = список or []

    def scalar_one_or_none(self):
        return self._значение

    def scalar(self):
        return self._значение

    def scalars(self):
        return SimpleNamespace(all=lambda: list(self._список))

    def all(self):
        return list(self._список)


class _СессияПоПлану(_Сессия):
    """Ответы на execute в порядке вызовов (стиль test_report_feedback)."""

    def __init__(self, *ответы: _Результат):
        super().__init__()
        self.ответы = list(ответы)

    async def execute(self, _запрос):
        assert self.ответы, "запросов больше, чем заготовленных ответов"
        return self.ответы.pop(0)


def _уведомления(сессия) -> list:
    from models.models import Notification

    return [о for о in сессия.добавлено if isinstance(о, Notification)]


@pytest.fixture
def рассылка(monkeypatch):
    """Заглушить Redis/APNs-рассылку в обоих входах модерации и запомнить,
    что и кому ушло — лента и рассылка обязаны говорить одно и то же."""
    from routers import admin, report

    ушло: list[tuple[list, str]] = []

    async def _тихо(ids, итог):
        ушло.append((list(ids), итог))

    monkeypatch.setattr(report, "notify_report_outcome", _тихо)
    monkeypatch.setattr(admin, "notify_report_outcome", _тихо)
    return ушло


async def test_эскалация_кладёт_итог_каждому_жалобщику(рассылка):
    """Третья жалоба прячет анкету — и все трое находят итог в ленте,
    даже те, кто вошёл без Telegram и с выключенными пушами."""
    from routers import report

    анкета = SimpleNamespace(user_id="цель", is_incognito=False)
    сессия = _СессияПоПлану(
        _Результат(значение=SimpleNamespace(
            id="цель", role="user", telegram_id=5, is_banned=False,
        )),
        _Результат(значение=None),                # дубля жалобы нет
        _Результат(список=["ж1", "ж2", "ж3"]),    # трое разных
        _Результат(значение=анкета),
    )

    await report.create_report(
        SimpleNamespace(reported_id="цель", reason="harassment", description=""),
        user=SimpleNamespace(id="ж3"),
        session=сессия,
    )

    лента = _уведомления(сессия)
    assert [(н.user_id, н.kind, н.payload) for н in лента] == [
        ("ж1", "report_outcome", {"outcome": "hidden"}),
        ("ж2", "report_outcome", {"outcome": "hidden"}),
        ("ж3", "report_outcome", {"outcome": "hidden"}),
    ]
    # Лента и рассылка — один итог из одной точки решения
    assert рассылка == [(["ж1", "ж2", "ж3"], "hidden")]


async def test_четвёртая_жалоба_не_дублирует_ленту(рассылка):
    """Порог пройден раньше: рассылку уже не повторяем — и ленту тоже."""
    from routers import report

    сессия = _СессияПоПлану(
        _Результат(значение=SimpleNamespace(
            id="цель", role="user", telegram_id=5, is_banned=False,
        )),
        _Результат(значение=None),
        _Результат(список=["ж1", "ж2", "ж3", "ж4"]),
        _Результат(значение=SimpleNamespace(user_id="цель", is_incognito=True)),
    )

    await report.create_report(
        SimpleNamespace(reported_id="цель", reason="harassment", description=""),
        user=SimpleNamespace(id="ж4"),
        session=сессия,
    )

    assert _уведомления(сессия) == []
    assert рассылка == []


# ════════════════════════════════════════════════════════════════
#  Write-point: решение модератора (routers/admin.py)
# ════════════════════════════════════════════════════════════════

async def test_решение_модератора_попадает_в_ленту(рассылка):
    """Отказ — тоже итог: без строки в ленте жалоба выглядит потерянной."""
    from routers import admin
    from routers.admin import ReportAction

    жалоба = SimpleNamespace(
        id="r1", reporter_id="ж1", reported_id="цель", status="pending"
    )
    сессия = _СессияПоПлану(
        _Результат(значение=жалоба),
        _Результат(значение=SimpleNamespace(
            id="цель", role="user", telegram_id=5, is_banned=False,
        )),
        _Результат(),  # имена-снапшоты для записи аудита
    )

    await admin.report_action(
        ReportAction(report_id="r1", action="dismiss"),
        user=SimpleNamespace(id="админ", role="admin"),
        session=сессия,
    )

    (н,) = _уведомления(сессия)
    assert (н.user_id, н.kind, н.payload) == (
        "ж1", "report_outcome", {"outcome": "dismissed"}
    )
    assert рассылка == [(["ж1"], "dismissed")]


async def test_лента_не_обещает_бана_которого_не_было(рассылка):
    """Цель — владелец, ban_user_for_violation откажет: в ленте «resolved»,
    как и в рассылке, а не обещанный «banned»."""
    from routers import admin
    from routers.admin import ReportAction

    сессия = _СессияПоПлану(
        _Результат(значение=SimpleNamespace(
            id="r1", reporter_id="ж1", reported_id="цель", status="pending"
        )),
        _Результат(значение=SimpleNamespace(
            id="цель", role="owner", telegram_id=5, is_banned=False,
        )),
        _Результат(),  # имена-снапшоты для записи аудита
    )

    await admin.report_action(
        ReportAction(report_id="r1", action="ban_reported"),
        user=SimpleNamespace(id="админ", role="admin"),
        session=сессия,
    )

    (н,) = _уведомления(сессия)
    assert н.payload == {"outcome": "resolved"}
    assert рассылка == [(["ж1"], "resolved")]


# ════════════════════════════════════════════════════════════════
#  Write-point: галочка вдогонку (routers/verification.py)
# ════════════════════════════════════════════════════════════════

@pytest.fixture
def sumsub_green(monkeypatch):
    """GREEN-вердикт с совпавшим лицом, вся сеть подменена. Профиль с одним
    фото: сверка остальных фото тривиальна и в сеть не ходит."""
    from routers import verification as v
    from services import sumsub

    async def _референс(_url):
        return b"reference-bytes"

    async def _селфи(_applicant_id):
        return b"selfie-bytes"

    async def _сверка(_селфи, _референс):
        return {"matches_profile": True, "reason": "ok"}

    async def _лог(*_a, **_kw):
        return None

    monkeypatch.setattr(v, "_скачать_референс", _референс)
    monkeypatch.setattr(sumsub, "best_selfie_frame", _селфи)
    monkeypatch.setattr(v, "verify_face_match", _сверка)
    monkeypatch.setattr(v, "log_moderation", _лог)


async def test_галочка_вдогонку_попадает_в_ленту_один_раз(sumsub_green):
    """Вердикт пришёл вебхуком при закрытой шторке — человек узнаёт о галочке
    из ленты. Ретрай вебхука не дублирует: повторный GREEN по уже
    верифицированному выходит до записи."""
    from routers.verification import _решить_sumsub

    пользователь = SimpleNamespace(id="у1", is_verified=False)
    задание = SimpleNamespace(
        user_id="у1", poses=[], status="issued", reason="",
        provider="sumsub", provider_ref="", decided_at=None,
    )
    профиль = SimpleNamespace(
        user_id="у1", photos=["https://cdn.test/me.jpg"], verified_photo=None
    )

    сессия = _СессияПоПлану(_Результат(значение=профиль))
    итог = await _решить_sumsub(сессия, пользователь, задание, "apl-1", "GREEN", "", "")
    assert итог == {"outcome": "approved", "reason": ""}
    assert пользователь.is_verified is True

    (н,) = _уведомления(сессия)
    assert (н.user_id, н.kind, н.payload) == ("у1", "verification_approved", {})

    # Ретрай доставки: тот же вердикт по уже верифицированному
    сессия2 = _СессияПоПлану()
    итог2 = await _решить_sumsub(сессия2, пользователь, задание, "apl-1", "GREEN", "", "")
    assert итог2 == {"outcome": "approved", "reason": ""}
    assert _уведомления(сессия2) == [], "ретрай вебхука не должен дублировать ленту"


async def test_отказ_не_попадает_в_ленту(sumsub_green, monkeypatch):
    """RED — не событие ленты: человеку показывают причину прямо в шторке,
    а «вам отказано» в колокольчике било бы второй раз без пользы."""
    from routers.verification import _решить_sumsub

    пользователь = SimpleNamespace(id="у1", is_verified=False)
    задание = SimpleNamespace(
        user_id="у1", poses=[], status="issued", reason="",
        provider="sumsub", provider_ref="", decided_at=None,
    )

    сессия = _СессияПоПлану()
    итог = await _решить_sumsub(
        сессия, пользователь, задание, "apl-1", "RED", "RETRY", "Selfie is blurry"
    )
    assert итог["outcome"] == "rejected"
    assert _уведомления(сессия) == []


# ════════════════════════════════════════════════════════════════
#  HTTP: лента, прочтение, бейдж — на живой базе
# ════════════════════════════════════════════════════════════════

@pytest.fixture
async def живая_база(tmp_path):
    """Настоящая SQLite: получательница Маша и посторонний Петя.

    Срез, unread и идемпотентность /read — свойства реальных запросов
    к базе, подменённой сессией их не проверить.
    """
    from models.models import Base, User

    файл = tmp_path / "notifications.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{файл}")
    async with engine.begin() as c:
        await c.run_sync(Base.metadata.create_all)

    Session = async_sessionmaker(engine, expire_on_commit=False)

    маша, петя = str(uuid.uuid4()), str(uuid.uuid4())
    async with Session() as s:
        s.add(User(id=маша, telegram_id=1, role="user",
                   last_seen_at=datetime.now(timezone.utc)))
        s.add(User(id=петя, telegram_id=2, role="user",
                   last_seen_at=datetime.now(timezone.utc)))
        await s.commit()

    yield {"Session": Session, "маша": маша, "петя": петя}
    await engine.dispose()


@pytest.fixture
async def клиент(app, живая_база):
    """Клиент с живой БД. `от_имени` переключает текущего пользователя."""
    from database.connection import get_session
    from middleware.auth import get_current_user
    from models.models import User

    Session = живая_база["Session"]
    текущий = {"id": живая_база["маша"]}

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


async def _насыпать(живая_база, user_id: str, сколько: int) -> None:
    """Уведомления с шагом в минуту: created_at задан явно, потому что
    server_default SQLite даёт секундную точность и рушит порядок."""
    from models.models import Notification

    старт = datetime(2026, 8, 22, 12, 0, tzinfo=timezone.utc)
    async with живая_база["Session"]() as s:
        for i in range(сколько):
            s.add(Notification(
                user_id=user_id,
                kind="report_outcome",
                payload={"outcome": "hidden", "i": str(i)},
                created_at=старт + timedelta(minutes=i),
            ))
        await s.commit()


async def test_лента_отдаёт_свежее_первым_а_unread_по_всей_ленте(клиент, живая_база):
    """Срез — ЛИМИТ строк, но unread честный: бейдж не должен обещать
    меньше, чем есть. Чужая лента не видна ни на чтение, ни в счётчике."""
    from routers.notifications import ЛИМИТ

    маша, петя = живая_база["маша"], живая_база["петя"]
    await _насыпать(живая_база, маша, ЛИМИТ + 1)
    await _насыпать(живая_база, петя, 1)

    r = await клиент.get("/api/notifications")
    assert r.status_code == 200, r.text
    тело = r.json()
    assert len(тело["items"]) == ЛИМИТ
    assert тело["unread"] == ЛИМИТ + 1
    assert тело["items"][0]["payload"]["i"] == str(ЛИМИТ), "свежее — первым"
    assert тело["items"][0]["kind"] == "report_outcome"
    assert тело["items"][0]["read_at"] is None
    # Самое старое (i=0) не влезло в срез — оно и должно выпадать
    assert all(эл["payload"]["i"] != "0" for эл in тело["items"])

    клиент.от_имени(петя)
    r = await клиент.get("/api/notifications")
    assert r.json()["unread"] == 1, "чужие уведомления не должны протекать"


async def test_прочтение_гасит_всё_разом_и_идемпотентно(клиент, живая_база):
    """Повторный POST — ноль, чужое не гасится: «прочитал я» не значит
    «прочитали все»."""
    from models.models import Notification

    маша, петя = живая_база["маша"], живая_база["петя"]
    await _насыпать(живая_база, маша, 3)
    await _насыпать(живая_база, петя, 1)

    r = await клиент.post("/api/notifications/read")
    assert r.status_code == 200, r.text
    assert r.json() == {"read": 3}

    r = await клиент.post("/api/notifications/read")
    assert r.json() == {"read": 0}, "повторное прочтение — не событие"

    assert (await клиент.get("/api/notifications")).json()["unread"] == 0

    async with живая_база["Session"]() as s:
        петины = (
            await s.execute(select(Notification).where(Notification.user_id == петя))
        ).scalars().all()
    assert [н.read_at for н in петины] == [None], "гасить можно только своё"


async def test_бейдж_несёт_колокольчик(клиент, живая_база):
    """Красная точка едет из /badges вместе с чатами и лайками — свой
    запрос ради одной цифры клиенту не нужен."""
    await _насыпать(живая_база, живая_база["маша"], 2)

    r = await клиент.get("/api/badges")
    assert r.status_code == 200, r.text
    assert r.json() == {"messages": 0, "likes": 0, "notifications": 2}

    await клиент.post("/api/notifications/read")
    assert (await клиент.get("/api/badges")).json()["notifications"] == 0


# ════════════════════════════════════════════════════════════════
#  Контракт API ↔ клиент
# ════════════════════════════════════════════════════════════════

def test_лента_есть_в_openapi(app):
    """Эндпоинты закрыты авторизацией и видны в схеме — клиенту есть куда
    ходить, а сторож мёртвых эндпоинтов их видит."""
    схема = app.openapi()["paths"]
    assert "get" in схема["/api/notifications"]
    assert "post" in схема["/api/notifications/read"]


def test_каждый_вид_события_имеет_текст_на_клиенте():
    """Тексты живут на клиенте (API не знает языка), и неизвестный kind
    клиент молча прячет — событие без ветки в Notifications.tsx исчезло бы
    без единой ошибки. Каждый вид и каждый исход обязаны быть в разметке."""
    from services.notifications import ВИДЫ
    from services.report_notify import ИТОГИ

    страница = (КОРЕНЬ / "web" / "src" / "pages" / "Notifications.tsx").read_text(
        encoding="utf-8"
    )
    for вид in ВИДЫ:
        assert f'"{вид}"' in страница, (
            f"вид {вид!r} не разобран в Notifications.tsx — событие молча пропадёт"
        )
    for исход in ИТОГИ:
        assert f'"{исход}"' in страница, (
            f"исход жалобы {исход!r} без текста — карточка уйдёт пустой"
        )
