"""Отзыв выданных JWT.

Токен живёт 72 часа и проверяется только по подписи — без внешнего списка
отозвать конкретную сессию нельзя. Бан ловится отдельно (`get_current_user`
читает `is_banned` из БД на каждый запрос), но «выйти на украденном
устройстве» или разлогинить одну сессию этим не покрывается.

Здесь два уровня отзыва, оба в Redis с TTL не дольше жизни самого токена —
список не растёт бесконечно:

* по `jti` — гасит один конкретный токен (выход из аккаунта);
* по пользователю (`revoked_before`) — гасит все токены, выданные до
  отметки времени (бан, «выйти на всех устройствах», угон аккаунта).

Токены без `jti`/`iat` считаются отозванными: доказать, что такой токен
выпущен после отметки отзыва, невозможно, а тихо пропускать его — значит
оставить обход всей проверки. Выпущенные до этого изменения токены
потребуют одного повторного входа.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from config import get_settings
from services.realtime import get_redis

settings = get_settings()
logger = logging.getLogger(__name__)

_JTI_PREFIX = "dating:jwt:revoked:"
_USER_PREFIX = "dating:jwt:revoked_before:"

# Отзыв по пользователю должен жить хотя бы столько же, сколько самый свежий
# токен на момент отзыва, иначе запись истечёт раньше токенов, которые гасит.
_USER_TTL_SECONDS = settings.JWT_ACCESS_EXPIRE_HOURS * 3600


def _now_ts() -> int:
    return int(datetime.now(timezone.utc).timestamp())


async def revoke_token(payload: dict) -> bool:
    """Отозвать один токен по его `jti`. Возвращает False, если не удалось."""
    jti = payload.get("jti")
    if not jti:
        return False

    # TTL ровно до истечения токена: после этого он мёртв и без списка
    ttl = int(payload.get("exp", 0)) - _now_ts()
    if ttl <= 0:
        return True  # уже истёк — отзывать нечего

    try:
        r = await get_redis()
        await r.set(f"{_JTI_PREFIX}{jti}", "1", ex=ttl)
        return True
    except Exception as e:
        logger.error(f"Token revoke failed (jti={jti}): {e}")
        return False


async def revoke_all_for_user(user_id: str) -> bool:
    """Отозвать все токены пользователя, выданные до текущего момента."""
    try:
        r = await get_redis()
        await r.set(f"{_USER_PREFIX}{user_id}", str(_now_ts()), ex=_USER_TTL_SECONDS)
        return True
    except Exception as e:
        logger.error(f"User tokens revoke failed (user={user_id}): {e}")
        return False


async def clear_user_revocation(user_id: str) -> None:
    """Снять отзыв по пользователю — при разбане, чтобы он смог войти снова."""
    try:
        r = await get_redis()
        await r.delete(f"{_USER_PREFIX}{user_id}")
    except Exception as e:
        logger.error(f"User revocation clear failed (user={user_id}): {e}")


async def is_revoked(payload: dict) -> bool:
    """Отозван ли токен — по `jti` или по отметке отзыва пользователя.

    При недоступном Redis пропускаем токен: бан всё равно проверяется по БД
    на каждом запросе, а падение кеша не должно разлогинивать весь сервис.
    """
    jti = payload.get("jti")
    iat = payload.get("iat")
    user_id = payload.get("sub")

    # Токен старого формата: проверить его принадлежность к отозванным нельзя
    if not jti or not iat:
        return True

    try:
        r = await get_redis()
        if await r.exists(f"{_JTI_PREFIX}{jti}"):
            return True

        revoked_before = await r.get(f"{_USER_PREFIX}{user_id}") if user_id else None
        # `iat` в JWT — целые секунды, поэтому токен, выпущенный в ту же
        # секунду, что и отзыв, неотличим от выпущенного мгновением раньше.
        # Гасим и его: лишний повторный вход дешевле, чем угнанная сессия,
        # живущая 72 часа.
        if revoked_before and int(iat) <= int(revoked_before):
            return True
    except Exception as e:
        logger.error(f"Revocation check failed (user={user_id}): {e}")
        return False

    return False
