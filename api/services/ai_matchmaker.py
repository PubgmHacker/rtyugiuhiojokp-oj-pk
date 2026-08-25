from __future__ import annotations

import asyncio
import json
import logging
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import get_settings
from models.models import Profile
from utils import as_list

settings = get_settings()
logger = logging.getLogger(__name__)

#: Столько ждём Zhipu. Скоринг мэтча зовётся в момент взаимного лайка, и без
#: таймаута зависший запрос задерживает уведомление о мэтче обоим — а это
#: главное событие продукта. Значение то же, что в модерации.
_AI_TIMEOUT = 12.0

_zhipu_client = None


def _get_zhipu_client():
    global _zhipu_client
    if _zhipu_client is None and settings.ZHIPU_API_KEY:
        try:
            from zhipuai import ZhipuAI
            # 15с в SDK — добить поток, который _AI_TIMEOUT уже перестал
            # ждать: wait_for снимает ожидание, но не сетевой вызов, и без
            # таймаута httpx зависшие скоринги копились бы в executor
            kwargs = {"api_key": settings.ZHIPU_API_KEY, "timeout": 15.0}
            # base_url только когда задан — как в ai_moderation: пустая
            # строка ломает URL, отсутствие аргумента = дефолт SDK (материк)
            if settings.ZHIPU_BASE_URL:
                kwargs["base_url"] = settings.ZHIPU_BASE_URL
            _zhipu_client = ZhipuAI(**kwargs)
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
        interests1 = as_list(p1.interests)
        interests2 = as_list(p2.interests)
        common = list(set(interests1) & set(interests2))

        # Zhipu SDK синхронный — не блокируем event loop
        response = await asyncio.wait_for(
            asyncio.to_thread(
                client.chat.completions.create,
                model=settings.ZHIPU_TEXT_MODEL,
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
            ),
            timeout=_AI_TIMEOUT,
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
    interests1 = set(as_list(p1.interests))
    interests2 = set(as_list(p2.interests))
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


_FALLBACK_ICEBREAKERS = [
    "Привет! Заметил(а), что у нас есть общие интересы — с чего всё началось у тебя?",
    "Если бы у тебя был свободный день без планов — как бы ты его провёл(а)?",
    "Какое место в твоём городе стоит показать в первую очередь?",
]


async def generate_icebreakers(
    session: AsyncSession,
    my_id: str,
    partner_id: str,
) -> list[str]:
    """AI-айсбрейкеры: 3 персональных первых сообщения по анкете партнёра."""
    result = await session.execute(select(Profile).where(Profile.user_id == my_id))
    me = result.scalar_one_or_none()
    result = await session.execute(select(Profile).where(Profile.user_id == partner_id))
    partner = result.scalar_one_or_none()

    client = _get_zhipu_client()
    if not client or not partner:
        return _FALLBACK_ICEBREAKERS

    try:
        response = await asyncio.wait_for(
            asyncio.to_thread(
                client.chat.completions.create,
                model=settings.ZHIPU_TEXT_MODEL,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "Ты помощник в дейтинг-приложении. Придумай 3 коротких, живых первых "
                            "сообщения (айсбрейкера) на русском для начала диалога. Без пошлости, "
                            "без банальных «привет, как дела». Опирайся на анкету собеседника. "
                            'Ответ строго JSON: {"icebreakers": ["...", "...", "..."]}'
                        ),
                    },
                    {
                        "role": "user",
                        "content": (
                            f"Моя анкета: {me.display_name if me else ''}, bio: {me.bio if me else ''}, "
                            f"интересы: {as_list(me.interests) if me else []}\n"
                            f"Анкета собеседника: {partner.display_name}, bio: {partner.bio}, "
                            f"интересы: {as_list(partner.interests)}, город: {partner.city}"
                        ),
                    },
                ],
                temperature=0.8,
                max_tokens=400,
            ),
            timeout=_AI_TIMEOUT,
        )
        content = response.choices[0].message.content.strip()
        if "{" in content and "}" in content:
            data = json.loads(content[content.index("{"):content.rindex("}") + 1])
            items = [str(x).strip() for x in data.get("icebreakers", []) if str(x).strip()]
            if items:
                return items[:3]
    except Exception as e:
        logger.error(f"AI icebreakers error: {e}")

    return _FALLBACK_ICEBREAKERS
