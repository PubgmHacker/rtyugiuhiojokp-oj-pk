from __future__ import annotations

from aiogram.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardRemove,
)

from config import SITE_URL


def main_kb() -> InlineKeyboardMarkup:
    """Главное меню. Держим коротким: смотреть анкеты — основное действие."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔍 Смотреть анкеты", callback_data="dating:start")],
            [
                InlineKeyboardButton(text="👤 Моя анкета", callback_data="profile:view"),
                InlineKeyboardButton(text="💕 Мэтчи", callback_data="matches:list"),
            ],
            [
                InlineKeyboardButton(
                    text="✨ Открыть приложение",
                    web_app={"url": f"{SITE_URL}/discover"},
                )
            ],
            [
                InlineKeyboardButton(text="⭐ Premium", callback_data="premium"),
                InlineKeyboardButton(text="🎁 Друзья", callback_data="referral"),
            ],
        ]
    )


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


def report_reasons_kb(target_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Спам или реклама", callback_data=f"report:send:{target_id}:spam")],
            [InlineKeyboardButton(text="Оскорбления", callback_data=f"report:send:{target_id}:harassment")],
            [InlineKeyboardButton(text="Нагота", callback_data=f"report:send:{target_id}:nudity")],
            [InlineKeyboardButton(text="Обман, мошенничество", callback_data=f"report:send:{target_id}:scam")],
            [InlineKeyboardButton(text="Чужие фото", callback_data=f"report:send:{target_id}:fake")],
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
        [
            InlineKeyboardButton(
                text="✨ Открыть в приложении",
                web_app={"url": f"{SITE_URL}/profile"},
            )
        ],
    ]
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
    rows = []
    for m in matches[:10]:
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

