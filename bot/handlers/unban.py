"""Платная досрочная разблокировка забаненного аккаунта.

Забаненного до этих обработчиков доводит бан-гейт (middlewares/ban_gate.py):
он пропускает только кнопку оплаты и платёжные апдейты, остальное отвечает
экраном блокировки. Сам зачёт оплаты живёт в handlers/premium.py — Telegram
присылает successful_payment одним типом апдейта на все покупки, и первый
router с этим фильтром забирает их все; premium диспетчеризует по payload
и зовёт process_unban_payment / process_unban_refund отсюда.

Оплата — только Telegram Stars: они доступны каждому без настройки,
а забаненному нельзя предлагать способ, который может оказаться выключенным
(CryptoBot и рублёвая оплата включаются токенами в переменных окружения).
"""
from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.types import CallbackQuery, LabeledPrice, Message

import texts as T
from config import RUB_PER_STAR, UNBAN_PRICE_RUB
from database import get_or_create_user, reban_after_refund, unban_after_payment
from keyboards import main_kb, unban_kb

logger = logging.getLogger(__name__)
router = Router()

#: Payload Stars-счёта за разблокировку. С версией: счёт, выставленный до
#: смены механики и оплаченный после деплоя, не должен потеряться.
UNBAN_PAYLOAD = "unban:v1"


def unban_stars() -> int:
    """Цена разблокировки в Stars — тот же курс, что у подписок."""
    return max(1, round(UNBAN_PRICE_RUB / RUB_PER_STAR))


@router.callback_query(F.data == "unban:pay")
async def pay_unban(callback: CallbackQuery):
    """Выставить Stars-счёт на досрочную разблокировку."""
    db_user = await get_or_create_user(
        callback.from_user.id,
        callback.from_user.username or "",
        callback.from_user.first_name or "",
    )
    if not db_user.get("is_banned"):
        # Разбанили, пока сообщение с кнопкой лежало в чате
        await callback.answer(T.UNBAN_NOT_BANNED, show_alert=True)
        return

    await callback.answer()
    await callback.message.answer_invoice(
        title="Досрочная разблокировка",
        description=(
            "Снимает блокировку аккаунта сразу после оплаты: анкета вернётся "
            "в поиск, лайки и переписки заработают."
        ),
        payload=UNBAN_PAYLOAD,
        currency="XTR",  # Telegram Stars
        prices=[LabeledPrice(label="Разблокировка", amount=unban_stars())],
    )


async def process_unban_payment(message: Message, user_id: str) -> None:
    """Зачесть оплаченную разблокировку (вызывается из premium.py).

    Если снимать нечего (двойная оплата, разбан админом между счётом и
    оплатой) — возвращаем Stars: деньги за отсутствующую услугу не берём.
    """
    charge_id = message.successful_payment.telegram_payment_charge_id
    итог = await unban_after_payment(
        user_id,
        charge_id,
        UNBAN_PRICE_RUB,
        stars=message.successful_payment.total_amount,
    )

    if итог.get("unbanned"):
        logger.warning(f"Разблокировка куплена: user={user_id} charge={charge_id}")
        await message.answer(T.UNBAN_DONE, reply_markup=main_kb())
        return

    logger.warning(
        f"Оплата разблокировки без бана: user={user_id} charge={charge_id} "
        f"({итог.get('reason')}) — возвращаю Stars"
    )
    try:
        await message.bot.refund_star_payment(
            user_id=message.from_user.id,
            telegram_payment_charge_id=charge_id,
        )
    except Exception as e:
        # Возврат не прошёл — след в логе, поддержка вернёт руками
        logger.error(f"Не удалось вернуть Stars за лишнюю разблокировку: {e}")
    await message.answer(T.UNBAN_NOT_NEEDED)


async def process_unban_refund(message: Message) -> None:
    """Вернуть бан после возврата Stars (вызывается из premium.py).

    Токены отзываем той же отметкой Redis, что и API при бане
    (services/token_revocation.py): без неё вернувшийся бан не гасил бы
    живые сессии мини-аппа до первого HTTP-запроса.
    """
    charge_id = message.refunded_payment.telegram_payment_charge_id
    итог = await reban_after_refund(charge_id)
    if not итог.get("rebanned"):
        logger.warning(f"Возврат за разблокировку без обратного бана: charge={charge_id}")
        return

    from services.redis_subscriber import revoke_user_tokens

    await revoke_user_tokens(итог["user_id"])
    await message.answer(
        T.UNBAN_REFUND_REBAN, reply_markup=unban_kb(UNBAN_PRICE_RUB)
    )
