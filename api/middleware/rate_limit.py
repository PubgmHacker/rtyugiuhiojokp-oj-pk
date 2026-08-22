"""Ограничение частоты запросов.

У API не было никаких лимитов: жалобы, загрузку фото, попытки входа и
обмен кодов привязки можно было слать сколько угодно. Для дейтинга это
прямой путь к спаму жалобами, засорению бакета и перебору кодов.

Счётчики живут в Redis, поэтому лимит общий для всех инстансов API.
Если Redis недоступен, обычные пути пропускаются: сервис, который перестаёт
работать вместе с кешем, хуже отсутствующего лимита. Но для чувствительных
путей (перебор кода, спам жалобами, поток загрузок — см. _CRITICAL_PREFIXES)
наоборот закрываемся: там открытый лимит опаснее короткой недоступности.

Лимиты заданы по пути, а не глобально: свайпать деку человек может
быстро, а жаловаться — нет.
"""

from __future__ import annotations

import logging
import time

from fastapi import Request
from fastapi.responses import JSONResponse
from jose import JWTError, jwt
from starlette.middleware.base import BaseHTTPMiddleware

from config import get_settings
from services.realtime import get_redis

logger = logging.getLogger(__name__)
settings = get_settings()

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
    # Видео до 50 МБ: суточный лимит публикаций проверяется в самом роутере,
    # но до него доходит уже прочитанный файл — здесь отсекаем поток попыток.
    # Лайк ролика лежит глубже по пути и получает свой лимит: правило
    # выбирается по самому длинному совпадению префикса, иначе пролистывание
    # ленты упиралось бы в лимит загрузки видео.
    ("/api/reels", "POST", 20, 3600),
    ("/api/reels/", "POST", 600, 3600),
    ("/api/blocks", "POST", 60, 3600),
    # Оценка фото — быстрое действие в один тап, лимит только против ботов
    ("/api/photo-ratings", "POST", 600, 3600),
    # Общий чат: антифлуд по минуте есть в роутере, здесь потолок за час
    ("/api/rooms", "POST", 200, 3600),
    # Свайпы — частое действие, лимит только против явных ботов
    ("/api/likes", "POST", 600, 3600),
    # Живая проверка: три кадра на запрос — дорого и по AI, и по CPU.
    # Суточный лимит отказов живёт в БД (routers/verification.py) и переживает
    # сбой Redis, поэтому путь не входит в _CRITICAL_PREFIXES.
    ("/api/verification", "POST", 20, 3600),
]

# Пути, где открытый лимит опаснее короткой недоступности сервиса: перебор кода
# привязки, спам жалобами, штамповка гостей, поток загрузок. Если Redis отвалился,
# по ним закрываемся (503), а не пропускаем — иначе окно недоступности кеша
# становится окном для брутфорса и спама. Остальные пути при сбое Redis
# пропускаются: лента и свайпы важнее лимита.
_CRITICAL_PREFIXES = {
    "/api/report",
    "/api/auth/link",
    "/api/auth/dev",
    "/api/auth/telegram",
    "/api/upload",
}


def _find_limit(path: str, method: str) -> tuple[str, int, int] | None:
    best: tuple[str, int, int] | None = None
    for prefix, meth, limit, window in LIMITS:
        if method == meth and path.startswith(prefix):
            if best is None or len(prefix) > len(best[0]):
                best = (prefix, limit, window)
    return best


def _client_ip(request: Request) -> str:
    """Адрес клиента с учётом доверенного прокси.

    За обратным прокси (Railway) настоящий адрес — не первый элемент
    X-Forwarded-For, а N-й справа, где N = TRUSTED_PROXY_COUNT (число
    прокси, которые сами дописывают заголовок). Левые элементы подставляет
    сам клиент, и брать их как ключ лимита — значит отдать ему ручку от
    счётчика: меняя заголовок, он крутит ключ и обходит лимит. При
    TRUSTED_PROXY_COUNT=0 заголовку не доверяем вовсе и берём адрес TCP-пира.
    """
    depth = settings.TRUSTED_PROXY_COUNT
    if depth > 0:
        forwarded = request.headers.get("x-forwarded-for", "")
        parts = [p.strip() for p in forwarded.split(",") if p.strip()]
        if parts:
            # N-й справа: за depth прокси столько элементов справа они и
            # добавили. Если клиент подставил лишние слева — они игнорируются.
            idx = max(0, len(parts) - depth)
            return parts[idx]
    return request.client.host if request.client else "unknown"


def _client_key(request: Request) -> str:
    """Идентификатор источника запроса.

    Ключ — user_id из ПРОВЕРЕННОГО токена, иначе IP. Раньше ключом служил
    хвост заголовка Authorization как есть, без проверки подписи, — и на
    неавторизованных путях это отдавало атакующему ручку от счётчика: меняя
    выдуманный «токен» на каждый запрос, он каждый раз начинал счёт с нуля и
    перебирал шестизначный код /api/auth/link без ограничений (лимит попыток
    в самих кодах — на каждый код отдельно и от перебора разных кодов не
    спасает). Проверка подписи закрывает и вторую лазейку: свежий валидный
    JWT на каждый запрос (iat/jti в нём меняются) давал новый хвост — а
    user_id у всех токенов одного человека один, ключ не сдвигается.

    Токен предпочтительнее IP: за одним мобильным NAT сидят тысячи людей,
    и лимит по адресу задел бы их всех. IP остаётся для неавторизованных
    путей и для мусорных токенов.
    """
    auth = request.headers.get("authorization", "")
    if auth.startswith("Bearer "):
        try:
            payload = jwt.decode(
                auth[7:], settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM]
            )
            uid = payload.get("sub")
            if uid:
                return f"u:{uid}"
        except JWTError:
            # Подделка, мусор или истёкший токен — считаем как анонима, по IP
            pass

    return f"ip:{_client_ip(request)}"


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
            logger.error(f"Rate limit check failed ({prefix}): {e}")
            # Для чувствительных путей закрываемся: открытый лимит там опаснее
            # короткой недоступности (см. _CRITICAL_PREFIXES). Для остальных
            # лимит — защита, а не условие работы сервиса, поэтому пропускаем.
            if prefix in _CRITICAL_PREFIXES:
                return JSONResponse(
                    status_code=503,
                    content={"detail": "Сервис временно недоступен, попробуйте позже"},
                )
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
