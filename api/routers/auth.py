from __future__ import annotations

import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import get_settings
from database.connection import get_session
from middleware.auth import (
    create_access_token,
    get_current_user,
    verify_telegram_init_data,
)
from models.models import User, Profile, Subscription
from models.schemas import AuthResponse, UserProfile

router = APIRouter(prefix="/auth", tags=["auth"])
settings = get_settings()


def _user_to_profile(user: User, profile: Profile | None) -> UserProfile:
    age = None
    if profile and profile.birth_date:
        now = datetime.now(timezone.utc)
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


@router.post("/telegram", response_model=AuthResponse)
async def auth_telegram(
    data: dict,
    session: AsyncSession = Depends(get_session),
):
    """Авторизация через Telegram initData."""
    init_data = data.get("initData", "")
    if not init_data:
        return AuthResponse(success=False, token="", user=UserProfile())

    tg_data = verify_telegram_init_data(init_data)

    user_str = tg_data.get("user", "{}")
    if isinstance(user_str, str):
        tg_user = json.loads(user_str)
    else:
        tg_user = user_str

    tg_id = int(tg_user.get("id", 0))
    username = tg_user.get("username", "")
    first_name = tg_user.get("first_name", "")
    last_name = tg_user.get("last_name", "")

    # Upsert user
    result = await session.execute(select(User).where(User.telegram_id == tg_id))
    user = result.scalar_one_or_none()

    if not user:
        user = User(
            telegram_id=tg_id,
            role="user",
        )
        session.add(user)
        await session.flush()
        # Create empty profile
        profile = Profile(
            user_id=user.id,
            display_name=f"{first_name} {last_name}".strip(),
        )
        session.add(profile)
    else:
        user.last_seen_at = datetime.now(timezone.utc)

    await session.flush()

    # Check ADMIN_IDS -> promote
    if tg_id in settings.admin_id_list and user.role not in ("admin", "owner"):
        user.role = "owner"

    await session.flush()

    # Get profile
    result = await session.execute(select(Profile).where(Profile.user_id == user.id))
    profile = result.scalar_one_or_none()

    token = create_access_token(user.id, user.telegram_id)

    return AuthResponse(
        success=True,
        token=token,
        user=_user_to_profile(user, profile),
    )


@router.get("/me", response_model=UserProfile)
async def get_me(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Получить текущего пользователя."""
    result = await session.execute(select(Profile).where(Profile.user_id == user.id))
    profile = result.scalar_one_or_none()
    return _user_to_profile(user, profile)
