"""Мэтчи и чат внутри бота.

Колбэки `profile:view` и `menu` живут в handlers/account.py: этот роутер
подключается позже, поэтому дубли здесь были бы недостижимым кодом —
aiogram останавливается на первом совпавшем обработчике.
"""

from __future__ import annotations

import logging

from aiogram import Router, F
from aiogram.types import CallbackQuery, Message
from aiogram.fsm.context import FSMContext

from database import (
    get_or_create_user,
    get_profile,
    get_user_matches,
    get_match_partner,
)
from keyboards import matches_list_kb, chat_kb, main_kb
from services.moderation import moderate_text, humanize
from states import ChatStates
from texts import chat_header
from utils import safe_edit_text

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
        await safe_edit_text(
            callback.message,
            "💕 Пока нет мэтчей. Продолжайте ставить 👍!\n\n"
            "Чем больше анкет вы посмотрите — тем выше шанс найти того самого.",
            reply_markup=main_kb(),
        )
        return

    # Имена собеседников приходят вместе с мэтчами: раньше здесь стоял цикл
    # с `get_profile` на каждый, и каждый вызов брал свою сессию из пула
    await safe_edit_text(
        callback.message,
        f"💕 <b>Ваши мэтчи ({len(matches)}):</b>\n\nВыберите мэтч для начала чата:",
        reply_markup=matches_list_kb(matches),
    )


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

    await safe_edit_text(
        callback.message,
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

    # Личка — самый объёмный канал контента, и через бота он шёл вообще без
    # проверки: тот же текст из мини-аппа модерируется (api/routers/chat.py),
    # а отсюда попадал собеседнику как есть. Заблокировать отправителя тот
    # может, но сообщение уже прочитано
    verdict = await moderate_text(text.strip())
    if verdict.get("blocked"):
        await message.answer(
            f"Сообщение не отправлено: {humanize(verdict.get('reason', ''))}"
        )
        return

    # Store message via API or directly in DB
    from database.connection import _session_cls
    from database.models import Message as MsgModel

    db_user = await get_or_create_user(
        message.from_user.id,
        message.from_user.username or "",
        message.from_user.first_name or "",
    )

    # Отправитель обязан быть участником живого мэтча (IDOR-защита)
    partner_profile = await get_match_partner(match_id, db_user["id"])
    if not partner_profile:
        await state.clear()
        await message.answer("⚠️ Этот чат недоступен.", reply_markup=main_kb())
        return

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
            msg_id = msg.id
            msg_created = msg.created_at.isoformat() if msg.created_at else None

    # Publish via Redis for real-time sync (web получит мгновенно)
    from services.redis_subscriber import publish_message_event, _notify_user_about_message
    await publish_message_event(match_id, db_user["id"], text.strip(), msg_id, msg_created)

    # И прямое уведомление партнёру в Telegram (web-сокет может быть закрыт)
    try:
        await _notify_user_about_message(
            message.bot, partner_profile["user_id"], db_user["id"], text.strip(),
        )
    except Exception as e:
        logger.warning(f"Partner TG notify failed: {e}")

    await message.answer("✅ Сообщение отправлено!")

    # Return to chat menu
    partner_name = partner_profile.get("display_name", "Партнёр")

    await state.set_state(ChatStates.in_chat)
    await message.answer(
        chat_header(partner_name),
        reply_markup=chat_kb(match_id),
    )


@router.callback_query(F.data.startswith("chat:hint:"))
async def chat_hint(callback: CallbackQuery):
    """Подсказка для первого сообщения (по общим интересам)."""
    match_id = callback.data.split(":")[-1]
    db_user = await get_or_create_user(
        callback.from_user.id,
        callback.from_user.username or "",
        callback.from_user.first_name or "",
    )

    partner = await get_match_partner(match_id, db_user["id"])
    me = await get_profile(db_user["id"])

    common = []
    if partner and me:
        common = list(set(partner.get("interests") or []) & set(me.get("interests") or []))

    if common:
        hint = (
            f"⚡ У вас общие интересы: <b>{', '.join(common[:3])}</b>.\n\n"
            f"Попробуйте начать с вопроса про «{common[0]}» — например, "
            f"как {partner.get('display_name', 'собеседник')} к этому пришёл(ла)."
        )
    elif partner and partner.get("bio"):
        hint = (
            "⚡ Зацепитесь за био собеседника:\n\n"
            f"«{partner['bio'][:150]}»\n\n"
            "Задайте открытый вопрос по нему — это работает лучше «привет»."
        )
    else:
        hint = (
            "⚡ Начните с открытого вопроса: «Как бы ты провёл(а) идеальный "
            "выходной?» — отвечать на такое интереснее, чем на «привет»."
        )

    await callback.answer()
    await callback.message.answer(hint, reply_markup=chat_kb(match_id))
