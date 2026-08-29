"""Топ по лайкам — публичный рейтинг анкет за неделю.

Считаем за окно, а не за всё время: вечный рейтинг занимают те, кто
зарегистрировался раньше, и новичку в него не попасть никогда — а значит и
смысла стараться нет.

Инкогнито, забаненные и заблокированные в рейтинг не идут. Своё место человек
видит всегда, даже если оно вне первой десятки: без этого рейтинг не мотивирует,
а только расстраивает.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import and_, desc, func, not_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from database.connection import get_session
from middleware.auth import get_current_user
from models.models import Block, Like, Profile, User
from models.schemas import LeaderboardEntry, LeaderboardOut
from utils import public_photos

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/leaderboard", tags=["leaderboard"])

#: За какой период считаем лайки по умолчанию (таб «неделя»).
WINDOW_DAYS = 7
#: Сколько мест в публичном топе.
TOP_SIZE = 20


def _window_start(period: str) -> datetime:
    """Начало окна для выбранного периода.

    «Сегодня» — от начала текущих суток в UTC, а не «последние 24 часа»:
    иначе в 23:59 таб «сегодня» показывал бы почти то же самое, что «неделя»,
    и не сбрасывался бы заново после полуночи. Тот же приём с naive/aware,
    что и в admin.py: считаем в aware UTC от `datetime.now`, а не берём
    полночь из БД, где хранение не всегда aware.
    """
    now = datetime.now(timezone.utc)
    if period == "today":
        return now.replace(hour=0, minute=0, second=0, microsecond=0)
    return now - timedelta(days=WINDOW_DAYS)


async def _ranked_rows(
    session: AsyncSession, hidden: set[str], viewer_id: str, period: str
) -> list[tuple[str, int]]:
    """(user_id, лайков) по убыванию за окно.

    Считаем в БД, а не в Python: выгружать все лайки за неделю ради сортировки
    значило бы тащить в память таблицу, которая растёт быстрее всех прочих.

    Просивших не показывать себя в чужих списках в рейтинг не берём — публичный
    топ видно вообще всем, это сильнее «Гостей». Исключение — сам смотрящий:
    своё место человек должен видеть независимо от настроек, иначе он просто
    не поймёт, работает ли рейтинг.
    """
    conditions = [
        Like.created_at >= _window_start(period),
        Like.type != "pass",
        User.is_banned == False,  # noqa: E712 — SQL-выражение
        Profile.display_name != "",
        # Инкогнито и «не показывать в списках» скрывают из чужого топа, но не
        # от самого себя
        or_(
            Like.liked_id == viewer_id,
            and_(
                not_(Profile.is_incognito),
                not_(Profile.is_paused),
                not_(Profile.hide_from_visitors),
            ),
        ),
    ]
    if hidden:
        conditions.append(not_(Like.liked_id.in_(hidden)))

    result = await session.execute(
        select(Like.liked_id, func.count(Like.id).label("cnt"))
        .join(User, Like.liked_id == User.id)
        .join(Profile, Profile.user_id == Like.liked_id)
        .where(and_(*conditions))
        .group_by(Like.liked_id)
        .order_by(desc("cnt"))
        # Берём с запасом: часть мест уйдёт под своё место и дубли не нужны
        .limit(TOP_SIZE * 2)
    )
    return [(row[0], row[1]) for row in result.all()]


@router.get("", response_model=LeaderboardOut)
async def get_leaderboard(
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
    limit: int = Query(default=TOP_SIZE, ge=3, le=TOP_SIZE),
    period: str = Query(default="week", pattern="^(today|week)$"),
):
    """Топ анкет по лайкам за период (сегодня/неделя) плюс своё место."""
    result = await session.execute(select(Block.blocked_id).where(Block.blocker_id == user.id))
    hidden = {row[0] for row in result.all()}
    result = await session.execute(select(Block.blocker_id).where(Block.blocked_id == user.id))
    hidden |= {row[0] for row in result.all()}

    rows = await _ranked_rows(session, hidden, user.id, period)
    top = rows[:limit]

    profiles_by_id: dict[str, Profile] = {}
    if top:
        result = await session.execute(
            select(Profile).where(Profile.user_id.in_([uid for uid, _ in top]))
        )
        profiles_by_id = {p.user_id: p for p in result.scalars().all()}

    entries = [
        LeaderboardEntry(
            place=index + 1,
            user_id=uid,
            display_name=(profiles_by_id[uid].display_name if uid in profiles_by_id else ""),
            photo=(
                public_photos(profiles_by_id[uid].photos)[0]
                if uid in profiles_by_id and public_photos(profiles_by_id[uid].photos)
                else ""
            ),
            likes=count,
            is_me=uid == user.id,
        )
        for index, (uid, count) in enumerate(top)
    ]

    # Своё место ищем по полному списку, а не по срезу: попадание в топ-20 —
    # редкость, а знать, насколько ты близко, интересно каждому
    my_place = next((i + 1 for i, (uid, _) in enumerate(rows) if uid == user.id), None)
    my_likes = next((count for uid, count in rows if uid == user.id), 0)

    return LeaderboardOut(
        window_days=1 if period == "today" else WINDOW_DAYS,
        period=period,
        entries=entries,
        my_place=my_place,
        my_likes=my_likes,
        # Ниже последнего посчитанного места точное значение неизвестно —
        # честнее сказать «вне рейтинга», чем выдумать номер
        my_place_exact=my_place is not None,
    )
