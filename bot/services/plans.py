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

#: Что даёт уровень — для витрины в боте. Держим в том же порядке и тем же
#: смыслом, что `TIERS[...].perks` в API: человек сравнивает уровни в боте, а
#: покупает в мини-аппе, и расхождение читается как обман.
TIER_PERKS: dict[str, tuple[str, ...]] = {
    TIER_PLUS: (
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
}


def tier_rank(tier: str) -> int:
    """Старшинство уровня; неизвестный считаем бесплатным."""
    try:
        return TIER_ORDER.index(tier)
    except ValueError:
        return 0


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
