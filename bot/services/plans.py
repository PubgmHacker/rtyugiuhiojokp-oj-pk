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

#: Копия api/services/plans.py::DIRECT_MESSAGES_PER_DAY — сколько писем без
#: взаимного лайка можно отправить за сутки. Free — 0 (фича закрыта).
DIRECT_MESSAGES_PER_DAY: dict[str, int] = {
    TIER_FREE: 0,
    TIER_PLUS: 3,
    TIER_ULTRA: 10,
}


def direct_messages_per_day(tier: str) -> int:
    return DIRECT_MESSAGES_PER_DAY.get(TIER_ORDER[tier_rank(tier)], 0)

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
    """
    from database import get_active_subscription

    sub = await get_active_subscription(user_id)
    tier = (sub or {}).get("plan") or TIER_FREE
    return tier_rank(tier) >= tier_rank(TIER_PLUS)
