from __future__ import annotations

import json
import logging
from typing import Optional

import redis.asyncio as redis

from config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)

_redis: Optional[redis.Redis] = None


async def get_redis() -> redis.Redis:
    global _redis
    if _redis is None:
        _redis = redis.from_url(settings.REDIS_URL, decode_responses=True)
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
    """Уведомить о новом лайке."""
    r = await get_redis()
    data = {"type": "new_like", "liker_id": liker_id}
    await r.publish(f"dating:user:{receiver_id}", json.dumps(data))


async def publish_message(match_id: str, sender_id: str, text: str):
    """Опубликовать новое сообщение для WebSocket рассылки."""
    r = await get_redis()
    data = {"type": "message", "match_id": match_id, "sender_id": sender_id, "text": text}
    await r.publish(f"dating:match:{match_id}", json.dumps(data))


async def publish_new_match_for_bot(match_id: str, user1_id: str, user2_id: str):
    """Опубликовать мэтч для Telegram-бота (отдельный канал)."""
    r = await get_redis()
    data = {"type": "new_match", "match_id": match_id, "user1_id": user1_id, "user2_id": user2_id}
    await r.publish("dating:bot:matches", json.dumps(data))


async def cache_deck_profile(user_id: str, profile_ids: list[str], ttl: int = 3600):
    """Кешировать IDs показанных анкет (чтобы не повторять)."""
    r = await get_redis()
    key = f"dating:deck:viewed:{user_id}"
    for pid in profile_ids:
        await r.sadd(key, pid)
    await r.expire(key, ttl)


async def get_viewed_profile_ids(user_id: str) -> set[str]:
    """Получить множество уже показанных ID анкет."""
    r = await get_redis()
    key = f"dating:deck:viewed:{user_id}"
    return {x async for x in r.smembers(key)}


async def clear_viewed_profiles(user_id: str):
    """Сбросить кеш показанных анкет."""
    r = await get_redis()
    await r.delete(f"dating:deck:viewed:{user_id}")
