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

    # Auto-ban after 3+ pending reports (simple anti-spam)
    from sqlalchemy import func
    result = await session.execute(
        select(func.count(Report.id)).where(
            and_(Report.reported_id == data.reported_id, Report.status == "pending")
        )
    )
    report_count = result.scalar() or 0

    if report_count >= 3:
        target.is_banned = True
        await session.flush()

    return ReportResponse(success=True, message="Report submitted. Thank you for keeping our community safe.")
