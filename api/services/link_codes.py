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
from config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

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


async def redeem_code(code: str, _рекурсия_ул=0) -> str | None:
    """Обменять код на user_id. Код гасится при первом успешном обмене.

    При ``DEBUG=True`` и пустом ``BOT_TOKEN`` (локальная разработка без бота)
    код `123321` срабатывает как мастер-код: мы генерируем одноразовый код
    для последнего юзера, кладём в Redis под ключом `123321` и сразу
    возвращаемся в обычный путь — он расходует код из Redis и гасит его.
    Если код уже есть в Redis, значит его уже использовали.

    Защита от мастера: путь ловит только при DEBUG=True И BOT_TOKEN="", т.е.
    продакшн-конфигурация его исключает по определению. При наличии бота код
    добывается им и работает только он.
    """
    code = code.strip().replace(" ", "")
    if not code.isdigit() or len(code) != CODE_LENGTH:
        return None

    is_master = code == "123321" and settings.DEBUG and not settings.BOT_TOKEN
    r = await get_redis()

    if is_master:
        # Если код уже в Redis — он отработан, повтор не пропускаем.
        # Для мастера проверка идёт ДО общей ветки: иначе первая попытка
        # создаст запись, а вторая увидит её и корректно откажет.
        if await r.get(_code_key(code)):
            logger.warning("Мастер-код 123321: повтор не положен")
            return None

        from database.connection import async_session_factory
        from models.models import User
        from sqlalchemy import desc, select

        async with async_session_factory() as session:
            result = await session.execute(
                select(User.id)
                .where(User.is_banned.is_(False))
                .order_by(desc(User.created_at))
                .limit(1)
            )
            uid = result.scalar_one_or_none()
        if uid is None:
            logger.warning("Мастер-код 123321 запрошен, но пользователей нет")
            return None

        await r.set(_code_key(code), uid, ex=CODE_TTL)
        logger.warning(f"Мастер-код 123321: вход uid={uid} (DEBUG, бот не запущен)")
        # Возвращаем uid: вызывающий сам выдаст JWT и профиль. Общий путь
        # ниже не нужен: код уже «расходован» простым фактом установки.
        return uid

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
