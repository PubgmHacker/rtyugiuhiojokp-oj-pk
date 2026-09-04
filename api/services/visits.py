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
from utils import официальный

logger = logging.getLogger(__name__)


async def record_visit(session: AsyncSession, visitor_id: str, host_id: str) -> None:
    """Отметить, что visitor открыл анкету host.

    Свой заход не считаем: «вы заходили к себе» — бесполезная строка.
    Уважаем настройку гостя «не попадать в раздел Гости»: проверяем её здесь,
    а не при чтении, чтобы визит вообще не попал в базу — иначе включивший
    настройку позже всё равно остался бы в чужих списках.

    Ошибку записи глушим: просмотр анкеты не должен падать из-за статистики.
    """
    if visitor_id == host_id:
        return

    try:
        result = await session.execute(
            select(Profile.hide_from_visitors).where(Profile.user_id == visitor_id)
        )
        if result.scalar_one_or_none():
            return

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


async def count_visits(
    session: AsyncSession, host_id: str, since: datetime | None = None
) -> int:
    """Сколько всего гостей — число показываем и без подписки.

    `since` — нижняя граница по последнему заходу (см. раздел «Гости» с
    выбором периода). Визит — одна строка на пару с обновлением времени, а не
    журнал, поэтому фильтр по `last_seen_at` — единственный доступный способ
    понять, заходил ли гость «сегодня»/«на неделе»: более раннего визита от
    той же пары мы уже не помним.
    """
    conditions = [ProfileVisit.host_id == host_id]
    if since is not None:
        conditions.append(ProfileVisit.last_seen_at >= since)
    result = await session.execute(
        select(func.count(ProfileVisit.id)).where(and_(*conditions))
    )
    return result.scalar() or 0


async def list_visitors(
    session: AsyncSession, host_id: str, limit: int = 50, since: datetime | None = None
) -> list[tuple[Profile | None, str, int, datetime, bool]]:
    """Гости с их анкетами: (профиль, id, сколько раз, когда, галочка).

    Галочка едет тем же запросом: карточка гостя рисуется как карточка деки,
    а там она есть — отдельный запрос на неё был бы N+1.

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
        select(ProfileVisit, Profile, User.is_verified, User.role)
        .join(User, ProfileVisit.visitor_id == User.id)
        .outerjoin(Profile, Profile.user_id == ProfileVisit.visitor_id)
        .where(and_(
            ProfileVisit.host_id == host_id,
            User.is_banned == False,  # noqa: E712 — SQL-выражение, не Python
            *([ProfileVisit.last_seen_at >= since] if since is not None else []),
        ))
        .order_by(desc(ProfileVisit.last_seen_at))
        .limit(limit)
    )
    result = await session.execute(query)

    out = []
    for visit, profile, is_verified, role in result.all():
        if visit.visitor_id in hidden:
            continue
        out.append((
            profile, visit.visitor_id, visit.visits, visit.last_seen_at,
            bool(is_verified), официальный(role),
        ))
    return out
