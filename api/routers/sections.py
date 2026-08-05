"""Учёт открытий разделов — основание решать по цифрам, а не по вкусу.

Клиент сообщает, что человек открыл раздел. Ответ пустой и ошибок не даёт:
аналитика не должна ломать экран, который она измеряет.

Сводка доступна админу: по ней видно, какие разделы держат людей, а какие
только занимают место в навигации.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import and_, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from database.connection import get_session
from middleware.admin_auth import require_admin
from middleware.auth import get_current_user
from models.models import SectionOpen, User
from models.schemas import SectionStat, SectionStats

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/sections", tags=["sections"])

#: Что считаем. Незнакомый код игнорируем: иначе опечатка в клиенте создаст
#: раздел-призрак, и сводка перестанет быть читаемой.
KNOWN_SECTIONS = frozenset(
    {"reels", "rooms", "voice", "photo_ratings", "cases", "leaderboard", "daily"}
)


@router.post("/{section}/open", status_code=204)
async def record_open(
    section: str,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """Отметить открытие раздела."""
    if section not in KNOWN_SECTIONS:
        # Молча игнорируем: падать на аналитике незачем, а мусор в сводку
        # пускать нельзя
        return Response(status_code=204)

    try:
        await session.execute(
            pg_insert(SectionOpen)
            .values(user_id=user.id, section=section, opens=1)
            .on_conflict_do_update(
                constraint="uq_section_open",
                set_={
                    "opens": SectionOpen.opens + 1,
                    "last_open_at": datetime.now(timezone.utc),
                },
            )
        )
        await session.commit()
    except Exception as e:
        logger.warning(f"Не удалось записать открытие раздела {section}: {e}")

    return Response(status_code=204)


@router.get("/stats", response_model=SectionStats)
async def get_section_stats(
    days: int = Query(default=30, ge=1, le=365),
    user: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    """Сводка по разделам: сколько людей заходило и сколько всего открытий.

    `users` важнее `opens`: один энтузиаст, открывший кейсы двести раз, не
    означает, что кейсы нужны продукту.
    """
    since = datetime.now(timezone.utc) - timedelta(days=days)

    result = await session.execute(
        select(
            SectionOpen.section,
            func.count(SectionOpen.id),
            func.sum(SectionOpen.opens),
        )
        .where(SectionOpen.last_open_at >= since)
        .group_by(SectionOpen.section)
    )
    rows = {row[0]: (row[1], row[2] or 0) for row in result.all()}

    result = await session.execute(
        select(func.count(User.id)).where(and_(
            User.is_banned == False,  # noqa: E712
            User.created_at <= datetime.now(timezone.utc),
        ))
    )
    total_users = result.scalar() or 0

    # Разделы без единого открытия тоже показываем: пустая строка — самый
    # честный аргумент за удаление
    stats = [
        SectionStat(
            section=section,
            users=rows.get(section, (0, 0))[0],
            opens=rows.get(section, (0, 0))[1],
            reach_percent=(
                round(rows.get(section, (0, 0))[0] * 100 / total_users)
                if total_users
                else 0
            ),
        )
        for section in sorted(KNOWN_SECTIONS)
    ]
    stats.sort(key=lambda s: s.users, reverse=True)

    return SectionStats(days=days, total_users=total_users, sections=stats)
