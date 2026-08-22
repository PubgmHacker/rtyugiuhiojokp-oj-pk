"""Центр уведомлений — лента событий без собственного экрана.

Читается при открытии колокольчика, помечается прочитанным одним махом:
лента короткая, и «прочитать по одному» дало бы только лишние тапы и
лишние запросы. Красная точка на колокольчике едет из /badges вместе с
остальными счётчиками — свой сокет ради одной цифры не нужен.

Пагинации нет намеренно: отдаём последние 50, лента — не архив. Старые
события человек не листает, а «показать ещё» появится, когда появится
кому его нажимать.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from database.connection import get_session
from middleware.auth import get_current_user
from models.models import Notification, User
from models.schemas import NotificationOut, NotificationsPage

router = APIRouter(prefix="/notifications", tags=["notifications"])

#: Больше человек всё равно не читает, а свежие всегда сверху.
ЛИМИТ = 50


@router.get("", response_model=NotificationsPage)
async def list_notifications(
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """Лента с числом непрочитанных. unread считается по всей ленте, а не
    по срезу в 50: бейдж не должен обещать меньше, чем есть."""
    строки = (
        await session.scalars(
            select(Notification)
            .where(Notification.user_id == user.id)
            .order_by(Notification.created_at.desc(), Notification.id)
            .limit(ЛИМИТ)
        )
    ).all()
    непрочитанных = (
        await session.scalar(
            select(func.count())
            .select_from(Notification)
            .where(
                Notification.user_id == user.id,
                Notification.read_at.is_(None),
            )
        )
    ) or 0
    return NotificationsPage(
        items=[NotificationOut.model_validate(n, from_attributes=True) for n in строки],
        unread=int(непрочитанных),
    )


@router.post("/read")
async def mark_all_read(
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """Погасить всё непрочитанное. Идемпотентно: повторный вызов — ноль."""
    result = await session.execute(
        update(Notification)
        .where(
            Notification.user_id == user.id,
            Notification.read_at.is_(None),
        )
        .values(read_at=datetime.now(timezone.utc))
    )
    await session.flush()
    return {"read": int(result.rowcount or 0)}
