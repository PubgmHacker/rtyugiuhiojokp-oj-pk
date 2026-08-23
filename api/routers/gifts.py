"""Активация подарочного кода получателем.

Покупка подарка живёт в routers/iap.py (/iap/verify-gift): там код рождается
и один раз показывается покупателю. Здесь вторая половина жизненного цикла:
получатель вводит код и забирает подписку. До этого роутера пути активации
не существовало — деньги за подарок списывались, а «/gifts/redeem» жил
только в докстринге сервиса.

Отказ — HTTPException: get_session откатит транзакцию запроса, поэтому
отказная ветка не оставляет следов и код НЕ сгорает (services/gifting.py
пишет redeemed_at только на пути успеха).
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from database.connection import get_session
from middleware.auth import get_current_user
from models.models import User
from models.schemas import GiftRedeemIn, GiftRedeemOut
from services.gifting import GiftError, redeem_gift

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/gifts", tags=["gifts"])

#: Коды отказов — в статусы. 404 «нет такого»; 402 — код существует, но
#: платёж покупателя ещё не прошёл; 409 — конфликт с состоянием получателя
#: (код уже использован / уровень уже выше — код при этом цел); 410 — код
#: был, но срок его действия вышел.
_СТАТУС_ОТКАЗА = {
    "not_found": 404,
    "not_paid": 402,
    "already_used": 409,
    "tier_lower": 409,
    "expired": 410,
}


@router.post("/redeem", response_model=GiftRedeemOut)
async def redeem(
    body: GiftRedeemIn,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Активировать подарочный код. Успех — сразу новая подписка в ответе:
    клиент показывает «Plus на 3 месяца» без второго запроса."""
    try:
        итог = await redeem_gift(session, body.code, user)
    except GiftError as отказ:
        raise HTTPException(
            status_code=_СТАТУС_ОТКАЗА.get(отказ.reason, 400),
            detail=отказ.text,
        )
    return GiftRedeemOut(**итог)
