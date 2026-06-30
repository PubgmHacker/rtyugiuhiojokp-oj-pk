from __future__ import annotations

import json
import logging

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext

from config import BANNERS, SITE_URL
from database import get_or_create_user, get_profile, get_deck_profiles, create_like, check_mutual_like
from keyboards import dating_action_kb, main_kb
from states import DatingStates
from texts import profile_card, no_more_profiles, match_notification
from services.redis_subscriber import publish_match_event

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

    # Try to send with photo
    photo = None
    photos = profile.get("photos", [])
    if photos and isinstance(photos, list) and photos:
        # If photos are URLs, use first one
        if isinstance(photos[0], str) and photos[0].startswith("http"):
            photo = photos[0]
        else:
            photo = BANNERS["deck"]

    kb = dating_action_kb(profile["user_id"])

    if photo:
        try:
            await message.answer_photo(photo=photo, caption=caption, reply_markup=kb)
        except Exception:
            await message.answer(caption, reply_markup=kb)
    else:
        await message.answer(caption, reply_markup=kb)


@router.callback_query(DatingStates.viewing_profile, F.data.startswith("like:"))
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
    await create_like(db_user["id"], target_id, like_type)

    if action == "pass":
        await callback.answer("👎 Пропущено")
        # Delete current profile message and show next
        try:
            await callback.message.delete()
        except Exception:
            pass
        await _show_next_from_deck(callback.message, db_user["id"], state)

    elif action == "message":
        await callback.answer("💌 Функция 'написать' — скоро!", show_alert=True)

    elif action == "like":
        # Check mutual
        result = await check_mutual_like(db_user["id"], target_id)
        if result and result.get("mutual"):
            await callback.answer("🎉 Это мэтч!", show_alert=True)
            # Get partner profile for notification
            partner = await get_profile(target_id)
            await callback.message.answer_photo(
                photo=BANNERS["match"],
                caption=match_notification(partner or {}),
                reply_markup=main_kb(),
            )
        else:
            await callback.answer("👍 Понравилось!")
            try:
                await callback.message.delete()
            except Exception:
                pass
            await _show_next_from_deck(callback.message, db_user["id"], state)


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
