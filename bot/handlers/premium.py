from __future__ import annotations

import logging
import re

from aiogram import Router, F
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LabeledPrice,
    Message,
    PreCheckoutQuery,
)

from config import (
    PAYMENT_PROVIDER_TOKEN,
    RUB_PER_STAR,
    RUB_PER_USDT,
    SBP_ENABLED,
)
from database import (
    get_or_create_user, get_active_subscription, activate_premium,
    activate_promo_code, redeem_gift_code, revoke_premium_payment,
    credit_pack, revoke_pack, get_profile,
)
from keyboards import main_kb
from states import PromoStates
from services import cryptobot
from services.plans import (
    PACK_ICONS,
    PACKS,
    PACKS_BY_CODE,
    PLANS_BY_CODE,
    TIER_ICONS,
    TIER_NAMES,
    TIER_ORDER,
    TIER_PERKS,
    Plan,
    plans_for,
    tier_rank,
)

logger = logging.getLogger(__name__)
router = Router()


def _без_значка(перк: str) -> str:
    """Перк без ведущего значка — для описания счёта, где эмодзи лишние.

    Раньше значки срезались перечислением (`lstrip("👀🥷⭐🚀✨🚪 ")`), и каждый
    новый перк приходилось дописывать в этот набор. Перки уровня Aurora (✉️ 📣
    📈) и «🔮 Все расклады Таро» в него не попали и уезжали в счёт вместе со
    значком. Срезаем всё, что не буква и не цифра, — набор больше не ведём.
    """
    return re.sub(r"^\W+", "", перк, flags=re.UNICODE)


def _tier_pitch(tier: str) -> str:
    """Описание уровня: что даёт и почём."""
    perks = "\n".join(TIER_PERKS[tier])
    cheapest = min(plans_for(tier), key=lambda p: p.price_per_month)
    return (
        f"<b>Симп {TIER_NAMES[tier]}</b>\n\n{perks}\n\n"
        f"<i>от {cheapest.price_per_month} ₽ в месяц</i>"
    )


def tiers_kb() -> InlineKeyboardMarkup:
    """Выбор уровня — первый шаг покупки.

    Кнопки собираются циклом по линейке, а не перечисляются руками: пока
    здесь стояли два литеральных блока, добавленный третий уровень (Aurora)
    остался без кнопки — а веб и мини-апп за оплатой уходят именно сюда, и
    купить верхний тариф было негде, кроме нативной сборки iOS.
    """
    кнопки = [
        [InlineKeyboardButton(
            text=(
                f"{TIER_ICONS.get(tier, '•')} {TIER_NAMES[tier]} — "
                f"от {min(p.price_per_month for p in plans_for(tier))} ₽/мес"
            ),
            callback_data=f"tier:{tier}",
        )]
        # Первый уровень бесплатный — покупать в нём нечего
        for tier in TIER_ORDER[1:]
    ]
    # Паки — под уровнями, а не среди них: это разовая покупка, а не подписка
    кнопки.append([InlineKeyboardButton(
        text="⚡ Паки: суперлайки и бусты", callback_data="packs",
    )])
    кнопки.append([InlineKeyboardButton(
        text="🎁 У меня есть код", callback_data="promo",
    )])
    кнопки.append([InlineKeyboardButton(text="🏠 В меню", callback_data="menu")])
    return InlineKeyboardMarkup(inline_keyboard=кнопки)


def packs_kb() -> InlineKeyboardMarkup:
    """Витрина паков. Кнопки циклом по каталогу — как tiers_kb по линейке:
    добавленный пак не должен оставаться без кнопки."""
    кнопки = [
        [InlineKeyboardButton(
            text=f"{PACK_ICONS.get(pack.kind, '•')} {pack.title} — {pack.price_stars} ⭐",
            callback_data=f"packbuy:{pack.code}",
        )]
        for pack in PACKS
    ]
    кнопки.append([InlineKeyboardButton(text="← Назад", callback_data="premium")])
    return InlineKeyboardMarkup(inline_keyboard=кнопки)


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
    """Способы оплаты: Stars всегда, CryptoBot и рубли — если настроены."""
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
        # «Карта или СБП», а не просто «СБП»: провайдер показывает в своей
        # форме оба способа, и обещать один — терять тех, кто платит картой.
        # Цена в рублях здесь ровно та, что в линейке: этот способ единственный,
        # где не нужен пересчёт курса
        rows.append([InlineKeyboardButton(
            text=f"🏦 Карта или СБП — {plan.price_rub} ₽",
            callback_data=f"pay:sbp:{code}",
        )])
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
    amount: int | None = None, currency: str | None = None,
):
    plan = PLANS_BY_CODE[code]
    sub = await activate_premium(
        user_id,
        days=plan.days,
        payment_id=payment_id,
        provider=provider,
        tier=plan.tier,
        amount=amount,
        currency=currency,
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


# ── Паки за Stars: суперлайки и бусты ────────────────────────────

@router.callback_query(F.data == "packs")
async def show_packs(callback: CallbackQuery):
    """Витрина паков — разовые покупки без подписки."""
    await callback.answer()
    await callback.message.answer(
        "<b>⚡ Паки</b>\n\n"
        "Разовые покупки за Telegram Stars — без подписки:\n\n"
        "⭐ <b>Суперлайки</b> — человек получает уведомление о вашей "
        "симпатии ещё до мэтча. Тратятся после суточных, не сгорают.\n"
        "🚀 <b>Бусты</b> — анкета на 30 минут поднимается и в деке, и в "
        "очереди «Оценка фото». Работают на любом тарифе.",
        reply_markup=packs_kb(),
    )


def _дней(n: int) -> str:
    """«1 день», «3 дня», «30 дней» — сроки промокодов произвольные."""
    if n % 10 == 1 and n % 100 != 11:
        слово = "день"
    elif n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14):
        слово = "дня"
    else:
        слово = "дней"
    return f"{n} {слово}"


def _месяцев(n: int) -> str:
    """«1 месяц», «3 месяца», «12 месяцев» — сроки подарков в месяцах."""
    if n % 10 == 1 and n % 100 != 11:
        слово = "месяц"
    elif n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14):
        слово = "месяца"
    else:
        слово = "месяцев"
    return f"{n} {слово}"


@router.callback_query(F.data == "promo")
async def promo_start(callback: CallbackQuery, state: FSMContext):
    """Кнопка «У меня есть промокод» — ждём код сообщением."""
    await callback.answer()
    await state.set_state(PromoStates.waiting_code)
    await callback.message.answer(
        "🎁 Пришлите промокод или подарочный код сообщением.\n\n"
        "Передумали — /cancel."
    )


@router.message(PromoStates.waiting_code, F.text)
async def promo_code_received(message: Message, state: FSMContext):
    """Код прислан — активируем.

    Одно поле на оба вида кодов: человеку всё равно, промокод у него из
    поста или подарочный код от друга. Сначала пробуем как промокод, на
    not_found — как подарок; только двойное «нет такого» показывает отказ.

    Опечатка (кода нет нигде) оставляет состояние: человек поправит и
    пришлёт снова. Остальные отказы окончательные — состояние снимаем,
    повторный ввод того же кода ничего не изменит. Исключение — tier_lower:
    код цел, но и повтор сейчас даст тот же отказ, поэтому состояние тоже
    снимаем, а текст объясняет, что код можно активировать позже.
    """
    db_user = await get_or_create_user(
        message.from_user.id,
        message.from_user.username or "",
        message.from_user.first_name or "",
    )
    итог = await activate_promo_code(db_user["id"], message.text or "")

    if итог.get("activated"):
        await state.clear()
        name = TIER_NAMES.get(итог["tier"], "Premium")
        logger.info(
            f"Promo redeemed: user={db_user['id']} tier={итог['tier']} "
            f"until={итог['expires_at']}"
        )
        await message.answer(
            f"🎉 <b>Промокод принят!</b>\n\n"
            f"{TIER_ICONS.get(итог['tier'], '⭐')} {name} на {_дней(итог['days'])} — "
            f"подписка активна до {итог['expires_at'][:10]}.",
            reply_markup=main_kb(),
        )
        return

    reason = итог.get("reason", "")
    if reason == "not_found":
        подарок = await redeem_gift_code(db_user["id"], message.text or "")

        if подарок.get("redeemed"):
            await state.clear()
            name = TIER_NAMES.get(подарок["tier"], "Premium")
            logger.info(
                f"Gift redeemed: user={db_user['id']} tier={подарок['tier']} "
                f"until={подарок['expires_at']}"
            )
            await message.answer(
                f"🎁 <b>Подарок принят!</b>\n\n"
                f"{TIER_ICONS.get(подарок['tier'], '⭐')} {name} на "
                f"{_месяцев(подарок['months'])} — подписка активна до "
                f"{подарок['expires_at'][:10]}.",
                reply_markup=main_kb(),
            )
            return

        причина_подарка = подарок.get("reason", "")
        if причина_подарка == "not_found":
            await message.answer(
                "Такого кода нет — ни промокода, ни подарочного. "
                "Проверьте код и пришлите ещё раз — или /cancel."
            )
            return

        await state.clear()
        тексты_подарка = {
            "not_paid": "Этот подарок ещё не оплачен — покупка не завершена.",
            "already_used": "Этот код уже активирован.",
            "expired": "Срок действия этого кода истёк.",
            "tier_lower": (
                "У вас уже действует уровень выше — код цел, активируйте "
                "его после окончания подписки или подарите другому."
            ),
        }
        await message.answer(
            тексты_подарка.get(причина_подарка, "Не получилось активировать код."),
            reply_markup=main_kb(),
        )
        return

    await state.clear()
    тексты = {
        "expired": "Срок действия этого промокода истёк.",
        "already_used": "Вы уже активировали этот промокод.",
        "exhausted": "Этот промокод уже закончился — активации разобрали.",
    }
    await message.answer(
        тексты.get(reason, "Не получилось активировать промокод."),
        reply_markup=main_kb(),
    )


@router.callback_query(F.data.startswith("packbuy:"))
async def buy_pack(callback: CallbackQuery):
    """Счёт за пак. Только Stars: мелкие суммы у СБП-провайдеров упираются
    в минималки, у крипты — в комиссии."""
    code = callback.data.split(":", 1)[1]
    pack = PACKS_BY_CODE.get(code)
    if pack is None:
        await callback.answer("Пак больше не доступен", show_alert=True)
        return

    db_user = await get_or_create_user(
        callback.from_user.id,
        callback.from_user.username or "",
        callback.from_user.first_name or "",
    )
    # Бонусы лежат на анкете — без неё начислять некуда. Проверка до счёта,
    # а не после оплаты: деньги за пустоту не берём
    if await get_profile(db_user["id"]) is None:
        await callback.answer(
            "Сначала заполните анкету — паки начисляются на неё.",
            show_alert=True,
        )
        return

    await callback.answer()
    await callback.message.answer_invoice(
        title=f"Пак: {pack.title}",
        description=(
            f"+{pack.qty} к балансу сразу после оплаты. "
            "Не сгорает, тратится после суточной квоты."
        ),
        # Код пака в payload: по нему successful_payment узнаёт, что начислять
        payload=f"pack:{pack.code}",
        currency="XTR",  # Telegram Stars
        prices=[LabeledPrice(label=pack.title, amount=pack.price_stars)],
    )


async def process_pack_payment(message: Message, user_id: str) -> None:
    """Начислить оплаченный пак (вызывается из on_successful_payment)."""
    charge_id = message.successful_payment.telegram_payment_charge_id
    payload = message.successful_payment.invoice_payload or ""
    code = payload.split(":", 1)[1]
    pack = PACKS_BY_CODE.get(code)
    if pack is None:
        # Счёт по снятому с продажи паку: деньги списаны, товара нет —
        # возвращаем Stars, а не выдумываем замену (у паков, в отличие от
        # подписок, нет «младшего уровня», который честно покрыл бы оплату)
        logger.warning(f"Оплата неизвестного пака payload={payload!r} — возвращаю Stars")
        try:
            await message.bot.refund_star_payment(
                user_id=message.from_user.id,
                telegram_payment_charge_id=charge_id,
            )
        except Exception as e:
            logger.error(f"Не удалось вернуть Stars за неизвестный пак: {e}")
        await message.answer(
            "⚠️ Этот пак больше не продаётся — Stars возвращены.",
            reply_markup=main_kb(),
        )
        return

    итог = await credit_pack(
        user_id,
        charge_id,
        kind=pack.kind,
        qty=pack.qty,
        stars=message.successful_payment.total_amount,
    )

    if итог.get("credited"):
        значок = PACK_ICONS.get(pack.kind, "⚡")
        куда = (
            "Включаются кнопкой молнии в деке мини-аппа."
            if pack.kind == "boosts"
            else "Кнопка суперлайка в деке спишет их после суточных."
        )
        logger.info(f"Пак куплен: user={user_id} charge={charge_id} pack={code}")
        await message.answer(
            f"🎉 <b>{значок} +{pack.qty} к балансу!</b>\n"
            f"Теперь на счету: {итог.get('balance')}. {куда}",
            reply_markup=main_kb(),
        )
        return

    if итог.get("reason") == "already_processed":
        # Дубль апдейта Telegram — начислено ровно один раз
        logger.info(f"Пак: повторный зачёт отклонён user={user_id} charge={charge_id}")
        await message.answer("⚡ Этот платёж уже зачтён.", reply_markup=main_kb())
        return

    # Анкеты нет (удалена между счётом и оплатой) — класть бонус некуда,
    # деньги за пустоту не держим
    logger.warning(
        f"Оплата пака без анкеты: user={user_id} charge={charge_id} — возвращаю Stars"
    )
    try:
        await message.bot.refund_star_payment(
            user_id=message.from_user.id,
            telegram_payment_charge_id=charge_id,
        )
    except Exception as e:
        # Возврат не прошёл — след в логе, поддержка вернёт руками
        logger.error(f"Не удалось вернуть Stars за пак без анкеты: {e}")
    await message.answer(
        "⚠️ Анкета не найдена, начислять пак некуда — Stars возвращены. "
        "Заполните анкету и купите пак заново.",
        reply_markup=main_kb(),
    )


async def process_pack_refund(message: Message) -> None:
    """Списать пак после возврата Stars (вызывается из on_refunded_payment).

    Не найден платёж — возврат уже обработан или зачёта не было: молчим,
    писать человеку «мы у вас ничего не забрали» не о чем.
    """
    charge_id = message.refunded_payment.telegram_payment_charge_id
    payload = message.refunded_payment.invoice_payload or ""
    code = payload.split(":", 1)[1] if ":" in payload else ""
    pack = PACKS_BY_CODE.get(code)
    if pack is None:
        logger.warning(f"Возврат неизвестного пака payload={payload!r} charge={charge_id}")
        return

    итог = await revoke_pack(charge_id, kind=pack.kind, qty=pack.qty)
    if not итог.get("revoked"):
        logger.warning(f"Возврат пака без зачтённого платежа: charge={charge_id}")
        return

    logger.info(f"Пак списан по возврату: charge={charge_id} pack={code}")
    await message.answer(
        f"Возврат получен — {pack.title} списаны с баланса. Если это ошибка, "
        "пак можно купить заново в разделе ⭐ Premium.",
        reply_markup=main_kb(),
    )


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
        title=f"Симп {plan.title}",
        description=", ".join(_без_значка(p) for p in TIER_PERKS[plan.tier]),
        payload=f"plan:{plan.code}",
        currency="XTR",  # Telegram Stars
        prices=[LabeledPrice(label=plan.title, amount=stars_for(plan))],
    )


@router.pre_checkout_query()
async def pre_checkout(query: PreCheckoutQuery):
    # Сумму и состав счёта хранит и сверяет Telegram — и для Stars, и для
    # рублёвого провайдера, поэтому подтверждаем всегда. Отказ здесь означал
    # бы «денег не берём», а решение о снятом с продажи тарифе принято ниже,
    # в on_successful_payment: человеку, уже нажавшему «оплатить», честнее
    # выдать младший платный уровень, чем ошибку без объяснения
    await query.answer(ok=True)


@router.message(F.successful_payment)
async def on_successful_payment(message: Message):
    db_user = await get_or_create_user(
        message.from_user.id,
        message.from_user.username or "",
        message.from_user.first_name or "",
    )
    payload = message.successful_payment.invoice_payload or ""

    # Telegram шлёт successful_payment одним типом апдейта на все покупки —
    # диспетчеризуем по payload. Разблокировка ДО фолбэка «неизвестный код →
    # plus_1m», иначе её оплата зачлась бы как подписка.
    if payload.startswith("unban"):
        from handlers.unban import process_unban_payment

        await process_unban_payment(message, db_user["id"])
        return

    # Паки — тоже ДО фолбэка «неизвестный код → plus_1m»: их оплата не
    # должна зачитываться как подписка
    if payload.startswith("pack:"):
        await process_pack_payment(message, db_user["id"])
        return

    code = payload.split(":", 1)[1] if payload.startswith("plan:") else ""
    if code not in PLANS_BY_CODE:
        # Счёт старого формата или снятый с продажи тариф: деньги списаны,
        # оставить человека без подписки нельзя — начисляем младший платный
        logger.warning(f"Оплата с неизвестным payload={payload!r}, начисляю plus_1m")
        code = "plus_1m"
    # Провайдера определяем по валюте: XTR — это Stars, всё остальное пришло
    # через платёжного провайдера. Ключ идемпотентности в журнале платежей —
    # пара (provider, external_id), и записать рублёвый платёж как "stars"
    # значило бы столкнуть их нумерации: чужой charge_id мог бы «уже быть
    # зачтён». А возврат Stars ищет платёж именно по provider="stars" и снял
    # бы подписку, оплаченную картой
    провайдер = "stars" if message.successful_payment.currency == "XTR" else "sbp"
    await _grant_premium(
        message,
        db_user["id"],
        message.successful_payment.telegram_payment_charge_id,
        provider=провайдер,
        code=code,
        # Сумма как её видел Telegram: XTR — звёзды, рубли — копейки.
        # По ней админка считает выручку (/api/admin/metrics)
        amount=message.successful_payment.total_amount,
        currency=message.successful_payment.currency,
    )


@router.message(F.refunded_payment)
async def on_refunded_payment(message: Message):
    """Stars вернули — подписку надо снять.

    Без этого обработчика возврат был бесплатным Ultra: человек оплачивал,
    получал уровень, возвращал Stars через поддержку Telegram и продолжал
    пользоваться до конца оплаченного срока.

    Срок урезаем ровно на дни этого платежа, а не гасим подписку целиком:
    рядом могла быть другая, честно оплаченная покупка.

    Рублёвых возвратов здесь не бывает: `refunded_payment` Telegram присылает
    только по Stars, а возврат карты или СБП делается в кабинете провайдера и
    боту не приходит вовсе. Поэтому provider="stars" зашит: искать рублёвый
    платёж этим обработчиком нечем, и подписку, оплаченную картой, он не
    тронет даже при совпадении charge_id.
    """
    # Возврат за разблокировку — не про подписку: бан возвращается на место
    if (message.refunded_payment.invoice_payload or "").startswith("unban"):
        from handlers.unban import process_unban_refund

        await process_unban_refund(message)
        return

    # Возврат за пак — списание баланса, подписка ни при чём
    if (message.refunded_payment.invoice_payload or "").startswith("pack:"):
        await process_pack_refund(message)
        return

    charge_id = message.refunded_payment.telegram_payment_charge_id
    итог = await revoke_premium_payment(charge_id, provider="stars")

    if not итог.get("revoked"):
        logger.warning(f"Возврат по неизвестному платежу charge={charge_id}")
        return

    logger.info(
        f"Возврат Stars: charge={charge_id} user={итог.get('user_id')} "
        f"снято дней={итог.get('days')} уровень={итог.get('plan')}"
    )
    await message.answer(
        "Возврат получен — подписка отменена. Если это ошибка, "
        "оформите её заново в разделе ⭐ Premium.",
        reply_markup=main_kb(),
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
        db_user["id"], amount=amount, title=f"Симп {plan.title}", plan_code=code,
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
    # callback_data подделывается, но владельца, тариф и сумму счёта сверяет
    # check_invoice_paid: подставив чужой invoice_id или код дорогого тарифа
    # к дешёвому счёту, оплаченного не получишь
    code = parts[2] if len(parts) > 2 and parts[2] in PLANS_BY_CODE else "plus_1m"
    plan = PLANS_BY_CODE[code]
    db_user = await get_or_create_user(
        callback.from_user.id,
        callback.from_user.username or "",
        callback.from_user.first_name or "",
    )

    try:
        paid = await cryptobot.check_invoice_paid(
            int(invoice_id),
            db_user["id"],
            plan_code=code,
            expected_amount=usdt_for(plan),
        )
    except (ValueError, TypeError):
        paid = False

    if paid:
        await callback.answer("Оплата найдена!")
        await _grant_premium(
            callback.message, db_user["id"], invoice_id,
            provider="cryptobot", code=code,
            # Цена тарифа, а не фактический платёж: CryptoBot принимает
            # переплату, но зачитывается ровно тариф — его и пишем. USDT
            # храним в сотых, как копейки у рубля
            amount=int(round(float(usdt_for(plan)) * 100)),
            currency="USDT",
        )
    else:
        await callback.answer("Оплата пока не поступила. Попробуйте через минуту.", show_alert=True)


# ── Рубли: карта и СБП через платёжного провайдера ───────────────

@router.callback_query(F.data.startswith("pay:sbp"))
async def pay_sbp(callback: CallbackQuery):
    """Счёт в рублях. Провайдер (ЮKassa и аналоги) сам показывает карту и СБП.

    Счёт держит Telegram, поэтому здесь нет ни своего HTTP-клиента, ни
    вебхука: оплата возвращается тем же `successful_payment`, что и Stars, и
    различается по валюте — см. on_successful_payment.

    Фильтр по префиксу, а не по точному совпадению: кнопка передаёт код
    тарифа (`pay:sbp:plus_1m`), и точное сравнение делало бы её мёртвой —
    нажатие не обрабатывалось бы вовсе, и Telegram показывал бы «часики».
    """
    code = callback.data.rsplit(":", 1)[-1]
    plan = PLANS_BY_CODE.get(code)
    if plan is None:
        await callback.answer("Тариф больше не доступен", show_alert=True)
        return
    if not PAYMENT_PROVIDER_TOKEN:
        # Кнопки без токена быть не должно (SBP_ENABLED), но callback_data
        # подделывается: без проверки Telegram вернул бы «invalid token»
        await callback.answer(
            "🏦 Оплата картой сейчас недоступна. Доступны Stars и криптовалюта.",
            show_alert=True,
        )
        return

    await callback.answer()
    try:
        await callback.message.answer_invoice(
            title=f"Симп {plan.title}",
            description=", ".join(_без_значка(p) for p in TIER_PERKS[plan.tier]),
            # Тот же payload, что у Stars: зачёт разбирает его в одном месте
            payload=f"plan:{plan.code}",
            provider_token=PAYMENT_PROVIDER_TOKEN,
            currency="RUB",
            # Рубли Telegram принимает в копейках. Ошибка в сто раз тут не
            # падает, а тихо продаёт Ultra за 8 рублей
            prices=[LabeledPrice(label=plan.title, amount=plan.price_rub * 100)],
        )
    except TelegramAPIError as e:
        # Чаще всего это неверный или отвязанный токен провайдера. Человеку
        # нужен не текст ошибки, а второй способ оплаты — тот же ход, что и
        # при отказе CryptoBot
        logger.warning(f"Счёт в рублях не создан plan={code}: {e}")
        await callback.message.answer(
            "⚠️ Не удалось создать счёт. Попробуйте позже или оплатите Stars.",
            reply_markup=payment_methods_kb(code),
        )
