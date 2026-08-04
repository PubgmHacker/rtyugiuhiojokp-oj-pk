"""Кейсы: попытка за подписку, награда — то, что работает в продукте.

У конкурента из кейса выпадают коллекционные персонажи. Здесь — суперлайки и
минуты буста: шестьдесят рисунков рисовать не для чего, а полезная награда
работает сразу.

Шансы заданы явно и в сумме дают единицу. Проверяется тестом: подкрутить
незаметно нельзя, а «щедрый» кейс, из которого всегда выпадает максимум, не
воспринимается как награда.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

REWARD_SUPERLIKE = "superlike"
REWARD_BOOST = "boost"


@dataclass(frozen=True)
class Reward:
    """Одна возможная награда."""

    code: str
    #: Сколько начисляем: суперлайков или минут буста.
    amount: int
    #: Вероятность выпадения, 0..1.
    chance: float
    title: str

    @property
    def unit(self) -> str:
        return "минут буста" if self.code == REWARD_BOOST else "суперлайк"


#: Порядок важен только для витрины «что можно выиграть». Сумма шансов = 1.
REWARDS: tuple[Reward, ...] = (
    Reward(REWARD_SUPERLIKE, 1, 0.44, "1 суперлайк"),
    Reward(REWARD_SUPERLIKE, 3, 0.22, "3 суперлайка"),
    Reward(REWARD_BOOST, 15, 0.20, "15 минут буста"),
    Reward(REWARD_SUPERLIKE, 10, 0.08, "10 суперлайков"),
    Reward(REWARD_BOOST, 60, 0.06, "60 минут буста"),
)

#: Сколько попыток в сутки даёт каждый уровень. Бесплатному — ни одной: это
#: бонус подписки, иначе он не помогает её продать.
OPENINGS_PER_DAY: dict[str, int] = {
    "free": 0,
    "plus": 1,
    "ultra": 3,
}


def openings_per_day(tier: str) -> int:
    """Незнакомый уровень считаем бесплатным: испорченная запись в БД не
    должна выдавать попытки."""
    return OPENINGS_PER_DAY.get(tier, 0)


def roll() -> Reward:
    """Выбрать награду по заданным шансам.

    `random.choices` с весами, а не сравнение с накопленной суммой: последнее
    легко написать так, что последняя награда не выпадет никогда.
    """
    return random.choices(REWARDS, weights=[r.chance for r in REWARDS], k=1)[0]
