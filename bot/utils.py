from __future__ import annotations

from aiogram.types import Message


async def safe_edit_text(message: Message, text: str, reply_markup=None):
    """edit_text падает на фото-сообщениях (главное меню — баннер).

    Пробуем отредактировать, иначе отправляем новое сообщение.
    """
    try:
        await message.edit_text(text, reply_markup=reply_markup)
    except Exception:
        try:
            await message.delete()
        except Exception:
            pass
        await message.answer(text, reply_markup=reply_markup)
