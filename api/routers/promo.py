"""Активация промокода из мини-аппа.

Один эндпоинт: POST /promo/activate. Выпуск и управление кодами живут в
админке (routers/admin.py), активация в боте — в bot/handlers/premium.py
через своё зеркало механики (bot/database/connection.py::activate_promo_code).

Отказ — HTTPException: get_session откатит транзакцию запроса, и отказная
ветка не оставит следов (services/promo.py рассчитывает именно на это,
списывая слот лимита до вставки активации).
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from database.connection import get_session
from middleware.auth import get_current_user
from models.models import User
from models.schemas import PromoActivateIn, PromoActivateOut
from services.promo import PromoError, activate_promo

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/promo", tags=["promo"])

#: Коды отказов — в статусы. 404 «нет такого» и для погашенных кодов;
#: 409 — конфликт с прошлой активацией этого же человека; 410 — код был,
#: но больше не даётся: слоты кончились или срок вышел.
_СТАТУС_ОТКАЗА = {
    "not_found": 404,
    "already_used": 409,
    "expired": 410,
    "exhausted": 410,
}


@router.post("/activate", response_model=PromoActivateOut)
async def activate(
    body: PromoActivateIn,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Активировать промокод. Успех — сразу новая подписка в ответе:
    клиент показывает «Plus до 21 сентября» без второго запроса."""
    try:
        итог = await activate_promo(session, user.id, body.code)
    except PromoError as отказ:
        raise HTTPException(
            status_code=_СТАТУС_ОТКАЗА.get(отказ.reason, 400),
            detail=отказ.text,
        )
    return PromoActivateOut(**итог)
