"""Доставка сообщения в личный чат: запись, realtime и уведомления.

Сообщение в личку рождается в двух местах — из WebSocket (`routers/chat.py`) и
из пересыла ролика (`routers/reels.py`). Пока путь был один, фан-аут жил прямо
в обработчике сокета; второй источник его не повторил, и пересланный ролик
молча ложился в базу: собеседник с открытым чатом ничего не видел, пуш не
уходил, бот не узнавал. Это тот же сорт расхождения, что аудит нашёл в
`hide_age` — правильный код есть, но ровно в одной копии.

Поэтому запись и фан-аут лежат здесь, а роутеры только вызывают. Порядок
важен: сначала коммит, потом рассылка. Событие о несохранённом сообщении хуже,
чем сохранённое сообщение без события, — второе исправит перезагрузка чата.
"""

from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy import and_, select

from database.connection import async_session_factory
from models.models import Match, Message, Profile, Reel
from services.push import is_configured, notify_new_message
from services.realtime import publish_bot_event
from services.ws_manager import manager

logger = logging.getLogger(__name__)

#: Чем короткое уведомление подписывает пересланный ролик. В пуше и в Telegram
#: нельзя показать само видео, а «прислал сообщение» без подписи непонятно.
REEL_FALLBACK_TEXT = "прислал видео"


def reel_preview(reel: Reel | None) -> dict | None:
    """Превью ролика для сообщения — единая форма для REST и для WebSocket.

    Скрытый модерацией ролик не отдаём даже в старой переписке: снятое с показа
    видео не должно продолжать ходить по чатам.
    """
    if not reel or reel.is_hidden:
        return None
    return {
        "id": reel.id,
        "video_url": reel.video_url,
        "cover_url": reel.cover_url,
        "caption": reel.caption,
    }


async def save_message(
    match_id: str,
    sender_id: str,
    text: str,
    image_url: Optional[str] = None,
    reel_id: Optional[str] = None,
) -> Optional[dict]:
    """Сохранить сообщение и собрать payload события. None — мэтч уже неактивен.

    Мэтч перепроверяется здесь, а не только у вызывающего: сокет живёт долго и
    пару могли развести, пока он был открыт.
    """
    async with async_session_factory() as session:
        async with session.begin():
            result = await session.execute(
                select(Match).where(and_(Match.id == match_id, Match.is_active == True))  # noqa: E712
            )
            if not result.scalar_one_or_none():
                return None

            message = Message(
                match_id=match_id,
                sender_id=sender_id,
                text=text,
                image_url=image_url,
                reel_id=reel_id,
            )
            session.add(message)
            await session.flush()

            preview = None
            if reel_id:
                result = await session.execute(select(Reel).where(Reel.id == reel_id))
                preview = reel_preview(result.scalar_one_or_none())

            return {
                "type": "message",
                "id": message.id,
                "match_id": match_id,
                "sender_id": sender_id,
                "text": text,
                "image_url": image_url,
                # Форма та же, что у GET /matches/{id}/messages: иначе клиенту
                # пришлось бы рисовать пересланный ролик двумя разными ветками
                "reel": preview,
                "created_at": message.created_at.isoformat() if message.created_at else None,
            }


async def _push_notification(
    match_id: str, sender_id: str, receiver_id: str, text: str,
) -> None:
    """Пуш в iOS — своя сессия, сокет её не держит."""
    if not is_configured():
        return
    try:
        async with async_session_factory() as session:
            async with session.begin():
                result = await session.execute(
                    select(Profile.display_name).where(Profile.user_id == sender_id)
                )
                sender_name = result.scalar_one_or_none() or ""
                await notify_new_message(
                    session, receiver_id, sender_name, text, match_id,
                )
    except Exception as e:
        logger.error(f"Message push failed ({match_id}): {e}")


async def fan_out(
    payload: dict,
    match_id: str,
    sender_id: str,
    receiver_id: str,
    notify_text: str,
) -> None:
    """Разослать сохранённое сообщение: WebSocket, Telegram, пуш.

    `publish`, а не `broadcast`: собеседник может сидеть на другом инстансе API,
    туда событие дойдёт только через Redis.

    Telegram и пуш — только если получателя нет в чате ни на одном инстансе:
    иначе человек с открытым приложением получает то же сообщение трижды.
    """
    await manager.publish(match_id, payload)

    if await manager.is_user_online(match_id, receiver_id):
        return

    await publish_bot_event({
        "type": "new_message",
        "match_id": match_id,
        "sender_id": sender_id,
        "receiver_id": receiver_id,
        "text": notify_text[:200],
    })
    await _push_notification(match_id, sender_id, receiver_id, notify_text)
