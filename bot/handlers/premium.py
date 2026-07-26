from __future__ import annotations

import logging

from aiogram import Router, F
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LabeledPrice,
    Message,
    PreCheckoutQuery,
)

from config import (
    PREMIUM_DAYS,
    PREMIUM_PRICE_STARS,
    PREMIUM_PRICE_USDT,
    SBP_ENABLED,
)
from database import get_or_create_user, get_active_subscription, activate_premium
from keyboards import main_kb
from services import cryptobot

logger = logging.getLogger(__name__)
router = Router()

PREMIUM_PITCH = (
    f"⭐ <b>Souldawn Premium</b> — {PREMIUM_DAYS} дней\n\n"
    "🥷 <b>Инкогнито-режим</b> — вас видят только те, кого лайкнули вы\n"
    "🚀 <b>Буст в выдаче</b> — ваша анкета выше в деке у других\n"
    "💎 <b>Значок Premium</b> в профиле"
)


def payment_methods_kb() -> InlineKeyboardMarkup:
    """Способы оплаты: Stars всегда, CryptoBot/СБП — если настроены."""
    rows = [[InlineKeyboardButton(
        text=f"⭐ Telegram Stars — {PREMIUM_PRICE_STARS} ⭐",
        callback_data="pay:stars",
    )]]
    if cryptobot.is_enabled():
        rows.append([InlineKeyboardButton(
            text=f"💎 Криптовалюта (USDT) — {PREMIUM_PRICE_USDT} USDT",
            callback_data="pay:crypto",
        )])
    if SBP_ENABLED:
        rows.append([InlineKeyboardButton(text="🏦 СБП", callback_data="pay:sbp")])
    rows.append([InlineKeyboardButton(text="🏠 В меню", callback_data="menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def send_premium_offer(message: Message, user_id: str):
    """Показать статус подписки и способы оплаты."""
    sub = await get_active_subscription(user_id)
    if sub:
        expires = (sub.get("expires_at") or "")[:10]
        await message.answer(
            f"⭐ <b>Premium активен</b> до {expires}.\n\nПродлить ещё на {PREMIUM_DAYS} дней:",
            reply_markup=payment_methods_kb(),
        )
    else:
        await message.answer("Выберите способ оплаты:", reply_markup=payment_methods_kb())


async def _grant_premium(message: Message, user_id: str, payment_id: str):
    sub = await activate_premium(user_id, days=PREMIUM_DAYS, payment_id=payment_id)
    logger.info(f"Premium activated: user={user_id} charge={payment_id} until={sub['expires_at']}")
    await message.answer(
        f"🎉 <b>Premium активирован</b> до {sub['expires_at'][:10]}!\n\n"
        "🥷 Инкогнито можно включить в веб-приложении (Профиль).\n"
        "🚀 Буст в выдаче уже работает.",
        reply_markup=main_kb(),
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


# ── Telegram Stars ───────────────────────────────────────────────

@router.callback_query(F.data == "pay:stars")
async def pay_stars(callback: CallbackQuery):
    await callback.answer()
    await callback.message.answer_invoice(
        title=f"Souldawn Premium — {PREMIUM_DAYS} дней",
        description="Инкогнито-режим, буст в выдаче и значок Premium",
        payload=f"premium_{PREMIUM_DAYS}d",
        currency="XTR",  # Telegram Stars
        prices=[LabeledPrice(label=f"Premium на {PREMIUM_DAYS} дней", amount=PREMIUM_PRICE_STARS)],
    )


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
    await _grant_premium(
        message, db_user["id"], message.successful_payment.telegram_payment_charge_id,
    )


# ── CryptoBot (Crypto Pay API) ───────────────────────────────────

@router.callback_query(F.data == "pay:crypto")
async def pay_crypto(callback: CallbackQuery):
    db_user = await get_or_create_user(
        callback.from_user.id,
        callback.from_user.username or "",
        callback.from_user.first_name or "",
    )
    await callback.answer()

    invoice = await cryptobot.create_premium_invoice(db_user["id"])
    if not invoice:
        await callback.message.answer(
            "⚠️ Не удалось создать счёт. Попробуйте позже или оплатите Stars.",
            reply_markup=payment_methods_kb(),
        )
        return

    await callback.message.answer(
        f"💎 Счёт на <b>{PREMIUM_PRICE_USDT} USDT</b> создан.\n\n"
        "1. Оплатите по кнопке ниже\n"
        "2. Вернитесь и нажмите «Проверить оплату»",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💳 Оплатить в CryptoBot", url=invoice["url"])],
            [InlineKeyboardButton(
                text="✅ Проверить оплату",
                callback_data=f"paycheck:{invoice['invoice_id']}",
            )],
        ]),
    )


@router.callback_query(F.data.startswith("paycheck:"))
async def check_crypto_payment(callback: CallbackQuery):
    invoice_id = callback.data.split(":", 1)[1]
    db_user = await get_or_create_user(
        callback.from_user.id,
        callback.from_user.username or "",
        callback.from_user.first_name or "",
    )

    try:
        paid = await cryptobot.check_invoice_paid(int(invoice_id), db_user["id"])
    except (ValueError, TypeError):
        paid = False

    if paid:
        await callback.answer("Оплата найдена!")
        await _grant_premium(callback.message, db_user["id"], f"cryptobot:{invoice_id}")
    else:
        await callback.answer("Оплата пока не поступила. Попробуйте через минуту.", show_alert=True)


# ── СБП (заглушка до подключения провайдера) ────────────────────

@router.callback_query(F.data == "pay:sbp")
async def pay_sbp(callback: CallbackQuery):
    await callback.answer("🏦 Оплата по СБП скоро появится!", show_alert=True)
