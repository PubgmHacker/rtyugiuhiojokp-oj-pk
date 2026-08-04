from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy import select, update, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession

from database.connection import async_session_factory
from middleware.auth import verify_access_token
from models.models import Match, Message, User
from services.ws_manager import manager
from services.realtime import publish_bot_event

logger = logging.getLogger(__name__)
router = APIRouter(tags=["chat"])


async def _ws_auth(websocket: WebSocket) -> str | None:
    """Аутентификация WebSocket через query param token."""
    token = websocket.query_params.get("token")
    if not token:
        await websocket.close(code=4001, reason="No token")
        return None
    try:
        payload = verify_access_token(token)
        user_id = payload.get("sub")
    except Exception:
        await websocket.close(code=4001, reason="Invalid token")
        return None

    # Токен валиден — но пользователь мог быть удалён/забанен после выдачи
    async with async_session_factory() as session:
        result = await session.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if not user or user.is_banned:
            await websocket.close(code=4003, reason="Forbidden")
            return None

    return user_id


async def _save_message(match_id: str, sender_id: str, text: str, image_url: str | None) -> dict | None:
    async with async_session_factory() as session:
        async with session.begin():
            # Мэтч мог быть разорван, пока сокет открыт
            result = await session.execute(
                select(Match).where(and_(Match.id == match_id, Match.is_active == True))
            )
            if not result.scalar_one_or_none():
                return None

            message = Message(
                match_id=match_id, sender_id=sender_id,
                text=text, image_url=image_url,
            )
            session.add(message)
            await session.flush()
            return {
                "type": "message",
                "id": message.id,
                "match_id": match_id,
                "sender_id": sender_id,
                "text": text,
                "image_url": image_url,
                "created_at": message.created_at.isoformat() if message.created_at else None,
            }


async def _mark_read(match_id: str, reader_id: str) -> None:
    """Отметить прочитанными все входящие сообщения в мэтче."""
    async with async_session_factory() as session:
        async with session.begin():
            await session.execute(
                update(Message)
                .where(and_(
                    Message.match_id == match_id,
                    Message.sender_id != reader_id,
                    Message.read_at.is_(None),
                ))
                .values(read_at=datetime.now(timezone.utc))
            )


@router.websocket("/ws/chat/{match_id}")
async def websocket_chat(websocket: WebSocket, match_id: str):
    """Real-time чат для мэтча: message / typing / read."""
    user_id = await _ws_auth(websocket)
    if not user_id:
        return

    await websocket.accept()

    async with async_session_factory() as session:
        result = await session.execute(
            select(Match).where(and_(
                Match.id == match_id,
                or_(Match.user1_id == user_id, Match.user2_id == user_id),
                Match.is_active == True,
            ))
        )
        match = result.scalar_one_or_none()
        if not match:
            await websocket.close(code=4004, reason="Match not found")
            return
        partner_id = match.user2_id if match.user1_id == user_id else match.user1_id

    await manager.connect(match_id, websocket, user_id)

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                continue

            msg_type = data.get("type", "message")

            # Любая активность продлевает присутствие: по нему решается,
            # дублировать ли сообщение в Telegram
            await manager.refresh_presence(match_id, user_id)

            if msg_type == "ping":
                continue

            if msg_type == "typing":
                await manager.publish(
                    match_id,
                    {"type": "typing", "user_id": user_id},
                    exclude=websocket,
                )
                continue

            if msg_type == "read":
                await _mark_read(match_id, user_id)
                await manager.publish(
                    match_id,
                    {"type": "read", "reader_id": user_id},
                    exclude=websocket,
                )
                continue

            # Обычное сообщение
            text = str(data.get("text", "")).strip()[:2000]
            image_url = data.get("image_url")
            if not text and not image_url:
                continue

            payload = await _save_message(match_id, user_id, text, image_url)
            if payload is None:
                await websocket.close(code=4004, reason="Match is no longer active")
                break
            # publish, а не broadcast: собеседник может сидеть на другом
            # инстансе API, до него событие дойдёт только через Redis
            await manager.publish(match_id, payload)

            # Партнёр не в чате (ни на одном инстансе) — уведомляем в Telegram
            if not await manager.is_user_online(match_id, partner_id):
                await publish_bot_event({
                    "type": "new_message",
                    "match_id": match_id,
                    "sender_id": user_id,
                    "receiver_id": partner_id,
                    "text": text[:200],
                })

    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.error(f"WS chat error: {e}")
    finally:
        manager.disconnect(match_id, websocket)
