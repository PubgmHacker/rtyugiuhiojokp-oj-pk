"""Старт бота как у Mimolet: язык → политика → рассылки → Начать."""

from __future__ import annotations

import logging

from aiogram import Router, F
from aiogram.filters import StateFilter
from aiogram.types import CallbackQuery, LinkPreviewOptions, Message
from aiogram.fsm.context import FSMContext

from config import legal_url
from database import get_or_create_user, get_profile, get_user_locale, set_user_locale
from keyboards import consent_kb, language_kb, main_kb, start_app_kb
from states import OnboardingStates
import texts as T

logger = logging.getLogger(__name__)
router = Router()

_VALID_LOCALES = set(T.ONBOARDING_LOCALES)

#: Где кнопкам онбординга разрешено срабатывать: его собственные шаги плюс
#: «сценария нет». Кнопки под старыми сообщениями в Telegram нажимаемы вечно, а
#: три обработчика ниже переводят состояние и чистят данные — без этого фильтра
#: тап по «Продолжить» из первого /start посреди анкеты стирал имя, возраст,
#: город и загруженные фото. Онбординг же ничего своего не теряет: до согласия
#: в state лежит один `onb_locale`.
_ГДЕ_ОНБОРДИНГ = StateFilter(OnboardingStates, None)


async def send_language_picker(message: Message, state: FSMContext) -> None:
    """Первое сообщение после /start — сетка языков."""
    await state.set_state(OnboardingStates.waiting_language)
    await message.answer(T.onboarding_choose_language(), reply_markup=language_kb())


async def send_consent(message: Message, state: FSMContext, locale: str) -> None:
    await state.update_data(onb_locale=locale)
    await state.set_state(OnboardingStates.waiting_consent)
    await message.answer(
        T.onboarding_consent(locale, legal_url("privacy"), legal_url("terms")),
        reply_markup=consent_kb(locale),
        link_preview_options=LinkPreviewOptions(is_disabled=True),
    )


async def send_broadcasts(message: Message, locale: str) -> None:
    """Маркетинговые рассылки Mimolet: субкультура, потом почта."""
    await message.answer(
        T.onboarding_broadcast_style(locale),
        reply_markup=start_app_kb(locale),
    )
    await message.answer(T.onboarding_broadcast_email(locale))


async def _язык(telegram_id: int, state: FSMContext) -> str:
    """Язык для ответа: state → аккаунт → русский.

    State первым: он свежее всех, человек мог только что нажать другой флаг, а
    до базы выбор доезжает отдельной записью. База вторым: state теряется при
    рестарте бота, смене storage и истечении ключа, и без неё тап по кнопке
    недельной давности отвечал по-русски тому, кто выбрал узбекский.

    Русский последним — не `ONBOARDING_LOCALE_FALLBACK`. Это разные ситуации:
    английский подставляется вместо непонятного кода (см. `resolve_locale`), а
    здесь мы не знаем о человеке вообще ничего — язык он ещё не выбирал, и
    русский по умолчанию верен, как и в колонке базы.

    Ни один сбой чтения не должен стоить ответа на тап: Telegram крутит часики
    на кнопке до таймаута, и молчание бота человек читает как «бот умер».
    """
    try:
        data = await state.get_data()
        сохранённый = data.get("onb_locale")
        if сохранённый:
            return T.resolve_locale(сохранённый)
    except Exception as e:
        logger.debug("не прочитали state для языка: %s", e)

    try:
        из_базы = await get_user_locale(telegram_id)
    except Exception as e:
        logger.debug("не прочитали язык из базы: %s", e)
        из_базы = None

    return из_базы or "ru"


@router.callback_query(_ГДЕ_ОНБОРДИНГ, F.data.startswith("onb:lang:"))
async def pick_language(callback: CallbackQuery, state: FSMContext):
    code = (callback.data or "").rsplit(":", 1)[-1]
    locale = code if code in _VALID_LOCALES else T.ONBOARDING_LOCALE_FALLBACK
    await callback.answer()
    # Пишем язык на аккаунт, а не только в state: FSM не переживает рестарт
    # бота и истечение ключа, а мини-апп его не видит вовсе — до этой записи
    # выбор узбекского жил до первого сбоя, дальше человек получал русский.
    # Строка в базе уже есть: /start вызывает get_or_create_user до того, как
    # покажет эту клавиатуру (см. bot.py). Сбой записи онбординг не ломает —
    # язык в state есть, шаг продолжается.
    try:
        await set_user_locale(callback.from_user.id, locale)
    except Exception as e:
        logger.warning("не сохранили язык %s для %s: %s", locale, callback.from_user.id, e)
    if callback.message:
        await send_consent(callback.message, state, locale)


@router.callback_query(_ГДЕ_ОНБОРДИНГ, F.data == "onb:consent")
async def accept_policy(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    locale = T.resolve_locale(data.get("onb_locale"))
    await callback.answer()
    # Чистим state целиком: онбординг закончен, а его шаг не должен остаться
    # висеть на человеке. Терять здесь нечего только потому, что сюда не
    # доходят тапы из других сценариев — см. `_ГДЕ_ОНБОРДИНГ`
    await state.clear()
    await state.update_data(onb_locale=locale, onb_consented=True)
    if callback.message:
        await send_broadcasts(callback.message, locale)


@router.callback_query(_ГДЕ_ОНБОРДИНГ, F.data == "onb:start")
async def start_app(callback: CallbackQuery, state: FSMContext):
    """Fallback без HTTPS: мини-апп не открыть, ведём в анкету бота."""
    await callback.answer()
    if not callback.message:
        return
    locale = await _язык(callback.from_user.id, state)

    db_user = await get_or_create_user(
        callback.from_user.id,
        callback.from_user.username or "",
        callback.from_user.first_name or "",
    )
    profile = await get_profile(db_user["id"])
    ready = bool(profile and profile.get("display_name") and profile.get("photos"))
    if not ready:
        from handlers.registration import ask_name

        await ask_name(callback.message, state)
        return

    await callback.message.answer(
        T.menu_text(is_ready=True),
        reply_markup=main_kb(),
    )
    logger.info("onb:start opened bot menu locale=%s", locale)


# Зарегистрирован последним намеренно: внутри роутера обработчики проверяются
# в порядке объявления, поэтому на своих шагах онбординга выигрывают три
# обработчика выше, а сюда попадают только тапы из чужих сценариев.
@router.callback_query(F.data.startswith("onb:"))
async def stale_onboarding_tap(callback: CallbackQuery, state: FSMContext):
    """Кнопка старта, нажатая посреди анкеты, чата или удаления аккаунта.

    Ничего не делает — и это вся её работа. Пропустить такой тап нельзя:
    Telegram крутит часики на кнопке до таймаута, человек жмёт второй и третий
    раз и решает, что бот умер. Состояние не трогаем вообще, даже данные читаем
    без записи: заполненная наполовину анкета обязана дожить до конца.
    """
    locale = await _язык(callback.from_user.id, state)
    сценарий = "неизвестно"
    try:
        сценарий = await state.get_state() or "нет состояния"
    except Exception as e:  # storage может быть недоступен — тап важнее лога
        logger.debug("не прочитали state для устаревшего тапа: %s", e)
    await callback.answer(T.onboarding_stale_tap(locale))
    logger.info(
        "устаревший тап %s в состоянии %s — сценарий не тронут",
        callback.data,
        сценарий,
    )
