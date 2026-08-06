"""Раздел Таро: карта дня + три развёрнутых расклада.

Ничего не пишем в БД под сами расклады — принцип тот же, что и в daily.py:
карты выводятся детерминированно из «кто + когда (+ тип расклада)», поэтому
обновление страницы не меняет результат раньше следующих суток.

Платный гейт сюда сознательно не зашит (services/plans.py трогать нельзя по
условиям задачи) — ограничение по тарифу и частоте предполагается на уровне
роутера отдельным PR, когда появится нужная константа в plans.py.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from middleware.auth import get_current_user
from models.models import User
from models.schemas import TarotCardOut, TarotSpreadOut
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


async def _respond(spread_type: str, positions) -> TarotSpreadOut:
    """Общая сборка ответа: интерпретация + обязательный дисклеймер —
    одно место, а не четыре копии одного и того же собирания объекта."""
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
    )


@router.get("/day", response_model=TarotSpreadOut)
async def get_day_spread(user: User = Depends(get_current_user)):
    """Карта дня в формате раздела Таро — бесплатный вход в раздел."""
    return await _respond("day", day_card(user.id))


@router.get("/pair", response_model=TarotSpreadOut)
async def get_pair_spread(
    name_a: str = Query(..., min_length=1, max_length=60, description="Ваше имя"),
    name_b: str = Query(..., min_length=1, max_length=60, description="Имя партнёра"),
    user: User = Depends(get_current_user),
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
async def get_three_card_spread(user: User = Depends(get_current_user)):
    """Три карты: прошлое, настоящее, будущее."""
    return await _respond("three", three_card_spread(user.id))


@router.get("/relationship", response_model=TarotSpreadOut)
async def get_relationship_spread(user: User = Depends(get_current_user)):
    """Расклад на отношения: чувства, страхи, что мешает, перспектива."""
    return await _respond("relationship", relationship_spread(user.id))
