"""Кейсы — бонус подписки.

Попытки не хранятся счётчиком: считаются как «положено по уровню минус открыто
за сутки». Счётчик пришлось бы обнулять по расписанию, и пропущенный запуск
открыл бы безлимит — тот же приём, что у суперлайков и бустов.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from database.connection import get_session
from middleware.auth import get_current_user
from models.models import CaseOpening, Profile, User
from models.schemas import CaseOpenResult, CaseRewardOut, CaseStateOut
from services.cases import REWARD_BOOST, REWARDS, openings_per_day, roll
from services.plans import BOOST_MINUTES
from services.premium import current_tier

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/cases", tags=["cases"])


def _showcase() -> list[CaseRewardOut]:
    """Витрина «что можно выиграть». Шансы показываем честно: скрытые шансы —
    ровно то, за что гача-механики и не любят."""
    return [
        CaseRewardOut(
            code=r.code,
            title=r.title,
            amount=r.amount,
            chance_percent=round(r.chance * 100),
        )
        for r in REWARDS
    ]


async def _openings_left(session: AsyncSession, user_id: str, tier: str) -> int:
    since = datetime.now(timezone.utc) - timedelta(days=1)
    result = await session.execute(
        select(func.count(CaseOpening.id)).where(and_(
            CaseOpening.user_id == user_id,
            CaseOpening.created_at >= since,
        ))
    )
    return max(0, openings_per_day(tier) - (result.scalar() or 0))


@router.get("", response_model=CaseStateOut)
async def get_case_state(
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """Сколько попыток осталось и что можно выиграть."""
    tier = await current_tier(session, user.id)
    return CaseStateOut(
        left_today=await _openings_left(session, user.id, tier),
        per_day=openings_per_day(tier),
        rewards=_showcase(),
    )


@router.post("/open", response_model=CaseOpenResult)
async def open_case(
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """Открыть кейс и начислить награду."""
    tier = await current_tier(session, user.id)
    per_day = openings_per_day(tier)
    if not per_day:
        raise HTTPException(status_code=403, detail="Кейсы доступны в Plus")

    left = await _openings_left(session, user.id, tier)
    if not left:
        raise HTTPException(status_code=429, detail="Попытки на сегодня закончились")

    result = await session.execute(select(Profile).where(Profile.user_id == user.id))
    profile = result.scalar_one_or_none()
    if not profile:
        raise HTTPException(status_code=400, detail="Сначала заполните анкету")

    reward = roll()

    if reward.code == REWARD_BOOST:
        # Продлеваем от текущего окончания, а не с нуля: иначе выпавшие минуты
        # сожгли бы уже действующий буст
        now = datetime.now(timezone.utc)
        base = profile.boost_until if (profile.boost_until and profile.boost_until > now) else now
        profile.boost_until = base + timedelta(minutes=reward.amount)
    else:
        profile.bonus_superlikes += reward.amount

    session.add(CaseOpening(user_id=user.id, reward=reward.code, amount=reward.amount))
    await session.flush()

    out = CaseOpenResult(
        reward=CaseRewardOut(
            code=reward.code,
            title=reward.title,
            amount=reward.amount,
            chance_percent=round(reward.chance * 100),
        ),
        left_today=await _openings_left(session, user.id, tier),
        per_day=per_day,
        boost_minutes=BOOST_MINUTES,
    )
    await session.commit()
    logger.info(f"Кейс открыт: user={user.id} reward={reward.code} amount={reward.amount}")
    return out
