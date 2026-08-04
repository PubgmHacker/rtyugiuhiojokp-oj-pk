"""Выдача одноразовых кодов привязки для нативного приложения.

Ключи и TTL обязаны совпадать с api/services/link_codes.py — код пишет бот,
а гасит его API при обмене на токен.
"""

from __future__ import annotations

import logging
import secrets

import redis.asyncio as redis

from config import REDIS_URL

logger = logging.getLogger(__name__)

CODE_TTL = 600  # 10 минут, как в API


async def issue_link_code(user_id: str) -> str | None:
    """Выдать код привязки. None — Redis недоступен, привязка невозможна."""
    try:
        r = redis.from_url(REDIS_URL, decode_responses=True)
        try:
            for _ in range(5):
                code = str(secrets.randbelow(900_000) + 100_000)
                # NX: не перетираем чужой активный код при коллизии
                if await r.set(f"dating:linkcode:{code}", user_id, ex=CODE_TTL, nx=True):
                    return code
            logger.error("Не удалось выделить свободный код привязки")
            return None
        finally:
            await r.aclose()
    except Exception as e:
        logger.error(f"Выдача кода привязки не удалась: {e}")
        return None
