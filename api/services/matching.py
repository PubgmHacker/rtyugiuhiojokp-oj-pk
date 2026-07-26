from __future__ import annotations

import math
import random
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select, and_, not_, func, or_
from sqlalchemy.ext.asyncio import AsyncSession

from config import get_settings
from models.models import User, Profile, Like, Subscription
from models.schemas import DeckProfile
from services.ai_matchmaker import score_match
from utils import as_list

settings = get_settings()


def _calculate_age(birth_date: Optional[datetime]) -> Optional[int]:
    if not birth_date:
        return None
    now = datetime.now()
    age = now.year - birth_date.year
    if (now.month, now.day) < (birth_date.month, birth_date.day):
        age -= 1
    return age


def _haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> int:
    """Расстояние между двумя точками в км."""
    if not all([lat1, lon1, lat2, lon2]):
        return 0
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    c = 2 * math.asin(math.sqrt(a))
    return int(R * c)


async def get_deck_profiles(
    session: AsyncSession,
    user_id: str,
    limit: int = 10,
) -> list[DeckProfile]:
    """Получить анкеты для свайп-дека с AI-сортировкой."""
    # Get user's profile for preferences
    result = await session.execute(select(Profile).where(Profile.user_id == user_id))
    my_profile = result.scalar_one_or_none()

    # Get already liked/passed IDs
    result = await session.execute(
        select(Like.liked_id).where(Like.liker_id == user_id)
    )
    liked_ids = {row[0] for row in result.all()}

    # Exclude: self, liked/passed, banned, incognito users.
    # Не отмечаем анкеты «просмотренными» при загрузке — иначе повторный
    # запрос деки (перезагрузка страницы) сжигает непросмотренные анкеты.
    exclude_ids = liked_ids | {user_id}

    result = await session.execute(
        select(Profile)
        .join(User, Profile.user_id == User.id)
        .where(
            and_(
                User.is_banned == False,
                not_(Profile.is_incognito),  # Hide incognito users from deck
                Profile.display_name != "",  # Пустые (незаполненные) анкеты не показываем
                not_(Profile.user_id.in_(exclude_ids)) if exclude_ids else True,
            )
        )
        .order_by(func.random())
        .limit(limit * 3)  # Fetch extra for filtering + smart sort
    )
    profiles = result.scalars().all()

    # Активные премиумы среди кандидатов — буст в выдаче
    premium_ids: set[str] = set()
    if profiles:
        result = await session.execute(
            select(Subscription.user_id).where(and_(
                Subscription.user_id.in_([p.user_id for p in profiles]),
                Subscription.plan != "free",
                or_(
                    Subscription.expires_at.is_(None),
                    Subscription.expires_at > datetime.now(timezone.utc),
                ),
            ))
        )
        premium_ids = {row[0] for row in result.all()}

    # Filter by preferences and build deck
    deck: list[DeckProfile] = []
    my_age = _calculate_age(my_profile.birth_date) if my_profile else None

    for profile in profiles:
        # Gender preference filter
        if my_profile and my_profile.looking_for != "any":
            if profile.gender != my_profile.looking_for and profile.gender != "other":
                continue

        # Age preference filter
        profile_age = _calculate_age(profile.birth_date)
        if my_profile and my_age and profile_age:
            if profile_age < my_profile.age_min or profile_age > my_profile.age_max:
                continue
        if my_profile and my_age:
            if my_age < profile.age_min or my_age > profile.age_max:
                continue

        # Looking for filter (reverse)
        if profile.looking_for != "any" and my_profile:
            if profile.looking_for != my_profile.gender and my_profile.gender != "other":
                continue

        # Distance
        distance = None
        if (my_profile and my_profile.latitude and my_profile.longitude
                and profile.latitude and profile.longitude):
            distance = _haversine(
                my_profile.latitude, my_profile.longitude,
                profile.latitude, profile.longitude,
            )
            if my_profile.distance_max and distance > my_profile.distance_max:
                continue

        # AI score for sorting
        ai_score = None
        ai_reason = None
        # Note: we do lightweight scoring here; full scoring happens on match

        deck.append(DeckProfile(
            id=profile.user_id,
            display_name=profile.display_name or "",
            age=profile_age,
            city=profile.city or "",
            bio=profile.bio or "",
            photos=as_list(profile.photos),
            interests=as_list(profile.interests),
            ai_bio=profile.ai_bio,
            distance=distance,
            match_score=ai_score,
            match_reason=ai_reason,
        ))

    # Умная сортировка вместо рандома: общие интересы, город, близость,
    # премиум-буст + лёгкий шум, чтобы дека не была детерминированной
    my_interests = set(as_list(my_profile.interests)) if my_profile else set()
    my_city = (my_profile.city or "").strip().lower() if my_profile else ""

    def _rank(p: DeckProfile) -> float:
        score = 0.0
        score += len(my_interests & set(p.interests)) * 10
        if my_city and (p.city or "").strip().lower() == my_city:
            score += 15
        if p.distance is not None:
            score += max(0.0, 20 - p.distance / 5)
        if p.id in premium_ids:
            score += 25
        return score + random.uniform(0, 8)

    deck.sort(key=_rank, reverse=True)
    return deck[:limit]
