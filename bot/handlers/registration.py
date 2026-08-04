"""Регистрация анкеты.

Порядок как в «Дайвинчике» — минимум трения:
имя → возраст → пол → кого ищем → город → фото → о себе.

Что здесь важно:
* с любого шага можно вернуться назад;
* неожидаемый тип сообщения не выбивает из состояния, а вызывает подсказку;
* фото и текст проходят модерацию до сохранения (раньше бот её обходил).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext

from config import BANNERS
from database import get_or_create_user, update_profile, set_profile_ready, get_profile
from keyboards import (
    main_kb,
    reg_gender_kb,
    reg_looking_kb,
    reg_goal_kb,
    reg_back_kb,
    reg_city_kb,
    reg_photo_kb,
    reg_bio_kb,
    remove_kb,
)
from services.moderation import moderate_image, moderate_text, humanize
from states import RegistrationStates
import texts as T

logger = logging.getLogger(__name__)
router = Router()

MAX_PHOTOS = 6


# ── Навигация по шагам ──────────────────────────────────────────

async def ask_name(message: Message, state: FSMContext) -> None:
    await state.set_state(RegistrationStates.waiting_name)
    await message.answer(T.reg_step("name"), reply_markup=remove_kb())


async def ask_age(message: Message, state: FSMContext) -> None:
    await state.set_state(RegistrationStates.waiting_age)
    await message.answer(T.reg_step("age"), reply_markup=reg_back_kb("name"))


async def ask_gender(message: Message, state: FSMContext) -> None:
    await state.set_state(RegistrationStates.waiting_gender)
    await message.answer(T.reg_step("gender"), reply_markup=reg_gender_kb())


async def ask_looking_for(message: Message, state: FSMContext) -> None:
    await state.set_state(RegistrationStates.waiting_looking_for)
    await message.answer(T.reg_step("looking_for"), reply_markup=reg_looking_kb())


async def ask_goal(message: Message, state: FSMContext) -> None:
    await state.set_state(RegistrationStates.waiting_goal)
    await message.answer(T.reg_step("goal"), reply_markup=reg_goal_kb())


async def ask_city(message: Message, state: FSMContext) -> None:
    await state.set_state(RegistrationStates.waiting_city)
    # Reply-клавиатура с геопозицией и inline-кнопка «Назад» не сочетаются
    # в одном сообщении, поэтому отправляем двумя
    await message.answer(T.reg_step("city"), reply_markup=reg_city_kb())
    await message.answer(
        "Если хотите вернуться:", reply_markup=reg_back_kb("goal")
    )


async def ask_photo(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    await state.set_state(RegistrationStates.waiting_photo)
    await message.answer(
        T.reg_step("photo"), reply_markup=reg_photo_kb(bool(data.get("reg_photos")))
    )


async def ask_bio(message: Message, state: FSMContext) -> None:
    await state.set_state(RegistrationStates.waiting_bio)
    await message.answer(T.reg_step("bio"), reply_markup=reg_bio_kb())


_STEP_ASK = {
    "name": ask_name,
    "age": ask_age,
    "gender": ask_gender,
    "looking_for": ask_looking_for,
    "goal": ask_goal,
    "city": ask_city,
    "photo": ask_photo,
    "bio": ask_bio,
}


@router.callback_query(F.data.startswith("reg:back:"))
async def go_back(callback: CallbackQuery, state: FSMContext):
    """Возврат на предыдущий шаг."""
    step = callback.data.rsplit(":", 1)[-1]
    handler = _STEP_ASK.get(step)
    await callback.answer()
    if handler:
        await handler(callback.message, state)


# ── Старт ───────────────────────────────────────────────────────

@router.callback_query(F.data == "profile:edit")
async def start_registration(callback: CallbackQuery, state: FSMContext):
    """Начать заполнение анкеты.

    Уже заполненные поля кладём в state: тот, кто правит только город,
    не должен вводить всё остальное заново.
    """
    await state.clear()
    await callback.answer()

    profile: dict = {}
    try:
        db_user = await get_or_create_user(
            callback.from_user.id,
            callback.from_user.username or "",
            callback.from_user.first_name or "",
        )
        profile = await get_profile(db_user["id"]) or {}
    except Exception as e:
        logger.warning(f"Не удалось загрузить профиль перед правкой: {e}")

    if profile:
        await state.update_data(
            reg_name=profile.get("display_name") or "",
            reg_age=profile.get("age"),
            reg_gender=profile.get("gender"),
            reg_looking_for=profile.get("looking_for"),
            reg_goal=profile.get("goal") or "",
            reg_city=profile.get("city") or "",
            reg_photos=list(profile.get("photos") or []),
            reg_bio=profile.get("bio") or "",
        )

    await ask_name(callback.message, state)


# ── Имя ─────────────────────────────────────────────────────────

@router.message(RegistrationStates.waiting_name, F.text)
async def process_name(message: Message, state: FSMContext):
    name = (message.text or "").strip()
    if len(name) < 2:
        await message.answer(T.REG_NAME_TOO_SHORT)
        return
    await state.update_data(reg_name=name[:50])
    await ask_age(message, state)


@router.message(RegistrationStates.waiting_name)
async def name_wrong_type(message: Message):
    await message.answer(T.REG_EXPECT_TEXT)


# ── Возраст ─────────────────────────────────────────────────────

@router.message(RegistrationStates.waiting_age, F.text)
async def process_age(message: Message, state: FSMContext):
    raw = (message.text or "").strip()
    if not raw.isdigit():
        await message.answer(T.REG_AGE_INVALID)
        return

    age = int(raw)
    if age < 18:
        await message.answer(T.REG_AGE_TOO_YOUNG)
        return
    if age > 99:
        await message.answer(T.REG_AGE_TOO_OLD)
        return

    await state.update_data(reg_age=age)
    await ask_gender(message, state)


@router.message(RegistrationStates.waiting_age)
async def age_wrong_type(message: Message):
    await message.answer(T.REG_EXPECT_TEXT)


# ── Пол ─────────────────────────────────────────────────────────

@router.callback_query(
    RegistrationStates.waiting_gender, F.data.startswith("reg:gender:")
)
async def process_gender(callback: CallbackQuery, state: FSMContext):
    await state.update_data(reg_gender=callback.data.rsplit(":", 1)[-1])
    await callback.answer()
    await ask_looking_for(callback.message, state)


@router.message(RegistrationStates.waiting_gender)
async def gender_wrong_type(message: Message):
    await message.answer(T.REG_EXPECT_BUTTON)


# ── Кого ищем ───────────────────────────────────────────────────

@router.callback_query(
    RegistrationStates.waiting_looking_for, F.data.startswith("reg:looking:")
)
async def process_looking_for(callback: CallbackQuery, state: FSMContext):
    await state.update_data(reg_looking_for=callback.data.rsplit(":", 1)[-1])
    await callback.answer()
    await ask_goal(callback.message, state)


@router.message(RegistrationStates.waiting_looking_for)
async def looking_wrong_type(message: Message):
    await message.answer(T.REG_EXPECT_BUTTON)


# ── Цель знакомства ─────────────────────────────────────────────

@router.callback_query(RegistrationStates.waiting_goal, F.data.startswith("reg:goal:"))
async def process_goal(callback: CallbackQuery, state: FSMContext):
    # «Пока не решил» присылает пустое значение — это законный ответ,
    # он означает «показывать всем, независимо от цели»
    await state.update_data(reg_goal=callback.data.rsplit(":", 1)[-1])
    await callback.answer()
    await ask_city(callback.message, state)


@router.message(RegistrationStates.waiting_goal)
async def goal_wrong_type(message: Message):
    await message.answer(T.REG_EXPECT_BUTTON)


# ── Город ───────────────────────────────────────────────────────

@router.message(RegistrationStates.waiting_city, F.location)
async def process_city_location(message: Message, state: FSMContext):
    """Геопозиция: сохраняем координаты, название города ищем по ним."""
    loc = message.location
    await state.update_data(reg_lat=loc.latitude, reg_lon=loc.longitude)

    city = await _reverse_geocode(loc.latitude, loc.longitude)
    if city:
        await state.update_data(reg_city=city)
        await message.answer(
            f"Определил город: <b>{city}</b> 📍", reply_markup=remove_kb()
        )
        await ask_photo(message, state)
        return

    # Название не определилось, но координаты уже сохранены
    await message.answer(
        "Координаты сохранил, а название города не определилось. "
        "Напишите его, пожалуйста, вручную.",
        reply_markup=remove_kb(),
    )


@router.message(RegistrationStates.waiting_city, F.text)
async def process_city_text(message: Message, state: FSMContext):
    city = (message.text or "").strip()
    if len(city) < 2:
        await message.answer("Напишите, пожалуйста, название города.")
        return
    await state.update_data(reg_city=city[:100])
    await message.answer(f"Город: <b>{city[:100]}</b>", reply_markup=remove_kb())
    await ask_photo(message, state)


@router.message(RegistrationStates.waiting_city)
async def city_wrong_type(message: Message):
    await message.answer(T.REG_EXPECT_TEXT)


async def _reverse_geocode(lat: float, lon: float) -> str:
    """Название города по координатам. Сбой не критичен — вернём пустую строку."""
    try:
        import aiohttp

        params = {
            "lat": f"{lat:.5f}",
            "lon": f"{lon:.5f}",
            "format": "json",
            "zoom": "10",
            "accept-language": "ru",
        }
        headers = {"User-Agent": "Souldawn-Dating-Bot/1.0 (support@souldawn.app)"}
        timeout = aiohttp.ClientTimeout(total=6)
        async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
            async with session.get(
                "https://nominatim.openstreetmap.org/reverse", params=params
            ) as resp:
                if resp.status != 200:
                    return ""
                data = await resp.json()
        addr = data.get("address") or {}
        for key in ("city", "town", "village", "municipality", "state"):
            if addr.get(key):
                return str(addr[key])[:100]
    except Exception as e:
        logger.info(f"Обратное геокодирование не удалось: {e}")
    return ""


# ── Фото ────────────────────────────────────────────────────────

@router.message(RegistrationStates.waiting_photo, F.photo)
async def process_photo(message: Message, state: FSMContext):
    data = await state.get_data()
    photos: list[str] = list(data.get("reg_photos") or [])

    if len(photos) >= MAX_PHOTOS:
        await message.answer(T.REG_PHOTO_LIMIT)
        await ask_bio(message, state)
        return

    photo = message.photo[-1]  # самое большое разрешение

    # Скачиваем один раз: байты нужны и модерации, и загрузке в R2
    buf: bytes = b""
    try:
        file = await message.bot.get_file(photo.file_id)
        downloaded = await message.bot.download_file(file.file_path)
        buf = downloaded.read()
    except Exception as e:
        logger.warning(f"Не удалось скачать фото из Telegram: {e}")

    if buf:
        verdict = await moderate_image(buf)
        if verdict.get("blocked"):
            await message.answer(
                T.REG_PHOTO_REJECTED.format(reason=humanize(verdict.get("reason", "")))
            )
            return

    # Перезаливаем в R2, чтобы фото было видно в вебе и в iOS-приложении;
    # если хранилище не настроено, остаётся file_id — бот его покажет
    stored = photo.file_id
    if buf:
        try:
            from services.r2_storage import upload_photo as r2_upload

            db_user = await get_or_create_user(
                message.from_user.id,
                message.from_user.username or "",
                message.from_user.first_name or "",
            )
            url = await r2_upload(db_user["id"], buf)
            if url:
                stored = url
        except Exception as e:
            logger.warning(f"Перезаливка фото в R2 не удалась: {e}")

    photos.append(stored)
    await state.update_data(reg_photos=photos)

    if len(photos) >= MAX_PHOTOS:
        await message.answer(T.REG_PHOTO_LIMIT)
        await ask_bio(message, state)
        return

    await message.answer(
        T.REG_PHOTO_ADDED.format(count=len(photos)),
        reply_markup=reg_photo_kb(True),
    )


@router.callback_query(RegistrationStates.waiting_photo, F.data == "reg:photo_done")
async def photo_done(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    if not data.get("reg_photos"):
        await callback.answer(T.REG_PHOTO_NEED_ONE, show_alert=True)
        return
    await callback.answer()
    await ask_bio(callback.message, state)


@router.message(RegistrationStates.waiting_photo)
async def photo_wrong_type(message: Message):
    await message.answer(T.REG_EXPECT_PHOTO)


# ── О себе ──────────────────────────────────────────────────────

@router.message(RegistrationStates.waiting_bio, F.text)
async def process_bio(message: Message, state: FSMContext):
    bio = (message.text or "").strip()[:500]

    if bio:
        verdict = await moderate_text(bio)
        if verdict.get("blocked"):
            await message.answer(
                T.REG_BIO_REJECTED.format(reason=humanize(verdict.get("reason", "")))
            )
            return

    await state.update_data(reg_bio=bio)
    await _finish_registration(message, state)


@router.callback_query(RegistrationStates.waiting_bio, F.data == "reg:bio_skip")
async def skip_bio(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.update_data(reg_bio="")
    await _finish_registration(callback.message, state)


@router.message(RegistrationStates.waiting_bio)
async def bio_wrong_type(message: Message):
    await message.answer(T.REG_EXPECT_TEXT)


# ── Сохранение ──────────────────────────────────────────────────

async def _finish_registration(message: Message, state: FSMContext):
    """Сохранить анкету и вернуть человека в меню."""
    data = await state.get_data()

    try:
        # message может принадлежать боту (после callback), поэтому
        # идентифицируем пользователя по chat.id, а не by from_user
        db_user = await get_or_create_user(message.chat.id, "", data.get("reg_name", ""))

        fields: dict = {
            "display_name": data.get("reg_name", ""),
            "gender": data.get("reg_gender", "other"),
            "city": data.get("reg_city", ""),
            "bio": data.get("reg_bio", ""),
            "looking_for": data.get("reg_looking_for", "any"),
            "goal": data.get("reg_goal", ""),
            "photos": data.get("reg_photos", []),
        }

        age = data.get("reg_age")
        if age:
            # Точный день рождения не спрашиваем: для подбора по возрасту
            # достаточно года
            fields["birth_date"] = datetime(
                datetime.now(timezone.utc).year - int(age), 1, 1
            )

        if data.get("reg_lat") is not None and data.get("reg_lon") is not None:
            fields["latitude"] = data["reg_lat"]
            fields["longitude"] = data["reg_lon"]

        await update_profile(db_user["id"], **fields)
        await set_profile_ready(db_user["id"])
    except Exception as e:
        logger.exception(f"Не удалось сохранить анкету: {e}")
        await message.answer(T.ERROR_GENERIC)
        return

    await state.clear()
    try:
        await message.answer_photo(
            photo=BANNERS["welcome"], caption=T.REG_DONE, reply_markup=main_kb()
        )
    except Exception:
        # Баннер может не загрузиться — текст важнее картинки
        await message.answer(T.REG_DONE, reply_markup=main_kb())
