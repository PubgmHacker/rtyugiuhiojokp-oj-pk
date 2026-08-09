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

import math
from dataclasses import dataclass, field

#: Уровни от младшего к старшему.
TIER_FREE = "free"
TIER_PLUS = "plus"
TIER_ULTRA = "ultra"
#: Верхний уровень. Название из той же истории, что и марка: Souldawn —
#: рассвет, Aurora — заря; латиницей, как и соседи, чтобы линейка читалась
#: одним рядом.
TIER_AURORA = "aurora"

TIER_ORDER: tuple[str, ...] = (TIER_FREE, TIER_PLUS, TIER_ULTRA, TIER_AURORA)


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
        """«Ultra на 3 мес.» — имя уровня берём из `TIERS`, а не из условия.

        Раньше здесь стоял тернарник «Ultra, иначе Plus»: с появлением
        третьего уровня он молча назвал бы Aurora «Plus», и человек увидел бы
        в счёте не то, что покупает.
        """
        name = TIERS[self.tier].name if self.tier in TIERS else self.tier
        if self.months == 1:
            return f"{name} на месяц"
        return f"{name} на {self.months} мес."

    @property
    def price_per_month(self) -> int:
        """Цена за месяц — по ней видно выгоду длинного срока."""
        return round(self.price_rub / self.months)

    @property
    def price_per_day(self) -> int:
        """Цена за день — ею длинный срок продаётся лучше всего: «4 ₽ в день»
        читается как мелочь, а «1290 ₽» как крупная трата. Округляем вверх,
        чтобы не обещать цену ниже настоящей.
        """
        return math.ceil(self.price_rub / self.days)


#: Скидка за срок намеренно заметная: длинный срок выгоднее и для нас —
#: он снижает отток. Месяц: Plus — 149 ₽, Ultra — 299 ₽, Aurora — 599 ₽.
#:
#: Шаг между уровнями примерно двукратный. Верхний уровень нужен не потому,
#: что «пусть будет дороже»: у трёх вариантов средний выбирают чаще, чем
#: старший из двух, — Ultra продаётся лучше именно на фоне Aurora.
PLANS: tuple[Plan, ...] = (
    Plan("plus_1m", TIER_PLUS, 1, 30, 149, "com.souldawn.dating.plus.monthly"),
    Plan("plus_3m", TIER_PLUS, 3, 90, 379, "com.souldawn.dating.plus.quarterly"),
    Plan("plus_12m", TIER_PLUS, 12, 365, 1290, "com.souldawn.dating.plus.yearly"),
    Plan("ultra_1m", TIER_ULTRA, 1, 30, 299, "com.souldawn.dating.ultra.monthly"),
    Plan("ultra_3m", TIER_ULTRA, 3, 90, 749, "com.souldawn.dating.ultra.quarterly"),
    Plan("ultra_12m", TIER_ULTRA, 12, 365, 2590, "com.souldawn.dating.ultra.yearly"),
    Plan("aurora_1m", TIER_AURORA, 1, 30, 599, "com.souldawn.dating.aurora.monthly"),
    Plan("aurora_3m", TIER_AURORA, 3, 90, 1490, "com.souldawn.dating.aurora.quarterly"),
    Plan("aurora_12m", TIER_AURORA, 12, 365, 4990, "com.souldawn.dating.aurora.yearly"),
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
        perks=("Свайпы без ограничений", "Чат с мэтчами", "1 суперлайк в день"),
    ),
    TIER_PLUS: TierInfo(
        TIER_PLUS,
        "Plus",
        superlikes=5,
        perks=(
            "Видно, кто вас лайкнул",
            "Режим инкогнито",
            "5 суперлайков в день вместо 1",
            "Буст анкеты раз в день",
            "Все расклады Таро и AI-таролог",
        ),
    ),
    TIER_ULTRA: TierInfo(
        TIER_ULTRA,
        "Ultra",
        superlikes=15,
        perks=(
            "Всё из Plus",
            "Кто заходил в вашу анкету",
            "15 суперлайков в день вместо 5",
            "3 буста в день вместо одного",
            "Приоритет в выдаче",
        ),
    ),
    TIER_AURORA: TierInfo(
        TIER_AURORA,
        "Aurora",
        superlikes=30,
        perks=(
            "Всё из Ultra",
            "Письма без взаимного лайка — 10 в день",
            "Ссылка на свой канал в анкете",
            "30 суперлайков в день вместо 15",
            "5 бустов в день",
            "Максимальный приоритет в выдаче",
        ),
    ),
}

#: Минимальный уровень для каждой платной возможности. Проверка идёт через
#: `tier_allows`, поэтому добавить возможность — это одна строка здесь.
#:
#: У каждого уровня свой ОТДЕЛЬНЫЙ повод купить именно его: на одних числах
#: («суперлайков побольше») верхний уровень не продаётся.
FEATURE_MIN_TIER: dict[str, str] = {
    "see_who_liked": TIER_PLUS,
    "incognito": TIER_PLUS,
    "deck_boost": TIER_PLUS,
    #: Расклады сверх карты дня. Карта дня остаётся бесплатной: она повод
    #: открыть приложение, а не товар.
    "tarot_spreads": TIER_PLUS,
    "visitors": TIER_ULTRA,
    #: Написать человеку, который вас не лайкал (см. services/direct_messages.py).
    #: Самый сильный крючок, поэтому стоит на верхнем уровне — так же, как у
    #: «Мимолёта», где это функция старшего тарифа.
    "direct_messages": TIER_AURORA,
    #: Ссылка на свой канал в анкете — витринная возможность верхнего уровня.
    "tg_channel": TIER_AURORA,
}

#: Сколько писем без взаимного лайка можно отправить за сутки. Ниже Aurora — 0
#: (фича закрыта совсем). Даже на верхнем уровне это НЕ безлимит: письма
#: незнакомым без лимита превращают платную функцию в канал для спама, а
#: получателю дейтинг с потоком писем от незнакомцев быстро надоедает.
DIRECT_MESSAGES_PER_DAY: dict[str, int] = {
    TIER_FREE: 0,
    TIER_PLUS: 0,
    TIER_ULTRA: 0,
    TIER_AURORA: 10,
}


def direct_messages_per_day(tier: str) -> int:
    return DIRECT_MESSAGES_PER_DAY.get(TIER_ORDER[tier_rank(tier)], 0)


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


#: Сколько раз в сутки можно включить буст на каждом уровне. Ноль — нельзя.
BOOSTS_PER_DAY: dict[str, int] = {
    TIER_FREE: 0,
    TIER_PLUS: 1,
    TIER_ULTRA: 3,
    TIER_AURORA: 5,
}

#: Сколько минут длится одно включение. Короткий срок намеренно: буст должен
#: тратиться тогда, когда человек сам в приложении и готов отвечать.
BOOST_MINUTES = 30


def boosts_per_day(tier: str) -> int:
    return BOOSTS_PER_DAY[TIER_ORDER[tier_rank(tier)]]


#: Прибавка к месту в деке. Продаётся дословно: «Приоритет в выдаче» — только
#: у Ultra, «Максимальный приоритет» — у Aurora. У Plus приоритета в перках
#: нет, поэтому и здесь ноль.
#:
#: Раньше в `services/matching.py` стояла одна константа на всех, кто вообще
#: платит (`Subscription.plan != "free"` → `score += 25`): Plus получал то, что
#: ему не продавали, а Aurora — ровно то же, что Ultra, хотя стоит вдвое
#: дороже именно за «максимальный». Слово в витрине должно отличаться числом.
DECK_PRIORITY: dict[str, int] = {
    TIER_FREE: 0,
    TIER_PLUS: 0,
    TIER_ULTRA: 25,
    TIER_AURORA: 45,
}


def deck_priority(tier: str) -> int:
    """Сколько очков ранжирования даёт уровень. Незнакомый — ноль."""
    return DECK_PRIORITY[TIER_ORDER[tier_rank(tier)]]


def tier_from_plan(plan: str | None) -> str:
    """Уровень по значению `Subscription.plan`, без обращения к БД.

    Одно место на весь проект: `current_tier` спрашивает срок и зовёт эту
    функцию, а ранжирование деки читает уровни пачкой одним запросом и зовёт
    её же. Пока разбор жил внутри `current_tier`, обойти его (как делала дека)
    означало молча потерять и совместимость со старым `plan="premium"`, и
    защиту от испорченного значения.
    """
    if not plan or plan == TIER_FREE:
        return TIER_FREE
    if plan == "premium":
        # Записи до появления линейки: тогда продавалось ровно то, что сейчас Plus
        return TIER_PLUS
    # Неизвестное значение не должно открывать платное
    return plan if tier_rank(plan) > 0 else TIER_FREE


def superlikes_for(tier: str) -> int:
    return TIERS[TIER_ORDER[tier_rank(tier)]].superlikes


def plan_for_appstore_id(product_id: str) -> Plan | None:
    return PLANS_BY_APPSTORE_ID.get(product_id)
