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
from keyboards import matches_list_kb, chat_kb, main_kb, limit_reached_kb
from services.enforcement import (
    TEXT_BAN_REASONS,
    answer_ban_screen,
    apply_text_strike,
    strike_suffix,
)
from services.moderation import moderate_text, humanize
from states import ChatStates
from texts import MATCH_LOCKED_SHORT, chat_header, match_limit_reached
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
    """Открыть чат с мэтчем.

    Это и есть «открытие мэтча» в смысле суточного лимита — здесь тратится
    слот (`spend=True`). Именно открытие, а не показ списка: заход в «Мои
    мэтчи» иначе сжигал бы всю квоту сразу.
    """
    match_id = callback.data.split(":")[-1]
    db_user = await get_or_create_user(
        callback.from_user.id,
        callback.from_user.username or "",
        callback.from_user.first_name or "",
    )

    partner_profile = await get_match_partner(match_id, db_user["id"], spend=True)

    if partner_profile and partner_profile.get("locked"):
        # Состояние чата не ставим: писать в закрытый мэтч нельзя, а
        # оставленный ChatStates.in_chat пустил бы туда следующее сообщение
        await state.clear()
        await callback.answer(MATCH_LOCKED_SHORT, show_alert=False)
        await safe_edit_text(
            callback.message,
            match_limit_reached(
                partner_profile["limit"], partner_profile["reset_at"]
            ),
            reply_markup=limit_reached_kb("matches:list"),
        )
        return

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

    # Пользователь нужен ДО модерации: нарушение пишется в журнал страйков
    # на его id (тип "chat_message" — как у API в routers/chat.py)
    db_user = await get_or_create_user(
        message.from_user.id,
        message.from_user.username or "",
        message.from_user.first_name or "",
    )

    # Личка — самый объёмный канал контента, и через бота он шёл вообще без
    # проверки: тот же текст из мини-аппа модерируется (api/routers/chat.py),
    # а отсюда попадал собеседнику как есть. Заблокировать отправителя тот
    # может, но сообщение уже прочитано
    verdict = await moderate_text(text.strip())
    исход = await apply_text_strike(
        db_user["id"], "chat_message", text.strip(), verdict
    )
    if verdict.get("blocked"):
        if исход is not None and исход.banned:
            await answer_ban_screen(
                message, TEXT_BAN_REASONS[исход.category], исход.banned_until
            )
            return
        await message.answer(
            f"Сообщение не отправлено: {humanize(verdict.get('reason', ''))}"
            + strike_suffix(исход)
        )
        return

    # Store message via API or directly in DB
    from database.connection import _session_cls
    from database.models import Message as MsgModel

    # Отправитель обязан быть участником живого мэтча (IDOR-защита)
    partner_profile = await get_match_partner(match_id, db_user["id"])
    if not partner_profile:
        await state.clear()
        await message.answer("⚠️ Этот чат недоступен.", reply_markup=main_kb())
        return

    if partner_profile.get("locked"):
        # Состояние могло остаться с прошлого сеанса — до того, как квота
        # кончилась. Проверяем и здесь: без этого сообщение уходило бы в
        # закрытый чат, то есть лимит обходился бы одним старым состоянием.
        # Слот не тратим (`spend` по умолчанию False): отправка — не открытие.
        await state.clear()
        await message.answer(
            match_limit_reached(
                partner_profile["limit"], partner_profile["reset_at"]
            ),
            reply_markup=limit_reached_kb("matches:list"),
        )
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

    if partner and partner.get("locked"):
        # Подсказка строится по интересам и био партнёра — для закрытого мэтча
        # это тот же слив, что и имя. Кнопка достижима со старого сообщения,
        # поэтому проверка нужна и здесь, а не только на открытии чата.
        await callback.answer(MATCH_LOCKED_SHORT, show_alert=False)
        await callback.message.answer(
            match_limit_reached(partner["limit"], partner["reset_at"]),
            reply_markup=limit_reached_kb("matches:list"),
        )
        return

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
