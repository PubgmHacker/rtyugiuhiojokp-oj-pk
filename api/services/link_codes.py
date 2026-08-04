"""Одноразовые коды привязки для нативного приложения.

В Telegram Mini App личность подтверждается через initData, но в нативной
сборке (Capacitor, собственный WKWebView) initData не существует — и без
отдельного механизма пользователь iOS-приложения не может войти вообще.

Схема: в боте команда `/link` выдаёт шестизначный код, пользователь вводит
его в приложении, сервер обменивает код на JWT. Код живёт минуты, гасится
при первом использовании и не переиспользуется — поэтому перехват кода из
чужого чата даёт слишком мало времени, а повтор не работает.

Коды лежат в Redis: они короткоживущие, и БД для них не нужна. Если Redis
недоступен, привязка честно отказывает вместо тихого пропуска.
"""

from __future__ import annotations

import logging
import secrets

from services.realtime import get_redis

logger = logging.getLogger(__name__)

CODE_TTL = 600  # 10 минут — успеть переключиться из Telegram в приложение
CODE_LENGTH = 6

# Попыток ввода на код: защита от подбора шестизначного числа
MAX_ATTEMPTS = 5


def _code_key(code: str) -> str:
    return f"dating:linkcode:{code}"


def _attempts_key(code: str) -> str:
    return f"dating:linkcode:attempts:{code}"


def generate_code() -> str:
    """Случайный код без ведущего нуля — его теряют при копировании."""
    return str(secrets.randbelow(900_000) + 100_000)


async def issue_code(user_id: str) -> str | None:
    """Выдать код привязки для пользователя. None — Redis недоступен."""
    try:
        r = await get_redis()
        for _ in range(5):
            code = generate_code()
            # NX: не перетираем чужой активный код при коллизии
            if await r.set(_code_key(code), user_id, ex=CODE_TTL, nx=True):
                return code
        logger.error("Не удалось выделить свободный код привязки")
        return None
    except Exception as e:
        logger.error(f"Выдача кода привязки не удалась: {e}")
        return None


async def redeem_code(code: str) -> str | None:
    """Обменять код на user_id. Код гасится при первом успешном обмене."""
    code = code.strip().replace(" ", "")
    if not code.isdigit() or len(code) != CODE_LENGTH:
        return None

    try:
        r = await get_redis()

        # Счётчик попыток живёт столько же, сколько сам код
        attempts = await r.incr(_attempts_key(code))
        if attempts == 1:
            await r.expire(_attempts_key(code), CODE_TTL)
        if attempts > MAX_ATTEMPTS:
            await r.delete(_code_key(code))
            logger.warning("Код привязки погашен из-за перебора попыток")
            return None

        # GETDEL — атомарно: два одновременных ввода не войдут оба
        user_id = await r.getdel(_code_key(code))
        if user_id:
            await r.delete(_attempts_key(code))
        return user_id or None
    except Exception as e:
        logger.error(f"Обмен кода привязки не удался: {e}")
        return None
