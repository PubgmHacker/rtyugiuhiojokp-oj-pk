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
from models.schemas import (
    IAPProducts,
    IAPVerifyRequest,
    IAPVerifyResponse,
    PlanOut,
    PlansOut,
    TierOut,
)
from services.appstore import (
    ReceiptInvalid, is_configured, verify_transaction, разобрать_уведомление,
)
from services.gifting import activate_gift, purchase_gift
from services.premium import activate_premium, current_tier, отозвать_покупку
from services.plans import PLANS, TIER_ORDER, TIERS, plan_for_appstore_id

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/iap", tags=["iap"])
settings = get_settings()


@router.get("/plans", response_model=PlansOut)
async def list_plans(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Витрина тарифов: уровни, что дают и сколько стоят.

    Цены отдаёт сервер, а не клиент: иначе бот, мини-апп и лендинг разошлись
    бы в ценнике, и человек увидел бы одну цену, а заплатил другую.
    """
    return PlansOut(
        current_tier=await current_tier(session, user.id),
        tiers=[
            TierOut(
                tier=info.tier,
                name=info.name,
                superlikes=info.superlikes,
                perks=list(info.perks),
                plans=[
                    PlanOut(
                        code=p.code,
                        tier=p.tier,
                        title=p.title,
                        months=p.months,
                        price_rub=p.price_rub,
                        price_per_month=p.price_per_month,
                        price_per_day=p.price_per_day,
                        appstore_id=p.appstore_id,
                    )
                    for p in PLANS
                    if p.tier == info.tier
                ],
            )
            # Бесплатный уровень тоже отдаём: в витрине он точка отсчёта,
            # просто список планов у него пустой
            for info in (TIERS[t] for t in TIER_ORDER)
        ],
    )


@router.get("/products", response_model=IAPProducts)
async def list_products():
    """Что можно купить в iOS. Пустой список — покупка недоступна,
    и клиент не должен показывать кнопку.

    Идентификаторы берём из линейки: держать их вторым списком в настройках
    значило бы однажды продать продукт, которого нет в тарифах.
    """
    if not is_configured():
        return IAPProducts(available=False, product_ids=[])

    return IAPProducts(
        available=True,
        product_ids=[p.appstore_id for p in PLANS if p.appstore_id],
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

    # Уровень определяет купленный продукт: Ultra и Plus продаются разными
    # идентификаторами, и начислить не тот — значит выдать неоплаченное
    plan = plan_for_appstore_id(purchase.product_id)
    if plan is None:
        raise HTTPException(status_code=400, detail="Неизвестный продукт")

    result = await activate_premium(
        session,
        user_id=user.id,
        days=plan.days,
        payment_id=purchase.transaction_id,
        provider="appstore",
        tier=plan.tier,
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
        gift_code=result.get("gift_code"),
    )


@router.post("/verify-gift", response_model=IAPVerifyResponse)
async def verify_gift_purchase(
    data: IAPVerifyRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Проверить покупку, но начислить не себе, а как подарок.

    В витрине уже сделан выбор тарифа на предыдущем шаге, и здесь клиент
    присылает тот же payload. Мы создаем запись подарка и активируем её
    платежом, а не связываем покупателя с текущей подпиской — иначе при
    подарке самому себе получилось бы двойное списание за один чек."""
    if not is_configured():
        raise HTTPException(status_code=503, detail="Покупки недоступны")

    try:
        purchase = verify_transaction(data.jws, expected_account_token=user.id)
    except ReceiptInvalid as e:
        logger.warning(f"gift IAP rejected (user={user.id}): {e}")
        raise HTTPException(status_code=400, detail=str(e))

    plan = plan_for_appstore_id(purchase.product_id)
    if plan is None:
        raise HTTPException(status_code=400, detail="Неизвестный продукт")

    gift = await purchase_gift(session, buyer=user, plan_code=plan.code)
    await activate_gift(session, gift)
    await session.commit()

    return IAPVerifyResponse(
        success=True,
        plan=plan.code,
        expires_at="",
        already_processed=False,
        gift_code=gift_code,
    )


@router.post("/appstore/notifications")
async def appstore_notifications(
    data: dict,
    session: AsyncSession = Depends(get_session),
):
    """Уведомления App Store Server Notifications V2.

    Apple зовёт этот адрес сама, поэтому он открытый — и именно поэтому
    подпись уведомления проверяется тем же верификатором, что и чеки. Без
    проверки любой прислал бы поддельный REFUND и погасил подписку кому
    угодно.

    До этого возврат ловился только в момент, когда клиент сам предъявлял чек:
    вернувший деньги продолжал пользоваться подпиской, а мог и вовсе больше не
    открывать приложение.

    Отвечаем 200 всегда, когда уведомление разобрано: Apple повторяет доставку
    при любом другом коде, а повторять нечего — неизвестный тип нам просто
    неинтересен.
    """
    if not is_configured():
        raise HTTPException(status_code=503, detail="Покупки недоступны")

    try:
        уведомление = разобрать_уведомление(str(data.get("signedPayload", "")))
    except ReceiptInvalid as e:
        # Подпись не сошлась — это не наше уведомление
        logger.warning(f"Уведомление App Store отклонено: {e}")
        raise HTTPException(status_code=400, detail="Уведомление не подтверждено")

    if not уведомление["отзыв"]:
        logger.info(f"Уведомление App Store: {уведомление['тип']} {уведомление['подтип']}")
        return {"handled": False}

    original_id = уведомление["original_transaction_id"]
    transaction_id = уведомление.get("transaction_id")
    if not original_id and not transaction_id:
        logger.error("Отзыв покупки без идентификатора транзакции")
        return {"handled": False}

    # Передаём оба: у продления transactionId новый, а в журнале платежей
    # лежит именно он, тогда как в уведомлении приходит originalTransactionId
    итог = await отозвать_покупку(
        session,
        transaction_id or original_id,
        provider="appstore",
        original_id=original_id,
    )
    await session.commit()
    return {"handled": bool(итог.get("revoked"))}
