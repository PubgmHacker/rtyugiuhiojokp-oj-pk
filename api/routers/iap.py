"""Покупки в приложении (App Store IAP).

Клиент присылает подписанную транзакцию StoreKit 2, сервер проверяет подпись
Apple и начисляет Premium. Начисление идемпотентно по `transactionId`: пока
клиент не вызвал `finish()`, StoreKit доставляет ту же транзакцию при каждом
запуске приложения, и без журнала платежей подписка начислялась бы заново.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from config import get_settings
from database.connection import get_session
from middleware.auth import get_current_user
from models.models import User
from models.schemas import IAPProducts, IAPVerifyRequest, IAPVerifyResponse
from services.appstore import ReceiptInvalid, is_configured, verify_transaction
from services.premium import activate_premium

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/iap", tags=["iap"])
settings = get_settings()


@router.get("/products", response_model=IAPProducts)
async def list_products():
    """Что можно купить. Пустой список — покупка в приложении недоступна,
    и клиент не должен показывать кнопку."""
    if not is_configured():
        return IAPProducts(available=False, product_ids=[])

    return IAPProducts(
        available=True,
        product_ids=[
            settings.APPSTORE_PRODUCT_MONTHLY,
            settings.APPSTORE_PRODUCT_YEARLY,
        ],
    )


@router.post("/verify", response_model=IAPVerifyResponse)
async def verify_purchase(
    data: IAPVerifyRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Проверить покупку и начислить Premium.

    Клиент подтверждает транзакцию (`finish()`) только после успешного ответа:
    иначе при сетевом сбое деньги списаны, а доступа нет, и повторно получить
    ту же транзакцию уже нельзя.
    """
    if not is_configured():
        raise HTTPException(status_code=503, detail="Покупки недоступны")

    try:
        # id пользователя — UUID, он же передаётся в appAccountToken при покупке
        purchase = verify_transaction(data.jws, expected_account_token=user.id)
    except ReceiptInvalid as e:
        logger.warning(f"IAP rejected (user={user.id}): {e}")
        raise HTTPException(status_code=400, detail=str(e))

    days = settings.appstore_product_days.get(purchase.product_id)
    if days is None:
        raise HTTPException(status_code=400, detail="Неизвестный продукт")

    result = await activate_premium(
        session,
        user_id=user.id,
        days=days,
        payment_id=purchase.transaction_id,
        provider="appstore",
        # Срок берём у Apple: считать самим — значит разойтись с ней
        # после продления или возврата
        expires_at=purchase.expires_at,
    )
    await session.commit()

    return IAPVerifyResponse(
        success=True,
        plan=result["plan"],
        expires_at=result["expires_at"],
        already_processed=result["already_processed"],
    )
