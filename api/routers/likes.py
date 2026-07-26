from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, and_, desc, text as sa_text
from sqlalchemy.ext.asyncio import AsyncSession

from database.connection import get_session
from middleware.auth import get_current_user
from models.models import User, Profile, Like, Match
from models.schemas import LikeRequest, LikeResponse, MatchResponse, UserProfile
from services.realtime import publish_match, publish_new_like, publish_new_match_for_bot
from services.ai_matchmaker import score_match
from utils import as_list

router = APIRouter(prefix="/likes", tags=["likes"])


def _pair(a: str, b: str) -> tuple[str, str]:
    """Нормализованная пара для Match — исключает дубликаты (A,B)/(B,A)."""
    return (a, b) if a < b else (b, a)


async def _find_match(session: AsyncSession, a: str, b: str) -> Optional[Match]:
    u1, u2 = _pair(a, b)
    result = await session.execute(
        select(Match).where(and_(Match.user1_id == u1, Match.user2_id == u2))
    )
    return result.scalar_one_or_none()


def _calc_age(birth_date) -> Optional[int]:
    if not birth_date:
        return None
    now = datetime.now()
    age = now.year - birth_date.year
    if (now.month, now.day) < (birth_date.month, birth_date.day):
        age -= 1
    return age


def _profile_to_user(profile: Optional[Profile], user_id: str) -> UserProfile:
    if not profile:
        return UserProfile(id=user_id)
    return UserProfile(
        id=user_id,
        display_name=profile.display_name or "",
        bio=profile.bio or "",
        gender=profile.gender or "other",
        age=_calc_age(profile.birth_date),
        city=profile.city or "",
        photos=as_list(profile.photos),
        interests=as_list(profile.interests),
    )


async def _to_resp(session: AsyncSession, match: Match, partner_id: str) -> MatchResponse:
    result = await session.execute(select(Profile).where(Profile.user_id == partner_id))
    profile = result.scalar_one_or_none()
    return MatchResponse(
        id=match.id, match_score=match.match_score,
        ai_reason=match.ai_reason, created_at=match.created_at,
        partner=_profile_to_user(profile, partner_id),
    )


@router.post("", response_model=LikeResponse)
async def create_like(
    data: LikeRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    if data.target_id == user.id:
        raise HTTPException(status_code=400, detail="Cannot like yourself")

    result = await session.execute(select(User).where(User.id == data.target_id))
    target = result.scalar_one_or_none()
    if not target or target.is_banned:
        raise HTTPException(status_code=404, detail="Profile not found")

    u1, u2 = _pair(user.id, data.target_id)
    # Advisory-lock на пару: без него два встречных лайка в параллельных
    # транзакциях не видят друг друга (READ COMMITTED) и мэтч теряется навсегда.
    await session.execute(
        sa_text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 0))"),
        {"k": f"dating:pair:{u1}:{u2}"},
    )

    result = await session.execute(
        select(Like).where(and_(Like.liker_id == user.id, Like.liked_id == data.target_id))
    )
    existing = result.scalar_one_or_none()

    # Новый лайк или апгрейд с pass — событие «вы понравились»
    notify_new_like = (
        data.type != "pass"
        and (existing is None or existing.type == "pass")
    )

    if existing:
        if existing.type != data.type:
            # Смена решения (rewind): pass → like, like → superlike и т.п.
            existing.type = data.type
    else:
        session.add(Like(liker_id=user.id, liked_id=data.target_id, type=data.type))
    await session.flush()

    if data.type == "pass":
        return LikeResponse(liked=False, matched=False)

    # Взаимность? (лайк уже под advisory-lock — гонки нет)
    result = await session.execute(
        select(Like).where(
            and_(Like.liker_id == data.target_id, Like.liked_id == user.id, Like.type != "pass")
        )
    )
    mutual_like = result.scalar_one_or_none()

    if not mutual_like:
        await session.commit()  # события — строго после коммита
        if notify_new_like:
            await publish_new_like(data.target_id, user.id)
        return LikeResponse(liked=True, matched=False)

    # Мэтч: берём существующую строку пары (unique constraint), реактивируем
    # после unmatch или создаём новую. Ветка также «лечит» пары, у которых
    # взаимные лайки есть, а мэтча нет.
    match = await _find_match(session, user.id, data.target_id)
    is_new_match = False
    if match and not match.is_active:
        match.is_active = True
        is_new_match = True
    elif not match:
        match_score, ai_reason = await score_match(session, user.id, data.target_id)
        match = Match(user1_id=u1, user2_id=u2,
                      match_score=match_score, ai_reason=ai_reason, is_active=True)
        session.add(match)
        await session.flush()
        is_new_match = True

    response = LikeResponse(liked=True, matched=True,
                            match=await _to_resp(session, match, data.target_id))
    match_id, match_score, ai_reason = match.id, match.match_score, match.ai_reason

    await session.commit()  # бот читает БД сразу по событию — коммитим до publish

    if is_new_match:
        await publish_match(user.id, data.target_id, match_id, match_score, ai_reason)
        await publish_match(data.target_id, user.id, match_id, match_score, ai_reason)
        # Уведомление обоим в Telegram через бота
        await publish_new_match_for_bot(match_id, u1, u2)

    return response


@router.get("/received", response_model=list[UserProfile])
async def get_likes_received(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """«Кто меня лайкнул»: входящие лайки без взаимности (и без мэтча)."""
    # Кого я уже оценил (лайк или пасс) — их не показываем
    result = await session.execute(select(Like.liked_id).where(Like.liker_id == user.id))
    my_rated = {row[0] for row in result.all()}

    result = await session.execute(
        select(Like)
        .join(User, Like.liker_id == User.id)
        .where(and_(
            Like.liked_id == user.id,
            Like.type != "pass",
            User.is_banned == False,
        ))
        .order_by(desc(Like.created_at))
        .limit(50)
    )
    likes = result.scalars().all()

    out: list[UserProfile] = []
    for lk in likes:
        if lk.liker_id in my_rated:
            continue
        result = await session.execute(select(Profile).where(Profile.user_id == lk.liker_id))
        profile = result.scalar_one_or_none()
        out.append(_profile_to_user(profile, lk.liker_id))
    return out
