from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from database.connection import get_session
from middleware.auth import get_current_user
from models.models import User, Report
from models.schemas import ReportRequest, ReportResponse

router = APIRouter(prefix="/report", tags=["report"])


@router.post("", response_model=ReportResponse)
async def create_report(
    data: ReportRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Жалоба на пользователя (App Store requirement)."""
    if data.reported_id == user.id:
        raise HTTPException(status_code=400, detail="Cannot report yourself")

    result = await session.execute(select(User).where(User.id == data.reported_id))
    target = result.scalar_one_or_none()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")

    # Check duplicate report
    result = await session.execute(
        select(Report).where(and_(
            Report.reporter_id == user.id,
            Report.reported_id == data.reported_id,
            Report.status == "pending",
        ))
    )
    existing = result.scalar_one_or_none()
    if existing:
        return ReportResponse(success=True, message="Report already submitted")

    report = Report(
        reporter_id=user.id,
        reported_id=data.reported_id,
        reason=data.reason,
        description=data.description,
    )
    session.add(report)
    await session.flush()

    # Эскалация по числу РАЗНЫХ жалобщиков (одного зациклить нельзя):
    # 3+ — профиль скрывается из выдачи до решения модератора,
    # 5+ — автобан. Полный бан руками — в админке.
    from sqlalchemy import func
    from models.models import Profile

    result = await session.execute(
        select(func.count(func.distinct(Report.reporter_id))).where(
            and_(Report.reported_id == data.reported_id, Report.status == "pending")
        )
    )
    distinct_reporters = result.scalar() or 0

    if distinct_reporters >= 5:
        target.is_banned = True
    elif distinct_reporters >= 3:
        result = await session.execute(
            select(Profile).where(Profile.user_id == data.reported_id)
        )
        reported_profile = result.scalar_one_or_none()
        if reported_profile:
            reported_profile.is_incognito = True  # скрыт из деки до ревью модератором
    await session.flush()

    return ReportResponse(success=True, message="Report submitted. Thank you for keeping our community safe.")
