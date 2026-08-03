from __future__ import annotations

import logging
from urllib.parse import quote

from aiogram import Router, F
from aiogram.filters import Command, StateFilter
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from config import BOT_USERNAME, REFERRAL_MIN_INVITES, REFERRAL_BOOST_PERCENT
from database import get_or_create_user, get_referral_count

logger = logging.getLogger(__name__)
router = Router()

SHARE_TEXT = "Залетай в Souldawn Dating — знакомства с AI-подбором 💕"


def referral_link(user_id: str) -> str:
    return f"https://t.me/{BOT_USERNAME}?start=ref_{user_id}"


def _referral_text(user_id: str, count: int) -> str:
    link = referral_link(user_id)
    if count >= REFERRAL_MIN_INVITES:
        status = (
            f"🚀 <b>Буст активен!</b> Ваша анкета показывается на "
            f"{REFERRAL_BOOST_PERCENT}% выше в выдаче."
        )
    else:
        left = REFERRAL_MIN_INVITES - count
        status = (
            f"Прогресс: <b>{count}/{REFERRAL_MIN_INVITES}</b> — "
            f"ещё {left}, и анкета получит буст +{REFERRAL_BOOST_PERCENT}% в выдаче."
        )
    return (
        "🎁 <b>Пригласи друзей — получи буст анкеты</b>\n\n"
        f"Приведи {REFERRAL_MIN_INVITES} друзей и твоя анкета будет показываться "
        f"выше у всех — <b>+{REFERRAL_BOOST_PERCENT}%</b> к позиции в деке.\n\n"
        f"{status}\n\n"
        f"Твоя ссылка:\n<code>{link}</code>"
    )


def referral_kb(user_id: str) -> InlineKeyboardMarkup:
    link = referral_link(user_id)
    share_url = f"https://t.me/share/url?url={quote(link)}&text={quote(SHARE_TEXT)}"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📤 Поделиться ссылкой", url=share_url)],
        [InlineKeyboardButton(text="🏠 В меню", callback_data="menu")],
    ])


@router.callback_query(F.data == "referral")
async def show_referral(callback: CallbackQuery):
    db_user = await get_or_create_user(
        callback.from_user.id,
        callback.from_user.username or "",
        callback.from_user.first_name or "",
    )
    count = await get_referral_count(db_user["id"])
    await callback.answer()
    await callback.message.answer(
        _referral_text(db_user["id"], count),
        reply_markup=referral_kb(db_user["id"]),
    )


@router.message(StateFilter("*"), Command("invite"))
async def invite_command(message: Message):
    db_user = await get_or_create_user(
        message.from_user.id,
        message.from_user.username or "",
        message.from_user.first_name or "",
    )
    count = await get_referral_count(db_user["id"])
    await message.answer(
        _referral_text(db_user["id"], count),
        reply_markup=referral_kb(db_user["id"]),
    )
