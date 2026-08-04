"""Тарифная линейка: что стоит и что даёт.

Один источник правды для API, бота и мини-аппа. Раньше премиум был бинарным
(`plan != "free"`), и любая платная возможность включалась всем одинаково —
продать «побольше» было нечего.

Порядок уровней важен: `TIER_ORDER` задаёт старшинство, и проверка права
работает как «не ниже требуемого уровня», а не перечислением. Иначе каждая
новая возможность требовала бы правки во всех местах, где её спрашивают.

Цены в рублях — для бота (Stars/CryptoBot пересчитывают сами) и для витрины.
В App Store цену назначает Apple по ценовой категории, поэтому там мы храним
только идентификатор продукта.
"""

from __future__ import annotations

from dataclasses import dataclass, field

#: Уровни от младшего к старшему.
TIER_FREE = "free"
TIER_PLUS = "plus"
TIER_ULTRA = "ultra"

TIER_ORDER: tuple[str, ...] = (TIER_FREE, TIER_PLUS, TIER_ULTRA)


@dataclass(frozen=True)
class Plan:
    """Один покупаемый вариант: уровень плюс срок."""

    code: str
    tier: str
    months: int
    days: int
    price_rub: int
    #: Идентификатор продукта в App Store Connect. Пусто — в iOS не продаём.
    appstore_id: str = ""

    @property
    def title(self) -> str:
        name = "Ultra" if self.tier == TIER_ULTRA else "Plus"
        if self.months == 1:
            return f"{name} на месяц"
        return f"{name} на {self.months} мес."

    @property
    def price_per_month(self) -> int:
        """Цена за месяц — по ней видно выгоду длинного срока."""
        return round(self.price_rub / self.months)


#: Скидка за срок намеренно заметная: длинный срок выгоднее и для нас —
#: он снижает отток. Месяц у Plus — 149 ₽, у Ultra — 299 ₽.
PLANS: tuple[Plan, ...] = (
    Plan("plus_1m", TIER_PLUS, 1, 30, 149, "com.souldawn.dating.plus.monthly"),
    Plan("plus_3m", TIER_PLUS, 3, 90, 379, "com.souldawn.dating.plus.quarterly"),
    Plan("plus_12m", TIER_PLUS, 12, 365, 1290, "com.souldawn.dating.plus.yearly"),
    Plan("ultra_1m", TIER_ULTRA, 1, 30, 299, "com.souldawn.dating.ultra.monthly"),
    Plan("ultra_3m", TIER_ULTRA, 3, 90, 749, "com.souldawn.dating.ultra.quarterly"),
    Plan("ultra_12m", TIER_ULTRA, 12, 365, 2590, "com.souldawn.dating.ultra.yearly"),
)

PLANS_BY_CODE: dict[str, Plan] = {p.code: p for p in PLANS}
PLANS_BY_APPSTORE_ID: dict[str, Plan] = {p.appstore_id: p for p in PLANS if p.appstore_id}


@dataclass(frozen=True)
class TierInfo:
    """Что даёт уровень. Возможности наследуются от младшего к старшему."""

    tier: str
    name: str
    #: Сколько суперлайков в сутки.
    superlikes: int
    #: Своё перечисление возможностей для витрины.
    perks: tuple[str, ...] = field(default_factory=tuple)


TIERS: dict[str, TierInfo] = {
    TIER_FREE: TierInfo(
        TIER_FREE,
        "Бесплатно",
        superlikes=1,
        perks=("Свайпы без ограничений", "Чат с мэтчами"),
    ),
    TIER_PLUS: TierInfo(
        TIER_PLUS,
        "Plus",
        superlikes=5,
        perks=(
            "Видно, кто вас лайкнул",
            "Режим инкогнито",
            "5 суперлайков в день",
            "Приоритет в выдаче",
        ),
    ),
    TIER_ULTRA: TierInfo(
        TIER_ULTRA,
        "Ultra",
        superlikes=15,
        perks=(
            "Всё из Plus",
            "15 суперлайков в день",
            "Кто заходил в вашу анкету",
            "Максимальный приоритет в выдаче",
        ),
    ),
}

#: Минимальный уровень для каждой платной возможности. Проверка идёт через
#: `tier_allows`, поэтому добавить возможность — это одна строка здесь.
FEATURE_MIN_TIER: dict[str, str] = {
    "see_who_liked": TIER_PLUS,
    "incognito": TIER_PLUS,
    "deck_boost": TIER_PLUS,
    "visitors": TIER_ULTRA,
}


def tier_rank(tier: str) -> int:
    """Старшинство уровня. Неизвестный уровень считаем бесплатным: так
    чужая или испорченная запись в БД не выдаёт платные возможности."""
    try:
        return TIER_ORDER.index(tier)
    except ValueError:
        return 0


def tier_allows(tier: str, feature: str) -> bool:
    """Доступна ли возможность на этом уровне.

    Незнакомая возможность считается закрытой: опечатка в названии не должна
    случайно открывать платное всем.
    """
    required = FEATURE_MIN_TIER.get(feature)
    if required is None:
        return False
    return tier_rank(tier) >= tier_rank(required)


def superlikes_for(tier: str) -> int:
    return TIERS[TIER_ORDER[tier_rank(tier)]].superlikes


def plan_for_appstore_id(product_id: str) -> Plan | None:
    return PLANS_BY_APPSTORE_ID.get(product_id)
