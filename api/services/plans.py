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
#: Верхний уровень. Латиницей, как и соседи, чтобы линейка Plus — Ultra —
#: Aurora читалась одним рядом.
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
    Plan("plus_1m", TIER_PLUS, 1, 30, 149, "com.simp.dating.plus.monthly"),
    Plan("plus_3m", TIER_PLUS, 3, 90, 379, "com.simp.dating.plus.quarterly"),
    Plan("plus_12m", TIER_PLUS, 12, 365, 1290, "com.simp.dating.plus.yearly"),
    Plan("ultra_1m", TIER_ULTRA, 1, 30, 299, "com.simp.dating.ultra.monthly"),
    Plan("ultra_3m", TIER_ULTRA, 3, 90, 749, "com.simp.dating.ultra.quarterly"),
    Plan("ultra_12m", TIER_ULTRA, 12, 365, 2590, "com.simp.dating.ultra.yearly"),
    Plan("aurora_1m", TIER_AURORA, 1, 30, 599, "com.simp.dating.aurora.monthly"),
    Plan("aurora_3m", TIER_AURORA, 3, 90, 1490, "com.simp.dating.aurora.quarterly"),
    Plan("aurora_12m", TIER_AURORA, 12, 365, 4990, "com.simp.dating.aurora.yearly"),
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
        perks=("10 лайков в день", "3 мэтча в день", "1 суперлайк в день"),
    ),
    TIER_PLUS: TierInfo(
        TIER_PLUS,
        "Plus",
        superlikes=5,
        perks=(
            "Лайки без ограничений",
            "Все мэтчи открыты, без суточного лимита",
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
    #: Свои цвета в чате поверх готовых пресетов. Пресетов бесплатных
    #: большинство — платим за произвольный цвет, а не за возможность
    #: вообще поменять оформление.
    "chat_theme_custom": TIER_PLUS,
    #: Премиальные схемы оформления приложения (см. services/appearance.py).
    "appearance_premium": TIER_PLUS,
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


#: Сентинел «без ограничения». Ноль здесь занят смыслом «нельзя совсем» —
#: так его читает соседняя `DIRECT_MESSAGES_PER_DAY`, где 0 закрывает фичу.
#: Если бы безлимит тоже был нулём, одна опечатка в таблице открыла бы
#: бесплатному уровню то, что ему не продано, и наоборот.
UNLIMITED = -1


def is_unlimited(limit: int) -> bool:
    return limit < 0


#: Сколько лайков в сутки. Бесплатный уровень — 10: это главный рычаг
#: конверсии, потому что лимит упирается ровно в тот момент, когда человек
#: уже втянулся в свайпы. Пропуск (👎) НЕ считается — иначе лимит превращался
#: бы в запрет смотреть анкеты, а нам нужно, чтобы смотрели дальше и видели,
#: кого не могут лайкнуть.
LIKES_PER_DAY: dict[str, int] = {
    TIER_FREE: 10,
    TIER_PLUS: UNLIMITED,
    TIER_ULTRA: UNLIMITED,
    TIER_AURORA: UNLIMITED,
}

#: Сколько мэтчей в сутки можно открыть на бесплатном уровне. Лимит на
#: РАЗНЫЕ мэтчи, а не на открытия: повторный вход в уже открытый чат в
#: пределах суток бесплатный, иначе человек тратил бы квоту на то, что уже
#: прочитал.
MATCH_VIEWS_PER_DAY: dict[str, int] = {
    TIER_FREE: 3,
    TIER_PLUS: UNLIMITED,
    TIER_ULTRA: UNLIMITED,
    TIER_AURORA: UNLIMITED,
}

#: Окно суточных лимитов — скользящие 24 часа, а не календарный день.
#: Причина та же, по которой так считается квота суперлайков: у нас нет
#: часового пояса пользователя, а полночь по UTC для половины аудитории
#: приходится на середину вечера. Скользящее окно ещё и возвращает лайки
#: постепенно, вместо давки в 00:00.
LIMIT_WINDOW_HOURS = 24


def likes_per_day(tier: str) -> int:
    """Лимит лайков уровня. `UNLIMITED` — без ограничения."""
    return LIKES_PER_DAY[TIER_ORDER[tier_rank(tier)]]


def match_views_per_day(tier: str) -> int:
    """Сколько разных мэтчей в сутки можно открыть. `UNLIMITED` — все."""
    return MATCH_VIEWS_PER_DAY[TIER_ORDER[tier_rank(tier)]]


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


def superlikes_for(tier: str) -> int:
    return TIERS[TIER_ORDER[tier_rank(tier)]].superlikes


def plan_for_appstore_id(product_id: str) -> Plan | None:
    return PLANS_BY_APPSTORE_ID.get(product_id)


# ── Паки: разовые покупки за Telegram Stars ──────────────────────

#: Виды паков. Суперлайки падают в Profile.bonus_superlikes, бусты — в
#: Profile.bonus_boosts; оба пула тратятся ПОСЛЕ суточной квоты, чтобы
#: купленное не сгорало вместо того, что и так вернётся завтра.
PACK_SUPERLIKES = "superlikes"
PACK_BOOSTS = "boosts"


@dataclass(frozen=True)
class Pack:
    """Один пак: что начисляет и почём в Stars.

    Цена в Stars, а не в рублях, — единственное исключение из правила
    «цены в рублях»: паки продаются только за Stars (импульсная покупка
    внутри Telegram, у СБП-провайдеров мелкие суммы упираются в минималки,
    у крипты — в комиссии), и пересчёт по курсу давал бы кривые 24⭐/26⭐
    при каждом сдвиге RUB_PER_STAR.
    """

    code: str
    kind: str
    qty: int
    price_stars: int

    @property
    def title(self) -> str:
        """«5 суперлайков» / «1 буст» — имя для счёта и кнопки."""
        if self.kind == PACK_SUPERLIKES:
            return f"{self.qty} {_склонение(self.qty, 'суперлайк', 'суперлайка', 'суперлайков')}"
        return f"{self.qty} {_склонение(self.qty, 'буст', 'буста', 'бустов')}"

    @property
    def price_per_item(self) -> float:
        """Цена за штуку — по ней тест закрепляет скидку за объём."""
        return self.price_stars / self.qty


def _склонение(n: int, один: str, два: str, пять: str) -> str:
    if n % 10 == 1 and n % 100 != 11:
        return один
    if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14):
        return два
    return пять


#: Крупный пак дешевле за штуку — иначе его покупать незачем. Бусты дороже
#: суперлайков: буст — полчаса приоритета в деке и очереди оценки фото,
#: суперлайк — одно уведомление.
PACKS: tuple[Pack, ...] = (
    Pack("superlikes_5", PACK_SUPERLIKES, 5, 25),
    Pack("superlikes_15", PACK_SUPERLIKES, 15, 59),
    Pack("superlikes_50", PACK_SUPERLIKES, 50, 149),
    Pack("boosts_1", PACK_BOOSTS, 1, 29),
    Pack("boosts_3", PACK_BOOSTS, 3, 69),
    Pack("boosts_10", PACK_BOOSTS, 10, 179),
)

PACKS_BY_CODE: dict[str, Pack] = {p.code: p for p in PACKS}
