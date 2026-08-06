"""Расклады Таро — детерминированный выбор карт плюс необязательная AI-фраза.

Общий принцип — как в дневной карте (services/daily_card.py): расклад не
хранится в БД, а выводится хешем от пары «кто + когда» (+ тип расклада и его
параметры). Нажатие «обновить» не меняет карты, пока не сменится дата —
иначе расклад ничего не стоит и не годится поводом для разговора в чате.

AI (Zhipu GLM) добавляет только живую фразу поверх готовых карт и их значений.
Без ключа ZHIPU_API_KEY раздел обязан работать и выдавать заготовленный
текст, а не ошибку и не пустой ответ — это тот же паттерн деградации, что и в
services/ai_matchmaker.py и services/daily_card.py.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from dataclasses import dataclass
from datetime import date

from services.tarot_deck import DECK, TarotCard

logger = logging.getLogger(__name__)


def _digest(*parts: str) -> bytes:
    """Хеш от произвольного набора строк — общая точка входа для всех
    раскладов, чтобы правило «один и тот же вход даёт один и тот же выход»
    не пришлось переописывать в каждой функции."""
    return hashlib.sha256(":".join(parts).encode()).digest()


def _pick(seed: str, index: int, exclude: set[int] | None = None) -> tuple[int, TarotCard]:
    """Выбрать карту колоды по хешу `seed:index`.

    `exclude` нужен для раскладов из нескольких карт: без него позиции
    расклада могли бы совпасть, и «прошлое» и «будущее» иногда были бы одной
    и той же картой — для расклада из нескольких позиций это выглядит как
    баг, а не как совпадение судьбы.
    """
    exclude = exclude or set()
    digest = _digest(seed, str(index))
    # Идём по последующим байтам хеша, если первый выбор уже занят —
    # экономнее, чем пересчитывать хеш целиком с новой солью.
    for offset, byte in enumerate(digest):
        candidate = byte % len(DECK)
        if candidate not in exclude:
            return candidate, DECK[candidate]
    # Колода из 22 карт и до 5 позиций в раскладе — практически недостижимо,
    # но явный фолбэк лучше, чем IndexError где-то в проде.
    for candidate in range(len(DECK)):
        if candidate not in exclude:
            return candidate, DECK[candidate]
    return 0, DECK[0]


def _today(today: date | None) -> str:
    return (today or date.today()).isoformat()


@dataclass(frozen=True)
class SpreadPosition:
    """Одна позиция в раскладе: название позиции + выпавшая карта."""

    position: str
    card: TarotCard


# ── Расклад «карта дня» — тонкая обёртка над daily_card, чтобы раздел Таро
# мог показать её вместе с остальными раскладами по общему интерфейсу ──────


def day_card(user_id: str, today: date | None = None) -> list[SpreadPosition]:
    """Карта дня в виде расклада из одной позиции.

    Специально не берём напрямую CARDS из daily_card.py: там своя, более
    старая версия колоды с советами, использующаяся в баннере на главном
    экране. Пересчитываем по общей колоде DECK тем же способом (хеш от
    пары «кто + когда»), чтобы карта дня в разделе Таро визуально не
    расходилась с остальными раскладами — она всё равно детерминирована так
    же, только на другой колоде считать не нужно: обе содержат одни и те же
    22 старших аркана.
    """
    _, card = _pick(f"{user_id}:{_today(today)}:day", 0)
    return [SpreadPosition("Карта дня", card)]


# ── Расклад «он и я» — совместимость по именам и датам, без обращения к
# профилю матча: так раздел не трогает models.py и не требует существующей
# пары в системе ──────────────────────────────────────────────────────────


def compatibility_spread(
    name_a: str,
    name_b: str,
    today: date | None = None,
) -> list[SpreadPosition]:
    """«Он и я»: две карты — что несёт каждый — и одна общая.

    Имена нормализуем (нижний регистр, без пробелов по краям): «Аня» и
    « аня » не должны давать разный расклад — человек не обязан вводить
    имя аккуратно дважды подряд.
    """
    a = name_a.strip().lower()
    b = name_b.strip().lower()
    seed = f"{a}:{b}:{_today(today)}:pair"

    idx_a, card_a = _pick(seed, 0)
    idx_b, card_b = _pick(seed, 1, exclude={idx_a})
    _, card_together = _pick(seed, 2, exclude={idx_a, idx_b})

    return [
        SpreadPosition(f"{name_a.strip() or 'Вы'}", card_a),
        SpreadPosition(f"{name_b.strip() or 'Он/Она'}", card_b),
        SpreadPosition("Что между вами", card_together),
    ]


# ── Расклад «три карты»: прошлое / настоящее / будущее ─────────────────────


def three_card_spread(user_id: str, today: date | None = None) -> list[SpreadPosition]:
    seed = f"{user_id}:{_today(today)}:three"
    idx1, card1 = _pick(seed, 0)
    idx2, card2 = _pick(seed, 1, exclude={idx1})
    _, card3 = _pick(seed, 2, exclude={idx1, idx2})
    return [
        SpreadPosition("Прошлое", card1),
        SpreadPosition("Настоящее", card2),
        SpreadPosition("Будущее", card3),
    ]


# ── Расклад на отношения: чувства / страхи / что мешает / перспектива ──────


def relationship_spread(user_id: str, today: date | None = None) -> list[SpreadPosition]:
    seed = f"{user_id}:{_today(today)}:relationship"
    names = ("Ваши чувства", "Ваши страхи", "Что мешает", "Перспектива")
    used: set[int] = set()
    positions: list[SpreadPosition] = []
    for i, name in enumerate(names):
        idx, card = _pick(seed, i, exclude=used)
        used.add(idx)
        positions.append(SpreadPosition(name, card))
    return positions


SPREAD_TITLES: dict[str, str] = {
    "day": "Карта дня",
    "pair": "Он и я",
    "three": "Три карты",
    "relationship": "Расклад на отношения",
}


async def interpretation_for(
    spread_type: str,
    positions: list[SpreadPosition],
) -> str:
    """Живая AI-интерпретация расклада целиком.

    Без ключа возвращает склейку заготовленных советов по картам — раздел
    обязан работать и на окружении без AI, как дневная карта и AI-мэтчер.
    """
    fallback = " ".join(f"{p.position}: {p.card.advice}." for p in positions)

    from services.ai_moderation import _get_zhipu_client

    client = _get_zhipu_client()
    if not client:
        return fallback

    cards_text = "; ".join(
        f"{p.position} — {p.card.name} ({p.card.meaning})" for p in positions
    )
    title = SPREAD_TITLES.get(spread_type, "Расклад")

    try:
        response = await asyncio.to_thread(
            client.chat.completions.create,
            model="glm-4-flash",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Ты пишешь короткую интерпретацию расклада Таро для "
                        "приложения знакомств. 2-4 предложения на русском, "
                        "без мистики и обещаний будущего — практический совет "
                        "про общение и отношения, в дружелюбном тоне."
                    ),
                },
                {
                    "role": "user",
                    "content": f"Расклад «{title}». Карты: {cards_text}.",
                },
            ],
            max_tokens=220,
            temperature=0.8,
        )
        text = (response.choices[0].message.content or "").strip()
        # Пустой или подозрительно длинный ответ — модель сорвалась, тогда
        # возвращаем заготовку вместо мусора на экране
        return text[:600] if 10 <= len(text) <= 800 else fallback
    except Exception as e:
        logger.warning(f"Не удалось получить интерпретацию расклада: {e}")
        return fallback
