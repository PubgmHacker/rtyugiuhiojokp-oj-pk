"""Последний ответ для апдейтов, которые не попали ни в один сценарий."""

from __future__ import annotations

from aiogram import Router
from aiogram.filters import StateFilter
from aiogram.types import Message

from keyboards import main_kb
import texts as T

router = Router()


@router.message(StateFilter(None))
async def unknown_message(message: Message):
    """Не оставлять пользователя в тишине после неизвестного сообщения."""
    await message.answer(T.UNKNOWN_MESSAGE, reply_markup=main_kb())
