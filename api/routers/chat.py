from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy import select, update, and_, or_

from database.connection import async_session_factory
from middleware.auth import verify_access_token
from models.models import Match, Message, User
from services.ws_manager import manager
from services.ai_moderation import log_moderation, moderate_text
from services.enforcement import TEXT_BAN_REASONS, register_text_strike
from services.chat_delivery import ДоставкаОтклонена, fan_out, save_message
from services.token_revocation import is_revoked
from services.quotas import open_match

logger = logging.getLogger(__name__)
router = APIRouter(tags=["chat"])


async def _ws_auth(websocket: WebSocket) -> tuple[str, dict] | None:
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

    # Сессия могла быть отозвана уже после выдачи токена
    if await is_revoked(payload):
        await websocket.close(code=4001, reason="Token revoked")
        return None

    # Токен валиден — но пользователь мог быть удалён/забанен после выдачи
    async with async_session_factory() as session:
        result = await session.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if not user or user.is_banned:
            await websocket.close(code=4003, reason="Forbidden")
            return None

    return user_id, payload


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
    auth = await _ws_auth(websocket)
    if not auth:
        return
    user_id, token_payload = auth

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

        # Суточный лимит открытых мэтчей: сокет — такой же вход в беседу, как
        # `GET /matches/{id}/messages`, и незакрытый обнулял бы лимит целиком.
        # Коммит здесь свой: сессия ручная, зависимость её не доведёт.
        итог = await open_match(session, user_id, match_id)
        if not итог.granted:
            await session.rollback()
            await websocket.close(code=4029, reason="Daily match limit")
            return
        await session.commit()

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

            # Бан или выход рвут и уже открытый сокет: проверка при коннекте
            # не помогает тому, кто подключился минуту назад
            if await is_revoked(token_payload):
                await websocket.close(code=4001, reason="Token revoked")
                break

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

            # Личный чат — самый объёмный канал, и до сих пор единственный
            # немодерируемый: bio, текст лайка и сообщения в комнатах
            # проверяются, а здесь можно было писать что угодно. Заблокировать
            # отправителя собеседник может, но сообщение он уже прочитал.
            if text:
                verdict = await moderate_text(text)
                await log_moderation(user_id, "chat_message", text, verdict)
                if verdict["blocked"]:
                    # Нарушение — страйк, как в REST-точках. Сессия своя:
                    # у сокета нет сессии запроса, а бан должен закоммититься
                    # немедленно, не дожидаясь конца соединения.
                    исход = None
                    try:
                        async with async_session_factory() as ban_session:
                            result = await ban_session.execute(
                                select(User).where(User.id == user_id)
                            )
                            нарушитель = result.scalar_one_or_none()
                            if нарушитель is not None:
                                исход = await register_text_strike(
                                    ban_session, нарушитель, verdict
                                )
                                await ban_session.commit()
                    except Exception as e:
                        # Сбой страйка не отменяет отказ: сообщение всё равно
                        # не уходит, эскалация просто подождёт следующего раза
                        logger.error(f"WS chat: страйк не записан: {e}")

                    if исход is not None and исход.banned:
                        # Токены уже отозваны баном — сокет доживал бы до
                        # следующего сообщения; закрываем сразу и явно
                        await websocket.send_json({
                            "type": "banned",
                            "reason": TEXT_BAN_REASONS[исход.category],
                            "banned_until": (
                                исход.banned_until.isoformat()
                                if исход.banned_until else None
                            ),
                        })
                        await websocket.close(code=4003, reason="Banned")
                        break

                    # Не рвём сокет: человек мог ошибиться формулировкой, а
                    # разрыв соединения выглядит как поломка приложения
                    счёт = f" {исход.warning_text()}" if исход is not None else ""
                    await websocket.send_json({
                        "type": "rejected",
                        "reason": f"Сообщение нарушает правила.{счёт}",
                    })
                    continue

            # Правила чата (чужая картинка, «одно письмо до ответа») проверяет
            # `save_message` — в одной транзакции с записью и под локом на
            # беседу. Здесь их было не удержать: сокет проверял свежий мэтч
            # отдельной сессией, и между проверкой и вставкой успевал пройти
            # второй кадр из того же соединения
            try:
                payload = await save_message(match_id, user_id, text, image_url)
            except ДоставкаОтклонена as отказ:
                await websocket.send_json({"type": "rejected", "reason": отказ.detail})
                continue
            if payload is None:
                await websocket.close(code=4004, reason="Match is no longer active")
                break
            await fan_out(payload, match_id, user_id, partner_id, text)

    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.error(f"WS chat error: {e}")
    finally:
        manager.disconnect(match_id, websocket)
