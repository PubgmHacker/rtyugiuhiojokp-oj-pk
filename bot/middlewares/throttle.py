"""Антифлуд.

Быстрые повторные тапы по «❤️» приводили к дублям лайков и гонкам при
создании мэтча. Ограничиваем частоту действий на пользователя.

Счётчики держим в памяти процесса: бот запускается одним инстансом, а
для защиты от случайных двойных нажатий этого достаточно. Если появится
несколько реплик, лимит стоит перенести в Redis.
"""

from __future__ import annotations

import logging
import time
from collections import OrderedDict
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from config import THROTTLE_CALLBACK, THROTTLE_MESSAGE

logger = logging.getLogger(__name__)

# Ограничиваем словарь, чтобы он не рос бесконечно на большом трафике
_MAX_TRACKED = 10_000


class ThrottleMiddleware(BaseMiddleware):
    """Пропускает не чаще одного действия в заданный интервал."""

    def __init__(self) -> None:
        self._last: OrderedDict[tuple[int, str], float] = OrderedDict()

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = data.get("event_from_user")
        if user is None:
            return await handler(event, data)

        if isinstance(event, CallbackQuery):
            kind, limit = "cb", THROTTLE_CALLBACK
        elif isinstance(event, Message):
            kind, limit = "msg", THROTTLE_MESSAGE
        else:
            return await handler(event, data)

        key = (user.id, kind)
        now = time.monotonic()
        last = self._last.get(key)

        if last is not None and now - last < limit:
            # Колбэк нужно закрыть, иначе у пользователя висят «часики»
            if isinstance(event, CallbackQuery):
                try:
                    await event.answer()
                except Exception:
                    pass
            return None

        self._last[key] = now
        self._last.move_to_end(key)
        while len(self._last) > _MAX_TRACKED:
            self._last.popitem(last=False)

        return await handler(event, data)
