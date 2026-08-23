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

from sqlalchemy import and_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from models.models import GiftSubscription, Match, User
from services.premium import activate_premium, current_tier
from services.plans import PLANS_BY_CODE, tier_rank
from services.promo import normalize_code

logger = logging.getLogger(__name__)


class GiftError(ValueError):
    """Отказ активации подарка: `reason` — машинный код для HTTP-статуса
    (routers/gifts.py) и текстов бота, `text` — фраза человеку. Наследует
    ValueError, чтобы ветки, ловившие отказы до появления причин,
    продолжали их ловить."""

    def __init__(self, reason: str, text: str):
        super().__init__(text)
        self.reason = reason
        self.text = text

# 12 знаков: короче, чем код карты, но достаточно, чтобы перебор был
# непрактичным, и читаем голосом вслух.
CODE_LEN = 12


def _hash_code(code: str) -> str:
    """Хешируем код при записи, чтобы в SQL-дампе и в логах подарок
    оставался секретом. sha256 достаточно медленный на этой длине."""
    return hashlib.sha256(code.encode()).hexdigest()


def new_gift_code() -> str:
    """Сгенерировать код подарка. Plaintext живёт только у вызывающего.

    Отдельно от purchase_gift потому, что показать код можно ровно один раз:
    в базе лежит хеш, и восстановить его оттуда нельзя. Раньше код рождался
    внутри и там же терялся — эндпоинт возвращал несуществующее имя.
    """
    return "".join(secrets.choice("ABCDEFGHJKLMNPQRSTUVWXYZ23456789") for _ in range(CODE_LEN))


async def purchase_gift(
    session: AsyncSession,
    buyer: User,
    plan_code: str,
    recipient: User | None = None,
    code: str | None = None,
    payment_id: str | None = None,
) -> GiftSubscription:
    """Создать черновик подарка под конкретный план.

    `code` передаёт тот, кому нужно показать plaintext (IAP-вход). Не передан —
    генерируем сами, и тогда код не покидает базу: так ведут себя бот и
    внутренние вызовы, им показывать нечего.

    `payment_id` делает вход идемпотентным: Apple повторяет доставку чека, а
    сеть теряет ответы. Без ключа один платёж выдавал бы новый подарок на
    каждую повторную проверку.
    """
    plan = PLANS_BY_CODE.get(plan_code)
    if not plan:
        raise ValueError(f"Неизвестный план: {plan_code}")

    if recipient and recipient.id == buyer.id:
        raise ValueError("Нельзя подарить подписку самому себе")

    if payment_id:
        уже = await session.scalar(
            select(GiftSubscription).where(GiftSubscription.payment_id == payment_id)
        )
        if уже is not None:
            return уже

    gift = GiftSubscription(
        buyer_user_id=buyer.id,
        recipient_user_id=recipient.id if recipient else None,
        plan=plan.tier,
        months=plan.months,
        code_hash=_hash_code(code or new_gift_code()),
        payment_id=payment_id,
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
) -> dict:
    """Активировать подарочный код у получателя.

    Проверки не кучкой в if-ах, а в той последовательности, в которой их
    увидит человек: код есть → код оплачен → код ещё не использован → код
    не просрочен → уровень не ниже действующего. Отказ — GiftError, и
    транзакцию запроса откатит get_session, поэтому при отказе код НЕ
    сгорает: владелец Aurora может отдать Plus-код другу, а не потерять его.

    Ищем по хешу: в базе plaintext не живёт (см. _hash_code), а человеку
    прощаем регистр, пробелы и дефисы — той же нормализацией, что у
    промокодов: код диктуют голосом и перепечатывают с картинок.

    Сжигание — одним UPDATE с `redeemed_at IS NULL` в WHERE: две
    одновременные активации обе видят свободный код при чтении, но UPDATE
    выигрывает ровно одна. Второй пояс — уникальный ключ (provider,
    external_id) журнала платежей внутри activate_premium: тот же ключ
    `gift_{id}` пишет и бот (bot/database/connection.py::redeem_gift_code),
    поэтому гонка «бот и мини-апп одновременно» тоже даёт одно начисление.
    """
    нормализованный = normalize_code(code)
    if not нормализованный:
        raise GiftError("not_found", "Код недействителен")

    result = await session.execute(
        select(GiftSubscription).where(
            GiftSubscription.code_hash == _hash_code(нормализованный)
        )
    )
    gift = result.scalar_one_or_none()
    if not gift:
        raise GiftError("not_found", "Код недействителен")

    if not gift.paid:
        raise GiftError("not_paid", "Подарок ещё не оплачен")

    if gift.redeemed_at:
        raise GiftError("already_used", "Этот код уже активирован")

    now = datetime.now(timezone.utc)
    if gift.expires_at:
        истекает = gift.expires_at
        if истекает.tzinfo is None:
            истекает = истекает.replace(tzinfo=timezone.utc)
        if истекает < now:
            raise GiftError("expired", "Срок действия кода истёк")

    # Подарок ниже действующего уровня не активируем и не сжигаем: иначе
    # Plus-код молча сгорал бы у владельца Aurora — ни подписки, ни кода.
    # Равный уровень активируем: это продление, купленное время не сгорает.
    # Истёкшая подписка уровнем не считается — current_tier вернёт free.
    действующий = await current_tier(session, redeemer.id)
    if tier_rank(действующий) > tier_rank(gift.plan):
        raise GiftError(
            "tier_lower",
            "У вас уже действует уровень выше — активируйте код после "
            "окончания подписки или подарите его другому",
        )

    сожжён = await session.execute(
        update(GiftSubscription)
        .where(and_(
            GiftSubscription.id == gift.id,
            GiftSubscription.redeemed_at.is_(None),
        ))
        .values(redeemed_at=now, recipient_user_id=redeemer.id)
    )
    if сожжён.rowcount == 0:
        raise GiftError("already_used", "Этот код уже активирован")
    # ORM-объект остался со старыми значениями — выравниваем с базой
    gift.redeemed_at = now
    gift.recipient_user_id = redeemer.id

    итог = await activate_premium(
        session,
        user_id=redeemer.id,
        days=gift.months * 30,
        payment_id=f"gift_{gift.id}",
        provider="gift",
        tier=gift.plan,
        expires_at=None,
    )
    logger.info("gift redeemed: buyer=%s plan=%s redeemer=%s", gift.buyer_user_id, gift.plan, redeemer.id)
    return {
        "tier": gift.plan,
        "months": gift.months,
        "plan": итог["plan"],
        "expires_at": итог["expires_at"] or "",
    }


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
