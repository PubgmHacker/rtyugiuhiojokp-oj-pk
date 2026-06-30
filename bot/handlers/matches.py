from __future__ import annotations

import logging

from aiogram import Router, F
from aiogram.types import CallbackQuery, Message
from aiogram.fsm.context import FSMContext

from config import BANNERS
from database import get_or_create_user, get_user_matches, get_match_partner, get_profile
from keyboards import matches_list_kb, chat_kb, main_kb
from states import ChatStates
from texts import chat_header

logger = logging.getLogger(__name__)
router = Router()


@router.callback_query(F.data == "matches:list")
async def list_matches(callback: CallbackQuery):
    """Показать список мэтчей."""
    db_user = await get_or_create_user(
        callback.from_user.id,
        callback.from_user.username or "",
        callback.from_user.first_name or "",
    )
    matches = await get_user_matches(db_user["id"])

    if not matches:
        await callback.message.edit_text(
            "💕 Пока нет мэтчей. Продолжайте ставить 👍!\n\n"
            "Чем больше анкет вы посмотрите — тем выше шанс найти того самого.",
            reply_markup=main_kb(),
        )
        return

    await callback.message.edit_text(
        f"💕 **Ваши мэтчи ({len(matches)}):**\n\nВыберите мэтч для начала чата:",
        reply_markup=matches_list_kb(matches),
    )


@router.callback_query(F.data == "profile:view")
async def view_profile(callback: CallbackQuery):
    """Просмотр своей анкеты."""
    db_user = await get_or_create_user(
        callback.from_user.id,
        callback.from_user.username or "",
        callback.from_user.first_name or "",
    )
    profile = await get_profile(db_user["id"])

    if not profile or not profile.get("display_name"):
        await callback.message.edit_text(
            "⚠️ Анкета не заполнена. Начните создание!",
            reply_markup=main_kb(),
        )
        return

    from texts import profile_card
    text = (
        "👤 **Ваша анкета:**\n\n"
        f"{profile_card(profile)}\n\n"
        f"{'✅ Анкета активна' if db_user.get('is_verified') else '⚠️ Заполните анкету'}"
    )

    await callback.message.edit_text(text, reply_markup=main_kb())


@router.callback_query(F.data.startswith("chat:open:"))
async def open_chat(callback: CallbackQuery, state: FSMContext):
    """Открыть чат с мэтчем."""
    match_id = callback.data.split(":")[-1]
    db_user = await get_or_create_user(
        callback.from_user.id,
        callback.from_user.username or "",
        callback.from_user.first_name or "",
    )

    partner_profile = await get_match_partner(match_id, db_user["id"])
    partner_name = partner_profile.get("display_name", "Партнёр") if partner_profile else "Партнёр"

    await state.set_state(ChatStates.in_chat)
    await state.update_data(active_match_id=match_id)

    await callback.message.edit_text(
        chat_header(partner_name),
        reply_markup=chat_kb(match_id),
    )


@router.callback_query(ChatStates.in_chat, F.data.startswith("chat:msg:"))
async def prompt_message(callback: CallbackQuery, state: FSMContext):
    """Запросить сообщение для отправки."""
    match_id = callback.data.split(":")[-1]
    await state.update_data(active_match_id=match_id)
    await callback.message.answer("✍️ Отправьте ваше сообщение:")
    await state.set_state(ChatStates.waiting_message)


@router.message(ChatStates.waiting_message)
async def send_message(message: Message, state: FSMContext):
    """Обработка отправленного сообщения."""
    data = await state.get_data()
    match_id = data.get("active_match_id")
    if not match_id:
        await state.clear()
        return

    text = message.text or ""
    if not text.strip():
        await message.answer("Сообщение не может быть пустым")
        return

    # Store message via API or directly in DB
    from database.connection import _session_cls
    from database.models import Message as MsgModel

    db_user = await get_or_create_user(
        message.from_user.id,
        message.from_user.username or "",
        message.from_user.first_name or "",
    )

    cls = _session_cls()
    async with cls() as session:
        async with session.begin():
            msg = MsgModel(
                match_id=match_id,
                sender_id=db_user["id"],
                text=text.strip(),
            )
            session.add(msg)
            await session.flush()

    # Publish via Redis for real-time sync
    from services.redis_subscriber import publish_message_event
    await publish_message_event(match_id, db_user["id"], text.strip())

    await message.answer(f"✅ Сообщение отправлено!")

    # Return to chat menu
    partner_profile = await get_match_partner(match_id, db_user["id"])
    partner_name = partner_profile.get("display_name", "Партнёр") if partner_profile else "Партнёр"

    await state.set_state(ChatStates.in_chat)
    await message.answer(
        chat_header(partner_name),
        reply_markup=chat_kb(match_id),
    )


@router.callback_query(F.data == "menu")
async def back_to_menu(callback: CallbackQuery, state: FSMContext):
    """Вернуться в главное меню."""
    await state.clear()
    db_user = await get_or_create_user(
        callback.from_user.id,
        callback.from_user.username or "",
        callback.from_user.first_name or "",
    )
    from texts import menu_text
    await callback.message.edit_text(
        menu_text(db_user.get("id", "")[:8], db_user.get("is_verified", False)),
        reply_markup=main_kb(),
    )


@router.callback_query(F.data == "settings")
async def show_settings(callback: CallbackQuery):
    await callback.message.edit_text(
        "⚙️ **Настройки**\n\n"
        "Настройки поиска и профиля доступны в Web App.",
        reply_markup=main_kb(),
    )
