"""Тарифная линейка на стороне бота.

Копия `api/services/plans.py` — бот отдельный сервис и импортировать код API
не может. Значения обязаны совпадать: их сверяет тест
`test_тарифы_совпадают_в_боте_и_api`, иначе человек увидел бы в боте одну цену,
а в мини-аппе другую.

Цены в рублях. Stars и CryptoBot считают в своих единицах, поэтому для них
рублёвая цена пересчитывается по курсу из настроек.
"""

from __future__ import annotations

from dataclasses import dataclass

TIER_FREE = "free"
TIER_PLUS = "plus"
TIER_ULTRA = "ultra"

TIER_ORDER: tuple[str, ...] = (TIER_FREE, TIER_PLUS, TIER_ULTRA)


@dataclass(frozen=True)
class Plan:
    code: str
    tier: str
    months: int
    days: int
    price_rub: int

    @property
    def title(self) -> str:
        name = "Ultra" if self.tier == TIER_ULTRA else "Plus"
        if self.months == 1:
            return f"{name} на месяц"
        return f"{name} на {self.months} мес."

    @property
    def price_per_month(self) -> int:
        return round(self.price_rub / self.months)


PLANS: tuple[Plan, ...] = (
    Plan("plus_1m", TIER_PLUS, 1, 30, 149),
    Plan("plus_3m", TIER_PLUS, 3, 90, 379),
    Plan("plus_12m", TIER_PLUS, 12, 365, 1290),
    Plan("ultra_1m", TIER_ULTRA, 1, 30, 299),
    Plan("ultra_3m", TIER_ULTRA, 3, 90, 749),
    Plan("ultra_12m", TIER_ULTRA, 12, 365, 2590),
)

PLANS_BY_CODE: dict[str, Plan] = {p.code: p for p in PLANS}

#: Что даёт уровень — для витрины в боте.
TIER_PERKS: dict[str, tuple[str, ...]] = {
    TIER_PLUS: (
        "👀 Видно, кто вас лайкнул",
        "🥷 Режим инкогнито",
        "⭐ 5 суперлайков в день",
        "🚀 Приоритет в выдаче",
    ),
    TIER_ULTRA: (
        "✨ Всё из Plus",
        "⭐ 15 суперлайков в день",
        "🚪 Кто заходил в вашу анкету",
        "🚀 Максимальный приоритет в выдаче",
    ),
}

TIER_NAMES: dict[str, str] = {
    TIER_FREE: "Бесплатно",
    TIER_PLUS: "Plus",
    TIER_ULTRA: "Ultra",
}


def tier_rank(tier: str) -> int:
    """Старшинство уровня; неизвестный считаем бесплатным."""
    try:
        return TIER_ORDER.index(tier)
    except ValueError:
        return 0


def plans_for(tier: str) -> list[Plan]:
    return [p for p in PLANS if p.tier == tier]
