from __future__ import annotations

import asyncio
import json
import logging

import redis.asyncio as redis

from config import REDIS_URL

logger = logging.getLogger(__name__)


async def _get_redis() -> redis.Redis:
    return redis.from_url(REDIS_URL, decode_responses=True)


async def publish_match_event(match_id: str, user1_id: str, user2_id: str):
    """Publish match event for bot Redis subscriber."""
    try:
        r = await _get_redis()
        data = {
            "type": "new_match",
            "match_id": match_id,
            "user1_id": user1_id,
            "user2_id": user2_id,
        }
        await r.publish("dating:bot:matches", json.dumps(data))
    except Exception as e:
        logger.error(f"Redis publish error: {e}")


async def publish_message_event(match_id: str, sender_id: str, text: str):
    """Publish message for real-time sync."""
    try:
        r = await _get_redis()
        data = {
            "type": "new_message",
            "match_id": match_id,
            "sender_id": sender_id,
            "text": text,
        }
        await r.publish(f"dating:match:{match_id}", json.dumps(data))
    except Exception as e:
        logger.error(f"Redis publish error: {e}")


async def start_redis_subscriber(bot):
    """Subscribe to Redis channels and forward events to Telegram users."""
    r = await _get_redis()
    pubsub = r.pubsub()

    await pubsub.subscribe("dating:bot:matches")

    logger.info("Redis subscriber started, listening for matches...")

    try:
        async for message in pubsub.listen():
            if message["type"] != "message":
                continue

            try:
                data = json.loads(message["data"])

                if data["type"] == "new_match":
                    match_id = data["match_id"]
                    user1_id = data["user1_id"]
                    user2_id = data["user2_id"]

                    # Notify both users
                    for uid in [user1_id, user2_id]:
                        await _notify_user_about_match(bot, uid, match_id)

            except Exception as e:
                logger.error(f"Redis message processing error: {e}")

    except asyncio.CancelledError:
        logger.info("Redis subscriber cancelled")
    finally:
        await pubsub.unsubscribe()
        await pubsub.aclose()
        await r.aclose()


async def _notify_user_about_match(bot, user_id: str, match_id: str):
    """Send match notification to Telegram user."""
    try:
        from database import get_user_by_id, get_match_partner

        user = await get_user_by_id(user_id)
        if not user or not user.get("telegram_id"):
            return

        partner = await get_match_partner(match_id, user_id)
        if not partner:
            return

        from texts import match_notification
        from config import BANNERS

        text = match_notification(partner)

        try:
            await bot.send_photo(
                chat_id=user["telegram_id"],
                photo=BANNERS["match"],
                caption=text,
            )
        except Exception as e:
            logger.warning(f"Failed to send match notification to {user['telegram_id']}: {e}")

    except Exception as e:
        logger.error(f"Match notification error: {e}")
