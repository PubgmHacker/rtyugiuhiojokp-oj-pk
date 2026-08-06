"""Четыре мелкие фичи вдогонку за «Мимолётом» — на настоящей базе.

Общая фикстура повторяет `живая_база`/`клиент` из `test_e2e_flow.py`: там уже
объяснено, зачем нужна настоящая SQLite, а не подменённая сессия. Здесь
своя копия фикстур, а не импорт, — так тесты этого файла не зависят от
внутренностей соседнего и не потянут его фикстуры мимо явного объявления.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


@pytest.fixture
async def живая_база(tmp_path):
    """Настоящая БД со схемой по моделям и двумя людьми в ней."""
    from models.models import Base, Profile, Subscription, User

    файл = tmp_path / "mimolet.db"
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
        # Аня платит: на ней проверяем платные гейты
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
    import services.realtime as realtime_mod

    Session = живая_база["Session"]

    for мод in (likes_mod, cases_mod):
        настоящий = мод.sa_text
        монк = (lambda н: lambda sql: н("SELECT 1") if "advisory" in sql else н(sql))(настоящий)
        monkeypatch.setattr(мод, "sa_text", монк)

    # Модуль кеширует Redis-соединение в глобальной переменной между тестами.
    # Если до этого файла отработал тест с деградацией Redis (test_http_behavior),
    # соединение остаётся привязанным к уже закрытому event loop чужого теста —
    # и `/likes` падает 500 на попытке опубликовать событие. Сбрасываем кеш,
    # чтобы новое соединение создалось в loop’е текущего теста.
    monkeypatch.setattr(realtime_mod, "_redis", None)

    текущий = {"id": живая_база["аня"]}

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


# ════════════════════════════════════════════════════════════════
#  (а) Буст поднимает и очередь оценки фото
# ════════════════════════════════════════════════════════════════

async def test_буст_поднимает_анкету_в_очереди_оценки_фото(клиент, живая_база):
    """Буст задуман для деки, но очередь оценки фото использует ту же колонку.

    Без буста порядок — по `sample_key` (случайный, но стабильный). После
    буста Боря обязан оказаться первым, хотя у Ани `sample_key` может быть
    меньше: буст должен перебивать порядок.
    """
    from models.models import Profile

    аня, боря = живая_база["аня"], живая_база["боря"]
    Session = живая_база["Session"]

    # Третий человек нужен, чтобы порядок вообще был видимым: с одним
    # кандидатом в очереди любой ORDER BY даёт тот же единственный результат
    вера = str(uuid.uuid4())
    async with Session() as s:
        from models.models import User
        s.add(User(id=вера, telegram_id=3, role="user", last_seen_at=datetime.now(timezone.utc)))
        s.add(Profile(
            user_id=вера, display_name="Вера", gender="female",
            birth_date=datetime(1998, 5, 5, tzinfo=timezone.utc),
            city="Москва", photos=["https://x/3.jpg"],
            interests=["кино"], looking_for="any",
        ))
        await s.commit()

    async with Session() as s:
        аня_профиль = (
            await s.execute(select(Profile).where(Profile.user_id == аня))
        ).scalar_one()
        боря_профиль = (
            await s.execute(select(Profile).where(Profile.user_id == боря))
        ).scalar_one()
        вера_профиль = (
            await s.execute(select(Profile).where(Profile.user_id == вера))
        ).scalar_one()
        # Гарантируем, что без буста Аня шла бы раньше Веры
        аня_профиль.sample_key = 0.0
        вера_профиль.sample_key = 1.0
        боря_профиль.sample_key = 0.5
        # Вера — с бустом на час вперёд
        вера_профиль.boost_until = datetime.now(timezone.utc) + timedelta(hours=1)
        await s.commit()

    клиент.от_имени(боря)
    r = await клиент.get("/api/photo-ratings/queue")
    assert r.status_code == 200, r.text
    порядок = [t["user_id"] for t in r.json()["targets"]]
    assert боря not in порядок, "Боря сам себе в очередь не попадает"
    assert порядок[0] == вера, "с бустом Вера должна оказаться первой, а не по sample_key"
    assert порядок[1] == аня


# ════════════════════════════════════════════════════════════════
#  (б) Период «сегодня»/«неделя» у рейтинга лайков
# ════════════════════════════════════════════════════════════════

async def test_рейтинг_лайков_за_сегодня_не_учитывает_старые_лайки(клиент, живая_база):
    from models.models import Like

    аня, боря = живая_база["аня"], живая_база["боря"]
    Session = живая_база["Session"]

    async with Session() as s:
        # Старый лайк — три дня назад, попадает в «неделю», но не в «сегодня»
        s.add(Like(
            liker_id=боря, liked_id=аня, type="like",
            created_at=datetime.now(timezone.utc) - timedelta(days=3),
        ))
        await s.commit()

    r = await клиент.get("/api/leaderboard", params={"period": "today"})
    assert r.status_code == 200, r.text
    данные = r.json()
    assert данные["period"] == "today"
    assert данные["my_likes"] == 0, "трёхдневный лайк не должен считаться в «сегодня»"

    r = await клиент.get("/api/leaderboard", params={"period": "week"})
    assert r.status_code == 200, r.text
    данные = r.json()
    assert данные["period"] == "week"
    assert данные["my_likes"] == 1, "тот же лайк должен войти в окно недели"


# ════════════════════════════════════════════════════════════════
#  (в) Период у списка гостей, гейт по тарифу не трогаем
# ════════════════════════════════════════════════════════════════

async def test_гости_фильтруются_по_периоду_и_гейт_остаётся(клиент, живая_база):
    from services.visits import record_visit

    аня, боря = живая_база["аня"], живая_база["боря"]
    Session = живая_база["Session"]

    async with Session() as s:
        # Старый визит — за пределами недели
        await record_visit(s, visitor_id=боря, host_id=аня)
        await s.commit()
        from models.models import ProfileVisit
        визит = (
            await s.execute(select(ProfileVisit).where(ProfileVisit.host_id == аня))
        ).scalar_one()
        визит.last_seen_at = datetime.now(timezone.utc) - timedelta(days=10)
        await s.commit()

    # Аня на Ultra — гости открыты, но за неделю визитов не должно быть
    клиент.от_имени(аня)
    r = await клиент.get("/api/profiles/me/visitors", params={"period": "week"})
    assert r.status_code == 200, r.text
    данные = r.json()
    assert данные["revealed"] is True
    assert данные["total"] == 0, "визит десятидневной давности не должен войти в «неделю»"

    r = await клиент.get("/api/profiles/me/visitors", params={"period": "all"})
    assert r.json()["total"] == 1

    # Боря без подписки — гейт должен остаться прежним независимо от периода
    клиент.от_имени(боря)
    async with Session() as s:
        await record_visit(s, visitor_id=аня, host_id=боря)
        await s.commit()

    r = await клиент.get("/api/profiles/me/visitors", params={"period": "all"})
    assert r.status_code == 200, r.text
    данные = r.json()
    assert данные["revealed"] is False, "бесплатному тарифу «кто» видеть нельзя ни при каком периоде"
    assert данные["visitors"] == []
    assert данные["total"] == 1, "число гостей видно всем, период его не прячет"


# ════════════════════════════════════════════════════════════════
#  (г) Telegram-канал: нормализация, гейт, отображение у другого
# ════════════════════════════════════════════════════════════════

async def test_канал_нормализуется_из_ссылки_и_валидируется(клиент, живая_база, monkeypatch):
    import services.plans as plans_mod

    аня = живая_база["аня"]
    # Фича объявлена в тарифах для теста; сам plans.py не трогаем — подмена
    # только в тестовом процессе
    monkeypatch.setitem(plans_mod.FEATURE_MIN_TIER, "tg_channel", plans_mod.TIER_PLUS)

    клиент.от_имени(аня)  # Аня на Ultra ⇒ Plus ей доступен

    r = await клиент.patch(
        "/api/profiles/me", json={"tg_channel": "https://t.me/Soul_Channel1"}
    )
    assert r.status_code == 200, r.text
    assert r.json()["tg_channel"] == "Soul_Channel1", "ссылка должна разобраться до голого username"

    r = await клиент.patch("/api/profiles/me", json={"tg_channel": "@ok"})
    assert r.status_code == 400, "короче пяти символов — невалидный юзернейм"

    r = await клиент.patch("/api/profiles/me", json={"tg_channel": "5start"})
    assert r.status_code == 400, "юзернейм не может начинаться с цифры"


async def test_канал_без_тарифа_молча_игнорируется(клиент, живая_база):
    """Пока `tg_channel` не объявлен в FEATURE_MIN_TIER, фича не должна падать 500."""
    боря = живая_база["боря"]  # без подписки

    клиент.от_имени(боря)
    r = await клиент.patch("/api/profiles/me", json={"tg_channel": "somechannel"})
    assert r.status_code == 200, r.text
    assert r.json()["tg_channel"] == "", "без тарифа значение не должно сохраниться"


async def test_канал_виден_в_мэтче_только_если_у_владельца_открыт_тариф(
    клиент, живая_база, monkeypatch
):
    import services.plans as plans_mod
    from models.models import Profile

    аня, боря = живая_база["аня"], живая_база["боря"]
    Session = живая_база["Session"]

    async with Session() as s:
        профиль = (
            await s.execute(select(Profile).where(Profile.user_id == аня))
        ).scalar_one()
        профиль.tg_channel = "anya_channel"
        await s.commit()

    # Пока фича не объявлена в тарифах — канал не должен светиться никому.
    # Смотрим прямо в ответ /api/likes (MatchResponse.partner собирает
    # routers/likes.py._profile_to_user) — этот путь мы правим, а
    # /api/matches принадлежит другому процессу и здесь не проверяется.
    клиент.от_имени(боря)
    await клиент.post("/api/likes", json={"target_id": аня, "type": "like"})
    клиент.от_имени(аня)
    r = await клиент.post("/api/likes", json={"target_id": боря, "type": "like"})
    assert r.json()["matched"] is True
    партнёр = r.json()["match"]["partner"]
    assert партнёр["tg_channel"] == "", "без объявленного тарифа канал не должен отдаваться"

    # Объявляем фичу — у Ани (Ultra) она теперь доступна
    monkeypatch.setitem(plans_mod.FEATURE_MIN_TIER, "tg_channel", plans_mod.TIER_PLUS)

    клиент.от_имени(боря)
    r = await клиент.get("/api/likes/received")
    # Аня уже не «входящий лайк» — оба лайкнули друг друга; проверяем канал
    # через тот же _profile_to_user на новом отправленном лайке от третьей
    # стороны недостаточно, поэтому проверяем повторно через /api/likes:
    # повторный лайк не создаёт новый мэтч, но partner собирается тем же кодом.
    # Партнёр в ответе — это target_id, поэтому смотрим с точки зрения Бори,
    # лайкнувшего Аню: тогда partner = Аня, и виден именно её канал.
    r = await клиент.post("/api/likes", json={"target_id": аня, "type": "like"})
    партнёр = r.json()["match"]["partner"]
    assert партнёр["tg_channel"] == "anya_channel", "у Ани (Ultra) канал должен показаться Боре"
