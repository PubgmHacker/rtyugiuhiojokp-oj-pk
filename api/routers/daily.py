"""Карта дня — повод открыть приложение и начать разговор.

Развлечение, а не предсказание: так и написано на экране. Расклад один на
сутки и не меняется при обновлении — карта, зависящая от нажатия «обновить»,
ничего не стоит.

Ничего не пишем в БД: расклад выводится из пары «кто + когда», и таблица под
него была бы журналом того, что и так воспроизводится вычислением.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from middleware.auth import get_current_user
from models.models import User
from models.schemas import DailyCardOut
from services.daily_card import card_for_day, phrase_for

router = APIRouter(prefix="/daily", tags=["daily"])


@router.get("/card", response_model=DailyCardOut)
async def get_daily_card(user: User = Depends(get_current_user)):
    """Карта дня с советом."""
    card = card_for_day(user.id)
    return DailyCardOut(
        name=card.name,
        meaning=card.meaning,
        advice=await phrase_for(card),
    )
