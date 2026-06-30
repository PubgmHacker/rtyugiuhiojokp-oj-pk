from __future__ import annotations

import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from sqlalchemy import select, and_, or_, desc
from sqlalchemy.ext.asyncio import AsyncSession

from database.connection import get_session, async_session_factory
from middleware.auth import verify_access_token
from models.models import User, Match, Message

router = APIRouter(tags=["chat"])


async def _ws_auth(websocket: WebSocket) -> str | None:
    """Аутентификация WebSocket через query param token."""
    token = websocket.query_params.get("token")
    if not token:
        await websocket.close(code=4001, reason="No token")
        return None
    try:
        payload = verify_access_token(token)
        return payload.get("sub")
    except Exception:
        await websocket.close(code=4001, reason="Invalid token")
        return None


@router.websocket("/ws/chat/{match_id}")
async def websocket_chat(websocket: WebSocket, match_id: str):
    """Real-time чат для мэтча."""
    user_id = await _ws_auth(websocket)
    if not user_id:
        return

    await websocket.accept()

    # Verify match exists and user is part of it
    async with async_session_factory() as session:
        async with session.begin():
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

    try:
        while True:
            data = await websocket.receive_text()

            async with async_session_factory() as session:
                async with session.begin():
                    msg_data = json.loads(data) if isinstance(data, str) else data
                    text = msg_data.get("text", "").strip()
                    image_url = msg_data.get("image_url")

                    if not text and not image_url:
                        continue

                    message = Message(
                        match_id=match_id,
                        sender_id=user_id,
                        text=text,
                        image_url=image_url,
                    )
                    session.add(message)
                    await session.flush()

                    await websocket.send_json({
                        "type": "message",
                        "id": message.id,
                        "sender_id": message.sender_id,
                        "text": message.text,
                        "image_url": message.image_url,
                        "created_at": message.created_at.isoformat() if message.created_at else None,
                    })

    except WebSocketDisconnect:
        pass
