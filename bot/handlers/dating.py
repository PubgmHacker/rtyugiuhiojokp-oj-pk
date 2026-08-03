from __future__ import annotations

import json
import logging

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext

from config import BANNERS, SITE_URL
from database import (
    get_or_create_user, get_profile, get_deck_profiles,
    create_like, check_mutual_like, create_match, get_user_by_id,
    create_report,
)
from keyboards import dating_action_kb, main_kb, profile_kb, report_reasons_kb
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
        await message.answer_photo(
            photo=BANNERS["menu"],
            caption=no_more_profiles(),
            reply_markup=main_kb(),
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
        await callback.answer("💌 Напишите после мэтча — поставьте 👍!", show_alert=True)
        return

    # Пользователь в середине заполнения анкеты (лайк из старого уведомления):
    # лайк засчитываем, но не трогаем FSM-состояние регистрации
    current_state = await state.get_state()
    in_registration = bool(current_state and current_state.startswith("RegistrationStates"))

    await create_like(db_user["id"], target_id, like_type)

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

    # action == "like"
    result = await check_mutual_like(db_user["id"], target_id)
    if result and result.get("mutual"):
        # Взаимно: создаём мэтч и уведомляем обоих напрямую.
        # publish_match_event тут НЕ зовём — его слушает этот же бот,
        # и оба пользователя получили бы уведомления дважды.
        match = await create_match(db_user["id"], target_id)
        await callback.answer("🎉 Это мэтч!", show_alert=True)

        # Убираем карточку с «живыми» кнопками (повторные тапы = спам)
        try:
            await callback.message.delete()
        except Exception:
            pass

        partner = await get_profile(target_id)
        await callback.message.answer_photo(
            photo=BANNERS["match"],
            caption=match_notification(partner or {}),
            reply_markup=main_kb(),
        )

        # Уведомляем партнёра в Telegram
        partner_user = await get_user_by_id(target_id)
        if partner_user and partner_user.get("telegram_id"):
            my_profile = await get_profile(db_user["id"])
            try:
                await callback.bot.send_photo(
                    chat_id=partner_user["telegram_id"],
                    photo=BANNERS["match"],
                    caption=match_notification(my_profile or {}),
                    reply_markup=main_kb(),
                )
            except Exception as e:
                logger.warning(f"Failed to notify match partner: {e}")

        # Продолжаем показ анкет
        if not in_registration:
            await _show_next_from_deck(callback.message, db_user["id"], state)
    else:
        await callback.answer("👍 Понравилось!")
        # Дайвинчик-механика: показываем партнёру анкету лайкнувшего
        partner_user = await get_user_by_id(target_id)
        if partner_user and partner_user.get("telegram_id"):
            my_profile = await get_profile(db_user["id"])
            if my_profile and my_profile.get("display_name"):
                try:
                    await callback.bot.send_message(
                        chat_id=partner_user["telegram_id"],
                        text="💌 Вы кому-то понравились! Взгляните на анкету:",
                    )
                    await _render_profile_to_chat(
                        callback.bot, partner_user["telegram_id"], my_profile,
                    )
                except Exception as e:
                    logger.warning(f"Failed to notify liked user: {e}")

        try:
            await callback.message.delete()
        except Exception:
            pass
        if not in_registration:
            await _show_next_from_deck(callback.message, db_user["id"], state)


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
