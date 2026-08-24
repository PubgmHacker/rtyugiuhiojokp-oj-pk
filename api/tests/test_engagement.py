"""Вовлечение (блок 4 «Рост»): пуш о сгорающей серии и дайджест дня-2.

До engagement.py вся инициатива исходила от людей: push.py слал только мэтч
и сообщение, рассылки запускал админ руками. Серия сгорала молча, человек
второго дня не имел причины вернуться. Здесь закреплены обещания механики:

- предупреждаем ровно те пары, чья серия сгорит в ближайшую полночь UTC
  («вчера писали, сегодня ещё нет»), и никого больше;
- дайджест получает аккаунт возрастом 24–48 часов с анкетой, один раз;
- оба уведомления ходят строго в своих часовых окнах;
- дедуп ставится ДО отправки, лежащий Redis глушит проход целиком —
  одинаковый пуш каждые полчаса хуже недоставленного.

Redis и APNs в тестах фальшивые: проверяется, ЧТО и КОМУ уходит, а не
транспорт — транспорт закреплён тестами realtime и push.
"""
import json
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.pool import StaticPool

from models.models import ChatStreak, Match, Profile, User
from services.engagement import (
    ОКНО_ДАЙДЖЕСТА,
    ОКНО_СТРИКА,
    _в_окне,
    кандидаты_дайджеста,
    предупредить_о_стриках,
    разослать_дайджест_дня2,
    сгорающие_стрики,
)

#: 18:00 UTC — внутри окна стрика (16–21), снаружи окна дайджеста (8–16).
ВЕЧЕР = datetime(2026, 8, 24, 18, 0, tzinfo=timezone.utc)
#: 12:00 UTC — наоборот.
ПОЛДЕНЬ = datetime(2026, 8, 24, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
async def sqlite_factory():
    """Фабрика сессий поверх одной in-memory базы.

    StaticPool обязателен: функции вовлечения открывают СВОЮ сессию через
    ту же фабрику, и без общего соединения каждая получала бы новую пустую
    базу вместо наполненной тестом.
    """
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(User.metadata.create_all)

    yield async_sessionmaker(engine, expire_on_commit=False)

    await engine.dispose()


async def _человек(
    session,
    uid: str,
    имя: str | None = None,
    *,
    возраст_аккаунта_ч: float = 72.0,
    бан: bool = False,
    now: datetime = ВЕЧЕР,
):
    """Пользователь, по желанию с анкетой (имя=None — анкеты нет)."""
    session.add(User(
        id=uid,
        telegram_id=abs(hash(uid)) % 10**9,
        created_at=now - timedelta(hours=возраст_аккаунта_ч),
        is_banned=бан,
    ))
    if имя is not None:
        session.add(Profile(
            user_id=uid,
            display_name=имя,
            gender="other",
            looking_for="any",
            age_min=18,
            age_max=99,
            sample_key=0.5,
            photos=[],
            interests=[],
        ))
    await session.commit()


async def _пара(
    session,
    uid1: str,
    uid2: str,
    *,
    дни: int = 5,
    писали: str = "вчера",
    активен: bool = True,
    now: datetime = ВЕЧЕР,
) -> str:
    """Мэтч со стриком; `писали` — в какие UTC-сутки зачтён последний день."""
    a, b = sorted([uid1, uid2])
    # id задаётся руками: дефолт модели срабатывает лишь на flush, а он
    # нужен строке стрика прямо сейчас
    match = Match(id=f"м-{a}-{b}", user1_id=a, user2_id=b, is_active=активен)
    session.add(match)
    сутки = now.replace(hour=0, minute=0, second=0, microsecond=0)
    последний = {
        "сегодня": сутки,
        "вчера": сутки - timedelta(days=1),
        "позавчера": сутки - timedelta(days=2),
    }[писали]
    session.add(ChatStreak(
        match_id=match.id, streak_days=дни, last_counted_for=последний,
    ))
    await session.commit()
    return match.id


# ── Окна ─────────────────────────────────────────────────────────


def test_окна_полуоткрытые():
    """[от, до): нижняя граница внутри, верхняя — уже снаружи."""
    assert _в_окне(ВЕЧЕР.replace(hour=16), ОКНО_СТРИКА)
    assert _в_окне(ВЕЧЕР.replace(hour=20), ОКНО_СТРИКА)
    assert not _в_окне(ВЕЧЕР.replace(hour=15), ОКНО_СТРИКА)
    assert not _в_окне(ВЕЧЕР.replace(hour=21), ОКНО_СТРИКА)
    assert _в_окне(ВЕЧЕР.replace(hour=8), ОКНО_ДАЙДЖЕСТА)
    assert not _в_окне(ВЕЧЕР.replace(hour=16), ОКНО_ДАЙДЖЕСТА)


# ── Кого предупреждать о серии ───────────────────────────────────


@pytest.mark.asyncio
async def test_под_угрозой_ровно_вчерашняя_серия(sqlite_factory):
    """Вчерашняя — в списке; сегодняшняя, позавчерашняя и нулевая — нет."""
    async with sqlite_factory() as s:
        for uid in ("а1", "а2", "б1", "б2", "в1", "в2", "г1", "г2"):
            await _человек(s, uid, uid.upper())
        горит = await _пара(s, "а1", "а2", дни=7, писали="вчера")
        await _пара(s, "б1", "б2", писали="сегодня")
        await _пара(s, "в1", "в2", писали="позавчера")
        await _пара(s, "г1", "г2", дни=0, писали="вчера")

        пары = await сгорающие_стрики(s, ВЕЧЕР)

    assert [п["match_id"] for п in пары] == [горит]
    assert пары[0]["days"] == 7
    assert sorted(пары[0]["user_ids"]) == ["а1", "а2"]


@pytest.mark.asyncio
async def test_бан_и_неактивный_мэтч_выключают_предупреждение(sqlite_factory):
    """Подталкивать писать тому, кто не может ответить, — жестоко."""
    async with sqlite_factory() as s:
        await _человек(s, "ж1", "Живой")
        await _человек(s, "ж2", "Живая")
        await _человек(s, "з1", "Зря")
        await _человек(s, "з2", "Забанен", бан=True)
        await _пара(s, "ж1", "ж2", активен=False)
        await _пара(s, "з1", "з2")

        assert await сгорающие_стрики(s, ВЕЧЕР) == []


@pytest.mark.asyncio
async def test_имена_сторон_и_запасное_имя(sqlite_factory):
    """names соответствует user_ids поимённо; без анкеты — «Ваш мэтч»."""
    async with sqlite_factory() as s:
        await _человек(s, "алиса", "Алиса")
        await _человек(s, "борис", имя=None)  # мэтч есть, анкету удалил
        await _пара(s, "алиса", "борис")

        (пара,) = await сгорающие_стрики(s, ВЕЧЕР)

    имена = dict(zip(пара["user_ids"], пара["names"]))
    assert имена == {"алиса": "Алиса", "борис": "Ваш мэтч"}


# ── Кому дайджест дня-2 ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_кандидат_дайджеста_только_день_второй(sqlite_factory):
    """24–48 часов от регистрации, с анкетой, без бана — и никто другой."""
    async with sqlite_factory() as s:
        await _человек(s, "второй", "Второй", возраст_аккаунта_ч=30, now=ПОЛДЕНЬ)
        await _человек(s, "свежий", "Свежий", возраст_аккаунта_ч=12, now=ПОЛДЕНЬ)
        await _человек(s, "старый", "Старый", возраст_аккаунта_ч=60, now=ПОЛДЕНЬ)
        await _человек(s, "пустой", имя=None, возраст_аккаунта_ч=30, now=ПОЛДЕНЬ)
        await _человек(
            s, "изгой", "Изгой", возраст_аккаунта_ч=30, бан=True, now=ПОЛДЕНЬ,
        )

        assert await кандидаты_дайджеста(s, ПОЛДЕНЬ) == ["второй"]


# ── Рассылка целиком: окна, дедуп, каналы ────────────────────────


class FakeRedis:
    """SET NX + publish; `лежит=True` — Redis недоступен, set бросает."""

    def __init__(self, лежит: bool = False):
        self.ключи: dict[str, str] = {}
        self.события: list[tuple[str, dict]] = []
        self.лежит = лежит

    async def set(self, ключ, значение, nx=False, ex=None):
        if self.лежит:
            raise ConnectionError("redis down")
        if nx and ключ in self.ключи:
            return None
        self.ключи[ключ] = значение
        return True

    async def publish(self, канал, полезное):
        self.события.append((канал, json.loads(полезное)))


@pytest.fixture
def стенд(sqlite_factory, monkeypatch):
    """Функции вовлечения смотрят в тестовую базу и фальшивые каналы."""
    import database.connection as conn_mod
    import services.push as push_mod
    import services.realtime as realtime_mod

    fake = FakeRedis()
    пуши: list[dict] = []

    monkeypatch.setattr(conn_mod, "async_session_factory", sqlite_factory)

    async def _get_redis():
        return fake

    monkeypatch.setattr(realtime_mod, "get_redis", _get_redis)

    async def _пуш(user_id, title, body, data=None, collapse_id=None):
        пуши.append({
            "user_id": user_id,
            "title": title,
            "body": body,
            "data": data,
            "collapse_id": collapse_id,
        })
        return 1

    monkeypatch.setattr(push_mod, "send_to_user", _пуш)
    return fake, пуши


@pytest.mark.asyncio
async def test_предупреждение_обеим_сторонам_с_именем_партнёра(
    sqlite_factory, стенд,
):
    """Каждому уходит имя ДРУГОЙ стороны — и в событие бота, и в пуш."""
    fake, пуши = стенд
    async with sqlite_factory() as s:
        await _человек(s, "алиса", "Алиса")
        await _человек(s, "борис", "Борис")
        мид = await _пара(s, "алиса", "борис", дни=3)

    assert await предупредить_о_стриках(now=ВЕЧЕР) == 1

    кому = {
        е["user_id"]: е for _, е in fake.события if е["type"] == "streak_expiring"
    }
    assert кому["алиса"]["partner_name"] == "Борис"
    assert кому["борис"]["partner_name"] == "Алиса"
    assert кому["алиса"]["days"] == 3
    assert all(к == "dating:bot:events" for к, _ in fake.события)

    assert {п["user_id"] for п in пуши} == {"алиса", "борис"}
    assert all(п["collapse_id"] == f"streak-{мид}" for п in пуши)
    assert "Борис" in next(п for п in пуши if п["user_id"] == "алиса")["body"]


@pytest.mark.asyncio
async def test_вне_окна_тишина(sqlite_factory, стенд):
    """Проход вне своего окна не трогает ни базу, ни каналы."""
    fake, пуши = стенд
    async with sqlite_factory() as s:
        await _человек(s, "алиса", "Алиса")
        await _человек(s, "борис", "Борис")
        await _пара(s, "алиса", "борис")
        await _человек(s, "второй", "Второй", возраст_аккаунта_ч=30)

    assert await предупредить_о_стриках(now=ПОЛДЕНЬ) == 0
    assert await разослать_дайджест_дня2(now=ВЕЧЕР) == 0
    assert fake.события == [] and пуши == []


@pytest.mark.asyncio
async def test_дедуп_второй_проход_молчит(sqlite_factory, стенд):
    """Проходы идут каждые полчаса — предупреждение за день только одно."""
    fake, пуши = стенд
    async with sqlite_factory() as s:
        await _человек(s, "алиса", "Алиса")
        await _человек(s, "борис", "Борис")
        await _пара(s, "алиса", "борис")

    assert await предупредить_о_стриках(now=ВЕЧЕР) == 1
    assert await предупредить_о_стриках(now=ВЕЧЕР.replace(hour=19)) == 0
    assert len(fake.события) == 2 and len(пуши) == 2


@pytest.mark.asyncio
async def test_redis_лёг_проход_пропущен_целиком(sqlite_factory, стенд):
    """Без живого дедупа не шлём ничего: дубль хуже недоставленного."""
    fake, пуши = стенд
    fake.лежит = True
    async with sqlite_factory() as s:
        await _человек(s, "алиса", "Алиса")
        await _человек(s, "борис", "Борис")
        await _пара(s, "алиса", "борис")

    assert await предупредить_о_стриках(now=ВЕЧЕР) == 0
    assert fake.события == [] and пуши == []


@pytest.mark.asyncio
async def test_дайджест_день2_карта_как_в_приложении(sqlite_factory, стенд):
    """Событие несёт ту же карту, что человек увидит в приложении, пуш
    схлопывается по получателю, второй раз дайджест не приходит никогда."""
    from services.daily_card import card_for_day

    fake, пуши = стенд
    async with sqlite_factory() as s:
        await _человек(s, "второй", "Второй", возраст_аккаунта_ч=30, now=ПОЛДЕНЬ)

    assert await разослать_дайджест_дня2(now=ПОЛДЕНЬ) == 1

    карта = card_for_day("второй", ПОЛДЕНЬ.date())
    (канал, событие) = fake.события[0]
    assert канал == "dating:bot:events"
    assert событие == {
        "type": "day2_digest",
        "user_id": "второй",
        "card_name": карта.name,
        "card_meaning": карта.meaning,
        "card_advice": карта.advice,
    }
    assert пуши[0]["collapse_id"] == "day2-второй"
    assert карта.name in пуши[0]["body"]

    assert await разослать_дайджест_дня2(now=ПОЛДЕНЬ) == 0
    assert len(fake.события) == 1


# ── Бот: тексты и доставка события ───────────────────────────────

import subprocess
from pathlib import Path

БОТ = Path(__file__).resolve().parents[2] / "bot"


def _в_боте(скрипт: str) -> dict:
    python = БОТ / ".venv" / "bin" / "python"
    if not python.exists():
        pytest.skip("venv бота не поднят в этом окружении")
    результат = subprocess.run(
        [str(python), "-c", скрипт],
        cwd=БОТ, capture_output=True, text=True, timeout=120,
    )
    assert результат.returncode == 0, результат.stderr[-1500:]
    return json.loads(результат.stdout.strip().splitlines()[-1])


def test_бот_тексты_склонение_и_экранирование():
    """Серия склоняется по-русски, имя партнёра не ломает HTML-разметку."""
    итог = _в_боте("""
import json
import texts as T
print(json.dumps({
    "один": T.streak_expiring("Алиса <script>", 1),
    "три": T.streak_expiring("Борис", 3),
    "одиннадцать": T.streak_expiring("Вера", 11),
    "сорок": T.streak_expiring("Глеб", 40),
    "дайджест": T.day2_digest("Солнце", "Смысл & свет", "Сделайте шаг"),
}, ensure_ascii=False))
""")
    assert "1 день" in итог["один"] and "&lt;script&gt;" in итог["один"]
    assert "3 дня" in итог["три"]
    assert "11 дней" in итог["одиннадцать"]
    assert "40 дней" in итог["сорок"]
    assert "Солнце" in итог["дайджест"]
    assert "Смысл &amp; свет" in итог["дайджест"]
    assert "Сделайте шаг" in итог["дайджест"]


def test_бот_доставляет_события_вовлечения():
    """Обработчики подписчика шлют текст в Telegram ровно тому, у кого есть
    telegram_id; незнакомый пользователь — тишина, а не падение."""
    итог = _в_боте("""
import asyncio, json
from datetime import datetime, timezone

class FakeBot:
    def __init__(self):
        self.сообщения = []
    async def send_message(self, chat_id, text, **kw):
        self.сообщения.append({"chat_id": chat_id, "text": text})

async def main():
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
    from sqlalchemy.pool import StaticPool
    import database.connection as conn
    from database.models import Base, User

    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as c:
        await c.run_sync(Base.metadata.create_all)
    conn.async_session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with conn.async_session_factory() as s:
        s.add(User(id="у1", telegram_id=111, created_at=datetime.now(timezone.utc)))
        await s.commit()

    from services.redis_subscriber import (
        _notify_day2_digest, _notify_streak_expiring,
    )

    bot = FakeBot()
    await _notify_streak_expiring(bot, "у1", "Алиса", 5)
    await _notify_day2_digest(bot, "у1", "Луна", "Смысл", "Совет")
    await _notify_streak_expiring(bot, "нет-такого", "Кто-то", 1)
    print(json.dumps({"сообщения": bot.сообщения}, ensure_ascii=False))

asyncio.run(main())
""")
    сообщения = итог["сообщения"]
    assert len(сообщения) == 2
    assert all(м["chat_id"] == 111 for м in сообщения)
    assert "Алиса" in сообщения[0]["text"] and "5 дней" in сообщения[0]["text"]
    assert "Луна" in сообщения[1]["text"] and "Совет" in сообщения[1]["text"]
