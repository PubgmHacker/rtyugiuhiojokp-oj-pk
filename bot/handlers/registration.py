from __future__ import annotations

import json
import logging
from datetime import datetime

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext

from config import BANNERS
from database import get_or_create_user, update_profile, set_profile_ready, get_profile
from keyboards import reg_gender_kb, reg_looking_kb, skip_kb, main_kb
from states import RegistrationStates
from texts import reg_step

logger = logging.getLogger(__name__)
router = Router()


@router.callback_query(F.data == "profile:edit")
async def start_registration(callback: CallbackQuery, state: FSMContext):
    """Начать/перезапустить создание анкеты."""
    await state.clear()
    await callback.answer()
    await callback.message.answer(reg_step("name"))
    await state.set_state(RegistrationStates.waiting_name)


@router.message(RegistrationStates.waiting_name)
async def process_name(message: Message, state: FSMContext):
    name = message.text or message.from_user.first_name or "Аноним"
    await state.update_data(reg_name=name[:50])
    await message.answer(reg_step("gender"), reply_markup=reg_gender_kb())
    await state.set_state(RegistrationStates.waiting_gender)


@router.callback_query(RegistrationStates.waiting_gender, F.data.startswith("reg:gender:"))
async def process_gender(callback: CallbackQuery, state: FSMContext):
    gender = callback.data.split(":")[-1]
    await state.update_data(reg_gender=gender)
    await callback.message.edit_text(reg_step("age"))
    await state.set_state(RegistrationStates.waiting_age)


@router.message(RegistrationStates.waiting_age)
async def process_age(message: Message, state: FSMContext):
    try:
        age = int(message.text.strip())
        if age < 18 or age > 99:
            raise ValueError
    except (ValueError, AttributeError):
        await message.answer("Введите число от 18 до 99:")
        return

    await state.update_data(reg_age=age)
    await message.answer(reg_step("city"))
    await state.set_state(RegistrationStates.waiting_city)


@router.message(RegistrationStates.waiting_city)
async def process_city(message: Message, state: FSMContext):
    city = (message.text or "Не указан")[:100]
    await state.update_data(reg_city=city)
    await message.answer(reg_step("bio"))
    await state.set_state(RegistrationStates.waiting_bio)


@router.message(RegistrationStates.waiting_bio)
async def process_bio(message: Message, state: FSMContext):
    bio = (message.text or "")[:500]
    await state.update_data(reg_bio=bio)
    await message.answer(reg_step("looking_for"), reply_markup=reg_looking_kb())
    await state.set_state(RegistrationStates.waiting_looking_for)


@router.callback_query(RegistrationStates.waiting_looking_for, F.data.startswith("reg:looking:"))
async def process_looking_for(callback: CallbackQuery, state: FSMContext):
    looking = callback.data.split(":")[-1]
    await state.update_data(reg_looking_for=looking)
    await callback.message.edit_text(
        reg_step("photo"),
        reply_markup=skip_kb(),
    )
    await state.set_state(RegistrationStates.waiting_photo)


@router.message(RegistrationStates.waiting_photo, F.photo)
async def process_photo(message: Message, state: FSMContext):
    data = await state.get_data()
    photos = data.get("reg_photos", [])

    if len(photos) >= 6:
        await message.answer("Максимум 6 фото. Отправьте /skip чтобы продолжить.")
        return

    # Get highest resolution photo
    photo = message.photo[-1]
    photos.append(photo.file_id)
    await state.update_data(reg_photos=photos)
    count = len(photos)
    await message.answer(f"📸 Фото {count}/6 добавлено. Отправьте ещё или /skip")
    if count >= 6:
        await message.answer("Максимум фото достигнут!")
        await _finish_registration(message, state)


@router.callback_query(RegistrationStates.waiting_photo, F.data == "reg:skip_photo")
async def skip_photo(callback: CallbackQuery, state: FSMContext):
    await callback.message.answer(reg_step("interests"))
    await state.set_state(RegistrationStates.waiting_interests)


@router.message(RegistrationStates.waiting_photo, F.text == "/skip")
async def skip_photo_cmd(message: Message, state: FSMContext):
    await message.answer(reg_step("interests"))
    await state.set_state(RegistrationStates.waiting_interests)


@router.message(RegistrationStates.waiting_interests)
async def process_interests(message: Message, state: FSMContext):
    interests_raw = message.text or ""
    interests = [x.strip()[:30] for x in interests_raw.replace(",", "\n").replace(";", "\n").split("\n") if x.strip()][:10]
    await state.update_data(reg_interests=interests)
    await _finish_registration(message, state)


async def _finish_registration(message: Message, state: FSMContext):
    """Save all registration data to DB."""
    data = await state.get_data()
    db_user = await get_or_create_user(
        message.from_user.id,
        message.from_user.username or "",
        data.get("reg_name", ""),
    )

    # Save profile
    await update_profile(
        db_user["id"],
        display_name=data.get("reg_name", ""),
        gender=data.get("reg_gender", "other"),
        birth_date=datetime(datetime.now().year - (data.get("reg_age", 25)), 1, 1) if data.get("reg_age") else None,
        city=data.get("reg_city", ""),
        bio=data.get("reg_bio", ""),
        looking_for=data.get("reg_looking_for", "any"),
        photos=data.get("reg_photos", []),
        interests=data.get("reg_interests", []),
    )

    await set_profile_ready(db_user["id"])

    await state.clear()
    await message.answer_photo(
        photo=BANNERS["welcome"],
        caption=(
            "✅ **Анкета создана!**\n\n"
            "Теперь вы можете смотреть анкеты и находить мэтчи.\n"
            "Нажмите /start чтобы перейти в меню."
        ),
        reply_markup=main_kb(),
    )
