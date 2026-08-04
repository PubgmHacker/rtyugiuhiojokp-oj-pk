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


async def activate_premium(
    session: AsyncSession,
    user_id: str,
    days: int,
    payment_id: str,
    provider: str,
    expires_at: datetime | None = None,
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

    sub.plan = "premium"
    sub.stripe_id = payment_id or sub.stripe_id
    sub.expires_at = new_expires
    await session.flush()

    logger.info(f"Premium activated: user={user_id} provider={provider} until={new_expires}")
    return {
        "plan": sub.plan,
        "expires_at": new_expires.isoformat(),
        "already_processed": False,
    }
