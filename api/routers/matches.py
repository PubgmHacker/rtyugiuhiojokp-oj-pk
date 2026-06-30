from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, and_, or_, desc
from sqlalchemy.ext.asyncio import AsyncSession

from database.connection import get_session
from middleware.auth import get_current_user
from models.models import User, Profile, Match, Message
from models.schemas import MatchResponse, UserProfile

router = APIRouter(prefix="/matches", tags=["matches"])


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
            photos=json.loads(profile.photos) if profile and profile.photos else [],
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
    result = await session.execute(
        select(Match).where(and_(
            Match.id == match_id,
            or_(Match.user1_id == user.id, Match.user2_id == user.id),
            Match.is_active == True,
        ))
    )
    match = result.scalar_one_or_none()
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")

    result = await session.execute(
        select(Message).where(Message.match_id == match_id)
        .order_by(Message.created_at).offset(offset).limit(limit)
    )
    messages = result.scalars().all()

    return [
        {"id": m.id, "sender_id": m.sender_id, "text": m.text,
         "image_url": m.image_url, "read_at": m.read_at.isoformat() if m.read_at else None,
         "created_at": m.created_at.isoformat() if m.created_at else None}
        for m in messages
    ]
