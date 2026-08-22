"""Тарифная линейка на стороне бота.

Копия `api/services/plans.py` — бот отдельный сервис и импортировать код API
не может. Значения обязаны совпадать: их сверяет тест
`test_тарифы_совпадают_в_боте_и_api`, иначе человек увидел бы в боте одну цену,
а в мини-аппе другую.

Цены в рублях. Stars и CryptoBot считают в своих единицах, поэтому для них
рублёвая цена пересчитывается по курсу из настроек.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

TIER_FREE = "free"
TIER_PLUS = "plus"
TIER_ULTRA = "ultra"
#: Верхний уровень — см. api/services/plans.py.
TIER_AURORA = "aurora"

TIER_ORDER: tuple[str, ...] = (TIER_FREE, TIER_PLUS, TIER_ULTRA, TIER_AURORA)


@dataclass(frozen=True)
class Plan:
    code: str
    tier: str
    months: int
    days: int
    price_rub: int

    @property
    def title(self) -> str:
        """Имя уровня берём из `TIER_NAMES`, а не из условия: тернарник
        «Ultra, иначе Plus» назвал бы Aurora в счёте чужим именем."""
        name = TIER_NAMES.get(self.tier, self.tier)
        if self.months == 1:
            return f"{name} на месяц"
        return f"{name} на {self.months} мес."

    @property
    def price_per_month(self) -> int:
        return round(self.price_rub / self.months)

    @property
    def price_per_day(self) -> int:
        """Цена за день — ею продаётся длинный срок. Вверх, чтобы не обещать
        цену ниже настоящей."""
        return math.ceil(self.price_rub / self.days)


PLANS: tuple[Plan, ...] = (
    Plan("plus_1m", TIER_PLUS, 1, 30, 149),
    Plan("plus_3m", TIER_PLUS, 3, 90, 379),
    Plan("plus_12m", TIER_PLUS, 12, 365, 1290),
    Plan("ultra_1m", TIER_ULTRA, 1, 30, 299),
    Plan("ultra_3m", TIER_ULTRA, 3, 90, 749),
    Plan("ultra_12m", TIER_ULTRA, 12, 365, 2590),
    Plan("aurora_1m", TIER_AURORA, 1, 30, 599),
    Plan("aurora_3m", TIER_AURORA, 3, 90, 1490),
    Plan("aurora_12m", TIER_AURORA, 12, 365, 4990),
)

PLANS_BY_CODE: dict[str, Plan] = {p.code: p for p in PLANS}

#: Копия api/services/plans.py::DIRECT_MESSAGES_PER_DAY — сколько писем без
#: взаимного лайка можно отправить за сутки. Ниже Aurora фича закрыта совсем.
DIRECT_MESSAGES_PER_DAY: dict[str, int] = {
    TIER_FREE: 0,
    TIER_PLUS: 0,
    TIER_ULTRA: 0,
    TIER_AURORA: 10,
}


def direct_messages_per_day(tier: str) -> int:
    return DIRECT_MESSAGES_PER_DAY.get(TIER_ORDER[tier_rank(tier)], 0)


#: Копия api/services/plans.py::UNLIMITED. Ноль занят смыслом «нельзя совсем»
#: (см. DIRECT_MESSAGES_PER_DAY выше), поэтому безлимит — отрицательный.
UNLIMITED = -1


def is_unlimited(limit: int) -> bool:
    return limit < 0


#: Копия api/services/plans.py::LIKES_PER_DAY. Бот пишет лайки напрямую через
#: `database/connection.like_and_match`, минуя API, поэтому лимит обязан жить и
#: здесь: иначе бесплатный аккаунт обходил бы его, просто свайпая в боте.
LIKES_PER_DAY: dict[str, int] = {
    TIER_FREE: 10,
    TIER_PLUS: UNLIMITED,
    TIER_ULTRA: UNLIMITED,
    TIER_AURORA: UNLIMITED,
}

#: Копия api/services/plans.py::MATCH_VIEWS_PER_DAY — сколько РАЗНЫХ мэтчей в
#: сутки можно открыть. Повторный вход в уже открытый чат бесплатный.
MATCH_VIEWS_PER_DAY: dict[str, int] = {
    TIER_FREE: 3,
    TIER_PLUS: UNLIMITED,
    TIER_ULTRA: UNLIMITED,
    TIER_AURORA: UNLIMITED,
}

#: Копия api/services/plans.py::LIMIT_WINDOW_HOURS — окно скользящее, а не
#: календарные сутки: часового пояса пользователя у нас нет.
LIMIT_WINDOW_HOURS = 24


def likes_per_day(tier: str) -> int:
    """Лимит лайков уровня. `UNLIMITED` — без ограничения."""
    return LIKES_PER_DAY[TIER_ORDER[tier_rank(tier)]]


def match_views_per_day(tier: str) -> int:
    """Сколько разных мэтчей в сутки можно открыть. `UNLIMITED` — все."""
    return MATCH_VIEWS_PER_DAY[TIER_ORDER[tier_rank(tier)]]


#: Что даёт уровень — для витрины в боте. Держим в том же порядке и тем же
#: смыслом, что `TIERS[...].perks` в API: человек сравнивает уровни в боте, а
#: покупает в мини-аппе, и расхождение читается как обман.
TIER_PERKS: dict[str, tuple[str, ...]] = {
    TIER_PLUS: (
        "💞 Лайки без ограничений",
        "💌 Все мэтчи открыты, без суточного лимита",
        "👀 Видно, кто вас лайкнул",
        "🥷 Режим инкогнито",
        "⭐ 5 суперлайков в день вместо 1",
        "🚀 Буст анкеты раз в день",
        "🔮 Все расклады Таро и AI-таролог",
    ),
    TIER_ULTRA: (
        "✨ Всё из Plus",
        "🚪 Кто заходил в вашу анкету",
        "⭐ 15 суперлайков в день вместо 5",
        "🚀 3 буста в день вместо одного",
        "📈 Приоритет в выдаче",
    ),
    TIER_AURORA: (
        "✨ Всё из Ultra",
        "✉️ Письма без взаимного лайка — 10 в день",
        "📣 Ссылка на свой канал в анкете",
        "⭐ 30 суперлайков в день вместо 15",
        "🚀 5 бустов в день",
        "📈 Максимальный приоритет в выдаче",
    ),
}

TIER_NAMES: dict[str, str] = {
    TIER_FREE: "Бесплатно",
    TIER_PLUS: "Plus",
    TIER_ULTRA: "Ultra",
    TIER_AURORA: "Aurora",
}

#: Значок уровня для клавиатур бота. Живёт рядом с именами, а не в хендлере:
#: пока значки были вписаны прямо в кнопки, добавленный уровень остался и без
#: значка, и без самой кнопки.
TIER_ICONS: dict[str, str] = {
    TIER_PLUS: "✨",
    TIER_ULTRA: "👑",
    TIER_AURORA: "💎",
}


#: Копия api/services/plans.py::FEATURE_MIN_TIER. Бот спрашивал права
#: сравнением с литералом (`tier_rank(tier) >= tier_rank(TIER_PLUS)`), и при
#: переносе возможности на другой уровень API и бот разъезжались молча: в
#: мини-аппе закрыто, в боте открыто. Совпадение сверяет тест
#: `test_гейты_фич_совпадают_в_боте_и_api`.
FEATURE_MIN_TIER: dict[str, str] = {
    "see_who_liked": TIER_PLUS,
    "incognito": TIER_PLUS,
    "deck_boost": TIER_PLUS,
    "tarot_spreads": TIER_PLUS,
    "visitors": TIER_ULTRA,
    "direct_messages": TIER_AURORA,
    "tg_channel": TIER_AURORA,
    #: Свои цвета в чате поверх готовых пресетов: платим за произвольный
    #: цвет, а не за возможность вообще поменять оформление.
    "chat_theme_custom": TIER_PLUS,
    #: Премиальные схемы оформления приложения.
    "appearance_premium": TIER_PLUS,
}


def tier_rank(tier: str) -> int:
    """Старшинство уровня; неизвестный считаем бесплатным."""
    try:
        return TIER_ORDER.index(tier)
    except ValueError:
        return 0


def tier_from_plan(plan: str | None) -> str:
    """Уровень по значению `Subscription.plan`. Копия api/services/plans.py.

    Понадобилась вместе с суточными лимитами: их считает
    `services/quotas.py`, и он обязан читать `plan` ровно так же, как API.
    Иначе подписчик со старой записью `plan="premium"` получал бы в боте
    десять лайков в сутки, а в мини-аппе — безлимит: одна и та же оплата, два
    разных лимита, и виноват выглядит продукт.
    """
    if not plan or plan == TIER_FREE:
        return TIER_FREE
    if plan == "premium":
        # Записи до появления линейки: тогда продавалось ровно то, что сейчас Plus
        return TIER_PLUS
    план = PLANS_BY_CODE.get(plan)
    if план is not None:
        # В колонке лежит код тарифа, а не уровень («plus_1m» вместо «plus»).
        # Сейчас так не пишет никто, но словари стоят рядом и путаются в одну
        # букву, а цена ошибки односторонняя: код — это оплаченный продукт, и
        # прочитать его как `free` значит молча отобрать купленное. Обратное
        # невозможно — неизвестное значение по-прежнему ниже.
        return план.tier
    # Неизвестное значение не должно открывать платное
    return plan if tier_rank(plan) > 0 else TIER_FREE


def tier_allows(tier: str, feature: str) -> bool:
    """Доступна ли возможность на этом уровне. Незнакомая — закрыта."""
    required = FEATURE_MIN_TIER.get(feature)
    if required is None:
        return False
    return tier_rank(tier) >= tier_rank(required)


def имя_уровня_для(feature: str) -> str:
    """Имя уровня, на котором открывается возможность — для текстов бота.

    Тексты писали литералом («видно в Plus»), и перенос возможности на другой
    уровень оставлял бота рекламировать старый: человек покупал Plus за то,
    что уже отдали Ultra.
    """
    return TIER_NAMES.get(FEATURE_MIN_TIER.get(feature, ""), "Premium")


def plans_for(tier: str) -> list[Plan]:
    return [p for p in PLANS if p.tier == tier]


async def видно_кто_лайкнул(user_id: str) -> bool:
    """Доступно ли этому человеку «кто вас лайкнул».

    Это платный гейт, и он продаётся дословно так: «👀 Видно, кто вас лайкнул»
    (см. FEATURES выше). В мини-аппе он соблюдается — `api/routers/likes.py`
    отдаёт бесплатному пользователю карточку без имени и фото. Бот же
    показывал анкету лайкнувшего целиком и любому, то есть раздавал бесплатно
    то, что сам же продаёт.

    Живёт здесь, а не в хендлере, потому что путей уведомления два: лайк из
    бота (`handlers/dating.py`) и лайк из мини-аппа, прилетающий через Redis
    (`services/redis_subscriber.py`). Ровно на таких парах в этом проекте и
    разъезжается логика.

    Уровень спрашиваем у таблицы возможностей, а не сравниваем с TIER_PLUS:
    перенеси API эту фичу выше — бот последует, а не останется раздавать её.
    """
    from database import get_active_subscription

    sub = await get_active_subscription(user_id)
    tier = (sub or {}).get("plan") or TIER_FREE
    return tier_allows(tier, "see_who_liked")


# ── Паки: разовые покупки за Telegram Stars ──────────────────────

#: Копия api/services/plans.py::PACK_* — виды паков.
PACK_SUPERLIKES = "superlikes"
PACK_BOOSTS = "boosts"


@dataclass(frozen=True)
class Pack:
    """Копия api/services/plans.py::Pack — сверяет test_паки_совпадают_в_боте_и_api.

    Цена в Stars, а не в рублях: паки продаются только за Stars, и пересчёт
    по курсу давал бы кривые суммы при каждом сдвиге RUB_PER_STAR.
    """

    code: str
    kind: str
    qty: int
    price_stars: int

    @property
    def title(self) -> str:
        if self.kind == PACK_SUPERLIKES:
            return f"{self.qty} {_склонение(self.qty, 'суперлайк', 'суперлайка', 'суперлайков')}"
        return f"{self.qty} {_склонение(self.qty, 'буст', 'буста', 'бустов')}"


def _склонение(n: int, один: str, два: str, пять: str) -> str:
    if n % 10 == 1 and n % 100 != 11:
        return один
    if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14):
        return два
    return пять


PACKS: tuple[Pack, ...] = (
    Pack("superlikes_5", PACK_SUPERLIKES, 5, 25),
    Pack("superlikes_15", PACK_SUPERLIKES, 15, 59),
    Pack("superlikes_50", PACK_SUPERLIKES, 50, 149),
    Pack("boosts_1", PACK_BOOSTS, 1, 29),
    Pack("boosts_3", PACK_BOOSTS, 3, 69),
    Pack("boosts_10", PACK_BOOSTS, 10, 179),
)

PACKS_BY_CODE: dict[str, Pack] = {p.code: p for p in PACKS}

#: Значок вида пака для кнопок — суперлайк узнают по звезде, буст по ракете.
PACK_ICONS: dict[str, str] = {
    PACK_SUPERLIKES: "⭐",
    PACK_BOOSTS: "🚀",
}
