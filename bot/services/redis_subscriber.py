from __future__ import annotations

import asyncio
import json
import logging

import redis.asyncio as redis

from config import REDIS_URL

logger = logging.getLogger(__name__)

#: Один клиент на процесс — как в `api/services/realtime.py`. Раньше здесь
#: стоял `redis.from_url` прямо в функции, и каждая публикация заводила НОВЫЙ
#: клиент с новым пулом соединений, который никто не закрывал. Публикация
#: происходит на каждое сообщение в чате (`handlers/matches.py`), так что бот
#: съедал по TCP-соединению на сообщение и упирался в `maxclients` Redis —
#: после чего переставали ходить вообще все события, включая мэтчи.
_redis: redis.Redis | None = None


async def _get_redis() -> redis.Redis:
    global _redis
    if _redis is None:
        _redis = redis.from_url(REDIS_URL, decode_responses=True)
    return _redis


async def close_redis() -> None:
    """Закрыть общий клиент — зовётся при остановке бота."""
    global _redis
    if _redis is not None:
        await _redis.aclose()
        _redis = None


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


async def publish_message_event(
    match_id: str,
    sender_id: str,
    text: str,
    message_id: str = "",
    created_at: str | None = None,
):
    """Publish message for real-time sync (web WS слушает канал dating:match:{id})."""
    try:
        r = await _get_redis()
        data = {
            "type": "message",
            "origin": "bot",
            "id": message_id,
            "match_id": match_id,
            "sender_id": sender_id,
            "text": text,
            "image_url": None,
            "created_at": created_at,
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
                event_type = data.get("type")

                if event_type == "new_match":
                    # Notify both users
                    for uid in [data["user1_id"], data["user2_id"]]:
                        await _notify_user_about_match(bot, uid, data["match_id"])

                elif event_type == "new_message":
                    await _notify_user_about_message(
                        bot, data["receiver_id"], data["sender_id"], data.get("text", ""),
                    )

                elif event_type == "new_like":
                    await _notify_user_about_like(bot, data["receiver_id"], data["liker_id"])

            except Exception as e:
                logger.error(f"Redis message processing error: {e}")

    except asyncio.CancelledError:
        logger.info("Redis subscriber cancelled")
    finally:
        await pubsub.unsubscribe()
        await pubsub.aclose()
        # Сам клиент здесь не закрываем: он общий на процесс (_get_redis),
        # и его закрытие из finally остановило бы все публикации и сделало бы
        # невозможным рестарт подписки.


async def supervise_redis_subscriber(bot, первая_пауза: float = 1.0) -> None:
    """Держать подписку живой, переподключаясь с ростом паузы.

    Без присмотра подписка — единственная точка отказа для ВСЕХ уведомлений в
    Telegram. У Redis pubsub нет ни персистентности, ни backpressure: когда
    исходящий буфер подписчика переполняется, Redis сам обрывает соединение,
    `async for` завершается, задача тихо умирает — и мэтчи, сообщения и лайки
    перестают доходить до людей насовсем, без единой строчки в логе.

    Пауза растёт до минуты, чтобы при лежащем Redis не молотить переподключения
    в пустоту. `CancelledError` пропускаем наружу: это штатная остановка бота.
    """
    пауза = первая_пауза
    while True:
        try:
            await start_redis_subscriber(bot)
            # Штатного выхода из подписки нет — значит соединение оборвали
            logger.warning("Redis subscriber exited, reconnecting in %.0fs", пауза)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error("Redis subscriber crashed (%s), reconnecting in %.0fs", e, пауза)
        await asyncio.sleep(пауза)
        пауза = min(пауза * 2, 60.0)


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


async def _notify_user_about_message(bot, receiver_id: str, sender_id: str, text: str):
    """Уведомить в Telegram о новом сообщении из web-чата."""
    try:
        from database import get_user_by_id, get_profile

        receiver = await get_user_by_id(receiver_id)
        if not receiver or not receiver.get("telegram_id"):
            return

        import html as _html

        sender = await get_profile(sender_id)
        sender_name = _html.escape((sender or {}).get("display_name") or "Ваш мэтч", quote=False)

        preview = (text[:100] + "…") if len(text) > 100 else text
        preview = _html.escape(preview, quote=False)
        await bot.send_message(
            chat_id=receiver["telegram_id"],
            text=f"💬 <b>{sender_name}</b> написал(а) вам:\n\n«{preview}»\n\n"
                 f"Откройте «💕 Мои мэтчи», чтобы ответить.",
        )
    except Exception as e:
        logger.error(f"Message notification error: {e}")


async def _notify_user_about_like(bot, receiver_id: str, liker_id: str):
    """Уведомить в Telegram о новом лайке из web-приложения (Дайвинчик-механика).

    Анкету лайкнувшего показываем только на Plus: «кто вас лайкнул» — платный
    гейт, и в мини-аппе он соблюдается. Этот путь — второй из пары (первый в
    handlers/dating.py), и раньше он тоже отдавал анкету бесплатно.
    """
    try:
        from database import get_user_by_id, get_profile
        from services.plans import видно_кто_лайкнул

        receiver = await get_user_by_id(receiver_id)
        if not receiver or not receiver.get("telegram_id"):
            return

        liker = await get_profile(liker_id)
        if not liker or not liker.get("display_name"):
            return

        if not await видно_кто_лайкнул(receiver_id):
            from keyboards import like_locked_kb
            import texts as T

            await bot.send_message(
                chat_id=receiver["telegram_id"],
                text=T.LIKE_LOCKED,
                reply_markup=like_locked_kb(),
            )
            return

        from handlers.dating import _render_profile_to_chat

        await bot.send_message(
            chat_id=receiver["telegram_id"],
            text="💌 Вы кому-то понравились! Взгляните на анкету:",
        )
        await _render_profile_to_chat(bot, receiver["telegram_id"], liker)
    except Exception as e:
        logger.error(f"Like notification error: {e}")
