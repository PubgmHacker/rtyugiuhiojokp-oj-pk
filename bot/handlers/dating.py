from __future__ import annotations

import logging

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext

from config import BANNERS, SITE_URL
from database import (
    get_or_create_user, get_profile, get_deck_profiles,
    like_and_match, get_user_by_id, get_daily_limits,
    create_report, block_user,
)
from keyboards import (
    dating_action_kb, like_locked_kb, limit_reached_kb, main_kb,
    no_more_profiles_kb, profile_kb, report_reasons_kb,
)
from services.moderation import moderate_text, humanize
from services.plans import видно_кто_лайкнул
from states import DatingStates
from texts import profile_card, no_more_profiles, match_notification
import texts as T

logger = logging.getLogger(__name__)
router = Router()


def _webapp_url(path: str = "") -> str:
    base = SITE_URL.rstrip("/")
    return f"{base}{path}" if path else base


@router.callback_query(F.data == "dating:start")
async def start_dating(callback: CallbackQuery, state: FSMContext):
    """Начать показ анкет."""
    await state.clear()
    db_user = await get_or_create_user(
        callback.from_user.id,
        callback.from_user.username or "",
        callback.from_user.first_name or "",
    )

    # Check profile
    profile = await get_profile(db_user["id"])
    if not profile or not profile.get("display_name"):
        await callback.answer("Сначала создайте анкету!", show_alert=True)
        await callback.message.answer(
            "👤 Ваша анкета ещё пуста — создайте её за минуту:",
            reply_markup=profile_kb(),
        )
        return

    await _show_next_profile(callback.message, callback.from_user.id, db_user["id"], state)


async def _show_next_profile(message: Message, tg_id: int, user_id: str, state: FSMContext):
    """Показать следующую анкету из deck'а."""
    profiles = await get_deck_profiles(user_id, limit=5)

    if not profiles:
        # Клавиатура сама решает, есть ли чем открыть мини-апп; текст обязан
        # говорить то же самое, иначе он обещает кнопку, которой в нём нет
        клавиатура = no_more_profiles_kb()
        есть_приложение = any(
            btn.web_app or btn.url for row in клавиатура.inline_keyboard for btn in row
        )
        await message.answer_photo(
            photo=BANNERS["menu"],
            caption=no_more_profiles(есть_приложение),
            reply_markup=клавиатура,
        )
        return

    # Store all profiles in state for navigation
    await state.update_data(
        deck_profiles=profiles,
        current_deck_index=0,
    )
    await state.set_state(DatingStates.viewing_profile)

    p = profiles[0]
    await _render_profile(message, p)


async def _render_profile(message: Message, profile: dict):
    """Отрендерить карточку анкеты."""
    caption = profile_card(profile)

    # Telegram принимает и URL, и file_id — берём первое фото как есть
    photos = profile.get("photos") or []
    photo = photos[0] if isinstance(photos, list) and photos else BANNERS["deck"]

    kb = dating_action_kb(profile["user_id"])

    try:
        await message.answer_photo(photo=photo, caption=caption, reply_markup=kb)
    except Exception:
        await message.answer(caption, reply_markup=kb)


# Без фильтра по состоянию: кнопки должны работать и из уведомлений
# «вы кому-то понравились», где FSM-состояния нет.
@router.callback_query(F.data.startswith("like:"))
async def handle_like(callback: CallbackQuery, state: FSMContext):
    """Обработка лайка/пасс."""
    parts = callback.data.split(":")
    action = parts[1]       # like, pass, message
    target_id = parts[2]

    db_user = await get_or_create_user(
        callback.from_user.id,
        callback.from_user.username or "",
        callback.from_user.first_name or "",
    )

    like_type = "pass" if action == "pass" else "like"

    if action == "message":
        # Лимит проверяем ДО того, как просить текст: иначе человек напишет
        # пару слов, а лайк уйдёт в отказ — мы приняли бы сообщение, которое
        # некуда отправить. Проверка тут только предупредительная, настоящая
        # (под локом) всё равно живёт в like_and_match.
        лимиты = await get_daily_limits(db_user["id"])
        if лимиты["likes"].exhausted:
            await callback.answer(T.LIKES_LIMIT_SHORT, show_alert=True)
            await callback.message.answer(
                T.likes_limit_reached(
                    лимиты["likes"].limit, лимиты["likes"].reset_at
                ),
                reply_markup=limit_reached_kb("dating:next"),
            )
            return

        # Текст уйдёт вместе с лайком, поэтому сначала спрашиваем его, а лайк
        # ставим уже после — иначе при отказе от ввода остался бы «немой» лайк
        await callback.answer()
        await state.update_data(like_message_target=target_id)
        await state.set_state(DatingStates.waiting_like_message)
        await callback.message.answer(T.LIKE_MESSAGE_ASK)
        return

    # Пользователь в середине заполнения анкеты (лайк из старого уведомления):
    # лайк засчитываем, но не трогаем FSM-состояние регистрации
    current_state = await state.get_state()
    in_registration = bool(current_state and current_state.startswith("RegistrationStates"))

    # Лайк и проверка взаимности — одной транзакцией под advisory-lock,
    # иначе два встречных лайка в один момент теряют мэтч
    like_result = await like_and_match(db_user["id"], target_id, like_type)

    if like_result.get("limited"):
        # Лайк НЕ записан: суточная квота бесплатного уровня исчерпана.
        # Карточку оставляем на месте — 👎 лимит не тратит, листать можно
        # дальше, и это единственная разница с обычным отказом
        await callback.answer(T.LIKES_LIMIT_SHORT, show_alert=True)
        await callback.message.answer(
            T.likes_limit_reached(like_result["limit"], like_result["reset_at"]),
            reply_markup=limit_reached_kb("dating:next"),
        )
        return

    if action == "pass":
        await callback.answer("👎 Пропущено")
        # Delete current profile message and show next
        try:
            await callback.message.delete()
        except Exception:
            pass
        if not in_registration:
            await _show_next_from_deck(callback.message, db_user["id"], state)
        return

    # Всплывающий ответ и снятие карточки — здесь: у ветки с сообщением
    # своего callback уже нет, а «живые» кнопки после решения оставлять
    # нельзя, повторные тапы это спам
    await callback.answer(
        _ответ_на_лайк(like_result),
        show_alert=like_result.get("matched", False),
    )
    try:
        await callback.message.delete()
    except Exception:
        pass

    await _after_like(
        callback.message, callback.bot, db_user, target_id, like_result,
        state, in_registration,
    )


def _ответ_на_лайк(like_result: dict) -> str:
    """Текст всплывашки после лайка, с остатком суточной квоты.

    Остаток показываем на последних лайках, а не всегда: постоянный счётчик
    рядом с «Понравилось!» превращает свайпы в бухгалтерию. А вот молчание до
    самого отказа хуже — первый отказ читается как поломка бота.

    Остаток приходит из `like_and_match`, который посчитал его под локом:
    отдельный запрос здесь означал бы лишний round-trip на каждый свайп.
    """
    if like_result.get("matched"):
        return "🎉 Это мэтч!"
    осталось = like_result.get("likes_left")
    if осталось is not None and осталось <= 3:
        if осталось == 0:
            return "👍 Понравилось! Это был последний лайк на сегодня"
        хвост = T.падеж(осталось, "лайк", "лайка", "лайков")
        return f"👍 Понравилось! Осталось {осталось} {хвост}"
    return "👍 Понравилось!"


async def _after_like(
    message: Message,
    bot,
    db_user: dict,
    target_id: str,
    like_result: dict,
    state: FSMContext,
    in_registration: bool,
    note: str = "",
):
    """Что происходит после успешно поставленного лайка.

    Общая часть для обычного лайка и лайка с сообщением: уведомления, показ
    следующей анкеты. `note` — приложенный текст, он уходит получателю вместе
    с карточкой.
    """
    if like_result.get("matched"):
        # Мэтч уже создан внутри like_and_match — здесь только уведомления.
        # publish_match_event тут НЕ зовём — его слушает этот же бот,
        # и оба пользователя получили бы уведомления дважды.
        partner = await get_profile(target_id)
        await message.answer_photo(
            photo=BANNERS["match"],
            caption=match_notification(partner or {}),
            reply_markup=main_kb(),
        )

        # Уведомляем партнёра в Telegram
        partner_user = await get_user_by_id(target_id)
        if partner_user and partner_user.get("telegram_id"):
            my_profile = await get_profile(db_user["id"])
            try:
                await bot.send_photo(
                    chat_id=partner_user["telegram_id"],
                    photo=BANNERS["match"],
                    caption=match_notification(my_profile or {}),
                    reply_markup=main_kb(),
                )
                if note:
                    await bot.send_message(
                        chat_id=partner_user["telegram_id"],
                        text=f"💌 <i>{T.escape(note)}</i>",
                    )
            except Exception as e:
                logger.warning(f"Failed to notify match partner: {e}")

        # Продолжаем показ анкет
        if not in_registration:
            await _show_next_from_deck(message, db_user["id"], state)
    else:
        # Дайвинчик-механика: сообщаем партнёру, что его лайкнули.
        # Анкету лайкнувшего показываем только на Plus — это платный гейт
        # «Видно, кто вас лайкнул», и в мини-аппе он соблюдается
        # (api/routers/likes.py отдаёт бесплатному карточку без имени и фото)
        partner_user = await get_user_by_id(target_id)
        if partner_user and partner_user.get("telegram_id"):
            my_profile = await get_profile(db_user["id"])
            if my_profile and my_profile.get("display_name"):
                видно = await видно_кто_лайкнул(target_id)
                try:
                    if not видно:
                        # Про сам лайк говорим: без этого человек не узнает,
                        # что у него вообще есть входящие, и платить не за что
                        await bot.send_message(
                            chat_id=partner_user["telegram_id"],
                            text=T.LIKE_LOCKED,
                            reply_markup=like_locked_kb(),
                        )
                    else:
                        await bot.send_message(
                            chat_id=partner_user["telegram_id"],
                            text=(
                                f"💌 Вам написали вместе с лайком:\n\n<i>{T.escape(note)}</i>"
                                if note
                                else "💌 Вы кому-то понравились! Взгляните на анкету:"
                            ),
                        )
                        await _render_profile_to_chat(
                            bot, partner_user["telegram_id"], my_profile,
                        )
                except Exception as e:
                    logger.warning(f"Failed to notify liked user: {e}")

        if not in_registration:
            await _show_next_from_deck(message, db_user["id"], state)


# ── Лайк с сообщением ───────────────────────────────────────────

MAX_LIKE_MESSAGE = 200


@router.message(DatingStates.waiting_like_message, F.text)
async def process_like_message(message: Message, state: FSMContext):
    """Принять пару слов и поставить лайк вместе с ними."""
    note = (message.text or "").strip()
    if len(note) > MAX_LIKE_MESSAGE:
        await message.answer(T.LIKE_MESSAGE_TOO_LONG)
        return

    data = await state.get_data()
    target_id = data.get("like_message_target")
    if not target_id:
        # Состояние пережило перезапуск, а цель потерялась — возвращаем
        # человека к анкетам, а не оставляем в тупике
        await state.set_state(DatingStates.viewing_profile)
        await message.answer(T.ERROR_GENERIC, reply_markup=main_kb())
        return

    # Получатель увидит текст до мэтча, то есть до того, как сможет
    # заблокировать отправителя — модерируем перед отправкой
    verdict = await moderate_text(note)
    if verdict.get("blocked"):
        await message.answer(
            T.LIKE_MESSAGE_REJECTED.format(reason=humanize(verdict.get("reason", "")))
        )
        return

    db_user = await get_or_create_user(
        message.from_user.id,
        message.from_user.username or "",
        message.from_user.first_name or "",
    )
    like_result = await like_and_match(db_user["id"], target_id, "like", note)

    await state.set_state(DatingStates.viewing_profile)
    await state.update_data(like_message_target=None)

    if like_result.get("limited"):
        # Квота кончилась между вопросом и ответом — например, человек лайкал
        # из мини-аппа, пока писал здесь. Текст НЕ отправлен, и говорим об этом
        # прямо: «Отправлено» с потерянным сообщением хуже отказа
        await message.answer(
            T.likes_limit_reached(like_result["limit"], like_result["reset_at"]),
            reply_markup=limit_reached_kb("dating:next"),
        )
        return

    await message.answer(T.LIKE_MESSAGE_SENT)

    await _after_like(
        message, message.bot, db_user, target_id, like_result,
        state, in_registration=False, note=note,
    )


@router.message(DatingStates.waiting_like_message)
async def like_message_wrong_type(message: Message):
    await message.answer(T.REG_EXPECT_TEXT)


async def _render_profile_to_chat(bot, chat_id: int, profile: dict):
    """Отправить карточку анкеты в произвольный чат (для уведомлений о лайке)."""
    caption = profile_card(profile)
    kb = dating_action_kb(profile["user_id"])
    photos = profile.get("photos") or []
    photo = photos[0] if photos else BANNERS["deck"]
    try:
        await bot.send_photo(chat_id=chat_id, photo=photo, caption=caption, reply_markup=kb)
    except Exception:
        await bot.send_message(chat_id=chat_id, text=caption, reply_markup=kb)


async def _show_next_from_deck(message: Message, user_id: str, state: FSMContext):
    """Показать следующую анкету из кеша."""
    data = await state.get_data()
    profiles = data.get("deck_profiles", [])
    index = data.get("current_deck_index", 0) + 1

    if index < len(profiles):
        await state.update_data(current_deck_index=index)
        await _render_profile(message, profiles[index])
    else:
        # Need to fetch more
        await _show_next_profile(message, 0, user_id, state)


# ── Жалоба на анкету (требование App Store: report в один тап) ───

@router.callback_query(F.data.startswith("report:send:"))
async def send_report(callback: CallbackQuery, state: FSMContext):
    """Принять жалобу с выбранной причиной и показать следующую анкету."""
    parts = callback.data.split(":")
    if len(parts) < 4:
        await callback.answer()
        return
    target_id, reason = parts[2], parts[3]

    try:
        db_user = await get_or_create_user(callback.from_user.id, "", "")
        await create_report(db_user["id"], target_id, reason)
    except Exception as e:
        logger.warning(f"Не удалось сохранить жалобу: {e}")

    await callback.answer("Жалоба отправлена")
    try:
        await callback.message.delete()
    except Exception:
        # Сообщение могло быть уже удалено или слишком старое
        pass
    await callback.message.answer(T.REPORT_SENT)

    try:
        db_user = await get_or_create_user(callback.from_user.id, "", "")
        await _show_next_from_deck(callback.message, db_user["id"], state)
    except Exception as e:
        logger.warning(f"Не удалось показать следующую анкету после жалобы: {e}")


@router.callback_query(F.data.startswith("block:"))
async def block_from_deck(callback: CallbackQuery, state: FSMContext):
    """Заблокировать навсегда и показать следующую анкету.

    Жалоба уходит модератору и решается не сразу, а блокировка нужна
    человеку немедленно — поэтому это отдельное действие.
    """
    target_id = callback.data.split(":", 1)[-1]

    try:
        db_user = await get_or_create_user(callback.from_user.id, "", "")
        await block_user(db_user["id"], target_id)
    except Exception as e:
        logger.warning(f"Не удалось заблокировать пользователя: {e}")
        await callback.answer(T.ERROR_GENERIC, show_alert=True)
        return

    await callback.answer("Заблокировано")
    try:
        await callback.message.delete()
    except Exception:
        pass
    await callback.message.answer(T.BLOCK_DONE)

    try:
        await _show_next_from_deck(callback.message, db_user["id"], state)
    except Exception as e:
        logger.warning(f"Не удалось показать следующую анкету после блокировки: {e}")


@router.callback_query(F.data.startswith("report:"), ~F.data.startswith("report:send:"))
async def ask_report_reason(callback: CallbackQuery):
    """Спросить причину жалобы."""
    target_id = callback.data.split(":", 1)[-1]
    await callback.answer()
    await callback.message.answer(
        "Что не так с этой анкетой?", reply_markup=report_reasons_kb(target_id)
    )


# ── Пауза просмотра ─────────────────────────────────────────────

@router.callback_query(F.data == "dating:stop")
async def stop_dating(callback: CallbackQuery, state: FSMContext):
    """«Хватит на сегодня» — выйти из просмотра в меню."""
    await state.clear()
    await callback.answer()
    await callback.message.answer(
        "Хорошо, на сегодня достаточно 🌙\n\nЗаходите, когда захотите.",
        reply_markup=main_kb(),
    )


@router.callback_query(F.data == "dating:next")
async def next_profile(callback: CallbackQuery, state: FSMContext):
    """Пропустить без действия — например, после отмены жалобы."""
    await callback.answer()
    try:
        db_user = await get_or_create_user(callback.from_user.id, "", "")
        await _show_next_from_deck(callback.message, db_user["id"], state)
    except Exception as e:
        logger.warning(f"Не удалось показать следующую анкету: {e}")
        await callback.message.answer(T.ERROR_GENERIC)
