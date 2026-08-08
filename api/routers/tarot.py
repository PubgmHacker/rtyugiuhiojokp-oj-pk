"""Раздел Таро: карта дня + три развёрнутых расклада.

Ничего не пишем в БД под сами расклады — принцип тот же, что и в daily.py:
карты выводятся детерминированно из «кто + когда (+ тип расклада)», поэтому
обновление страницы не меняет результат раньше следующих суток.

Платный гейт: карта дня бесплатна — это повод открыть приложение, а не товар.
Три развёрнутых расклада закрыты фичей `tarot_spreads` (см. services/plans.py,
FEATURE_MIN_TIER) и проверяются одной зависимостью `_require_spreads`. Имя
уровня в тексте отказа берём из тарифной линейки, а не пишем словом: фича может
переехать на другой уровень, и зашитое имя тогда молча соврёт.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from database.connection import get_session
from middleware.auth import get_current_user
from models.models import User
from models.schemas import TarotCardOut, TarotSpreadOut
from services.plans import FEATURE_MIN_TIER, TIERS, tier_allows
from services.premium import current_tier
from services.tarot_deck import DISCLAIMER
from services.tarot_spreads import (
    SPREAD_TITLES,
    compatibility_spread,
    day_card,
    interpretation_for,
    relationship_spread,
    three_card_spread,
)

router = APIRouter(prefix="/tarot", tags=["tarot"])


async def _require_spreads(
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> User:
    """Пускает к развёрнутым раскладам только с подходящим тарифом.

    Отдаёт того же `user`, что и `get_current_user`, — эндпоинту он всё равно
    нужен, а второй зависимости на пользователя тогда не заводим.
    """
    if not tier_allows(await current_tier(session, user.id), "tarot_spreads"):
        name = TIERS[FEATURE_MIN_TIER["tarot_spreads"]].name
        raise HTTPException(status_code=403, detail=f"Расклады доступны на {name}")
    return user


async def _respond(
    spread_type: str, positions, *, spreads_open: bool = True
) -> TarotSpreadOut:
    """Общая сборка ответа: интерпретация + обязательный дисклеймер —
    одно место, а не четыре копии одного и того же собирания объекта.

    `spreads_open` осмыслен только у карты дня: до остальных эндпоинтов запрос
    не доходит, если тариф не позволяет, — их отсекает `_require_spreads`.
    """
    interpretation = await interpretation_for(spread_type, positions)
    return TarotSpreadOut(
        spread=spread_type,
        title=SPREAD_TITLES[spread_type],
        cards=[
            TarotCardOut(position=p.position, name=p.card.name, meaning=p.card.meaning)
            for p in positions
        ],
        interpretation=interpretation,
        disclaimer=DISCLAIMER,
        spreads_open=spreads_open,
        required_tier_name=TIERS[FEATURE_MIN_TIER["tarot_spreads"]].name,
    )


@router.get("/day", response_model=TarotSpreadOut)
async def get_day_spread(
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """Карта дня в формате раздела Таро — бесплатный вход в раздел.

    Заодно сообщает, открыты ли развороты: клиент показывает замок сразу и не
    выясняет это отдельной пробой закрытого эндпоинта. Из-за той пробы карта
    дня грузилась дважды за одно открытие экрана и мигала.
    """
    открыты = tier_allows(await current_tier(session, user.id), "tarot_spreads")
    return await _respond("day", day_card(user.id), spreads_open=открыты)


@router.get("/pair", response_model=TarotSpreadOut)
async def get_pair_spread(
    name_a: str = Query(..., min_length=1, max_length=60, description="Ваше имя"),
    name_b: str = Query(..., min_length=1, max_length=60, description="Имя партнёра"),
    user: User = Depends(_require_spreads),
):
    """«Он и я»: совместимость по двум именам.

    Специально не берём анкету матча из БД — так расклад не требует
    существующей пары в системе и не задевает models.py/matches.py, над
    которыми параллельно работают другие. Дата подмешивается в сид неявно
    внутри compatibility_spread — иначе тот же id пользователя пришлось бы
    передавать вручную, а он API не нужен.
    """
    return await _respond("pair", compatibility_spread(name_a, name_b))


@router.get("/three", response_model=TarotSpreadOut)
async def get_three_card_spread(user: User = Depends(_require_spreads)):
    """Три карты: прошлое, настоящее, будущее."""
    return await _respond("three", three_card_spread(user.id))


@router.get("/relationship", response_model=TarotSpreadOut)
async def get_relationship_spread(user: User = Depends(_require_spreads)):
    """Расклад на отношения: чувства, страхи, что мешает, перспектива."""
    return await _respond("relationship", relationship_spread(user.id))
