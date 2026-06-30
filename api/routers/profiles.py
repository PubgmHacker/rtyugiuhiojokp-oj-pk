from __future__ import annotations

import json
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from config import get_settings
from database.connection import get_session
from middleware.auth import get_current_user
from models.models import User, Profile, Like, SwipeSession
from models.schemas import DeckProfile, ProfileUpdate, UserProfile
from services.matching import get_deck_profiles
from services.ai_moderation import moderate_text

router = APIRouter(prefix="/profiles", tags=["profiles"])
settings = get_settings()


@router.get("/deck", response_model=list[DeckProfile])
async def get_deck(
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
    limit: int = Query(default=10, ge=1, le=20),
):
    """Получить анкеты для свайпов."""
    profiles = await get_deck_profiles(session, user.id, limit)
    return profiles


@router.get("/me", response_model=UserProfile)
async def get_my_profile(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Получить свою анкету."""
    result = await session.execute(select(Profile).where(Profile.user_id == user.id))
    profile = result.scalar_one_or_none()

    age = None
    if profile and profile.birth_date:
        now = datetime.now()
        age = now.year - profile.birth_date.year
        if (now.month, now.day) < (profile.birth_date.month, profile.birth_date.day):
            age -= 1

    return UserProfile(
        id=user.id,
        telegram_id=user.telegram_id,
        role=user.role,
        is_banned=user.is_banned,
        is_verified=user.is_verified,
        created_at=user.created_at,
        display_name=profile.display_name if profile else "",
        bio=profile.bio if profile else "",
        gender=profile.gender if profile else "other",
        age=age,
        city=profile.city if profile else "",
        photos=json.loads(profile.photos) if profile and profile.photos else [],
        interests=json.loads(profile.interests) if profile and profile.interests else [],
        ai_bio=profile.ai_bio if profile else None,
        looking_for=profile.looking_for if profile else "any",
        is_incognito=profile.is_incognito if profile else False,
    )


@router.patch("/me", response_model=UserProfile)
async def update_my_profile(
    data: ProfileUpdate,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Обновить свою анкету."""
    result = await session.execute(select(Profile).where(Profile.user_id == user.id))
    profile = result.scalar_one_or_none()

    if not profile:
        profile = Profile(user_id=user.id)
        session.add(profile)
        await session.flush()

    update_fields = data.model_dump(exclude_unset=True)

    if "birth_date" in update_fields and update_fields["birth_date"]:
        try:
            update_fields["birth_date"] = datetime.strptime(
                update_fields["birth_date"], "%Y-%m-%d"
            ).date()
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid birth_date format. Use YYYY-MM-DD")

    for key, value in update_fields.items():
        if key in ("interests", "photos") and value is not None:
            setattr(profile, key, json.dumps(value))
        else:
            setattr(profile, key, value)

    if len(json.loads(profile.photos)) > settings.MAX_PHOTOS:
        raise HTTPException(status_code=400, detail=f"Max {settings.MAX_PHOTOS} photos allowed")
    if len(profile.bio) > settings.MAX_BIO_LENGTH:
        raise HTTPException(status_code=400, detail=f"Bio must be under {settings.MAX_BIO_LENGTH} chars")

    if data.bio:
        mod_result = await moderate_text(profile.bio)
        if mod_result["blocked"]:
            raise HTTPException(status_code=422, detail="Bio violates content policy")

    await session.flush()

    age = None
    if profile.birth_date:
        now = datetime.now()
        age = now.year - profile.birth_date.year
        if (now.month, now.day) < (profile.birth_date.month, profile.birth_date.day):
            age -= 1

    return UserProfile(
        id=user.id,
        telegram_id=user.telegram_id,
        role=user.role,
        is_banned=user.is_banned,
        is_verified=user.is_verified,
        created_at=user.created_at,
        display_name=profile.display_name,
        bio=profile.bio,
        gender=profile.gender,
        age=age,
        city=profile.city,
        photos=json.loads(profile.photos) if profile.photos else [],
        interests=json.loads(profile.interests) if profile.interests else [],
        ai_bio=profile.ai_bio,
        looking_for=profile.looking_for,
        is_incognito=profile.is_incognito,
    )
