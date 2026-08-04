"""Визиты в анкету — раздел «Гости».

Запись идёт через UPSERT: визит либо создаётся, либо обновляет время и
счётчик одним запросом. Иначе на каждое открытие анкеты приходилось бы
делать SELECT и потом INSERT или UPDATE, а два одновременных открытия
падали бы на уникальном ключе.

Сам факт визита пишем всем — даже тем, кто не увидит раздел без подписки:
иначе купивший Ultra получил бы пустой список и решил, что фича не работает.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import and_, desc, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from models.models import Block, Profile, ProfileVisit, User

logger = logging.getLogger(__name__)


async def record_visit(session: AsyncSession, visitor_id: str, host_id: str) -> None:
    """Отметить, что visitor открыл анкету host.

    Свой заход не считаем: «вы заходили к себе» — бесполезная строка.
    Ошибку записи глушим: просмотр анкеты не должен падать из-за статистики.
    """
    if visitor_id == host_id:
        return

    try:
        stmt = (
            pg_insert(ProfileVisit)
            .values(visitor_id=visitor_id, host_id=host_id, visits=1)
            .on_conflict_do_update(
                constraint="uq_visit_pair",
                set_={
                    "visits": ProfileVisit.visits + 1,
                    "last_seen_at": datetime.now(timezone.utc),
                },
            )
        )
        await session.execute(stmt)
    except Exception as e:
        logger.warning(f"Не удалось записать визит {visitor_id}->{host_id}: {e}")


async def count_visits(session: AsyncSession, host_id: str) -> int:
    """Сколько всего гостей — число показываем и без подписки."""
    result = await session.execute(
        select(func.count(ProfileVisit.id)).where(ProfileVisit.host_id == host_id)
    )
    return result.scalar() or 0


async def list_visitors(
    session: AsyncSession, host_id: str, limit: int = 50
) -> list[tuple[Profile | None, str, int, datetime]]:
    """Гости с их анкетами: (профиль, id, сколько раз, когда последний раз).

    Заблокированные в обе стороны не показываются: жертва харассмента не
    должна видеть обидчика даже в списке визитов.
    """
    result = await session.execute(
        select(Block.blocked_id).where(Block.blocker_id == host_id)
    )
    hidden = {row[0] for row in result.all()}
    result = await session.execute(
        select(Block.blocker_id).where(Block.blocked_id == host_id)
    )
    hidden |= {row[0] for row in result.all()}

    query = (
        select(ProfileVisit, Profile)
        .join(User, ProfileVisit.visitor_id == User.id)
        .outerjoin(Profile, Profile.user_id == ProfileVisit.visitor_id)
        .where(and_(
            ProfileVisit.host_id == host_id,
            User.is_banned == False,  # noqa: E712 — SQL-выражение, не Python
        ))
        .order_by(desc(ProfileVisit.last_seen_at))
        .limit(limit)
    )
    result = await session.execute(query)

    out = []
    for visit, profile in result.all():
        if visit.visitor_id in hidden:
            continue
        out.append((profile, visit.visitor_id, visit.visits, visit.last_seen_at))
    return out
