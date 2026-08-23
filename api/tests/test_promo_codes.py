"""Промокоды на подписку (Блок В3).

Промокод — маркетинговый инструмент: код из поста или рекламы даёт подписку
бесплатно. Этим он отличается от подарочного кода (оплачен и одноразов):
промокод бесплатен и многоразов — один код на max_uses разных людей, но
каждый человек активирует его только один раз.

Ломается это там же, где деньги: две одновременные активации не должны
перепродать последний слот лимита; повторная активация тем же человеком —
пройти дважды; сбой начисления — съесть слот; а активация — попасть в
выручку админки (промокод не деньги, amount=None).

Механика живёт в двух местах: api/services/promo.py (мини-апп) и
bot/database/connection.py::activate_promo_code (бот) — у бота своя копия,
потому что импортировать код API он не может. Обе проверяются здесь.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from services.promo import (
    CODE_LEN,
    MAX_CODE_LEN,
    MIN_CODE_LEN,
    generate_promo_code,
    normalize_code,
    валидный_кастомный_код,
)
from tests.test_unban_purchase import _ШАПКА, _в_боте


# ════════════════════════════════════════════════════════════════
#  Код: генерация, нормализация, кастомные коды админа
# ════════════════════════════════════════════════════════════════

def test_генерированный_код_без_похожих_знаков():
    """Код диктуют голосом и перепечатывают с картинок: 0/O и 1/I в нём
    неразличимы, поэтому их в алфавите нет."""
    for _ in range(50):
        код = generate_promo_code()
        assert len(код) == CODE_LEN
        assert not set(код) & set("0O1I"), f"похожие знаки в коде {код}"
        assert валидный_кастомный_код(код), "свой же код не прошёл бы админку"


def test_нормализация_прощает_оформление():
    """Человек копирует «SIMP-2026» из поста или набирает «simp 2026» с
    телефона — это один и тот же код."""
    assert normalize_code("  simp-2026 ") == "SIMP2026"
    assert normalize_code("SIMP 20 26") == "SIMP2026"
    assert normalize_code("simp2026") == "SIMP2026"
    assert normalize_code(" - ") == ""


def test_кастомный_код_проверяется():
    """Админ волен выпускать человеческие коды с 0/1/I/O («HELLO2026»),
    но не короче 4 и не длиннее 32 знаков, и только латиница с цифрами."""
    assert валидный_кастомный_код("HELLO2026")
    assert валидный_кастомный_код("O0I1")  # человеческие знаки законны
    assert not валидный_кастомный_код("ABC")  # короче MIN_CODE_LEN
    assert not валидный_кастомный_код("A" * (MAX_CODE_LEN + 1))
    assert not валидный_кастомный_код("ПРИВЕТ2026")  # кириллица
    assert not валидный_кастомный_код("HE LLO")  # пробел
    assert MIN_CODE_LEN <= CODE_LEN <= MAX_CODE_LEN, (
        "генерированный код не прошёл бы собственную проверку"
    )


# ════════════════════════════════════════════════════════════════
#  API: выпуск в админке и активация в мини-аппе
# ════════════════════════════════════════════════════════════════

@pytest.fixture
async def живая_база(tmp_path):
    """Настоящая БД: админ Аня, платящая Вера (Aurora), бесплатный Гоша.

    Активация пишет слот, активацию, маркер и подписку одной транзакцией —
    подменённой сессией не обойтись (та же причина, что у фикстур
    test_feature_gates.py и test_star_packs.py).
    """
    from models.models import Base, Subscription, User

    файл = tmp_path / "promos.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{файл}")
    async with engine.begin() as c:
        await c.run_sync(Base.metadata.create_all)

    Session = async_sessionmaker(engine, expire_on_commit=False)

    аня, вера, гоша = (str(uuid.uuid4()) for _ in range(3))
    async with Session() as s:
        s.add(User(id=аня, telegram_id=1, role="admin",
                   last_seen_at=datetime.now(timezone.utc)))
        s.add(User(id=вера, telegram_id=2, role="user",
                   last_seen_at=datetime.now(timezone.utc)))
        s.add(User(id=гоша, telegram_id=3, role="user",
                   last_seen_at=datetime.now(timezone.utc)))
        # У Веры уже месяц Aurora: промо младшего тарифа не должно понизить
        s.add(Subscription(
            user_id=вера, plan="aurora",
            expires_at=datetime.now(timezone.utc) + timedelta(days=30),
        ))
        await s.commit()

    yield {"engine": engine, "Session": Session, "аня": аня, "вера": вера, "гоша": гоша}
    await engine.dispose()


@pytest.fixture
async def клиент(app, живая_база):
    """Клиент с живой БД. `от_имени` переключает текущего пользователя."""
    from database.connection import get_session
    from middleware.auth import get_current_user
    from models.models import User

    Session = живая_база["Session"]
    текущий = {"id": живая_база["гоша"]}

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


async def _выпустить(клиент, живая_база, **поля) -> dict:
    """Выпустить код от имени админа и вернуть строку ответа."""
    клиент.от_имени(живая_база["аня"])
    r = await клиент.post("/api/admin/promos", json={
        "tier": "plus", "days": 30, "max_uses": 0, **поля,
    })
    assert r.status_code == 200, r.text
    return r.json()


async def _промо_из_базы(живая_база, promo_id: str):
    from models.models import PromoCode

    async with живая_база["Session"]() as s:
        return (
            await s.execute(select(PromoCode).where(PromoCode.id == promo_id))
        ).scalar_one()


async def test_активация_даёт_подписку_и_след(клиент, живая_база):
    """Счастливый путь целиком: выпуск → активация с человеческим вводом
    («launch-2026» вместо LAUNCH2026) → подписка, слот, активация и маркер
    в базе. Маркер без суммы: промокод — не выручка, метрики его не видят."""
    from models.models import ProcessedPayment, PromoActivation, Subscription

    гоша = живая_база["гоша"]
    строка = await _выпустить(
        клиент, живая_база, code="LAUNCH2026", days=30, max_uses=5,
    )
    assert строка["code"] == "LAUNCH2026"

    клиент.от_имени(гоша)
    r = await клиент.post("/api/promo/activate", json={"code": " launch-2026 "})
    assert r.status_code == 200, r.text
    тело = r.json()
    assert (тело["tier"], тело["days"], тело["plan"]) == ("plus", 30, "plus")

    до = datetime.fromisoformat(тело["expires_at"])
    assert abs((до - (datetime.now(timezone.utc) + timedelta(days=30))).total_seconds()) < 600

    промо = await _промо_из_базы(живая_база, строка["id"])
    assert промо.used_count == 1

    async with живая_база["Session"]() as s:
        подписка = (
            await s.execute(select(Subscription).where(Subscription.user_id == гоша))
        ).scalar_one()
        assert подписка.plan == "plus"

        активация = (
            await s.execute(select(PromoActivation).where(
                PromoActivation.promo_id == строка["id"],
                PromoActivation.user_id == гоша,
            ))
        ).scalar_one()
        assert активация is not None

        маркер = (
            await s.execute(select(ProcessedPayment).where(
                ProcessedPayment.provider == "promo",
                ProcessedPayment.external_id == f"{строка['id']}:{гоша}",
            ))
        ).scalar_one()
        assert маркер.amount is None, "промокод попал бы в выручку админки"
        assert маркер.days == 30


async def test_повторная_активация_не_проходит(клиент, живая_база):
    """Код многоразовый для РАЗНЫХ людей. Один и тот же человек второй раз
    получает 409, слот не тратится, подписка не продлевается."""
    from models.models import Subscription

    гоша = живая_база["гоша"]
    строка = await _выпустить(клиент, живая_база, max_uses=5)

    клиент.от_имени(гоша)
    assert (await клиент.post("/api/promo/activate", json={"code": строка["code"]})).status_code == 200

    async with живая_база["Session"]() as s:
        было = (
            await s.execute(select(Subscription.expires_at).where(Subscription.user_id == гоша))
        ).scalar_one()

    r = await клиент.post("/api/promo/activate", json={"code": строка["code"]})
    assert r.status_code == 409, r.text
    assert "уже активировали" in r.json()["detail"]

    промо = await _промо_из_базы(живая_база, строка["id"])
    assert промо.used_count == 1, "повтор списал бы второй слот"

    async with живая_база["Session"]() as s:
        стало = (
            await s.execute(select(Subscription.expires_at).where(Subscription.user_id == гоша))
        ).scalar_one()
    assert было == стало, "повтор продлил бы подписку без слота"


async def test_код_многоразовый_и_не_понижает_тариф(клиент, живая_база):
    """Второй человек активирует тот же код. У Веры куплена Aurora — промо
    на Plus добавляет дни, но не отбирает уплаченный уровень."""
    вера, гоша = живая_база["вера"], живая_база["гоша"]
    строка = await _выпустить(клиент, живая_база, days=30, max_uses=0)

    клиент.от_имени(гоша)
    assert (await клиент.post("/api/promo/activate", json={"code": строка["code"]})).status_code == 200

    клиент.от_имени(вера)
    r = await клиент.post("/api/promo/activate", json={"code": строка["code"]})
    assert r.status_code == 200, r.text
    тело = r.json()
    assert тело["tier"] == "plus", "в ответе тариф промокода"
    assert тело["plan"] == "aurora", "промо Plus понизило бы купленную Aurora"

    # Дни легли поверх остатка: было 30 вперёд, стало 60
    до = datetime.fromisoformat(тело["expires_at"])
    assert abs((до - (datetime.now(timezone.utc) + timedelta(days=60))).total_seconds()) < 600

    промо = await _промо_из_базы(живая_база, строка["id"])
    assert промо.used_count == 2


async def test_лимит_исчерпывается(клиент, живая_база):
    """max_uses=1: первый успел, второй получает 410 «закончился», и отказ
    не оставляет следов — слот не уходит выше лимита."""
    вера, гоша = живая_база["вера"], живая_база["гоша"]
    строка = await _выпустить(клиент, живая_база, max_uses=1)

    клиент.от_имени(гоша)
    assert (await клиент.post("/api/promo/activate", json={"code": строка["code"]})).status_code == 200

    клиент.от_имени(вера)
    r = await клиент.post("/api/promo/activate", json={"code": строка["code"]})
    assert r.status_code == 410, r.text
    assert "закончился" in r.json()["detail"]

    промо = await _промо_из_базы(живая_база, строка["id"])
    assert промо.used_count == 1, "отказ оставил бы слот списанным"


async def test_просроченный_код(клиент, живая_база):
    """Срок вышел — 410 «истёк», слот цел."""
    строка = await _выпустить(
        клиент, живая_база,
        expires_at=(datetime.now(timezone.utc) - timedelta(days=1)).isoformat(),
    )

    клиент.от_имени(живая_база["гоша"])
    r = await клиент.post("/api/promo/activate", json={"code": строка["code"]})
    assert r.status_code == 410, r.text
    assert "истёк" in r.json()["detail"]
    assert (await _промо_из_базы(живая_база, строка["id"])).used_count == 0


async def test_несуществующий_и_пустой_код(клиент, живая_база):
    """Опечатка и пустой ввод — 404 без деталей, какие коды бывают."""
    клиент.от_имени(живая_база["гоша"])
    r = await клиент.post("/api/promo/activate", json={"code": "NOPE2026"})
    assert r.status_code == 404, r.text
    # « - » нормализуется в пустоту — тот же 404, а не 500
    r = await клиент.post("/api/promo/activate", json={"code": " - "})
    assert r.status_code == 404, r.text


async def test_погашенный_код_не_палится(клиент, живая_база):
    """Выключенный админом код отвечает «не найден», как несуществующий:
    погашенный после утечки код не должен подтверждать, что он настоящий.
    Включённый обратно — снова работает."""
    гоша, аня = живая_база["гоша"], живая_база["аня"]
    строка = await _выпустить(клиент, живая_база)

    клиент.от_имени(аня)
    r = await клиент.patch(f"/api/admin/promos/{строка['id']}", json={"is_active": False})
    assert r.status_code == 200, r.text
    assert r.json()["is_active"] is False

    клиент.от_имени(гоша)
    r = await клиент.post("/api/promo/activate", json={"code": строка["code"]})
    assert r.status_code == 404, "погашенный код ответил бы не как несуществующий"

    клиент.от_имени(аня)
    await клиент.patch(f"/api/admin/promos/{строка['id']}", json={"is_active": True})
    клиент.от_имени(гоша)
    assert (await клиент.post("/api/promo/activate", json={"code": строка["code"]})).status_code == 200


async def test_сбой_начисления_не_съедает_слот(клиент, живая_база, monkeypatch):
    """Слот списывается ДО начисления — упади начисление, get_session
    обязан откатить транзакцию целиком: слот вернулся, активации нет,
    человек попробует ещё раз и получит подписку, а не пустой слот."""
    import services.promo as promo_mod
    from models.models import PromoActivation, Subscription

    гоша = живая_база["гоша"]
    строка = await _выпустить(клиент, живая_база, max_uses=1)

    async def _взрыв(*a, **kw):
        raise RuntimeError("начисление упало")

    monkeypatch.setattr(promo_mod, "activate_premium", _взрыв)

    клиент.от_имени(гоша)
    with pytest.raises(RuntimeError):
        await клиент.post("/api/promo/activate", json={"code": строка["code"]})

    промо = await _промо_из_базы(живая_база, строка["id"])
    assert промо.used_count == 0, "сбой начисления съел бы слот лимита"
    async with живая_база["Session"]() as s:
        активации = (await s.execute(select(PromoActivation))).scalars().all()
        подписка = (
            await s.execute(select(Subscription).where(Subscription.user_id == гоша))
        ).scalar_one_or_none()
    assert активации == [], "сбой оставил бы активацию без подписки"
    assert подписка is None


# ════════════════════════════════════════════════════════════════
#  Админка: валидация выпуска, список, аудит, права
# ════════════════════════════════════════════════════════════════

async def test_выпуск_проверяет_входные(клиент, живая_база):
    """Каждое поле с границей отбивается человеческим 400, дубль кода — 409:
    разыгранный код перевыпускать нельзя, старые активации повисли бы на
    новом смысле кода."""
    клиент.от_имени(живая_база["аня"])

    async def _пост(**поля):
        return await клиент.post("/api/admin/promos", json={
            "tier": "plus", "days": 30, "max_uses": 1, **поля,
        })

    assert (await _пост(tier="vip")).status_code == 400
    assert (await _пост(days=0)).status_code == 400
    assert (await _пост(days=3651)).status_code == 400
    assert (await _пост(max_uses=-1)).status_code == 400
    assert (await _пост(code="AB")).status_code == 400  # короче 4 знаков
    assert (await _пост(code="ПРИВЕТ")).status_code == 400

    # Кастомный код нормализуется как при активации: «hello-2026» и есть
    # HELLO2026 — иначе код из поста не совпал бы с кодом из базы
    r = await _пост(code="hello-2026")
    assert r.status_code == 200, r.text
    assert r.json()["code"] == "HELLO2026"

    assert (await _пост(code="HELLO2026")).status_code == 409, "дубль кода прошёл бы"


async def test_выпуск_без_кода_генерирует_сам(клиент, живая_база):
    """Пустой code — сервер генерирует код безопасного алфавита."""
    строка = await _выпустить(клиент, живая_база)
    assert len(строка["code"]) == CODE_LEN
    assert not set(строка["code"]) & set("0O1I")
    assert строка["used_count"] == 0
    assert строка["is_active"] is True


async def test_список_свежие_сверху_и_живой_счётчик(клиент, живая_база):
    """GET /admin/promos: свежие сверху, used_count — живой счётчик
    активаций, отдельного журнала админке не нужно."""
    первый = await _выпустить(клиент, живая_база, code="FIRST2026")
    второй = await _выпустить(клиент, живая_база, code="SECOND2026")

    клиент.от_имени(живая_база["гоша"])
    assert (await клиент.post("/api/promo/activate", json={"code": "FIRST2026"})).status_code == 200

    клиент.от_имени(живая_база["аня"])
    r = await клиент.get("/api/admin/promos")
    assert r.status_code == 200, r.text
    строки = {p["id"]: p for p in r.json()}
    assert строки[первый["id"]]["used_count"] == 1
    assert строки[второй["id"]]["used_count"] == 0


async def test_гашение_несуществующего_404(клиент, живая_база):
    клиент.от_имени(живая_база["аня"])
    r = await клиент.patch("/api/admin/promos/нет-такого", json={"is_active": False})
    assert r.status_code == 404


async def test_выпуск_и_гашение_пишут_аудит(клиент, живая_база):
    """Кто выпустил и кто погасил код — вопрос первого же спорного тикета
    («мне обещали месяц бесплатно»). Журнал в той же транзакции."""
    from models.models import AdminAuditLog

    строка = await _выпустить(клиент, живая_база, code="AUDIT2026")
    клиент.от_имени(живая_база["аня"])
    await клиент.patch(f"/api/admin/promos/{строка['id']}", json={"is_active": False})

    async with живая_база["Session"]() as s:
        записи = (await s.execute(select(AdminAuditLog))).scalars().all()
    действия = {з.action for з in записи}
    assert "promo_create" in действия
    assert "promo_toggle" in действия
    выпуск = next(з for з in записи if з.action == "promo_create")
    assert выпуск.details["code"] == "AUDIT2026"
    assert выпуск.admin_id == живая_база["аня"]


async def test_выпуск_только_админу(клиент, живая_база):
    """Обычный пользователь не выпускает, не листает и не гасит коды."""
    клиент.от_имени(живая_база["гоша"])
    assert (await клиент.post("/api/admin/promos", json={
        "tier": "plus", "days": 30, "max_uses": 1,
    })).status_code == 403
    assert (await клиент.get("/api/admin/promos")).status_code == 403
    assert (await клиент.patch("/api/admin/promos/x", json={"is_active": False})).status_code == 403


# ════════════════════════════════════════════════════════════════
#  Бот: та же механика на его копии моделей (subprocess его venv)
# ════════════════════════════════════════════════════════════════

def test_бот_активация_промо_на_настоящей_базе():
    """Полный круг на настоящей схеме бота (SQLite): активация с
    человеческим вводом → повтор отбит → второй человек прошёл → лимит
    исчерпан → просроченный, погашенный и несуществующий отвечают своими
    причинами → подписка не понижается, маркер без суммы."""
    итог = _в_боте(
        """
import asyncio, json
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

import database.connection as conn
from database.models import (
    Base, ProcessedPayment, PromoActivation, PromoCode, Subscription, User,
)


async def main():
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
    conn.async_session_factory = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )
    async with engine.begin() as c:
        await c.run_sync(Base.metadata.create_all)

    now = datetime.utcnow()
    async with conn.async_session_factory() as s:
        async with s.begin():
            s.add(User(id="u1", telegram_id=111))
            s.add(User(id="u2", telegram_id=222))
            s.add(User(id="u3", telegram_id=333))
            # У u2 куплена Aurora на 5 дней вперёд: промо Plus не понижает
            s.add(Subscription(
                user_id="u2", plan="aurora", expires_at=now + timedelta(days=5),
            ))
            s.add(PromoCode(id="p_live", code="LIVE2026", tier="plus",
                            days=7, max_uses=2))
            s.add(PromoCode(id="p_old", code="OLD2026", tier="plus", days=7,
                            max_uses=0, expires_at=now - timedelta(days=1)))
            s.add(PromoCode(id="p_off", code="OFF2026", tier="plus", days=7,
                            max_uses=0, is_active=False))

    первый = await conn.activate_promo_code("u1", " live-2026 ")
    повтор = await conn.activate_promo_code("u1", "LIVE2026")
    второй = await conn.activate_promo_code("u2", "LIVE2026")
    лимит = await conn.activate_promo_code("u3", "LIVE2026")
    просрочен = await conn.activate_promo_code("u3", "OLD2026")
    погашен = await conn.activate_promo_code("u3", "OFF2026")
    чужой = await conn.activate_promo_code("u3", "NOPE")

    async with conn.async_session_factory() as s:
        промо = (
            await s.execute(select(PromoCode).where(PromoCode.id == "p_live"))
        ).scalar_one()
        под1 = (
            await s.execute(select(Subscription).where(Subscription.user_id == "u1"))
        ).scalar_one()
        под2 = (
            await s.execute(select(Subscription).where(Subscription.user_id == "u2"))
        ).scalar_one()
        активаций = len(
            (await s.execute(select(PromoActivation))).scalars().all()
        )
        маркеры = sorted(
            [м.provider, м.external_id, м.days, м.amount]
            for м in (await s.execute(select(ProcessedPayment))).scalars().all()
        )

    print(json.dumps({
        "первый": первый, "повтор": повтор, "второй": второй,
        "лимит": лимит, "просрочен": просрочен, "погашен": погашен,
        "чужой": чужой, "использовано": промо.used_count,
        "план1": под1.plan,
        "дни1": round((под1.expires_at - now).total_seconds() / 86400),
        "план2": под2.plan,
        "дни2": round((под2.expires_at - now).total_seconds() / 86400),
        "активаций": активаций, "маркеры": маркеры,
    }, ensure_ascii=False))


asyncio.run(main())
"""
    )

    assert итог["первый"]["activated"] is True
    assert (итог["первый"]["tier"], итог["первый"]["days"]) == ("plus", 7)
    assert итог["повтор"] == {"activated": False, "reason": "already_used"}
    assert итог["второй"]["activated"] is True
    assert итог["лимит"] == {"activated": False, "reason": "exhausted"}
    assert итог["просрочен"] == {"activated": False, "reason": "expired"}
    assert итог["погашен"] == {"activated": False, "reason": "not_found"}, (
        "погашенный код подтвердил бы, что он настоящий"
    )
    assert итог["чужой"] == {"activated": False, "reason": "not_found"}

    assert итог["использовано"] == 2, "отказы тратили бы слоты"
    assert итог["активаций"] == 2

    assert (итог["план1"], итог["дни1"]) == ("plus", 7)
    # Aurora не понизилась, дни легли поверх остатка: 5 + 7
    assert (итог["план2"], итог["дни2"]) == ("aurora", 12), итог["второй"]

    assert итог["маркеры"] == [
        ["promo", "p_live:u1", 7, None],
        ["promo", "p_live:u2", 7, None],
    ], "маркер с суммой попал бы в выручку админки"


_ПРОМО_FSM = _ШАПКА + """
# Ответ активации меняется по ходу сценария: premium.py взял ссылку на
# db.activate_promo_code при импорте, поэтому прокси ставим ДО импорта
ОТВЕТ_ПРОМО = {"activated": True, "tier": "plus", "days": 7,
               "plan": "plus", "expires_at": "2026-09-17T00:00:00"}

async def _промо(user_id, raw_code):
    вызовы.append(("activate_promo_code", user_id, raw_code))
    return dict(ОТВЕТ_ПРОМО)
db.activate_promo_code = _промо

# Каскад: на not_found от промо хендлер пробует ввод как подарочный код
ОТВЕТ_ПОДАРКА = {"redeemed": False, "reason": "not_found"}

async def _подарок(user_id, raw_code):
    вызовы.append(("redeem_gift_code", user_id, raw_code))
    return dict(ОТВЕТ_ПОДАРКА)
db.redeem_gift_code = _подарок

from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage

from handlers import premium
from states import PromoStates


async def main():
    state = FSMContext(
        storage=MemoryStorage(),
        key=StorageKey(bot_id=42, chat_id=42, user_id=42),
    )

    # 1. Кнопка «У меня есть промокод» включает ожидание кода
    кнопка = CallbackQuery.model_construct(
        id="1", from_user=_кто, chat_instance="c", data="promo",
        message=сообщение(),
    ).as_(бот)
    await premium.promo_start(кнопка, state)
    после_кнопки = await state.get_state()

    # 2. Верный код: активация, ожидание снято
    await premium.promo_code_received(сообщение(text=" live-2026 "), state)
    после_успеха = await state.get_state()

    # 3. Опечатка (кода нет ни среди промо, ни среди подарков) оставляет
    # ожидание — человек поправит и пришлёт снова
    ОТВЕТ_ПРОМО.clear()
    ОТВЕТ_ПРОМО.update({"activated": False, "reason": "not_found"})
    await state.set_state(PromoStates.waiting_code)
    await premium.promo_code_received(сообщение(text="ОПЕЧАТКА"), state)
    после_опечатки = await state.get_state()

    # 4. Окончательный отказ (слоты кончились) снимает ожидание
    ОТВЕТ_ПРОМО.clear()
    ОТВЕТ_ПРОМО.update({"activated": False, "reason": "exhausted"})
    await state.set_state(PromoStates.waiting_code)
    await premium.promo_code_received(сообщение(text="LIVE2026"), state)
    после_отказа = await state.get_state()

    # 5. Подарочный код: промо его не знает, каскад активирует подарок
    ОТВЕТ_ПРОМО.clear()
    ОТВЕТ_ПРОМО.update({"activated": False, "reason": "not_found"})
    ОТВЕТ_ПОДАРКА.clear()
    ОТВЕТ_ПОДАРКА.update({"redeemed": True, "tier": "ultra", "months": 3,
                          "plan": "ultra", "expires_at": "2026-11-22T00:00:00"})
    await state.set_state(PromoStates.waiting_code)
    await premium.promo_code_received(сообщение(text=" gift-код "), state)
    после_подарка = await state.get_state()

    # 6. Подарок ниже действующего уровня: отказ окончательный (код цел,
    # но повтор сейчас даст то же), ожидание снято
    ОТВЕТ_ПОДАРКА.clear()
    ОТВЕТ_ПОДАРКА.update({"redeemed": False, "reason": "tier_lower"})
    await state.set_state(PromoStates.waiting_code)
    await premium.promo_code_received(сообщение(text="GIFT2"), state)
    после_ниже = await state.get_state()

    print(json.dumps({
        "после_кнопки": после_кнопки, "после_успеха": после_успеха,
        "после_опечатки": после_опечатки, "после_отказа": после_отказа,
        "после_подарка": после_подарка, "после_ниже": после_ниже,
        "вызовы": вызовы,
    }, ensure_ascii=False))


asyncio.run(main())
"""


def test_бот_кнопка_и_состояния_промокода():
    """FSM вокруг активации: кнопка включает ожидание кода; успех и
    окончательные отказы снимают его; опечатка оставляет — человек
    поправит код, не нажимая кнопку заново. Сырой ввод уходит в активацию
    как есть: нормализация — забота одного места, механики.

    Поле одно на оба вида кодов: на not_found от промо хендлер пробует
    ввод как подарочный код — человеку всё равно, из поста его код или
    от друга. «Нет такого» показывается только после двойного промаха."""
    итог = _в_боте(_ПРОМО_FSM.replace("ЗАБАНЕН", "False").replace(
        "ОТВЕТ_РАЗБАНА", '{"unbanned": True, "reason": ""}'
    ))
    вызовы = [tuple(в) for в in итог["вызовы"]]

    assert итог["после_кнопки"] == "PromoStates:waiting_code"
    assert итог["после_успеха"] is None, "ожидание пережило бы активацию"
    assert итог["после_опечатки"] == "PromoStates:waiting_code", (
        "опечатка выбросила бы человека из ввода кода"
    )
    assert итог["после_отказа"] is None
    assert итог["после_подарка"] is None, "ожидание пережило бы активацию подарка"
    assert итог["после_ниже"] is None

    активации = [в for в in вызовы if в[0] == "activate_promo_code"]
    assert активации[0] == ("activate_promo_code", "u1", " live-2026 "), (
        "хендлер порезал бы ввод до механики"
    )

    подарки = [в for в in вызовы if в[0] == "redeem_gift_code"]
    assert ("redeem_gift_code", "u1", " gift-код ") in подарки, (
        "хендлер порезал бы ввод до механики подарка"
    )
    # Успешный промокод до каскада не дошёл: подарок дёргается только на
    # not_found, а не на каждый ввод
    assert ("redeem_gift_code", "u1", " live-2026 ") not in подарки

    отправки = [в[1] for в in вызовы if в[0] == "send"]
    assert any("Пришлите промокод" in т for т in отправки)
    assert any("Промокод принят" in т for т in отправки)
    assert any("Такого кода нет" in т for т in отправки), (
        "после двойного промаха человек должен увидеть, что не подошло ничто"
    )
    assert any("закончился" in т for т in отправки)
    assert any("Подарок принят" in т for т in отправки)
    assert any("уровень выше" in т for т in отправки), (
        "tier_lower без объяснения выглядел бы как сгоревший код"
    )


def test_кнопка_промокода_в_витрине_тарифов():
    """Кнопка «У меня есть промокод» живёт в витрине тарифов бота — без
    неё код из поста некуда ввести."""
    from pathlib import Path

    premium = (
        Path(__file__).resolve().parents[2] / "bot" / "handlers" / "premium.py"
    ).read_text(encoding="utf-8")
    assert 'callback_data="promo"' in premium
    assert "промокод" in premium.lower()
