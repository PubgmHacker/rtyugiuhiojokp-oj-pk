"""Суточные лимиты бесплатного уровня в БОТЕ — на настоящей БД в памяти.

Проверяется не форма кода, а поведение: свайпы бота пишут лайки напрямую через
`database/connection.like_and_match`, минуя HTTP API. Лимит, живущий только в
`api/services/quotas.py`, обходился бы одним нажатием «❤️» в чате с ботом — то
есть не существовал бы вовсе. Ровно это здесь и закрывается.

Отдельно проверяются исключения, без которых лимит калечит бесплатный уровень
вместо того, чтобы его ограничивать:

  • пропуск («👎») не тратит ничего — иначе лимит запрещал бы листать деку;
  • повторный лайк той же анкеты бесплатный — он уже лежит в подсчёте;
  • платный уровень безлимитен;
  • повторный вход в уже открытый чат слот не тратит.

`pg_advisory_xact_lock` подменяется: его нет в SQLite. Подменяется ровно он,
слово «advisory» в тексте остаётся — по нему журнал сессии ловит порядок
захвата ключей, а порядок здесь инвариант, общий с API (личный → парный), и
обратный порядок в одном из сервисов — классический дедлок.

Запускается интерпретатором бота из `tests/test_query_scale.py`.
Ответ — JSON на последней строке stdout.
"""

import asyncio
import json
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, ".")

from sqlalchemy import select, text as настоящий_text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import database.connection as c
import services.quotas as quotas
from database.models import Like, Match, MatchView, Profile, Subscription, User
from services.plans import (
    LIKES_PER_DAY,
    MATCH_VIEWS_PER_DAY,
    PLANS_BY_CODE,
    TIER_FREE,
    TIER_PLUS,
    TIER_ULTRA,
)

ЛАЙКОВ = LIKES_PER_DAY[TIER_FREE]
МЭТЧЕЙ = MATCH_VIEWS_PER_DAY[TIER_FREE]

#: Кому лайкаем. Целей заведомо больше лимита — иначе «отказали на 11-м»
#: нельзя отличить от «анкеты кончились».
ЦЕЛЕЙ = ЛАЙКОВ + 5


def _без_advisory(sql):
    """`text()` бота, но без Postgres-локов.

    Маркер «advisory» в подменённом запросе сохраняем: журнал сессии ищет
    захваты по нему, и подмена на чистый `SELECT 1` сделала бы проверку
    порядка локов вечнозелёной.
    """
    if "advisory" in sql:
        return настоящий_text("SELECT 1 -- advisory")
    return настоящий_text(sql)


class Сессия:
    """Настоящая сессия, пишущая в журнал захваты локов.

    Ключ лока приходит не в тексте запроса, а в параметрах (`:k`) — поэтому
    журнал ведётся здесь, а не разбором SQL.
    """

    def __init__(self, сессия, журнал):
        self._s = сессия
        self._журнал = журнал

    async def execute(self, statement=None, *a, **kw):
        if "advisory" in str(statement):
            параметры = a[0] if a and isinstance(a[0], dict) else kw.get("parameters") or {}
            self._журнал.append(параметры.get("k", "?"))
        return await self._s.execute(statement, *a, **kw)

    def __getattr__(self, имя):
        return getattr(self._s, имя)


class Контекст:
    def __init__(self, сессия, журнал):
        self._сессия = сессия
        self._журнал = журнал

    async def __aenter__(self):
        return Сессия(await self._сессия.__aenter__(), self._журнал)

    async def __aexit__(self, *a):
        return await self._сессия.__aexit__(*a)


class Фабрика:
    """То, что `connection._session_cls()` возвращает в бою — sessionmaker.

    Нужна своя, потому что сессии оборачиваются журналом: код бота зовёт
    `cls = _session_cls()`, а потом `cls()`, то есть подменять надо ФАБРИКУ,
    а не сессию.
    """

    def __init__(self, session_cls, журнал):
        self._cls = session_cls
        self._журнал = журнал

    def __call__(self):
        return Контекст(self._cls(), self._журнал)


async def поднять_базу():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(User.metadata.create_all)
    return engine


def подключить(engine, журнал: list[str]):
    """Направить бота на эту базу и вернуть чистый sessionmaker для подготовки."""
    session_cls = async_sessionmaker(engine, expire_on_commit=False)
    фабрика = Фабрика(session_cls, журнал)
    c._session_cls = lambda: фабрика
    return session_cls


def человек(session, uid: str, tg: int, имя: str, ищет: str = "any"):
    session.add(User(id=uid, telegram_id=tg))
    session.add(Profile(user_id=uid, display_name=имя, gender="female", looking_for=ищет))


# ── Лайки ───────────────────────────────────────────────────────

async def проверить_лайки(журнал: list[str]) -> dict:
    engine = await поднять_базу()
    session_cls = подключить(engine, журнал)

    async with session_cls() as s:
        человек(s, "F0", 500, "Бесплатный")
        for i in range(1, ЦЕЛЕЙ + 1):
            человек(s, f"T{i}", 500 + i, f"Цель {i}")
        await s.commit()

    итог: dict = {}

    # Пропуск до всяких лайков: он не должен попасть в подсчёт
    пропуск = await c.like_and_match("F0", "T1", "pass")
    итог["пропуск_ограничен"] = bool(пропуск.get("limited"))

    # Ровно `ЛАЙКОВ` лайков подряд — все обязаны пройти
    остатки: list = []
    отказ_на = None
    for i in range(2, 2 + ЛАЙКОВ):
        ответ = await c.like_and_match("F0", f"T{i}", "like")
        остатки.append(ответ.get("likes_left"))
        if ответ.get("limited"):
            отказ_на = i - 1
            break
    итог["отказ_внутри_квоты_на"] = отказ_на
    итог["остатки"] = остатки

    # Следующая новая цель — отказ, и лайк НЕ записан
    сверх = await c.like_and_match("F0", f"T{2 + ЛАЙКОВ}", "like")
    итог["сверх_квоты_ограничен"] = bool(сверх.get("limited"))
    итог["лайк_сверх_квоты_лимит"] = сверх.get("limit")
    итог["лайк_сверх_квоты_есть_reset"] = сверх.get("reset_at") is not None
    итог["сверх_квоты_не_мэтч"] = сверх.get("matched") is False

    # Пропуск ПОСЛЕ исчерпания — по-прежнему свободен
    пропуск_после = await c.like_and_match("F0", f"T{3 + ЛАЙКОВ}", "pass")
    итог["пропуск_после_исчерпания_ограничен"] = bool(пропуск_после.get("limited"))

    # Повторный лайк уже лайкнутой цели — бесплатный
    повтор = await c.like_and_match("F0", "T2", "like")
    итог["повтор_ограничен"] = bool(повтор.get("limited"))

    # Смена пропуска на лайк — это НОВЫЙ лайк, и он обязан упереться в лимит:
    # иначе квота обходилась бы «сначала 👎 всем, потом ❤️ всем»
    апгрейд = await c.like_and_match("F0", "T1", "like")
    итог["апгрейд_пропуска_ограничен"] = bool(апгрейд.get("limited"))

    async with session_cls() as s:
        строки = (await s.execute(
            select(Like.liked_id, Like.type).where(Like.liker_id == "F0")
        )).all()
    итог["лайков_в_базе"] = sum(1 for _, тип in строки if тип != "pass")
    итог["пропусков_в_базе"] = sum(1 for _, тип in строки if тип == "pass")
    итог["сверхлимитный_записан"] = any(
        цель == f"T{2 + ЛАЙКОВ}" for цель, _ in строки
    )

    await engine.dispose()
    return итог


async def проверить_платный() -> dict:
    """Платный уровень: лимита нет ни на лайки, ни на открытия.

    В колонке `Subscription.plan` лежит УРОВЕНЬ («plus»), а не код тарифа
    («plus_1m») — так пишут оба пути активации (`api/services/premium.py` и
    `database/connection.activate_premium_payment`). Проверяем ту форму, что
    реально попадает в базу; за код тарифа отвечает `проверить_код_тарифа`.
    """
    engine = await поднять_базу()
    session_cls = подключить(engine, [])

    всего_мэтчей = МЭТЧЕЙ + 3
    async with session_cls() as s:
        человек(s, "P0", 700, "Платный")
        for i in range(1, ЦЕЛЕЙ + 1):
            человек(s, f"Q{i}", 700 + i, f"Цель {i}")
        for i in range(1, всего_мэтчей + 1):
            человек(s, f"PM{i}", 7700 + i, f"Собеседник {i}")
            s.add(Match(
                id=f"PP{i}", user1_id="P0", user2_id=f"PM{i}", is_active=True,
                created_at=datetime(2026, 1, 1) + timedelta(minutes=i),
            ))
        s.add(Subscription(
            user_id="P0", plan=TIER_PLUS,
            expires_at=datetime.now(timezone.utc) + timedelta(days=30),
        ))
        await s.commit()

    отказ_на = None
    for i in range(1, ЛАЙКОВ + 4):
        ответ = await c.like_and_match("P0", f"Q{i}", "like")
        if ответ.get("limited"):
            отказ_на = i
            break
    последний = await c.like_and_match("P0", f"Q{ЛАЙКОВ + 4}", "like")

    # Открытий тоже больше квоты бесплатного: безлимит обязан быть на обоих
    # лимитах, а не только на лайках
    мэтч_закрыли_на = None
    for i in range(1, всего_мэтчей + 1):
        партнёр = await c.get_match_partner(f"PP{i}", "P0", spend=True)
        if партнёр is None or партнёр.get("locked"):
            мэтч_закрыли_на = i
            break

    async with session_cls() as s:
        лимиты = await quotas.limits_summary(Сессия(s, []), "P0")

    итог = {
        "платному_отказали_на": отказ_на,
        "платному_остаток_none": последний.get("likes_left") is None,
        "платному_мэтч_закрыли_на": мэтч_закрыли_на,
        "платный_уровень": лимиты["tier"],
        "платный_лайки_безлимит": лимиты["likes"].unlimited,
        "платный_мэтчи_безлимит": лимиты["matches"].unlimited,
        "платный_не_free": лимиты["free"] is False,
    }
    await engine.dispose()
    return итог


async def проверить_код_тарифа() -> dict:
    """Код тарифа в колонке уровня — тоже оплата, а не `free`.

    Уровень и код различаются одной буквой («plus» против «plus_1m»), лежат в
    соседних словарях и попадают в одну и ту же колонку из разных путей оплаты.
    Пока `tier_from_plan` знал только уровни, такая запись читалась как `free`:
    человек заплатил, а получил десять лайков в сутки — молча, без единой
    ошибки в логах. Проверяется на боте, потому что здесь у лимита своя копия
    разбора.
    """
    engine = await поднять_базу()
    session_cls = подключить(engine, [])

    код = next(п.code for п in PLANS_BY_CODE.values() if п.tier == TIER_PLUS)
    async with session_cls() as s:
        человек(s, "K0", 800, "С кодом тарифа")
        for i in range(1, ЛАЙКОВ + 3):
            человек(s, f"KT{i}", 8800 + i, f"Цель {i}")
        s.add(Subscription(
            user_id="K0", plan=код,
            expires_at=datetime.now(timezone.utc) + timedelta(days=30),
        ))
        await s.commit()

    отказ_на = None
    for i in range(1, ЛАЙКОВ + 3):
        ответ = await c.like_and_match("K0", f"KT{i}", "like")
        if ответ.get("limited"):
            отказ_на = i
            break

    async with session_cls() as s:
        лимиты = await quotas.limits_summary(Сессия(s, []), "K0")

    итог = {
        "код_тарифа": код,
        "по_коду_уровень": лимиты["tier"],
        "по_коду_отказали_на": отказ_на,
        "по_коду_безлимит": лимиты["likes"].unlimited,
    }
    await engine.dispose()
    return итог


async def проверить_просроченный() -> dict:
    """Истёкшая подписка — это `free`. Иначе платили бы один раз."""
    engine = await поднять_базу()
    session_cls = подключить(engine, [])

    async with session_cls() as s:
        человек(s, "E0", 900, "Просроченный")
        for i in range(1, ЦЕЛЕЙ + 1):
            человек(s, f"R{i}", 900 + i, f"Цель {i}")
        s.add(Subscription(
            user_id="E0", plan=TIER_ULTRA,
            expires_at=datetime.now(timezone.utc) - timedelta(days=1),
        ))
        await s.commit()

    отказ_на = None
    for i in range(1, ЛАЙКОВ + 3):
        ответ = await c.like_and_match("E0", f"R{i}", "like")
        if ответ.get("limited"):
            отказ_на = i
            break

    await engine.dispose()
    return {"просроченному_отказали_на": отказ_на}


# ── Открытые мэтчи ──────────────────────────────────────────────

async def проверить_мэтчи() -> dict:
    engine = await поднять_базу()
    session_cls = подключить(engine, [])

    всего = МЭТЧЕЙ + 2
    async with session_cls() as s:
        человек(s, "M0", 300, "Я")
        for i in range(1, всего + 1):
            человек(s, f"N{i}", 300 + i, f"Собеседник {i}")
            s.add(Match(
                id=f"MM{i}", user1_id="M0", user2_id=f"N{i}", is_active=True,
                created_at=datetime(2026, 1, 1) + timedelta(minutes=i),
            ))
        await s.commit()

    итог: dict = {}

    # До первого открытия список отдаёт имена: показ списка квоту не тратит
    список_до = await c.get_user_matches("M0")
    итог["закрытых_до_открытий"] = sum(1 for м in список_до if м.get("locked"))

    # Открываем ровно квоту — все обязаны отдать анкету, а не замок
    закрыт_внутри_квоты = None
    for i in range(1, МЭТЧЕЙ + 1):
        партнёр = await c.get_match_partner(f"MM{i}", "M0", spend=True)
        if партнёр is None or партнёр.get("locked"):
            закрыт_внутри_квоты = i
            break
    итог["закрыт_внутри_квоты_на"] = закрыт_внутри_квоты

    # Следующий — замок, и без единого признака собеседника
    сверх = await c.get_match_partner(f"MM{МЭТЧЕЙ + 1}", "M0", spend=True)
    итог["сверх_квоты_закрыт"] = bool(сверх and сверх.get("locked"))
    итог["мэтч_сверх_квоты_лимит"] = (сверх or {}).get("limit")
    итог["мэтч_сверх_квоты_есть_reset"] = (сверх or {}).get("reset_at") is not None
    итог["в_замке_нет_имени"] = "display_name" not in (сверх or {})
    итог["в_замке_нет_фото"] = "photos" not in (сверх or {})

    # Повторный вход в уже открытый чат — бесплатно и с анкетой. Здесь квота
    # уже потрачена целиком, и именно поэтому проверка имеет смысл: слот не
    # тратится, а состояние лимита при этом `exhausted`
    повтор = await c.get_match_partner("MM1", "M0", spend=True)
    итог["повтор_открыт"] = bool(повтор and not повтор.get("locked"))
    итог["повтор_с_именем"] = (повтор or {}).get("display_name")

    # Проверка участия и подсказка слот не тратят: `spend` по умолчанию False.
    # Открытый мэтч они обязаны отдавать как есть
    без_траты = await c.get_match_partner("MM2", "M0")
    итог["без_траты_открыт"] = bool(без_траты and not без_траты.get("locked"))

    # Закрытый мэтч без траты — тоже замок: путей к партнёру четыре, и
    # «замок только на кнопке открытия» протекал бы в трёх остальных
    закрытый_без_траты = await c.get_match_partner(f"MM{МЭТЧЕЙ + 2}", "M0")
    итог["закрытый_без_траты_закрыт"] = bool(
        закрытый_без_траты and закрытый_без_траты.get("locked")
    )

    async with session_cls() as s:
        итог["просмотров_в_базе"] = (await s.execute(
            select(MatchView).where(MatchView.user_id == "M0")
        )).scalars().all().__len__()

    # Список после исчерпания: открытые — с именами, остальные под замком
    список_после = await c.get_user_matches("M0")
    открытые = {f"MM{i}" for i in range(1, МЭТЧЕЙ + 1)}
    итог["всего_в_списке"] = len(список_после)
    итог["закрытых_после"] = sum(1 for м in список_после if м.get("locked"))
    итог["открытые_с_именами"] = all(
        м["partner_name"].startswith("Собеседник")
        for м in список_после if м["id"] in открытые
    )
    итог["имена_закрытых"] = sorted({
        м["partner_name"] for м in список_после if м.get("locked")
    })
    # Сам мэтч из списка не исчезает — он и есть витрина подписки
    итог["закрытые_остались_в_списке"] = all(
        м["id"] in {х["id"] for х in список_после}
        for м in список_до
    )

    # Чужой match_id по-прежнему не открывается: лимит не должен был подменить
    # проверку участия замком, иначе IDOR вернулся бы «закрытым» ответом
    async with session_cls() as s:
        человек(s, "X0", 999, "Посторонний")
        await s.commit()
    чужой = await c.get_match_partner("MM1", "X0", spend=True)
    итог["чужой_мэтч_none"] = чужой is None

    async with session_cls() as s:
        сводка = await quotas.limits_summary(Сессия(s, []), "M0")
    итог["сводка_мэтчи_осталось"] = сводка["matches"].left
    итог["сводка_мэтчи_лимит"] = сводка["matches"].limit
    итог["сводка_лайки_осталось"] = сводка["likes"].left
    итог["сводка_free"] = сводка["free"]

    await engine.dispose()
    return итог


async def проверить_окно() -> dict:
    """Слот возвращается по истечении окна, а не в календарную полночь."""
    engine = await поднять_базу()
    session_cls = подключить(engine, [])

    давно = datetime.now(timezone.utc) - timedelta(hours=25)
    async with session_cls() as s:
        человек(s, "W0", 400, "Вчерашний")
        for i in range(1, МЭТЧЕЙ + 2):
            человек(s, f"V{i}", 400 + i, f"Собеседник {i}")
            s.add(Match(
                id=f"WM{i}", user1_id="W0", user2_id=f"V{i}", is_active=True,
                created_at=datetime(2026, 1, 1) + timedelta(minutes=i),
            ))
            # Квота выбрана целиком, но вчера — окно скользящее, значит слоты
            # уже вернулись
            if i <= МЭТЧЕЙ:
                s.add(MatchView(user_id="W0", match_id=f"WM{i}", viewed_at=давно))
        for i in range(1, ЛАЙКОВ + 1):
            человек(s, f"L{i}", 4400 + i, f"Лайкнутый {i}")
            s.add(Like(liker_id="W0", liked_id=f"L{i}", type="like", created_at=давно))
        await s.commit()

    новый = await c.get_match_partner(f"WM{МЭТЧЕЙ + 1}", "W0", spend=True)
    лайк = await c.like_and_match("W0", "V1", "like")

    async with session_cls() as s:
        сводка = await quotas.limits_summary(Сессия(s, []), "W0")
        # Просмотр из прошлого окна продлевается на месте, а не дублируется:
        # пара (user_id, match_id) уникальна
        старый = await c.get_match_partner("WM1", "W0", spend=True)
        просмотров = len((await s.execute(
            select(MatchView).where(MatchView.user_id == "W0")
        )).scalars().all())

    итог = {
        "мэтч_за_окном_открылся": bool(новый and not новый.get("locked")),
        "лайк_за_окном_прошёл": not лайк.get("limited"),
        # Обе цифры — расход ВНУТРИ окна. Вчерашние строки лежат в базе и в
        # счёт не идут, поэтому здесь по единице: ровно то одно действие,
        # которое сделано выше
        "лайков_в_окне": сводка["likes"].used,
        "просмотров_в_окне": сводка["matches"].used,
        "старый_мэтч_переоткрылся": bool(старый and not старый.get("locked")),
        "просмотров_в_базе_после_окна": просмотров,
    }
    await engine.dispose()
    return итог


def слить(ответ: dict, добавка: dict) -> None:
    """Сложить результаты сценария в общий ответ, падая на совпадении ключей.

    Сценарии пишут в одно пространство имён, и `dict.update` тихо затирал бы
    одноимённые ключи последним значением. Так уже вышло: «лимит сверх квоты»
    писали и лайки, и мэтчи, и тест сравнивал лимит открытий с числом лайков —
    зелёный тест на разъехавшихся данных. Дубликат — это ошибка скрипта, и она
    обязана быть видна сразу.
    """
    for ключ, значение in добавка.items():
        assert ключ not in ответ, f"ключ {ключ!r} пишут два сценария"
        ответ[ключ] = значение


async def main() -> None:
    журнал: list[str] = []
    ответ: dict = {}
    слить(ответ, await проверить_лайки(журнал))
    слить(ответ, await проверить_платный())
    слить(ответ, await проверить_код_тарифа())
    слить(ответ, await проверить_просроченный())
    слить(ответ, await проверить_мэтчи())
    слить(ответ, await проверить_окно())
    ответ["лимит_лайков"] = ЛАЙКОВ
    ответ["лимит_мэтчей"] = МЭТЧЕЙ
    # Порядок захвата на первом лайке: личный, потом парный. Совпадает с
    # api/routers/likes.py — обратный порядок в одном из сервисов это дедлок
    ответ["первые_локи"] = журнал[:2]
    print(json.dumps(ответ, ensure_ascii=False, default=str))


# `text` подменяем на уровне модуля бота: advisory-локов в SQLite нет, а
# остальной SQL обязан идти как есть
c.text = _без_advisory
quotas.sa_text = _без_advisory

asyncio.run(main())
