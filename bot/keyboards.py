from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from config import SITE_URL


def main_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🔍 Смотреть анкеты", callback_data="dating:start"),
        ],
        [
            InlineKeyboardButton(text="👤 Моя анкета", callback_data="profile:view"),
            InlineKeyboardButton(text="💕 Мои мэтчи", callback_data="matches:list"),
        ],
        [
            InlineKeyboardButton(
                text="🌐 Открыть Web App",
                web_app={"url": f"{SITE_URL}/discover"},
            ),
        ],
        [
            InlineKeyboardButton(text="⭐ Premium", callback_data="premium"),
            InlineKeyboardButton(text="⚙️ Настройки", callback_data="settings"),
        ],
    ])


def reg_gender_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="👨 Мужчина", callback_data="reg:gender:male"),
            InlineKeyboardButton(text="👩 Женщина", callback_data="reg:gender:female"),
        ],
        [
            InlineKeyboardButton(text="🧑 Другое", callback_data="reg:gender:other"),
        ],
    ])


def reg_looking_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="👨 Мужчин", callback_data="reg:looking:male"),
            InlineKeyboardButton(text="👩 Женщин", callback_data="reg:looking:female"),
        ],
        [
            InlineKeyboardButton(text="🧑 Любой", callback_data="reg:looking:any"),
        ],
    ])


def dating_action_kb(profile_user_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="👎", callback_data=f"like:pass:{profile_user_id}"),
            InlineKeyboardButton(text="💌", callback_data=f"like:message:{profile_user_id}"),
            InlineKeyboardButton(text="👍", callback_data=f"like:like:{profile_user_id}"),
        ],
        [
            InlineKeyboardButton(text="💬 Открыть чат в Web", web_app={"url": f"{SITE_URL}/chat"}),
        ],
    ])


def profile_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✏️ Редактировать", callback_data="profile:edit"),
        ],
        [
            InlineKeyboardButton(text="🌐 Откройте в Web App", web_app={"url": f"{SITE_URL}/profile"}),
        ],
        [
            InlineKeyboardButton(text="🔙 Назад", callback_data="menu"),
        ],
    ])


def matches_list_kb(matches: list[dict]) -> InlineKeyboardMarkup:
    rows = []
    for m in matches[:10]:
        label = m.get("partner_name") or f"Мэтч #{m['partner_id'][:8]}"
        rows.append([InlineKeyboardButton(
            text=f"💕 {label}",
            callback_data=f"chat:open:{m['id']}",
        )])
    rows.append([InlineKeyboardButton(text="🔙 Назад", callback_data="menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def chat_kb(match_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="💬 Отправить сообщение", callback_data=f"chat:msg:{match_id}"),
        ],
        [
            InlineKeyboardButton(text="⚡ Подсказка от AI", callback_data=f"chat:hint:{match_id}"),
        ],
        [
            InlineKeyboardButton(text="🔙 К мэтчам", callback_data="matches:list"),
        ],
    ])


def skip_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⏭️ Пропустить", callback_data="reg:skip_photo")],
    ])


def back_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Назад", callback_data="menu")],
    ])
