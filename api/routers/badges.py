"""Счётчики для таббара — одним лёгким запросом при входе.

Бейджи «Чаты» и «Лайки» обязаны жить с первого кадра: раньше они
появлялись только после захода на сам экран, и вкладка с новым
сообщением выглядела пустой. Для мессенджера это провал базового
ожидания — Telegram и WhatsApp приучили, что цифра на вкладке видна
сразу.

Отдельный эндпоинт вместо полного GET /matches: список чатов тянет
профили, последние сообщения и стрики, а бейджу нужны два целых числа.
Клиент дёргает его на старте и при возвращении на вкладку — дешевле,
чем держать отдельный сокет ради двух цифр.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import and_, exists, func, or_, select
from sqlalchemy.orm import aliased
from sqlalchemy.ext.asyncio import AsyncSession

from database.connection import get_session
from middleware.auth import get_current_user
from models.models import Like, Match, Message, Notification, User
from models.schemas import BadgeCounts

router = APIRouter(prefix="/badges", tags=["badges"])


@router.get("", response_model=BadgeCounts)
async def get_badges(
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """Сколько непрочитанного ждёт человека. Условия не свои: сообщения
    считаются так же, как красятся строки в списке чатов
    (routers/matches.py), лайки — как строится «кто меня лайкнул»
    (routers/likes.py). Разошедшиеся формулы дали бы бейдж, который
    обещает больше, чем показывает экран."""
    messages = await session.scalar(
        select(func.count(Message.id))
        .join(Match, Message.match_id == Match.id)
        .where(and_(
            or_(Match.user1_id == user.id, Match.user2_id == user.id),
            Match.is_active == True,  # noqa: E712 — сравнение строит SQL
            Message.sender_id != user.id,
            Message.read_at.is_(None),
        ))
    )

    # Кого я уже оценил (лайк или пасс) — их лайки не считаются: на экране
    # «кто меня лайкнул» этих карточек тоже нет. Анти-джойн через NOT EXISTS,
    # а не NOT IN: NOT IN заставляет планировщик материализовать всю историю
    # оценок (и спотыкается о NULL-семантику), NOT EXISTS остаётся индексным
    # пробником по uq_like_pair — дека фильтрует себя так же.
    МояОценка = aliased(Like)
    likes = await session.scalar(
        select(func.count(Like.id))
        .join(User, Like.liker_id == User.id)
        .where(and_(
            Like.liked_id == user.id,
            Like.type != "pass",
            User.is_banned == False,  # noqa: E712 — сравнение строит SQL
            ~exists().where(and_(
                МояОценка.liker_id == user.id,
                МояОценка.liked_id == Like.liker_id,
            )),
        ))
    )

    # Красная точка колокольчика: формула та же, что в GET /notifications —
    # непрочитанное по всей ленте
    notifications = await session.scalar(
        select(func.count())
        .select_from(Notification)
        .where(and_(
            Notification.user_id == user.id,
            Notification.read_at.is_(None),
        ))
    )

    return BadgeCounts(
        messages=int(messages or 0),
        likes=int(likes or 0),
        notifications=int(notifications or 0),
    )
