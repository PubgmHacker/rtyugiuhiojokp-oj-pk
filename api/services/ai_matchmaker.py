from __future__ import annotations

import json
import logging
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import get_settings
from models.models import User, Profile, Like

settings = get_settings()
logger = logging.getLogger(__name__)

_zhipu_client = None


def _get_zhipu_client():
    global _zhipu_client
    if _zhipu_client is None and settings.ZHIPU_API_KEY:
        try:
            from zhipuai import ZhipuAI
            _zhipu_client = ZhipuAI(api_key=settings.ZHIPU_API_KEY)
        except ImportError:
            logger.warning("zhipuai package not installed")
    return _zhipu_client


async def score_match(
    session: AsyncSession,
    user1_id: str,
    user2_id: str,
) -> tuple[int, Optional[str]]:
    """AI-скоринг совместимости двух пользователей.

    Returns: (score 0-100, reason_text)
    """
    result = await session.execute(select(Profile).where(Profile.user_id == user1_id))
    p1 = result.scalar_one_or_none()
    result = await session.execute(select(Profile).where(Profile.user_id == user2_id))
    p2 = result.scalar_one_or_none()

    if not p1 or not p2:
        return 50, None

    client = _get_zhipu_client()
    if not client:
        # Fallback: simple scoring based on common interests
        return _simple_score(p1, p2)

    try:
        interests1 = json.loads(p1.interests) if p1.interests else []
        interests2 = json.loads(p2.interests) if p2.interests else []
        common = list(set(interests1) & set(interests2))

        response = client.chat.completions.create(
            model="glm-4-flash",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are an AI matchmaker for a dating app. Analyze compatibility.\n"
                        "Respond with JSON only:\n"
                        '{"score": 0-100, "reason": "1-2 sentence explanation in Russian"}\n'
                        "Consider: interests overlap, bio complementarity, age range compatibility."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"User 1: {p1.display_name}, {p1.gender}, bio: {p1.bio}, "
                        f"interests: {interests1}, looking for: {p1.looking_for}\n"
                        f"User 2: {p2.display_name}, {p2.gender}, bio: {p2.bio}, "
                        f"interests: {interests2}, looking for: {p2.looking_for}\n"
                        f"Common interests: {common}"
                    ),
                },
            ],
            temperature=0.3,
            max_tokens=300,
        )
        content = response.choices[0].message.content.strip()
        try:
            data = json.loads(content)
            score = min(100, max(0, int(data.get("score", 50))))
            reason = data.get("reason", "")
            return score, reason
        except json.JSONDecodeError:
            if "{" in content and "}" in content:
                start = content.index("{")
                end = content.rindex("}") + 1
                data = json.loads(content[start:end])
                return min(100, max(0, int(data.get("score", 50)))), data.get("reason", "")
            return 50, None
    except Exception as e:
        logger.error(f"AI matchmaker error: {e}")
        return _simple_score(p1, p2)


def _simple_score(p1: Profile, p2: Profile) -> tuple[int, Optional[str]]:
    """Fallback scoring without AI."""
    interests1 = set(json.loads(p1.interests) if p1.interests else [])
    interests2 = set(json.loads(p2.interests) if p2.interests else [])
    common = interests1 & interests2

    # Looking for compatibility
    looking_ok = (
        p1.looking_for == "any" or p2.looking_for == "any" or
        p1.looking_for == p2.gender or p2.looking_for == p1.gender
    )

    score = 30  # base
    score += min(40, len(common) * 8)  # up to 40 for interests
    if looking_ok:
        score += 20  # looking for compatibility
    if p1.city and p2.city and p1.city == p2.city:
        score += 10  # same city

    reason = None
    if common:
        reason = f"Общие интересы: {', '.join(list(common)[:3])}"

    return min(100, score), reason
