"""Старт бота как у Mimolet: язык → политика → Начать.

Весь онбординг живёт в ОДНОМ сообщении: тап по кнопке редактирует его в
следующий экран, а не шлёт новый. Так повторные тапы не плодят копий (кнопка
исчезает вместе с редактированием), а переписка после старта — один экран, а
не лестница из четырёх. Рассылки Mimolet (субкультура, почта) отсюда убраны:
они ставятся в очередь и уходят отложенными пушами — см. services/nudges.py.
"""

from __future__ import annotations

import logging

from aiogram import Router, F
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import StateFilter
from aiogram.types import CallbackQuery, LinkPreviewOptions, Message
from aiogram.fsm.context import FSMContext

from config import legal_url
from database import get_or_create_user, get_profile, get_user_locale, set_user_locale
from keyboards import consent_kb, language_kb, main_kb, start_app_kb
from services.nudges import запланировать_пуши_онбординга
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
    экран = await message.answer(T.onboarding_choose_language(), reply_markup=language_kb())
    # id экрана — в state: повторный /start удалит его (см. cmd_start в
    # bot.py), а не оставит в переписке второй рабочий онбординг. Сбой записи
    # не страшнее лишнего сообщения при следующем /start.
    try:
        await state.update_data(onb_msg_id=экран.message_id)
    except Exception as e:
        logger.debug("не записали id экрана онбординга: %s", e)


async def _показать(message: Message, state: FSMContext, текст: str, **kwargs) -> None:
    """Следующий экран онбординга — редактированием текущего сообщения.

    Раньше каждый шаг отвечал новым сообщением, и повторные тапы плодили
    копии: кнопки под старыми экранами в Telegram нажимаемы вечно. Правка на
    месте убирает и лестницу сообщений, и сами старые кнопки.

    Редактирование недоступно (сообщение с медиа, тот же текст, любая другая
    причуда Bot API) — шлём новое и запоминаем его id вместо прежнего: шаг
    важнее форм-фактора.
    """
    try:
        await message.edit_text(текст, **kwargs)
        return
    except TelegramBadRequest as e:
        # «message is not modified» — экран уже показан, слать копию не надо
        if "is not modified" in str(e):
            return
        logger.debug("экран онбординга не отредактировался: %s", e)
    except Exception as e:
        logger.warning("правка экрана онбординга упала: %s", e)
    экран = await message.answer(текст, **kwargs)
    try:
        await state.update_data(onb_msg_id=экран.message_id)
    except Exception as e:
        logger.debug("не записали id экрана онбординга: %s", e)


async def send_consent(message: Message, state: FSMContext, locale: str) -> None:
    await state.update_data(onb_locale=locale)
    await state.set_state(OnboardingStates.waiting_consent)
    await _показать(
        message,
        state,
        T.onboarding_consent(locale, legal_url("privacy"), legal_url("terms")),
        reply_markup=consent_kb(locale),
        link_preview_options=LinkPreviewOptions(is_disabled=True),
    )


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
        await state.update_data(onb_msg_id=callback.message.message_id)
        await _показать(
            callback.message,
            state,
            T.onboarding_ready(locale),
            reply_markup=start_app_kb(locale),
        )
    # Рассылки про субкультуру и почту здесь НЕ уходят — ставятся в очередь
    # и уезжают завлекающими пушами после паузы (services/nudges.py): реклама
    # тремя сообщениями подряд поверх живого онбординга читается как спам.
    await запланировать_пуши_онбординга(callback.from_user.id, locale)


async def _убрать_кнопку(message: Message) -> None:
    """Снять с доски сообщение, чья кнопка уже сработала.

    Пока «Начать» висит в переписке, каждый тап рождает новое сообщение —
    человек жмёт три раза и получает три первых вопроса анкеты. Удаление
    решает это на корню: удалённая кнопка не нажимается. Удалить нельзя
    (сообщению больше 48 часов) — хотя бы снимаем клавиатуру.
    """
    try:
        await message.delete()
        return
    except Exception as e:
        logger.debug("экран с кнопкой не удалился: %s", e)
    try:
        await message.edit_reply_markup(reply_markup=None)
    except Exception as e:
        logger.debug("клавиатура с экрана не снялась: %s", e)


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
    await _убрать_кнопку(callback.message)
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
