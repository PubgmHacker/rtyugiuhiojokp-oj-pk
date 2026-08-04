"""Ограничение частоты запросов.

У API не было никаких лимитов: жалобы, загрузку фото, попытки входа и
обмен кодов привязки можно было слать сколько угодно. Для дейтинга это
прямой путь к спаму жалобами, засорению бакета и перебору кодов.

Счётчики живут в Redis, поэтому лимит общий для всех инстансов API.
Если Redis недоступен, запросы пропускаются: сервис, который перестаёт
работать вместе с кешем, хуже отсутствующего лимита.

Лимиты заданы по пути, а не глобально: свайпать деку человек может
быстро, а жаловаться — нет.
"""

from __future__ import annotations

import logging
import time

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from services.realtime import get_redis

logger = logging.getLogger(__name__)

# (префикс пути, метод) → (сколько запросов, за сколько секунд).
# Проверяется самое длинное совпадение префикса.
LIMITS: list[tuple[str, str, int, int]] = [
    # Жалоба ведёт к скрытию и автобану — самый чувствительный путь
    ("/api/report", "POST", 5, 3600),
    # Перебор шестизначного кода привязки
    ("/api/auth/link", "POST", 10, 600),
    # Штамповка гостевых аккаунтов при включённом DEBUG
    ("/api/auth/dev", "POST", 10, 3600),
    ("/api/auth/telegram", "POST", 30, 3600),
    # Загрузка фото: перекодирование стоит процессорного времени
    ("/api/upload", "POST", 30, 3600),
    ("/api/blocks", "POST", 60, 3600),
    # Свайпы — частое действие, лимит только против явных ботов
    ("/api/likes", "POST", 600, 3600),
]


def _find_limit(path: str, method: str) -> tuple[str, int, int] | None:
    best: tuple[str, int, int] | None = None
    for prefix, meth, limit, window in LIMITS:
        if method == meth and path.startswith(prefix):
            if best is None or len(prefix) > len(best[0]):
                best = (prefix, limit, window)
    return best


def _client_key(request: Request) -> str:
    """Идентификатор источника запроса.

    Токен предпочтительнее IP: за одним мобильным NAT сидят тысячи людей,
    и лимит по адресу задел бы их всех. IP остаётся для неавторизованных
    путей — там токена ещё нет.
    """
    auth = request.headers.get("authorization", "")
    if auth.startswith("Bearer "):
        # Хвоста подписи достаточно для различения сессий, и он не пишется
        # в логи целиком
        return f"t:{auth[-32:]}"

    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return f"ip:{forwarded.split(',')[0].strip()}"
    return f"ip:{request.client.host if request.client else 'unknown'}"


class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        found = _find_limit(request.url.path, request.method)
        if not found:
            return await call_next(request)

        prefix, limit, window = found

        try:
            r = await get_redis()
            # Окно фиксированное: ключ включает номер интервала, поэтому
            # истекает сам и не требует отдельной очистки
            bucket = int(time.time()) // window
            key = f"dating:rl:{prefix}:{_client_key(request)}:{bucket}"
            used = await r.incr(key)
            if used == 1:
                await r.expire(key, window)
        except Exception as e:
            # Лимит — защита, а не условие работы сервиса
            logger.error(f"Rate limit check failed ({prefix}): {e}")
            return await call_next(request)

        if used > limit:
            retry_after = window - int(time.time()) % window
            logger.warning(f"Rate limit exceeded: {prefix} {_client_key(request)}")
            return JSONResponse(
                status_code=429,
                content={"detail": "Слишком много запросов, попробуйте позже"},
                headers={"Retry-After": str(retry_after)},
            )

        return await call_next(request)
