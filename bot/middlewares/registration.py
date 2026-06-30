from __future__ import annotations

import logging

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject

from database import get_or_create_user

logger = logging.getLogger(__name__)


class RegistrationMiddleware(BaseMiddleware):
    """Автоматическая регистрация/обновление каждого пользователя."""

    async def __call__(self, handler, event: TelegramObject, data: dict):
        user = getattr(event, "from_user", None)
        if user and user.id and not user.is_bot:
            try:
                db_user = await get_or_create_user(
                    user.id,
                    user.username or "",
                    user.first_name or "",
                )
                data["db_user"] = db_user
            except Exception as e:
                logger.error(f"Registration middleware error: {e}")

        return await handler(event, data)
