from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession

from database.connection import get_session
from middleware.auth import get_current_user
from models.models import User, Like, Match
from models.schemas import LikeRequest, LikeResponse, MatchResponse, UserProfile
from services.realtime import publish_match, publish_new_like
from services.ai_matchmaker import score_match

router = APIRouter(prefix="/likes", tags=["likes"])


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

    # Check existing like
    result = await session.execute(
        select(Like).where(and_(Like.liker_id == user.id, Like.liked_id == data.target_id))
    )
    existing = result.scalar_one_or_none()

    if existing:
        if existing.type != "pass":
            result = await session.execute(
                select(Like).where(
                    and_(Like.liker_id == data.target_id, Like.liked_id == user.id, Like.type != "pass")
                )
            )
            mutual_like = result.scalar_one_or_none()
            if mutual_like:
                result = await session.execute(
                    select(Match).where(
                        or_(
                            and_(Match.user1_id == user.id, Match.user2_id == data.target_id),
                            and_(Match.user1_id == data.target_id, Match.user2_id == user.id),
                        )
                    )
                )
                match_obj = result.scalar_one_or_none()
                return LikeResponse(liked=True, matched=True,
                    match=_to_resp(match_obj, data.target_id) if match_obj else None)
        return LikeResponse(liked=True, matched=False)

    like = Like(liker_id=user.id, liked_id=data.target_id, type=data.type)
    session.add(like)
    await session.flush()

    if data.type != "pass":
        await publish_new_like(data.target_id, user.id)

    # Check mutual
    result = await session.execute(
        select(Like).where(
            and_(Like.liker_id == data.target_id, Like.liked_id == user.id, Like.type != "pass")
        )
    )
    mutual_like = result.scalar_one_or_none()

    if mutual_like and data.type != "pass":
        match_score, ai_reason = await score_match(session, user.id, data.target_id)
        match = Match(user1_id=user.id, user2_id=data.target_id,
                      match_score=match_score, ai_reason=ai_reason, is_active=True)
        session.add(match)
        await session.flush()

        await publish_match(user.id, data.target_id, match.id, match_score, ai_reason)
        await publish_match(data.target_id, user.id, match.id, match_score, ai_reason)

        return LikeResponse(liked=True, matched=True, match=_to_resp(match, data.target_id))

    return LikeResponse(liked=True, matched=False)


def _to_resp(match: Match, partner_id: str) -> MatchResponse:
    return MatchResponse(id=match.id, match_score=match.match_score,
                         ai_reason=match.ai_reason, created_at=match.created_at,
                         partner=UserProfile(id=partner_id))
