"""Активация Premium на стороне API.

Раньше премиум начислялся только ботом (`bot/database/connection.py`),
а API умел лишь читать статус. Покупка в iOS приходит именно сюда, поэтому
логика нужна и здесь — с той же защитой от повторного начисления.

Идемпотентность держится на уникальном ключе `(provider, external_id)` в
`dating_processed_payments`, а не на сравнении с последним платежом: одна и
та же транзакция App Store может прийти повторно (StoreKit шлёт её при
каждом запуске, пока клиент не вызовет `finish()`), и без журнала повтор
начислял бы подписку заново.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from models.models import ProcessedPayment, Subscription
from services.plans import TIER_FREE, TIER_PLUS, tier_from_plan, tier_rank

logger = logging.getLogger(__name__)


async def is_premium(session: AsyncSession, user_id: str) -> bool:
    """Активна ли подписка. `expires_at IS NULL` — бессрочная."""
    result = await session.execute(
        select(Subscription.id).where(and_(
            Subscription.user_id == user_id,
            Subscription.plan != "free",
            or_(
                Subscription.expires_at.is_(None),
                Subscription.expires_at > datetime.now(timezone.utc),
            ),
        ))
    )
    return result.scalar_one_or_none() is not None


async def current_tier(session: AsyncSession, user_id: str) -> str:
    """Действующий уровень подписки: free / plus / ultra / aurora.

    Истёкшая подписка — это free, поэтому срок проверяется здесь, а не в
    вызывающем коде: иначе каждое место пришлось бы помнить про expires_at.

    Сам разбор значения (старый `plan="premium"` → Plus, испорченное → free)
    живёт в `plans.tier_from_plan`: ранжирование деки читает уровни пачкой и
    обязано понимать их точно так же.
    """
    result = await session.execute(
        select(Subscription.plan).where(and_(
            Subscription.user_id == user_id,
            or_(
                Subscription.expires_at.is_(None),
                Subscription.expires_at > datetime.now(timezone.utc),
            ),
        ))
    )
    return tier_from_plan(result.scalar_one_or_none())


async def activate_premium(
    session: AsyncSession,
    user_id: str,
    days: int,
    payment_id: str,
    provider: str,
    expires_at: datetime | None = None,
    tier: str = TIER_PLUS,
) -> dict:
    """Начислить или продлить Premium ровно один раз на платёж.

    `expires_at` задаётся, когда срок известен извне: у подписки App Store
    он приходит в самой транзакции, и считать его самим означало бы разойтись
    с Apple после продления или возврата. Иначе продлеваем на `days` поверх
    остатка — купленное время не должно сгорать.
    """
    # Отдельная транзакция: при гонке двух проверок одного платежа второй
    # INSERT упадёт на уникальном ключе и начисления не произойдёт
    try:
        async with session.begin_nested():
            session.add(ProcessedPayment(
                provider=provider,
                external_id=payment_id,
                user_id=user_id,
                days=days,
            ))
    except IntegrityError:
        result = await session.execute(
            select(Subscription).where(Subscription.user_id == user_id)
        )
        sub = result.scalar_one_or_none()
        return {
            "plan": sub.plan if sub else "free",
            "expires_at": sub.expires_at.isoformat() if sub and sub.expires_at else "",
            "already_processed": True,
        }

    result = await session.execute(
        select(Subscription).where(Subscription.user_id == user_id)
    )
    sub = result.scalar_one_or_none()
    if not sub:
        sub = Subscription(user_id=user_id)
        session.add(sub)

    if expires_at is not None:
        new_expires = expires_at
    else:
        # Продление поверх остатка, а не с текущей даты
        now = datetime.now(timezone.utc)
        base = now
        if sub.expires_at:
            current = sub.expires_at
            if current.tzinfo is None:
                current = current.replace(tzinfo=timezone.utc)
            if current > now:
                base = current
        new_expires = base + timedelta(days=days)

    # Уровень не понижаем задним числом: если человек купил Ultra, а потом
    # продлил Plus, продление добавляет срок, но не отбирает уплаченный уровень
    sub.plan = tier if tier_rank(tier) >= tier_rank(sub.plan or TIER_FREE) else sub.plan
    sub.stripe_id = payment_id or sub.stripe_id
    sub.expires_at = new_expires
    await session.flush()

    logger.info(f"Premium activated: user={user_id} provider={provider} until={new_expires}")
    return {
        "plan": sub.plan,
        "expires_at": new_expires.isoformat(),
        "already_processed": False,
    }


async def отозвать_покупку(
    session: AsyncSession,
    payment_id: str,
    provider: str = "appstore",
    original_id: str | None = None,
) -> dict:
    """Закрыть доступ после возврата денег.

    Раньше отзыв ловился только когда клиент сам предъявлял чек: до этого
    момента вернувший деньги пользовался подпиской, а мог и вовсе больше не
    открывать приложение. Уведомление от Apple приходит сразу, поэтому и
    доступ закрываем сразу.

    `original_id` нужен из-за того, что у продления подписки `transactionId`
    каждый раз новый, а `originalTransactionId` остаётся прежним. В журнале
    платежей лежит первый, в уведомлении приходит второй — искать только по
    одному значило бы молча не находить продлённые подписки. Поэтому
    подстраховываемся ещё и полем `Subscription.stripe_id`, куда пишется
    последний зачтённый платёж.

    Гасим подписку целиком, а не урезаем на дни: у App Store срок живёт на
    стороне Apple, и «остатка от других покупок» тут не бывает — подписка одна
    и продлевается той же цепочкой.
    """
    ключи = [k for k in (payment_id, original_id) if k]

    result = await session.execute(
        select(ProcessedPayment).where(and_(
            ProcessedPayment.provider == provider,
            ProcessedPayment.external_id.in_(ключи),
        ))
    )
    платежи = list(result.scalars().all())

    sub = None
    if платежи:
        user_id = платежи[0].user_id
        result = await session.execute(
            select(Subscription).where(Subscription.user_id == user_id)
        )
        sub = result.scalar_one_or_none()
    else:
        # Продление: в журнале лежит transactionId первой покупки, а пришёл
        # originalTransactionId. Последний зачтённый платёж записан в подписке
        result = await session.execute(
            select(Subscription).where(Subscription.stripe_id.in_(ключи))
        )
        sub = result.scalar_one_or_none()
        if not sub:
            return {"revoked": False, "reason": "платёж не найден"}
        user_id = sub.user_id

    if sub:
        sub.expires_at = datetime.now(timezone.utc)
        sub.plan = TIER_FREE

    # Записи убираем: если человек оплатит заново, тот же transaction_id
    # должен снова зачесться, а не считаться уже обработанным
    for платёж in платежи:
        await session.delete(платёж)
    await session.flush()

    logger.warning(f"Purchase revoked: user={user_id} provider={provider}")
    return {"revoked": True, "user_id": user_id}
