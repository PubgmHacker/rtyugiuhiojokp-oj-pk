"""Групповые чаты по интересам — способ познакомиться до мэтча.

Написать в общий чат проще, чем первым в личку, поэтому комнаты закрывают
разрыв между «увидел анкету» и «начал разговор».

Сообщения модерируются тем же фильтром, что и остальной публичный текст: в
личке собеседника можно заблокировать, а в общем чате грубость видят все.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, desc, func, not_, select
from sqlalchemy.ext.asyncio import AsyncSession

from database.connection import get_session
from middleware.auth import get_current_user
from models.models import Block, Profile, Room, RoomMessage, User
from models.schemas import (
    RoomMessageOut,
    RoomMessages,
    RoomOut,
    RoomSend,
    RoomsOut,
)
from services.ai_moderation import log_moderation, moderate_text
from utils import as_list

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/rooms", tags=["rooms"])

#: Сколько сообщений отдаём за раз.
PAGE_SIZE = 50
#: Антифлуд: сообщений за минуту от одного человека. Лимит в middleware общий
#: по пути, а этот — про поведение в конкретной комнате.
FLOOD_PER_MINUTE = 10


@router.get("", response_model=RoomsOut)
async def list_rooms(
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """Список комнат со счётчиком сообщений за сутки.

    Счётчик показывает, где сейчас живо: пустая комната без пометки выглядит
    так же, как активная, и человек уходит, не дождавшись ответа.
    """
    result = await session.execute(
        select(Room).where(Room.is_active == True).order_by(Room.title)  # noqa: E712
    )
    rooms = list(result.scalars().all())

    since = datetime.now(timezone.utc) - timedelta(days=1)
    result = await session.execute(
        select(RoomMessage.room_id, func.count(RoomMessage.id))
        .where(and_(RoomMessage.created_at >= since, RoomMessage.is_hidden == False))  # noqa: E712
        .group_by(RoomMessage.room_id)
    )
    counts = {row[0]: row[1] for row in result.all()}

    return RoomsOut(
        rooms=[
            RoomOut(
                id=r.id,
                slug=r.slug,
                title=r.title,
                description=r.description,
                city=r.city,
                messages_today=counts.get(r.id, 0),
            )
            for r in rooms
        ]
    )


async def _room_or_404(session: AsyncSession, room_id: str) -> Room:
    result = await session.execute(
        select(Room).where(and_(Room.id == room_id, Room.is_active == True))  # noqa: E712
    )
    room = result.scalar_one_or_none()
    if not room:
        raise HTTPException(status_code=404, detail="Комната не найдена")
    return room


@router.get("/{room_id}/messages", response_model=RoomMessages)
async def get_room_messages(
    room_id: str,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
    before: Optional[str] = Query(default=None),
):
    """История комнаты, свежие снизу.

    Сообщения заблокированных не показываем: человек заблокировал обидчика
    именно чтобы его не видеть, и общий чат не исключение.
    """
    await _room_or_404(session, room_id)

    result = await session.execute(select(Block.blocked_id).where(Block.blocker_id == user.id))
    hidden = {row[0] for row in result.all()}
    result = await session.execute(select(Block.blocker_id).where(Block.blocked_id == user.id))
    hidden |= {row[0] for row in result.all()}

    conditions = [
        RoomMessage.room_id == room_id,
        RoomMessage.is_hidden == False,  # noqa: E712
    ]
    if before:
        try:
            conditions.append(RoomMessage.created_at < datetime.fromisoformat(before))
        except ValueError:
            raise HTTPException(status_code=400, detail="Некорректный параметр before")

    result = await session.execute(
        select(RoomMessage)
        .where(and_(*conditions))
        .order_by(desc(RoomMessage.created_at))
        .limit(PAGE_SIZE * 2)
    )
    rows = [m for m in result.scalars().all() if m.sender_id not in hidden][:PAGE_SIZE]

    profiles: dict[str, Profile] = {}
    if rows:
        result = await session.execute(
            select(Profile).where(Profile.user_id.in_({m.sender_id for m in rows}))
        )
        profiles = {p.user_id: p for p in result.scalars().all()}

    # Разворачиваем: запрашивали свежие сверху, а читать удобнее снизу вверх
    rows.reverse()

    return RoomMessages(
        messages=[
            RoomMessageOut(
                id=m.id,
                sender_id=m.sender_id,
                sender_name=(profiles[m.sender_id].display_name if m.sender_id in profiles else ""),
                sender_photo=(
                    as_list(profiles[m.sender_id].photos)[0]
                    if m.sender_id in profiles and as_list(profiles[m.sender_id].photos)
                    else ""
                ),
                text=m.text,
                is_mine=m.sender_id == user.id,
                created_at=m.created_at,
            )
            for m in rows
        ],
        next_before=rows[0].created_at.isoformat() if rows else None,
    )


@router.post("/{room_id}/messages", response_model=RoomMessageOut, status_code=201)
async def send_room_message(
    room_id: str,
    data: RoomSend,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """Написать в комнату."""
    await _room_or_404(session, room_id)

    text = data.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="Пустое сообщение")

    # Антифлуд по комнате: общий лимит по пути не мешает залить одну комнату
    since = datetime.now(timezone.utc) - timedelta(minutes=1)
    result = await session.execute(
        select(func.count(RoomMessage.id)).where(and_(
            RoomMessage.sender_id == user.id,
            RoomMessage.created_at >= since,
        ))
    )
    if (result.scalar() or 0) >= FLOOD_PER_MINUTE:
        raise HTTPException(status_code=429, detail="Слишком много сообщений подряд")

    # В личке собеседника можно заблокировать, а в общем чате грубость видят
    # все — поэтому текст проверяем до публикации
    verdict = await moderate_text(text)
    await log_moderation(user.id, "room_message", text, verdict)
    if verdict["blocked"]:
        raise HTTPException(status_code=422, detail="Сообщение нарушает правила")

    message = RoomMessage(room_id=room_id, sender_id=user.id, text=text)
    session.add(message)
    await session.flush()

    result = await session.execute(select(Profile).where(Profile.user_id == user.id))
    profile = result.scalar_one_or_none()

    out = RoomMessageOut(
        id=message.id,
        sender_id=user.id,
        sender_name=profile.display_name if profile else "",
        sender_photo=(as_list(profile.photos)[0] if profile and as_list(profile.photos) else ""),
        text=message.text,
        is_mine=True,
        created_at=message.created_at,
    )
    await session.commit()
    return out
