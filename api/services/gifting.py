"""Подарить подписку другому пользователю.

Как в Telegram: выбираешь план, платёж проходит с тебя, а друг получает
подарочный код. Не придумываем свою биллинговую систему: используем те
же планы и App Store-идентификаторы, что и для себя — это не даёт
рассинхронизации между покупкой себе и покупкой другу.

Жизненный цикл подарка:
1. Покупатель выбирает план (Plus/Ultra/Aurora) и срок.
2. Создаётся черновик GiftSubscription с одноразовым кодом (sha256-хеш).
3. Покупатель оплачивает в магазине (App Store) или через бота.
4. После успешного платежа код активируется и один раз показывается
   покупателю — дальше секрет живёт в БД только как хеш.
5. Покупатель делится кодом с получателем удобным способом (скопировать,
   открыть в Telegram, переслать голосом).
6. Получатель активирует его по /gifts/redeem; тогда же код помечается
   использованным, а в профиле получателя появляется та же подписка.
"""
from __future__ import annotations

import hashlib
import logging
import secrets
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.models import GiftSubscription, Match, Subscription, User
from services.premium import activate_premium
from services.plans import PLANS_BY_CODE, tier_rank

logger = logging.getLogger(__name__)

# 12 знаков: короче, чем код карты, но достаточно, чтобы перебор был
# непрактичным, и читаем голосом вслух.
CODE_LEN = 12


def _hash_code(code: str) -> str:
    """Хешируем код при записи, чтобы в SQL-дампе и в логах подарок
    оставался секретом. sha256 достаточно медленный на этой длине."""
    return hashlib.sha256(code.encode()).hexdigest()


async def purchase_gift(
    session: AsyncSession,
    buyer: User,
    plan_code: str,
    recipient: User | None = None,
) -> GiftSubscription:
    """Создать черновик подарка под конкретный план.

    Код показываем создателю один раз, и здесь он живёт только в ответе.
    Если получатель указан сразу — не даём подарить самому себе: этот путь
    не предназначен для самопокупки, для него есть /premium/activate."""
    plan = PLANS_BY_CODE.get(plan_code)
    if not plan:
        raise ValueError(f"Неизвестный план: {plan_code}")

    if recipient and recipient.id == buyer.id:
        raise ValueError("Нельзя подарить подписку самому себе")

    code = "".join(secrets.choice("ABCDEFGHJKLMNPQRSTUVWXYZ23456789") for _ in range(CODE_LEN))
    gift = GiftSubscription(
        buyer_user_id=buyer.id,
        recipient_user_id=recipient.id if recipient else None,
        plan=plan.tier,
        months=plan.months,
        code_hash=_hash_code(code),
    )
    session.add(gift)
    await session.flush()
    return gift


async def activate_gift(
    session: AsyncSession, gift: GiftSubscription
) -> None:
    """Активировать подарок после успешного платежа.

    Payment-входы обрабатывают IAP и бот сами; здесь только меняем состояние,
    которое увидит клиент после редиректа. Откат платежа — отдельная история,
    она занимается снаружи."""
    gift.paid = True
    await session.flush()


async def redeem_gift(
    session: AsyncSession,
    code: str,
    redeemer: User,
) -> GiftSubscription:
    """Активировать подарочный код у получателя.

    Проверки не кучкой в if-ах, а в той последовательности, в которой их
    увидит человек: код есть → код оплачен → код ещё не использован → код
    не просрочен. Сначала самое понятное, последнее — самое тонкое."""

    result = await session.execute(
        select(GiftSubscription).where(GiftSubscription.code_hash == code)
    )
    gift = result.scalar_one_or_none()
    if not gift:
        raise ValueError("Код недействителен")

    if not gift.paid:
        raise ValueError("Подарок ещё не оплачен")

    if gift.redeemed_at:
        raise ValueError("Этот код уже активирован")

    if gift.expires_at and gift.expires_at < datetime.now(timezone.utc):
        raise ValueError("Срок действия кода истёк")

    # Код сгорает при самом чтении: найти значит зажечь. Если начали с
    # записи redeemed_at — то же DDL что и по времени, иначе транзакция
    # пропустит вторую активацию тем же кодом на следующий день.
    gift.redeemed_at = datetime.now(timezone.utc)
    gift.recipient_user_id = redeemer.id

    # Перезаписываем подписку только если у получателя нет того же уровня или
    # выше: иначе подарок понизит Aurora до Plus, а это не то, за что заплатили.
    existing = await session.execute(select(Subscription).where(Subscription.user_id == redeemer.id))
    sub = existing.scalar_one_or_none()
    if not sub or tier_rank(gift.plan) > tier_rank(sub.plan):
        # Заменяем код подарка на подписку: plan из GiftSubscription — это тариф
        await activate_premium(
            session,
            user_id=redeemer.id,
            days=gift.months * 30,
            payment_id=f"gift_{gift.id}",
            provider="gift",
            tier=gift.plan,
            expires_at=None,
        )
    logger.info("gift redeemed: buyer=%s plan=%s redeemer=%s", gift.buyer_user_id, gift.plan, redeemer.id)
    return gift


async def gift_from_match(
    session: AsyncSession, buyer: User, match: Match, plan_code: str
) -> GiftSubscription:
    """Подарок прямо по чату, чтобы покупателя не уводить в /plans.

    Отличаем от purchase_gift только тем, что получатель здесь уже известен:
    тот, с кем чат. Поэтому его не требуем отдельно."""
    partner_id = match.user2_id if match.user1_id == buyer.id else match.user1_id
    partner = await session.get(User, partner_id)
    if not partner:
        raise ValueError("Партнёр не найден")
    return await purchase_gift(session, buyer, plan_code, recipient=partner)
