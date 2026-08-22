from __future__ import annotations

from aiogram.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardRemove,
    WebAppInfo,
)

from config import mini_app_openable, mini_app_url, webapp_https
from services.plans import имя_уровня_для
import texts as T


def кнопка_приложения(text: str, path: str = "") -> InlineKeyboardButton | None:
    """Кнопка в мини-апп — или None, если открывать его нечем.

    Telegram отклоняет web_app не по HTTPS, и отклоняет СООБЩЕНИЕ ЦЕЛИКОМ, а не
    одну кнопку: `Bad Request: BUTTON_TYPE_INVALID` — и человек не получает ни
    меню, ни текста. Ровно на HTTP-конфигурации это и происходило, то есть на
    той самой, где `start_app_kb` уводит человека в анкету бота, рассчитывая,
    что меню придёт следом.

    По HTTP без петли остаётся обычная url-кнопка: тот же адрес во внешнем
    браузере. Хуже, чем внутри Telegram, но это работающий стенд.

    Петлю не отдаём никому: `http://localhost:5173` в чужом Telegram — адрес
    самого телефона получателя. Кнопки нет вовсе, и вызывающий строит клавиатуру
    без неё, а не с мёртвой.
    """
    if webapp_https():
        return InlineKeyboardButton(text=text, web_app=WebAppInfo(url=mini_app_url(path)))
    if mini_app_openable():
        return InlineKeyboardButton(text=text, url=mini_app_url(path))
    return None

# Сетка как у Mimolet: 2×3 + 中文 отдельной строкой. Нереализованные
# локали всё равно показываем — тексты после выбора падают в en.
ONBOARDING_LANGUAGES: tuple[tuple[str, str], ...] = (
    ("ru", "🇷🇺 Русский"),
    ("en", "🇬🇧 English"),
    ("uz", "🇺🇿 O'zbekcha"),
    ("es", "🇪🇸 Español"),
    ("tr", "🇹🇷 Türkçe"),
    ("id", "🇮🇩 Bahasa Indonesia"),
    ("zh", "🇨🇳 中文"),
)


def language_kb() -> InlineKeyboardMarkup:
    """Выбор языка — сетка флагов, как у Mimolet после /start."""
    rows: list[list[InlineKeyboardButton]] = []
    pair: list[InlineKeyboardButton] = []
    for code, label in ONBOARDING_LANGUAGES:
        pair.append(
            InlineKeyboardButton(text=label, callback_data=f"onb:lang:{code}")
        )
        if len(pair) == 2:
            rows.append(pair)
            pair = []
    if pair:
        rows.append(pair)
    return InlineKeyboardMarkup(inline_keyboard=rows)


def consent_kb(locale: str = "ru") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=T.onboarding_continue_label(locale),
                    callback_data="onb:consent",
                )
            ]
        ]
    )


def start_app_kb(locale: str = "ru") -> InlineKeyboardMarkup:
    """«Начать» открывает мини-апп. Без HTTPS Telegram web_app не примет —
    тогда кнопка ведёт в анкету бота, чтобы /start не заканчивался тупиком."""
    label = T.onboarding_start_label(locale)
    button = кнопка_приложения(label)
    if button is None:
        button = InlineKeyboardButton(text=label, callback_data="onb:start")
    return InlineKeyboardMarkup(inline_keyboard=[[button]])


def main_kb() -> InlineKeyboardMarkup:
    """Главное меню. Держим коротким: смотреть анкеты — основное действие."""
    rows = [
        [InlineKeyboardButton(text="🔍 Смотреть анкеты", callback_data="dating:start")],
        [
            InlineKeyboardButton(text="👤 Моя анкета", callback_data="profile:view"),
            InlineKeyboardButton(text="💕 Мэтчи", callback_data="matches:list"),
        ],
    ]
    приложение = кнопка_приложения("✨ Открыть приложение", "/discover")
    if приложение:
        rows.append([приложение])
    rows.append(
        [
            InlineKeyboardButton(text="⭐ Premium", callback_data="premium"),
            InlineKeyboardButton(text="🎁 Друзья", callback_data="referral"),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ── Регистрация ─────────────────────────────────────────────────

def _with_back(rows: list[list[InlineKeyboardButton]], back_to: str | None):
    """Добавляет «Назад» последней строкой, если есть куда возвращаться."""
    if back_to:
        rows.append(
            [InlineKeyboardButton(text="← Назад", callback_data=f"reg:back:{back_to}")]
        )
    return rows


def reg_gender_kb(back_to: str | None = "age") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=_with_back(
            [
                [
                    InlineKeyboardButton(text="Парень", callback_data="reg:gender:male"),
                    InlineKeyboardButton(text="Девушка", callback_data="reg:gender:female"),
                ],
                [InlineKeyboardButton(text="Другое", callback_data="reg:gender:other")],
            ],
            back_to,
        )
    )


def reg_looking_kb(back_to: str | None = "gender") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=_with_back(
            [
                [
                    InlineKeyboardButton(text="Девушек", callback_data="reg:looking:female"),
                    InlineKeyboardButton(text="Парней", callback_data="reg:looking:male"),
                ],
                [InlineKeyboardButton(text="Всех", callback_data="reg:looking:any")],
            ],
            back_to,
        )
    )


def reg_goal_kb(back_to: str | None = "looking_for") -> InlineKeyboardMarkup:
    """Цель знакомства. Значения совпадают с web/src/lib/profileOptions.ts —
    иначе выбранное в боте не найдётся фильтром в мини-аппе."""
    return InlineKeyboardMarkup(
        inline_keyboard=_with_back(
            [
                [
                    InlineKeyboardButton(text="Отношения", callback_data="reg:goal:relationship"),
                    InlineKeyboardButton(text="Дружба", callback_data="reg:goal:friendship"),
                ],
                [
                    InlineKeyboardButton(text="Общение", callback_data="reg:goal:chat"),
                    InlineKeyboardButton(text="Свидания", callback_data="reg:goal:dates"),
                ],
                [InlineKeyboardButton(text="Пока не решил", callback_data="reg:goal:")],
            ],
            back_to,
        )
    )


def reg_relation_type_kb(back_to: str | None = "goal") -> InlineKeyboardMarkup:
    """Тип связи («с кем») — отдельная ось от цели знакомства («зачем»).
    Значения совпадают с web/src/lib/profileOptions.ts (RELATION_TYPES) —
    иначе выбранное в боте не найдётся фильтром в мини-аппе."""
    return InlineKeyboardMarkup(
        inline_keyboard=_with_back(
            [
                [
                    InlineKeyboardButton(text="Друзья", callback_data="reg:relation_type:friends"),
                    InlineKeyboardButton(text="Подруги", callback_data="reg:relation_type:girlfriends"),
                ],
                [InlineKeyboardButton(text="Партнёр", callback_data="reg:relation_type:partner")],
                [InlineKeyboardButton(text="Не важно", callback_data="reg:relation_type:")],
            ],
            back_to,
        )
    )


def reg_back_kb(back_to: str) -> InlineKeyboardMarkup:
    """Только «Назад» — для шагов со свободным вводом."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="← Назад", callback_data=f"reg:back:{back_to}")]
        ]
    )


def reg_city_kb() -> ReplyKeyboardMarkup:
    """Кнопка геопозиции: показать людей рядом без ручного ввода города."""
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📍 Отправить геопозицию", request_location=True)]],
        resize_keyboard=True,
        one_time_keyboard=True,
        input_field_placeholder="Или напишите город",
    )


def reg_photo_kb(has_photo: bool) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if has_photo:
        rows.append([InlineKeyboardButton(text="✅ Готово", callback_data="reg:photo_done")])
    rows.append([InlineKeyboardButton(text="← Назад", callback_data="reg:back:city")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def reg_bio_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Пропустить", callback_data="reg:bio_skip")],
            [InlineKeyboardButton(text="← Назад", callback_data="reg:back:photo")],
        ]
    )


def remove_kb() -> ReplyKeyboardRemove:
    return ReplyKeyboardRemove()


# ── Просмотр анкет ──────────────────────────────────────────────

def dating_action_kb(profile_user_id: str) -> InlineKeyboardMarkup:
    """Как в «Дайвинчике»: два основных действия рядом, остальное — ниже."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="👎", callback_data=f"like:pass:{profile_user_id}"),
                InlineKeyboardButton(text="❤️", callback_data=f"like:like:{profile_user_id}"),
            ],
            [
                InlineKeyboardButton(
                    text="💌 Написать", callback_data=f"like:message:{profile_user_id}"
                ),
                InlineKeyboardButton(text="⚠️", callback_data=f"report:{profile_user_id}"),
            ],
            [InlineKeyboardButton(text="💤 Хватит на сегодня", callback_data="dating:stop")],
        ]
    )


def no_more_profiles_kb() -> InlineKeyboardMarkup:
    """Анкеты закончились: настроек поиска (возраст, дистанция, нишевые
    фильтры) в самом боте нет — кнопка ведёт прямо в мини-апп, где они есть,
    а не просто в главное меню.

    Если мини-апп открывать нечем, кнопки нет, и текст рядом не обещает
    настройки (`texts.no_more_profiles`): обещание без кнопки читается как
    поломка, а не как отсутствующая функция.
    """
    rows = []
    приложение = кнопка_приложения("✨ Открыть настройки поиска", "/discover")
    if приложение:
        rows.append([приложение])
    rows.append([InlineKeyboardButton(text="← Меню", callback_data="menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def like_locked_kb() -> InlineKeyboardMarkup:
    """Пришёл лайк, но кто именно — за платный уровень.

    Кнопка ведёт на витрину подписки, а не в мини-апп: там та же карточка
    будет закрыта (api/routers/likes.py отдаёт бесплатному `is_locked`), и
    человек просто прошёл бы круг зря.

    Имя уровня на кнопке — из таблицы возможностей: вписанное словом, оно
    осталось бы обещать Plus после переноса фичи на другой уровень.
    """
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(
                text=f"⭐ Открыть в {имя_уровня_для('see_who_liked')}",
                callback_data="premium",
            )],
            [InlineKeyboardButton(text="← Меню", callback_data="menu")],
        ]
    )


def limit_reached_kb(back_to: str = "menu") -> InlineKeyboardMarkup:
    """Суточный лимит исчерпан: витрина подписки и путь назад.

    Кнопка ведёт на `premium` внутри бота, а не в мини-апп: лимит серверный и
    там тот же (api/services/quotas.py), так что человек прошёл бы круг зря.

    `back_to` — куда вернуться: из деки к следующей анкете, из мэтчей к списку.
    Один и тот же «← Меню» после отказа выбрасывал бы человека из потока,
    в котором он был.
    """
    подписи = {
        "dating:next": "← Смотреть дальше",
        "matches:list": "← К мэтчам",
        "menu": "← Меню",
    }
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(
                text="⭐ Открыть без лимитов", callback_data="premium",
            )],
            [InlineKeyboardButton(
                text=подписи.get(back_to, "← Меню"), callback_data=back_to,
            )],
        ]
    )


def report_reasons_kb(target_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Спам", callback_data=f"report:send:{target_id}:spam"),
                InlineKeyboardButton(text="Оскорбления", callback_data=f"report:send:{target_id}:harassment"),
            ],
            [
                InlineKeyboardButton(text="Нагота", callback_data=f"report:send:{target_id}:nudity"),
                InlineKeyboardButton(text="Мошенничество", callback_data=f"report:send:{target_id}:scam"),
            ],
            [
                InlineKeyboardButton(text="Чужие фото", callback_data=f"report:send:{target_id}:fake"),
                InlineKeyboardButton(text="Наркотики", callback_data=f"report:send:{target_id}:drugs"),
            ],
            [InlineKeyboardButton(text="Похоже, ребёнок", callback_data=f"report:send:{target_id}:underage")],
            # Блокировка — отдельное действие: жалоба уходит модератору,
            # а заблокированный исчезает из выдачи сразу и навсегда
            [InlineKeyboardButton(text="🚫 Заблокировать", callback_data=f"block:{target_id}")],
            [InlineKeyboardButton(text="← Отмена", callback_data="dating:next")],
        ]
    )


# ── Профиль ─────────────────────────────────────────────────────

def profile_kb(is_paused: bool = False) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text="✏️ Изменить анкету", callback_data="profile:edit")],
    ]
    приложение = кнопка_приложения("✨ Открыть в приложении", "/profile")
    if приложение:
        rows.append([приложение])
    if is_paused:
        rows.append(
            [InlineKeyboardButton(text="▶️ Вернуть в поиск", callback_data="profile:resume")]
        )
    else:
        rows.append(
            [InlineKeyboardButton(text="💤 Скрыть из поиска", callback_data="profile:pause")]
        )
    rows.append([InlineKeyboardButton(text="← Меню", callback_data="menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def delete_confirm_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Отмена", callback_data="delete:cancel")],
        ]
    )


# ── Мэтчи и чат ─────────────────────────────────────────────────

def matches_list_kb(matches: list[dict]) -> InlineKeyboardMarkup:
    """Список мэтчей. Закрытые суточным лимитом остаются в списке — они и есть
    витрина подписки, — но под замком и без имени: имя закрытого сюда уже не
    приходит (см. database/connection.get_user_matches).

    Кнопка живая, а не выключенная: нажатие объясняет лимит и предлагает
    подписку, а серая кнопка не объясняет ничего.
    """
    rows = []
    for m in matches[:10]:
        if m.get("locked"):
            rows.append(
                [InlineKeyboardButton(
                    text="🔒 Мэтч — открыть по подписке",
                    callback_data=f"chat:open:{m['id']}",
                )]
            )
            continue
        label = m.get("partner_name") or "Мэтч"
        rows.append(
            [InlineKeyboardButton(text=f"💬 {label}", callback_data=f"chat:open:{m['id']}")]
        )
    rows.append([InlineKeyboardButton(text="← Меню", callback_data="menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def chat_kb(match_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="💬 Написать", callback_data=f"chat:msg:{match_id}")],
            [
                InlineKeyboardButton(
                    text="⚡ Подсказать фразу", callback_data=f"chat:hint:{match_id}"
                )
            ],
            [InlineKeyboardButton(text="← К мэтчам", callback_data="matches:list")],
        ]
    )


def back_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="← Меню", callback_data="menu")]]
    )


def unban_kb(price_rub: int) -> InlineKeyboardMarkup:
    """Единственное действие забаненного — оплатить досрочную разблокировку.

    Кнопка «в меню» здесь была бы обманом: любое нажатие всё равно упрётся
    в бан-гейт (middlewares/ban_gate.py).
    """
    return InlineKeyboardMarkup(
        inline_keyboard=[[
            InlineKeyboardButton(
                text=f"🔓 Разблокировать за {price_rub} ₽",
                callback_data="unban:pay",
            )
        ]]
    )

