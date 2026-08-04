from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import JSONResponse
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from sqlalchemy import and_, or_

from config import get_settings
from database.connection import get_session
from middleware.auth import get_current_user
from models.models import (
    User,
    Profile,
    Like,
    Match,
    Message,
    Referral,
    Subscription,
    SwipeSession,
)
from models.schemas import DeckProfile, ProfileUpdate, UserProfile
from services.matching import get_deck_profiles
from services.ai_moderation import moderate_text
from utils import as_list

logger = logging.getLogger(__name__)

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


@router.post("/deck/reset")
async def reset_deck(
    user: User = Depends(get_current_user),
):
    """Сбросить кеш просмотренных анкет (кнопка «Обновить»)."""
    from services.realtime import clear_viewed_profiles
    await clear_viewed_profiles(user.id)
    return {"success": True}


async def _referral_stats(session: AsyncSession, user_id: str) -> dict:
    result = await session.execute(
        select(func.count(Referral.id)).where(Referral.referrer_id == user_id)
    )
    invited = result.scalar() or 0
    return {
        "invited_count": invited,
        "referral_boost": invited >= settings.REFERRAL_MIN_INVITES,
        "referral_target": settings.REFERRAL_MIN_INVITES,
        "referral_boost_percent": settings.REFERRAL_BOOST_PERCENT,
    }


async def _is_premium(session: AsyncSession, user_id: str) -> bool:
    result = await session.execute(
        select(Subscription.id).where(and_(
            Subscription.user_id == user_id,
            Subscription.plan != "free",
            or_(
                Subscription.expires_at.is_(None),
                Subscription.expires_at > datetime.now(timezone.utc),
            ),
        ))
    )
    return result.scalar_one_or_none() is not None


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
        photos=as_list(profile.photos) if profile else [],
        interests=as_list(profile.interests) if profile else [],
        ai_bio=profile.ai_bio if profile else None,
        looking_for=profile.looking_for if profile else "any",
        is_incognito=profile.is_incognito if profile else False,
        is_premium=await _is_premium(session, user.id),
        age_min=profile.age_min if profile else 18,
        age_max=profile.age_max if profile else 99,
        distance_max=profile.distance_max if profile else 100,
        has_location=bool(profile and profile.latitude is not None),
        **(await _referral_stats(session, user.id)),
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

    # Инкогнито-режим — премиум-фича (выключить может любой)
    if update_fields.get("is_incognito") is True and not await _is_premium(session, user.id):
        raise HTTPException(status_code=403, detail="Инкогнито-режим доступен в Premium")

    if "birth_date" in update_fields and update_fields["birth_date"]:
        try:
            # Колонка DateTime(timezone=True) — храним datetime, не date
            update_fields["birth_date"] = datetime.strptime(
                update_fields["birth_date"], "%Y-%m-%d"
            ).replace(tzinfo=timezone.utc)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid birth_date format. Use YYYY-MM-DD")

    for key, value in update_fields.items():
        if value is None:
            continue  # explicit null не затирает non-nullable колонки (иначе 500)
        setattr(profile, key, value)

    if len(as_list(profile.photos)) > settings.MAX_PHOTOS:
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
        photos=as_list(profile.photos),
        interests=as_list(profile.interests),
        ai_bio=profile.ai_bio,
        looking_for=profile.looking_for,
        is_incognito=profile.is_incognito,
        is_premium=await _is_premium(session, user.id),
        age_min=profile.age_min,
        age_max=profile.age_max,
        distance_max=profile.distance_max,
        has_location=profile.latitude is not None,
        **(await _referral_stats(session, user.id)),
    )


@router.get("/me/export")
async def export_my_data(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Выгрузка своих данных одним JSON-файлом.

    Ожидаемая возможность для приватности: пользователь должен иметь
    доступ к тому, что о нём хранится.
    """
    result = await session.execute(select(Profile).where(Profile.user_id == user.id))
    profile = result.scalar_one_or_none()

    result = await session.execute(select(Like).where(Like.liker_id == user.id))
    likes = result.scalars().all()

    result = await session.execute(
        select(Match).where(or_(Match.user1_id == user.id, Match.user2_id == user.id))
    )
    matches = result.scalars().all()

    result = await session.execute(select(Message).where(Message.sender_id == user.id))
    messages = result.scalars().all()

    payload = {
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "account": {
            "id": user.id,
            "telegram_id": user.telegram_id,
            "created_at": user.created_at.isoformat() if user.created_at else None,
            "is_verified": user.is_verified,
        },
        "profile": {
            "display_name": profile.display_name if profile else "",
            "bio": profile.bio if profile else "",
            "gender": profile.gender if profile else "",
            "city": profile.city if profile else "",
            "birth_date": (
                profile.birth_date.isoformat() if profile and profile.birth_date else None
            ),
            "photos": as_list(profile.photos) if profile else [],
            "interests": as_list(profile.interests) if profile else [],
            "has_location": bool(profile and profile.latitude is not None),
        },
        "likes_given": [
            {"target_id": l.liked_id, "type": l.type, "at": l.created_at.isoformat() if l.created_at else None}
            for l in likes
        ],
        "matches": [
            {
                "id": m.id,
                "partner_id": m.user2_id if m.user1_id == user.id else m.user1_id,
                "at": m.created_at.isoformat() if m.created_at else None,
            }
            for m in matches
        ],
        "messages_sent": [
            {
                "match_id": msg.match_id,
                "text": msg.text,
                "at": msg.created_at.isoformat() if msg.created_at else None,
            }
            for msg in messages
        ],
    }

    filename = f"souldawn-data-{user.id[:8]}.json"
    return JSONResponse(
        content=payload,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.delete("/me", status_code=204)
async def delete_my_account(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Полное удаление аккаунта и всех связанных данных.

    Обязательная возможность по требованию App Store 5.1.1(v): удалять
    надо действительно, а не помечать флагом. Связанные таблицы
    вычищаются каскадом (ondelete="CASCADE" в моделях).
    """
    photo_urls: list[str] = []
    result = await session.execute(select(Profile).where(Profile.user_id == user.id))
    profile = result.scalar_one_or_none()
    if profile:
        photo_urls = [p for p in as_list(profile.photos) if isinstance(p, str)]

    result = await session.execute(select(User).where(User.id == user.id))
    db_user = result.scalar_one_or_none()
    if not db_user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    await session.delete(db_user)
    await session.commit()

    # Файлы в объектном хранилище каскад не удалит — чистим отдельно.
    # Сбой здесь не должен отменять уже выполненное удаление аккаунта.
    if photo_urls:
        try:
            from services.r2_storage import delete_photo_from_r2

            prefix = (settings.R2_PUBLIC_URL or "").rstrip("/") + "/"
            for url in photo_urls:
                # В базе хранятся публичные URL, а удаление принимает ключ
                # объекта; file_id из Telegram пропускаем
                if prefix != "/" and url.startswith(prefix):
                    await delete_photo_from_r2(url[len(prefix) :])
        except Exception as e:
            logger.warning(f"Не удалось удалить фото из R2 после удаления аккаунта: {e}")

    return Response(status_code=204)
