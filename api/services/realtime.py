from __future__ import annotations

import asyncio
import json
import logging
from typing import Optional

import redis.asyncio as redis

from config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)

_redis: Optional[redis.Redis] = None
#: Цикл, на котором создан клиент. BlockingConnectionPool держит
#: asyncio.Condition, привязанный к первому циклу, — клиент с прошлого
#: цикла на новом падает «Event loop is closed». В проде цикл один на
#: процесс и клиент создаётся ровно один раз; циклы сменяются только
#: в тестах (у каждого теста свой), там прежний клиент просто бросаем —
#: закрыть его нельзя, его соединения живут на уже мёртвом цикле.
_redis_цикл: Optional[object] = None


async def get_redis() -> redis.Redis:
    global _redis, _redis_цикл
    цикл = asyncio.get_running_loop()
    if _redis is None or _redis_цикл is not цикл:
        # Таймауты обязательны: без socket_timeout зависший Redis (blackhole
        # при сетевом сбое) вешает publish навсегда — вместе с обработчиком
        # запроса и его соединением к Postgres. Pubsub этого клиента не
        # страдает: ws_manager читает только get_message(timeout=1.0), то
        # есть каждый read ограничен секундой и до socket_timeout не доходит.
        # health_check пингует простоявшее соединение перед использованием —
        # иначе первый publish после тихого часа улетал бы в мёртвый сокет.
        # Пул именно Blocking: у обычного ConnectionPool max_connections —
        # это ОШИБКА «Too many connections» при исчерпании, и залп первой
        # волны (лимитер дёргает Redis на каждом запросе) отвечал бы 503
        # легитимным людям. BlockingConnectionPool ставит лишние запросы в
        # очередь за соединением (операции — миллисекунды), timeout=5 — предел
        # этого ожидания, после него честная ошибка вместо вечной очереди.
        pool = redis.BlockingConnectionPool.from_url(
            settings.REDIS_URL,
            decode_responses=True,
            socket_timeout=5.0,
            socket_connect_timeout=2.0,
            retry_on_timeout=True,
            health_check_interval=30,
            max_connections=50,
            timeout=5.0,
        )
        _redis = redis.Redis(connection_pool=pool)
        _redis_цикл = цикл
    return _redis


async def publish_match(
    user_id: str,
    partner_id: str,
    match_id: str,
    score: Optional[int] = None,
    reason: Optional[str] = None,
):
    """Опубликовать событие мэтча в Redis."""
    r = await get_redis()
    data = {
        "type": "match",
        "match_id": match_id,
        "partner_id": partner_id,
        "score": score,
        "reason": reason,
    }
    await r.publish(f"dating:user:{user_id}", json.dumps(data))
    logger.info(f"Match published: user={user_id} partner={partner_id}")


async def publish_new_like(receiver_id: str, liker_id: str):
    """Уведомить о новом лайке (web-канал + Telegram-бот)."""
    r = await get_redis()
    data = {"type": "new_like", "liker_id": liker_id}
    await r.publish(f"dating:user:{receiver_id}", json.dumps(data))
    await publish_bot_event({"type": "new_like", "receiver_id": receiver_id, "liker_id": liker_id})


async def publish_new_match_for_bot(match_id: str, user1_id: str, user2_id: str):
    """Опубликовать мэтч для Telegram-бота (отдельный канал)."""
    await publish_bot_event({
        "type": "new_match", "match_id": match_id,
        "user1_id": user1_id, "user2_id": user2_id,
    })


async def publish_bot_event(data: dict):
    """Событие для Telegram-бота (new_match / new_message / new_like)."""
    try:
        r = await get_redis()
        await r.publish("dating:bot:matches", json.dumps(data))
    except Exception as e:
        logger.error(f"Bot event publish failed: {e}")
