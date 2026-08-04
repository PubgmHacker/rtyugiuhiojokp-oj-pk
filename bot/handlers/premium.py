from __future__ import annotations

import logging

from aiogram import Router, F
from aiogram.filters import Command, StateFilter
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LabeledPrice,
    Message,
    PreCheckoutQuery,
)

from config import (
    RUB_PER_STAR,
    RUB_PER_USDT,
    SBP_ENABLED,
)
from database import get_or_create_user, get_active_subscription, activate_premium
from keyboards import main_kb
from services import cryptobot
from services.plans import (
    PLANS_BY_CODE,
    TIER_NAMES,
    TIER_PERKS,
    TIER_PLUS,
    TIER_ULTRA,
    Plan,
    plans_for,
    tier_rank,
)

logger = logging.getLogger(__name__)
router = Router()


def _tier_pitch(tier: str) -> str:
    """Описание уровня: что даёт и почём."""
    perks = "\n".join(TIER_PERKS[tier])
    cheapest = min(plans_for(tier), key=lambda p: p.price_per_month)
    return (
        f"<b>Souldawn {TIER_NAMES[tier]}</b>\n\n{perks}\n\n"
        f"<i>от {cheapest.price_per_month} ₽ в месяц</i>"
    )


def tiers_kb() -> InlineKeyboardMarkup:
    """Выбор уровня — первый шаг покупки."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=f"✨ Plus — от {min(p.price_per_month for p in plans_for(TIER_PLUS))} ₽/мес",
            callback_data=f"tier:{TIER_PLUS}",
        )],
        [InlineKeyboardButton(
            text=f"👑 Ultra — от {min(p.price_per_month for p in plans_for(TIER_ULTRA))} ₽/мес",
            callback_data=f"tier:{TIER_ULTRA}",
        )],
        [InlineKeyboardButton(text="🏠 В меню", callback_data="menu")],
    ])


def periods_kb(tier: str) -> InlineKeyboardMarkup:
    """Сроки внутри уровня. Выгода длинного срока показана явно —
    без неё цифра «2590 ₽» выглядит просто дороже месячной."""
    monthly = PLANS_BY_CODE[f"{tier}_1m"].price_rub
    rows = []
    for plan in plans_for(tier):
        label = f"{plan.title} — {plan.price_rub} ₽"
        if plan.months > 1:
            saving = round(100 - plan.price_per_month * 100 / monthly)
            label += f"  (−{saving}%)"
        rows.append([InlineKeyboardButton(text=label, callback_data=f"buy:{plan.code}")])
    rows.append([InlineKeyboardButton(text="← Назад", callback_data="premium")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def payment_methods_kb(code: str) -> InlineKeyboardMarkup:
    """Способы оплаты: Stars всегда, CryptoBot/СБП — если настроены."""
    plan = PLANS_BY_CODE[code]
    rows = [[InlineKeyboardButton(
        text=f"⭐ Telegram Stars — {stars_for(plan)} ⭐",
        callback_data=f"pay:stars:{code}",
    )]]
    if cryptobot.is_enabled():
        rows.append([InlineKeyboardButton(
            text=f"💎 Криптовалюта — {usdt_for(plan)} USDT",
            callback_data=f"pay:crypto:{code}",
        )])
    if SBP_ENABLED:
        rows.append([InlineKeyboardButton(text="🏦 СБП", callback_data=f"pay:sbp:{code}")])
    rows.append([InlineKeyboardButton(text="← Назад", callback_data=f"tier:{plan.tier}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def stars_for(plan: Plan) -> int:
    """Цена в Stars. Курс держим в настройках: Telegram меняет его сам,
    а рублёвая цена в линейке остаётся единой для всех способов оплаты."""
    return max(1, round(plan.price_rub / RUB_PER_STAR))


def usdt_for(plan: Plan) -> str:
    return f"{plan.price_rub / RUB_PER_USDT:.2f}"


async def send_premium_offer(message: Message, user_id: str):
    """Показать статус подписки и витрину уровней."""
    sub = await get_active_subscription(user_id)
    if sub and tier_rank(sub.get("plan") or "") > 0:
        expires = (sub.get("expires_at") or "")[:10]
        name = TIER_NAMES.get(sub.get("plan") or "", "Premium")
        await message.answer(
            f"⭐ <b>{name} активен</b> до {expires}.\n\nПродлить или перейти выше:",
            reply_markup=tiers_kb(),
        )
    else:
        await message.answer("Выберите уровень:", reply_markup=tiers_kb())


async def _grant_premium(
    message: Message, user_id: str, payment_id: str, provider: str, code: str,
):
    plan = PLANS_BY_CODE[code]
    sub = await activate_premium(
        user_id,
        days=plan.days,
        payment_id=payment_id,
        provider=provider,
        tier=plan.tier,
    )
    name = TIER_NAMES[plan.tier]
    if sub.get("already_processed"):
        # Этот платёж уже был зачтён — повторное нажатие «Проверить оплату»
        # не должно продлевать подписку второй раз
        logger.info(f"Premium: повторный зачёт отклонён user={user_id} charge={payment_id}")
        expires = (sub.get("expires_at") or "")[:10]
        await message.answer(
            f"⭐ Этот платёж уже зачтён. Подписка активна до {expires}.",
            reply_markup=main_kb(),
        )
        return
    logger.info(
        f"Premium activated: user={user_id} plan={code} charge={payment_id} "
        f"until={sub['expires_at']}"
    )
    await message.answer(
        f"🎉 <b>{name} активирован</b> до {sub['expires_at'][:10]}!\n\n"
        + "\n".join(TIER_PERKS[plan.tier]),
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
    await send_premium_offer(callback.message, db_user["id"])


@router.callback_query(F.data.startswith("tier:"))
async def choose_tier(callback: CallbackQuery):
    """Выбран уровень — показываем, что он даёт, и сроки."""
    tier = callback.data.split(":", 1)[1]
    if tier not in TIER_PERKS:
        await callback.answer("Неизвестный тариф", show_alert=True)
        return
    await callback.answer()
    await callback.message.answer(_tier_pitch(tier), reply_markup=periods_kb(tier))


@router.callback_query(F.data.startswith("buy:"))
async def choose_period(callback: CallbackQuery):
    """Выбран срок — показываем способы оплаты."""
    code = callback.data.split(":", 1)[1]
    plan = PLANS_BY_CODE.get(code)
    if plan is None:
        await callback.answer("Тариф больше не доступен", show_alert=True)
        return
    await callback.answer()
    await callback.message.answer(
        f"<b>{plan.title}</b> — {plan.price_rub} ₽\n\nВыберите способ оплаты:",
        reply_markup=payment_methods_kb(code),
    )


@router.message(StateFilter("*"), Command("premium"))
async def premium_command(message: Message):
    db_user = await get_or_create_user(
        message.from_user.id,
        message.from_user.username or "",
        message.from_user.first_name or "",
    )
    await send_premium_offer(message, db_user["id"])


# ── Telegram Stars ───────────────────────────────────────────────

@router.callback_query(F.data.startswith("pay:stars:"))
async def pay_stars(callback: CallbackQuery):
    code = callback.data.rsplit(":", 1)[-1]
    plan = PLANS_BY_CODE.get(code)
    if plan is None:
        await callback.answer("Тариф больше не доступен", show_alert=True)
        return
    await callback.answer()
    # Код тарифа уходит в payload: по нему при успешной оплате мы узнаем,
    # что именно куплено — сам платёж такой информации не несёт
    await callback.message.answer_invoice(
        title=f"Souldawn {plan.title}",
        description=", ".join(p.lstrip("👀🥷⭐🚀✨🚪 ") for p in TIER_PERKS[plan.tier]),
        payload=f"plan:{plan.code}",
        currency="XTR",  # Telegram Stars
        prices=[LabeledPrice(label=plan.title, amount=stars_for(plan))],
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
    payload = message.successful_payment.invoice_payload or ""
    code = payload.split(":", 1)[1] if payload.startswith("plan:") else ""
    if code not in PLANS_BY_CODE:
        # Счёт старого формата или снятый с продажи тариф: деньги списаны,
        # оставить человека без подписки нельзя — начисляем младший платный
        logger.warning(f"Оплата с неизвестным payload={payload!r}, начисляю plus_1m")
        code = "plus_1m"
    await _grant_premium(
        message,
        db_user["id"],
        message.successful_payment.telegram_payment_charge_id,
        provider="stars",
        code=code,
    )


# ── CryptoBot (Crypto Pay API) ───────────────────────────────────

@router.callback_query(F.data.startswith("pay:crypto:"))
async def pay_crypto(callback: CallbackQuery):
    code = callback.data.rsplit(":", 1)[-1]
    plan = PLANS_BY_CODE.get(code)
    if plan is None:
        await callback.answer("Тариф больше не доступен", show_alert=True)
        return

    db_user = await get_or_create_user(
        callback.from_user.id,
        callback.from_user.username or "",
        callback.from_user.first_name or "",
    )
    await callback.answer()

    amount = usdt_for(plan)
    invoice = await cryptobot.create_premium_invoice(
        db_user["id"], amount=amount, title=f"Souldawn {plan.title}",
    )
    if not invoice:
        await callback.message.answer(
            "⚠️ Не удалось создать счёт. Попробуйте позже или оплатите Stars.",
            reply_markup=payment_methods_kb(code),
        )
        return

    await callback.message.answer(
        f"💎 Счёт на <b>{amount} USDT</b> за {plan.title} создан.\n\n"
        "1. Оплатите по кнопке ниже\n"
        "2. Вернитесь и нажмите «Проверить оплату»",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💳 Оплатить в CryptoBot", url=invoice["url"])],
            [InlineKeyboardButton(
                text="✅ Проверить оплату",
                # Код тарифа в callback_data: сам инвойс не помнит, что куплено
                callback_data=f"paycheck:{invoice['invoice_id']}:{code}",
            )],
        ]),
    )


@router.callback_query(F.data.startswith("paycheck:"))
async def check_crypto_payment(callback: CallbackQuery):
    parts = callback.data.split(":")
    invoice_id = parts[1]
    # callback_data подделывается, но сумму и владельца счёта проверяет
    # check_invoice_paid: подставив чужой код, оплаченного не получишь
    code = parts[2] if len(parts) > 2 and parts[2] in PLANS_BY_CODE else "plus_1m"
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
        await _grant_premium(
            callback.message, db_user["id"], invoice_id,
            provider="cryptobot", code=code,
        )
    else:
        await callback.answer("Оплата пока не поступила. Попробуйте через минуту.", show_alert=True)


# ── СБП (заглушка до подключения провайдера) ────────────────────

@router.callback_query(F.data == "pay:sbp")
async def pay_sbp(callback: CallbackQuery):
    await callback.answer("🏦 Оплата по СБП скоро появится!", show_alert=True)
