from __future__ import annotations

import logging

from aiogram import Router, F
from aiogram.types import (
    CallbackQuery,
    LabeledPrice,
    Message,
    PreCheckoutQuery,
)

from database import get_or_create_user, get_active_subscription, activate_premium
from keyboards import main_kb
from utils import safe_edit_text

logger = logging.getLogger(__name__)
router = Router()

PREMIUM_PRICE_STARS = 250  # ~ несколько долларов, платёж через Telegram Stars
PREMIUM_DAYS = 30

PREMIUM_PITCH = (
    "⭐ <b>Souldawn Premium</b> — 30 дней\n\n"
    "🥷 <b>Инкогнито-режим</b> — вас видят только те, кого лайкнули вы\n"
    "🚀 <b>Буст в выдаче</b> — ваша анкета выше в деке у других\n"
    "💎 <b>Значок Premium</b> в профиле\n\n"
    f"Цена: <b>{PREMIUM_PRICE_STARS} ⭐ Stars</b>"
)


async def send_premium_offer(message: Message, user_id: str):
    """Показать оффер или статус активной подписки."""
    sub = await get_active_subscription(user_id)
    if sub:
        expires = (sub.get("expires_at") or "")[:10]
        await message.answer(
            f"⭐ <b>Premium активен</b> до {expires}.\n\n"
            "Хотите продлить ещё на 30 дней?",
        )
    await message.answer_invoice(
        title="Souldawn Premium — 30 дней",
        description="Инкогнито-режим, буст в выдаче и значок Premium на 30 дней",
        payload=f"premium_{PREMIUM_DAYS}d",
        currency="XTR",  # Telegram Stars
        prices=[LabeledPrice(label=f"Premium на {PREMIUM_DAYS} дней", amount=PREMIUM_PRICE_STARS)],
    )


@router.callback_query(F.data == "premium")
async def premium_from_menu(callback: CallbackQuery):
    db_user = await get_or_create_user(
        callback.from_user.id,
        callback.from_user.username or "",
        callback.from_user.first_name or "",
    )
    await callback.answer()
    await callback.message.answer(PREMIUM_PITCH)
    await send_premium_offer(callback.message, db_user["id"])


@router.message(F.text == "/premium")
async def premium_command(message: Message):
    db_user = await get_or_create_user(
        message.from_user.id,
        message.from_user.username or "",
        message.from_user.first_name or "",
    )
    await message.answer(PREMIUM_PITCH)
    await send_premium_offer(message, db_user["id"])


@router.pre_checkout_query()
async def pre_checkout(query: PreCheckoutQuery):
    # Stars-платёж: подтверждаем всегда (валидацию суммы делает Telegram)
    await query.answer(ok=True)


@router.message(F.successful_payment)
async def on_successful_payment(message: Message):
    db_user = await get_or_create_user(
        message.from_user.id,
        message.from_user.username or "",
        message.from_user.first_name or "",
    )
    payment = message.successful_payment
    sub = await activate_premium(
        db_user["id"],
        days=PREMIUM_DAYS,
        payment_id=payment.telegram_payment_charge_id,
    )
    logger.info(
        f"Premium activated: user={db_user['id']} "
        f"charge={payment.telegram_payment_charge_id} until={sub['expires_at']}"
    )
    await message.answer(
        f"🎉 <b>Premium активирован</b> до {sub['expires_at'][:10]}!\n\n"
        "🥷 Инкогнито можно включить в веб-приложении (Профиль).\n"
        "🚀 Буст в выдаче уже работает.",
        reply_markup=main_kb(),
    )
