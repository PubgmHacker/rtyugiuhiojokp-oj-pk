from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, and_, or_, desc
from sqlalchemy.ext.asyncio import AsyncSession

from datetime import datetime

from database.connection import get_session
from middleware.auth import get_current_user
from models.models import User, Profile, Like, Match, Message
from models.schemas import MatchResponse, UserProfile
from services.ai_matchmaker import generate_icebreakers
from utils import as_list

router = APIRouter(prefix="/matches", tags=["matches"])


def _calc_age(birth_date):
    if not birth_date:
        return None
    now = datetime.now()
    age = now.year - birth_date.year
    if (now.month, now.day) < (birth_date.month, birth_date.day):
        age -= 1
    return age


async def _get_own_match(session: AsyncSession, match_id: str, user_id: str) -> Match:
    result = await session.execute(
        select(Match).where(and_(
            Match.id == match_id,
            or_(Match.user1_id == user_id, Match.user2_id == user_id),
            Match.is_active == True,
        ))
    )
    match = result.scalar_one_or_none()
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")
    return match


@router.get("", response_model=list[MatchResponse])
async def get_matches(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(
        select(Match)
        .where(and_(
            or_(Match.user1_id == user.id, Match.user2_id == user.id),
            Match.is_active == True,
        ))
        .order_by(desc(Match.created_at))
    )
    matches = result.scalars().all()

    responses = []
    for m in matches:
        partner_id = m.user2_id if m.user1_id == user.id else m.user1_id

        result = await session.execute(select(Profile).where(Profile.user_id == partner_id))
        profile = result.scalar_one_or_none()

        partner_profile = UserProfile(
            id=partner_id,
            display_name=profile.display_name if profile else "",
            bio=profile.bio if profile else "",
            age=_calc_age(profile.birth_date) if profile else None,
            city=profile.city if profile else "",
            photos=as_list(profile.photos) if profile else [],
            interests=as_list(profile.interests) if profile else [],
        )

        responses.append(MatchResponse(
            id=m.id, match_score=m.match_score, ai_reason=m.ai_reason,
            created_at=m.created_at, partner=partner_profile,
        ))

    return responses


@router.get("/{match_id}/messages")
async def get_messages(
    match_id: str, offset: int = 0, limit: int = 50,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    await _get_own_match(session, match_id, user.id)

    # Последние `limit` сообщений (desc + reverse), не первые
    result = await session.execute(
        select(Message).where(Message.match_id == match_id)
        .order_by(desc(Message.created_at)).offset(offset).limit(limit)
    )
    messages = list(reversed(result.scalars().all()))

    return [
        {"id": m.id, "sender_id": m.sender_id, "text": m.text,
         "image_url": m.image_url, "read_at": m.read_at.isoformat() if m.read_at else None,
         "created_at": m.created_at.isoformat() if m.created_at else None}
        for m in messages
    ]


@router.post("/{match_id}/unmatch")
async def unmatch(
    match_id: str,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Размэтчиться: чат становится недоступен обоим.

    Удаляем и взаимные лайки — иначе любой новый лайк одной из сторон
    мгновенно реактивирует мэтч против воли второй.
    """
    match = await _get_own_match(session, match_id, user.id)
    match.is_active = False
    await session.execute(
        Like.__table__.delete().where(or_(
            and_(Like.liker_id == match.user1_id, Like.liked_id == match.user2_id),
            and_(Like.liker_id == match.user2_id, Like.liked_id == match.user1_id),
        ))
    )
    await session.flush()
    return {"success": True}


@router.get("/{match_id}/icebreakers")
async def get_icebreakers(
    match_id: str,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """AI-айсбрейкеры: 3 варианта первого сообщения под анкету партнёра."""
    match = await _get_own_match(session, match_id, user.id)
    partner_id = match.user2_id if match.user1_id == user.id else match.user1_id
    icebreakers = await generate_icebreakers(session, user.id, partner_id)
    return {"icebreakers": icebreakers}
