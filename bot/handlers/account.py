"""Служебные команды: меню, анкета, пауза, удаление аккаунта, справка.

Команды работают из любого состояния FSM: человек не должен застревать
посреди регистрации без выхода. Роутер подключается первым, поэтому его
обработчики перехватывают команды раньше шагов анкеты.
"""

from __future__ import annotations

import logging

from aiogram import Router, F
from aiogram.filters import Command, StateFilter
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from aiogram.fsm.context import FSMContext

from database import (
    get_or_create_user,
    get_profile,
    set_profile_hidden,
    is_profile_hidden,
    delete_user_account,
)
from keyboards import (
    main_kb,
    profile_kb,
    delete_confirm_kb,
    back_kb,
    remove_kb,
)
from states import DeleteStates
import texts as T

logger = logging.getLogger(__name__)
router = Router()


def _fill_profile_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Заполнить анкету", callback_data="profile:edit")]
        ]
    )


async def _user_id(message: Message) -> str:
    db_user = await get_or_create_user(
        message.from_user.id,
        message.from_user.username or "",
        message.from_user.first_name or "",
    )
    return db_user["id"]


# ── Меню и справка ──────────────────────────────────────────────

@router.message(StateFilter("*"), Command("menu"))
async def cmd_menu(message: Message, state: FSMContext):
    await state.clear()
    profile = await get_profile(await _user_id(message))
    is_ready = bool(profile and profile.get("display_name") and profile.get("photos"))
    await message.answer(
        T.menu_text(is_ready=is_ready), reply_markup=main_kb() if is_ready else None
    )
    if not is_ready:
        await message.answer(T.NEED_PROFILE, reply_markup=_fill_profile_kb())


@router.message(StateFilter("*"), Command("help"))
async def cmd_help(message: Message, state: FSMContext):
    await message.answer(T.HELP, reply_markup=back_kb())


@router.message(StateFilter("*"), Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext):
    current = await state.get_state()
    await state.clear()
    if current:
        await message.answer(T.CANCELLED, reply_markup=main_kb())
    else:
        await message.answer(T.menu_text(is_ready=True), reply_markup=main_kb())


@router.callback_query(F.data == "menu")
async def cb_menu(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.answer()
    await callback.message.answer(T.menu_text(is_ready=True), reply_markup=main_kb())


# ── Моя анкета ──────────────────────────────────────────────────

@router.message(StateFilter("*"), Command("profile"))
async def cmd_profile(message: Message, state: FSMContext):
    await state.clear()
    await _show_profile(message)


@router.callback_query(F.data == "profile:view")
async def cb_profile(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.answer()
    await _show_profile(callback.message, telegram_id=callback.from_user.id)


async def _show_profile(message: Message, telegram_id: int | None = None):
    """Показать свою анкету так, как её видят другие."""
    tg_id = telegram_id or message.from_user.id
    try:
        db_user = await get_or_create_user(tg_id, "", "")
        profile = await get_profile(db_user["id"])
        hidden = await is_profile_hidden(db_user["id"])
    except Exception as e:
        logger.warning(f"Не удалось загрузить анкету: {e}")
        await message.answer(T.ERROR_GENERIC)
        return

    if not profile or not profile.get("display_name"):
        await message.answer(T.NEED_PROFILE, reply_markup=_fill_profile_kb())
        return

    caption = T.profile_card(profile)
    if hidden:
        caption += "\n\n💤 <i>Анкета скрыта из поиска</i>"

    photos = profile.get("photos") or []
    if photos:
        try:
            await message.answer_photo(
                photo=photos[0], caption=caption, reply_markup=profile_kb(hidden)
            )
            return
        except Exception as e:
            logger.info(f"Не удалось отправить фото анкеты: {e}")
    await message.answer(caption, reply_markup=profile_kb(hidden))


# ── Пауза показа ────────────────────────────────────────────────

@router.message(StateFilter("*"), Command("pause"))
async def cmd_pause(message: Message, state: FSMContext):
    await state.clear()
    await set_profile_hidden(await _user_id(message), True)
    await message.answer(T.PAUSED, reply_markup=main_kb())


@router.message(StateFilter("*"), Command("resume"))
async def cmd_resume(message: Message, state: FSMContext):
    await state.clear()
    await set_profile_hidden(await _user_id(message), False)
    await message.answer(T.RESUMED, reply_markup=main_kb())


@router.callback_query(F.data == "profile:pause")
async def cb_pause(callback: CallbackQuery):
    db_user = await get_or_create_user(callback.from_user.id, "", "")
    await set_profile_hidden(db_user["id"], True)
    await callback.answer("Анкета скрыта")
    await callback.message.answer(T.PAUSED, reply_markup=main_kb())


@router.callback_query(F.data == "profile:resume")
async def cb_resume(callback: CallbackQuery):
    db_user = await get_or_create_user(callback.from_user.id, "", "")
    await set_profile_hidden(db_user["id"], False)
    await callback.answer("Анкета в поиске")
    await callback.message.answer(T.RESUMED, reply_markup=main_kb())


# ── Удаление аккаунта (требование App Store) ────────────────────

@router.message(StateFilter("*"), Command("delete"))
async def cmd_delete(message: Message, state: FSMContext):
    await state.clear()
    await state.set_state(DeleteStates.confirming)
    await message.answer(T.DELETE_CONFIRM, reply_markup=delete_confirm_kb())


@router.callback_query(DeleteStates.confirming, F.data == "delete:cancel")
async def cb_delete_cancel(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.answer()
    await callback.message.answer(T.DELETE_CANCELLED, reply_markup=main_kb())


@router.message(DeleteStates.confirming, F.text)
async def confirm_delete(message: Message, state: FSMContext):
    if (message.text or "").strip() != "УДАЛИТЬ":
        await message.answer(T.DELETE_WRONG_WORD, reply_markup=delete_confirm_kb())
        return

    try:
        db_user = await get_or_create_user(message.from_user.id, "", "")
        await delete_user_account(db_user["id"])
    except Exception as e:
        logger.exception(f"Не удалось удалить аккаунт: {e}")
        await state.clear()
        await message.answer(T.ERROR_GENERIC)
        return

    await state.clear()
    await message.answer(T.DELETE_DONE, reply_markup=remove_kb())


@router.message(DeleteStates.confirming)
async def delete_wrong_type(message: Message):
    await message.answer(T.DELETE_WRONG_WORD, reply_markup=delete_confirm_kb())
