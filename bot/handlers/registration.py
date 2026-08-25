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

from config import BANNERS, MAX_AGE, MIN_AGE
from database import clear_verification, get_or_create_user, update_profile, get_profile, track_event
from keyboards import (
    main_kb,
    reg_gender_kb,
    reg_looking_kb,
    reg_goal_kb,
    reg_relation_type_kb,
    reg_back_kb,
    reg_city_kb,
    reg_photo_kb,
    reg_bio_kb,
    remove_kb,
)
from services.nudges import запланировать_пуши_онбординга
from services.enforcement import (
    TEXT_BAN_REASONS,
    answer_ban_screen,
    apply_text_strike,
    log_moderation,
    strike_suffix,
)
from services.moderation import (
    humanize,
    moderate_image,
    moderate_text,
    verify_profile_photo,
)
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


async def ask_relation_type(message: Message, state: FSMContext) -> None:
    await state.set_state(RegistrationStates.waiting_relation_type)
    await message.answer(T.reg_step("relation_type"), reply_markup=reg_relation_type_kb())


async def ask_city(message: Message, state: FSMContext) -> None:
    await state.set_state(RegistrationStates.waiting_city)
    # Reply-клавиатура с геопозицией и inline-кнопка «Назад» не сочетаются
    # в одном сообщении, поэтому отправляем двумя
    await message.answer(T.reg_step("city"), reply_markup=reg_city_kb())
    await message.answer(
        "Если хотите вернуться:", reply_markup=reg_back_kb("relation_type")
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
    "relation_type": ask_relation_type,
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
            reg_relation_type=profile.get("relation_type") or "",
            reg_city=profile.get("city") or "",
            reg_photos=list(profile.get("photos") or []),
            reg_bio=profile.get("bio") or "",
        )

    await ask_name(callback.message, state)


# ── Имя ─────────────────────────────────────────────────────────

@router.message(RegistrationStates.waiting_name, F.text)
async def process_name(message: Message, state: FSMContext, db_user: dict | None = None):
    name = (message.text or "").strip()
    if len(name) < 2:
        await message.answer(T.REG_NAME_TOO_SHORT)
        return

    # Имя проверяем наравне с био: его видно в деке, в чатах и в комнатах
    # чаще, чем анкету целиком, а модерация стояла только на био — через имя
    # уходили реклама, контакты и брань
    verdict = await moderate_text(name)
    # db_user кладёт RegistrationMiddleware; тип записи — "display_name",
    # как у API (routers/profiles.py): счёт страйков общий на оба канала
    исход = await apply_text_strike(
        db_user["id"] if db_user else None, "display_name", name, verdict
    )
    if verdict.get("blocked"):
        if исход is not None and исход.banned:
            await answer_ban_screen(
                message, TEXT_BAN_REASONS[исход.category], исход.banned_until
            )
            return
        await message.answer(
            T.REG_NAME_REJECTED.format(reason=humanize(verdict.get("reason", "")))
            + strike_suffix(исход)
        )
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
    if age < MIN_AGE:
        await message.answer(T.REG_AGE_TOO_YOUNG)
        return
    if age > MAX_AGE:
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
    await ask_relation_type(callback.message, state)


@router.message(RegistrationStates.waiting_goal)
async def goal_wrong_type(message: Message):
    await message.answer(T.REG_EXPECT_BUTTON)


# ── Тип связи ────────────────────────────────────────────────────

@router.callback_query(
    RegistrationStates.waiting_relation_type, F.data.startswith("reg:relation_type:")
)
async def process_relation_type(callback: CallbackQuery, state: FSMContext):
    # «Не важно» присылает пустое значение — законный ответ, означает
    # «не сужать по этому полю» (см. matching._passes_niche_filters)
    await state.update_data(reg_relation_type=callback.data.rsplit(":", 1)[-1])
    await callback.answer()
    await ask_city(callback.message, state)


@router.message(RegistrationStates.waiting_relation_type)
async def relation_type_wrong_type(message: Message):
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
        headers = {"User-Agent": "Simp-Dating-Bot/1.0 (support@simp.app)"}
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
async def process_photo(
    message: Message, state: FSMContext, db_user: dict | None = None
):
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

    # Без байтов фото ни проверить, ни перезалить. Раньше оно молча уходило
    # в анкету голым file_id — непроверенный снимок попадал в общую выдачу.
    if not buf:
        await message.answer(T.REG_PHOTO_FETCH_FAILED)
        return

    verdict = await moderate_image(buf)
    if verdict.get("unavailable"):
        # Проверка не состоялась — это не «фото плохое», человеку нужна
        # другая формулировка: виноват сервис, а не снимок
        await message.answer(T.REG_PHOTO_MOD_UNAVAILABLE)
        return

    # Журнал — как в API-канале (routers/upload.py пишет вердикт каждого
    # фото, в записи file_id — по нему админ найдёт снимок). Страйк — только
    # за рекламу в кадре ("ad"), тем же счётом, что за рекламный текст: блок
    # с пустой категорией (нудити и прочее) — отказ без страйка, иначе
    # register_text_strike нормализовал бы "" в "text"
    исход = None
    if db_user:
        if verdict.get("category") == "ad":
            исход = await apply_text_strike(
                db_user["id"], "photo", photo.file_id, verdict
            )
        else:
            await log_moderation(db_user["id"], "photo", photo.file_id, verdict)
    if исход is not None and исход.banned:
        await answer_ban_screen(
            message, TEXT_BAN_REASONS[исход.category], исход.banned_until
        )
        return
    if verdict.get("blocked"):
        await message.answer(
            T.REG_PHOTO_REJECTED.format(reason=humanize(verdict.get("reason", "")))
            + strike_suffix(исход)
        )
        return

    # Гейт анкеты: модерация выше отвечает «нет ли запрещённого», а анкете
    # нужен живой человек — кот, чёрный фон или скриншот из интернета
    # модерацию проходят, но в общую выдачу попасть не должны
    gate = await verify_profile_photo(buf)
    if gate.get("unavailable"):
        await message.answer(T.REG_PHOTO_MOD_UNAVAILABLE)
        return
    if not gate.get("face"):
        await message.answer(T.REG_PHOTO_NO_FACE)
        return
    if not gate.get("authentic"):
        await message.answer(T.REG_PHOTO_NOT_AUTHENTIC)
        return

    # Перезаливаем в R2, чтобы фото было видно в вебе и в iOS-приложении;
    # если хранилище не настроено, остаётся file_id — бот его покажет
    stored = photo.file_id
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
async def process_bio(message: Message, state: FSMContext, db_user: dict | None = None):
    bio = (message.text or "").strip()[:500]

    if bio:
        verdict = await moderate_text(bio)
        # Тип записи — "bio", как у API (routers/profiles.py)
        исход = await apply_text_strike(
            db_user["id"] if db_user else None, "bio", bio, verdict
        )
        if verdict.get("blocked"):
            if исход is not None and исход.banned:
                await answer_ban_screen(
                    message, TEXT_BAN_REASONS[исход.category], исход.banned_until
                )
                return
            await message.answer(
                T.REG_BIO_REJECTED.format(reason=humanize(verdict.get("reason", "")))
                + strike_suffix(исход)
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

    сброс_галочки = False
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
            "relation_type": data.get("reg_relation_type", ""),
            "photos": data.get("reg_photos", []),
        }

        # Галочка «проверенный» обещает: все фото анкеты принадлежат человеку,
        # прошедшему живую проверку. API при добавлении фото сверяет его с
        # опорным (api/routers/profiles.py), бот сверять лица не умеет —
        # поэтому правило проще и жёстче: верифицированный добавил новое фото
        # или убрал опорное — галочка снимается, вернёт её повторная проверка
        # в мини-аппе. Удаление и перестановка прочих фото галочку не трогают:
        # эти снимки уже были в анкете, когда проверка проходила. Сравниваем
        # со свежим состоянием базы, а не с тем, что легло в state на старте:
        # анкету могли параллельно править из мини-аппа.
        if db_user.get("is_verified"):
            прежний = await get_profile(db_user["id"]) or {}
            прежние_фото = set(прежний.get("photos") or [])
            опорное = прежний.get("verified_photo") or ""
            новые_фото = fields["photos"]
            добавлено = any(ф not in прежние_фото for ф in новые_фото)
            опорное_убрано = bool(опорное) and опорное not in новые_фото
            сброс_галочки = добавлено or опорное_убрано

        # Снимаем ДО записи фото: если снять галочку не вышло, исключение
        # не даст сохраниться и фотографиям — непроверенный снимок не может
        # оказаться в анкете с галочкой даже на сбое
        if сброс_галочки:
            await clear_verification(db_user["id"])

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

        # Галочку «проверенный» конец анкеты больше не даёт: is_verified
        # выдаёт только живая проверка лица в мини-аппе
        await update_profile(db_user["id"], **fields)
    except Exception as e:
        logger.exception(f"Не удалось сохранить анкету: {e}")
        await message.answer(T.ERROR_GENERIC)
        return

    # Веха воронки: анкета в боте дошла до конца. После сохранения — сорванная
    # запись анкеты не считается. Повторное прохождение гасит dedup_key;
    # та же веха из мини-аппа (profiles.py) пишется тем же ключом
    await track_event(db_user["id"], "profile_created", once=True)

    # Конец анкеты двигает отсчёт отложенных пушей: иначе «укажи субкультуру»
    # пришло бы через 45 минут после согласия — посреди только что законченной
    # анкеты. Ошибку функция гасит сама (см. services/nudges.py).
    await запланировать_пуши_онбординга(message.chat.id, db_user.get("locale") or "ru")

    await state.clear()
    итог = T.REG_DONE
    if сброс_галочки:
        итог = f"{T.REG_DONE}\n\n{T.REG_VERIFY_RESET}"
    try:
        await message.answer_photo(
            photo=BANNERS["welcome"], caption=итог, reply_markup=main_kb()
        )
    except Exception:
        # Баннер может не загрузиться — текст важнее картинки
        await message.answer(итог, reply_markup=main_kb())
