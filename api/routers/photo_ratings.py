"""Оценка фото — отдельный формат помимо свайпов.

Показываем чужое фото, человек ставит от 1 до 5. Заходить в приложение
становится зачем-то ещё, а анкета получает обратную связь: по средней оценке
видно, работает ли главное фото.

Оценка не влияет на подбор и никак не связана с лайками: превращать её в
скрытый рейтинг привлекательности, по которому выдаётся дека, значит делать
сервис, где «некрасивых» никто не видит.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, func, not_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from database.connection import get_session
from middleware.auth import get_current_user
from models.models import Block, PhotoRating, Profile, User
from models.schemas import (
    MyPhotoRating,
    PhotoRatingRequest,
    PhotoRatingTarget,
    PhotoRatingTargets,
)
from utils import as_list

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/photo-ratings", tags=["photo-ratings"])


@router.get("/queue", response_model=PhotoRatingTargets)
async def get_rating_queue(
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
    limit: int = Query(default=10, ge=1, le=30),
):
    """Чьи фото показать на оценку.

    Уже оценённых не показываем: переоценить можно только осознанно, а не
    случайно наткнувшись на то же лицо в очереди.
    """
    result = await session.execute(
        select(PhotoRating.target_id).where(PhotoRating.rater_id == user.id)
    )
    rated = {row[0] for row in result.all()}

    result = await session.execute(select(Block.blocked_id).where(Block.blocker_id == user.id))
    hidden = {row[0] for row in result.all()}
    result = await session.execute(select(Block.blocker_id).where(Block.blocked_id == user.id))
    hidden |= {row[0] for row in result.all()}

    exclude = rated | hidden | {user.id}

    conditions = [
        User.is_banned == False,  # noqa: E712 — SQL-выражение
        not_(Profile.is_incognito),
        Profile.display_name != "",
    ]
    if exclude:
        conditions.append(not_(Profile.user_id.in_(exclude)))

    result = await session.execute(
        select(Profile)
        .join(User, Profile.user_id == User.id)
        .where(and_(*conditions))
        # Тот же приём, что в деке: случайная точка по индексированному ключу
        # вместо ORDER BY random(), которому нужна сортировка всей таблицы.
        # Берём с запасом — анкеты без фото отсеются уже здесь, в Python:
        # в SQL так нельзя, тип JSON в Postgres не сравнивается на равенство
        .order_by(Profile.sample_key)
        .limit(limit * 3)
    )
    profiles = [p for p in result.scalars().all() if as_list(p.photos)][:limit]

    return PhotoRatingTargets(
        targets=[
            PhotoRatingTarget(
                user_id=p.user_id,
                display_name=p.display_name or "",
                photo=as_list(p.photos)[0],
            )
            for p in profiles
        ]
    )


@router.post("", status_code=204)
async def rate_photo(
    data: PhotoRatingRequest,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """Поставить оценку. Повторная оценка того же человека обновляет прежнюю."""
    if data.target_id == user.id:
        raise HTTPException(status_code=400, detail="Нельзя оценивать себя")

    result = await session.execute(select(User).where(User.id == data.target_id))
    target = result.scalar_one_or_none()
    if not target or target.is_banned:
        raise HTTPException(status_code=404, detail="Анкета не найдена")

    # UPSERT: два быстрых тапа подряд иначе упали бы на уникальном ключе
    await session.execute(
        pg_insert(PhotoRating)
        .values(rater_id=user.id, target_id=data.target_id, score=data.score)
        .on_conflict_do_update(
            constraint="uq_photo_rating",
            set_={"score": data.score, "updated_at": datetime.now(timezone.utc)},
        )
    )
    await session.commit()


@router.get("/mine", response_model=MyPhotoRating)
async def get_my_rating(
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """Средняя оценка своего фото и сколько человек оценили.

    Кто именно поставил — не показываем: оценка анонимна, иначе за тройку
    прилетит обида конкретному человеку, а честных оценок не станет.
    """
    result = await session.execute(
        select(func.avg(PhotoRating.score), func.count(PhotoRating.id)).where(
            PhotoRating.target_id == user.id
        )
    )
    average, total = result.one()

    result = await session.execute(select(Profile).where(Profile.user_id == user.id))
    profile = result.scalar_one_or_none()
    photos = as_list(profile.photos) if profile else []

    return MyPhotoRating(
        photo=photos[0] if photos else "",
        # Округляем до десятых: «4.3» понятно, «4.28571» — шум
        average=round(float(average), 1) if average is not None else None,
        total=total or 0,
    )
