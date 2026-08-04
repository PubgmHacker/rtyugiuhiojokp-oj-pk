from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import and_, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from database.connection import get_session
from middleware.auth import get_current_user
from models.models import Block, Like, Match, Profile, User
from models.schemas import UserProfile
from utils import as_list

router = APIRouter(prefix="/blocks", tags=["blocks"])


@router.post("/{target_id}")
async def block_user(
    target_id: str,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Заблокировать пользователя навсегда.

    Отличается от размэтча: тот лишь удаляет лайки, после чего пара может
    снова встретиться в деке и всё начнётся заново. Блокировка убирает обоих
    из выдачи друг друга и закрывает общий чат безвозвратно — это то, чего
    требует App Store Guideline 1.2 и чего ждёт человек, столкнувшийся
    с харассментом.
    """
    if target_id == user.id:
        raise HTTPException(status_code=400, detail="Cannot block yourself")

    result = await session.execute(select(User).where(User.id == target_id))
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="User not found")

    try:
        async with session.begin_nested():
            session.add(Block(blocker_id=user.id, blocked_id=target_id))
    except IntegrityError:
        # Уже заблокирован — повторный вызов не ошибка, результат тот же
        return {"success": True, "already_blocked": True}

    # Мэтч деактивируем, лайки в обе стороны убираем: иначе после снятия
    # блокировки пара мгновенно смэтчится заново старыми лайками
    result = await session.execute(
        select(Match).where(or_(
            and_(Match.user1_id == user.id, Match.user2_id == target_id),
            and_(Match.user1_id == target_id, Match.user2_id == user.id),
        ))
    )
    match = result.scalar_one_or_none()
    if match:
        match.is_active = False

    await session.execute(
        Like.__table__.delete().where(or_(
            and_(Like.liker_id == user.id, Like.liked_id == target_id),
            and_(Like.liker_id == target_id, Like.liked_id == user.id),
        ))
    )
    await session.flush()
    return {"success": True}


@router.delete("/{target_id}")
async def unblock_user(
    target_id: str,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Снять блокировку. Мэтч и лайки не восстанавливаются — знакомиться
    заново придётся с чистого листа, как с любым новым человеком."""
    await session.execute(
        Block.__table__.delete().where(and_(
            Block.blocker_id == user.id,
            Block.blocked_id == target_id,
        ))
    )
    await session.flush()
    return {"success": True}


@router.get("", response_model=list[UserProfile])
async def list_blocked(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Кого я заблокировал — экран управления блокировками."""
    result = await session.execute(
        select(Block.blocked_id).where(Block.blocker_id == user.id)
    )
    ids = [row[0] for row in result.all()]
    if not ids:
        return []

    result = await session.execute(select(Profile).where(Profile.user_id.in_(ids)))
    profiles = {p.user_id: p for p in result.scalars().all()}

    return [
        UserProfile(
            id=uid,
            display_name=profiles[uid].display_name if uid in profiles else "",
            bio=profiles[uid].bio if uid in profiles else "",
            photos=as_list(profiles[uid].photos) if uid in profiles else [],
        )
        for uid in ids
    ]
