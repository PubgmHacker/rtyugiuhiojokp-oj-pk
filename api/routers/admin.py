from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select, func, and_, or_, desc, case, String
from sqlalchemy.ext.asyncio import AsyncSession

from database.connection import get_session
from middleware.admin_auth import require_admin
from models.models import (
    User, Profile, Like, Match, Message, Report, Subscription, AiModerationLog
)

router = APIRouter(prefix="/admin", tags=["admin"])


# ════════════════════════════════════════════════════════════════
#  SCHEMAS
# ════════════════════════════════════════════════════════════════

class AdminStats(BaseModel):
    total_users: int
    active_today: int
    total_matches: int
    total_likes: int
    total_reports: int
    pending_reports: int
    premium_users: int
    banned_users: int
    new_users_week: int
    new_users_month: int
    registrations_chart: list[dict]  # [{date, count}]


class AdminUserBrief(BaseModel):
    id: str
    telegram_id: int | None
    display_name: str
    gender: str
    age: int | None
    city: str
    role: str
    is_banned: bool
    is_verified: bool
    created_at: datetime | None


class AdminReport(BaseModel):
    id: str
    reporter_id: str
    reporter_name: str
    reported_id: str
    reported_name: str
    reason: str
    description: str
    status: str
    created_at: datetime | None


class AdminModerationLog(BaseModel):
    id: str
    user_id: str
    user_name: str
    content_type: str
    content_preview: str
    result: str
    action: str
    reason: str
    created_at: datetime | None


class BanRequest(BaseModel):
    user_id: str
    reason: str = ""


class ReportAction(BaseModel):
    report_id: str
    action: str  # "dismiss" | "resolve" | "ban_reported"
    note: str = ""


# ════════════════════════════════════════════════════════════════
#  STATS DASHBOARD
# ════════════════════════════════════════════════════════════════

@router.get("/stats", response_model=AdminStats)
async def get_admin_stats(
    user: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    """Полная статистика для дашборда."""

    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_ago = now - timedelta(days=7)
    month_ago = now - timedelta(days=30)

    # Total users
    result = await session.execute(select(func.count(User.id)))
    total_users = result.scalar() or 0

    # Active today (seen in last 24h)
    result = await session.execute(
        select(func.count(User.id)).where(User.last_seen_at >= today_start)
    )
    active_today = result.scalar() or 0

    # Total matches
    result = await session.execute(select(func.count(Match.id)))
    total_matches = result.scalar() or 0

    # Total likes
    result = await session.execute(
        select(func.count(Like.id)).where(Like.type != "pass")
    )
    total_likes = result.scalar() or 0

    # Reports
    result = await session.execute(select(func.count(Report.id)))
    total_reports = result.scalar() or 0

    result = await session.execute(
        select(func.count(Report.id)).where(Report.status == "pending")
    )
    pending_reports = result.scalar() or 0

    # Premium
    result = await session.execute(
        select(func.count(Subscription.id)).where(Subscription.plan != "free")
    )
    premium_users = result.scalar() or 0

    # Banned
    result = await session.execute(
        select(func.count(User.id)).where(User.is_banned == True)
    )
    banned_users = result.scalar() or 0

    # New users (week, month)
    result = await session.execute(
        select(func.count(User.id)).where(User.created_at >= week_ago)
    )
    new_users_week = result.scalar() or 0

    result = await session.execute(
        select(func.count(User.id)).where(User.created_at >= month_ago)
    )
    new_users_month = result.scalar() or 0

    # Registrations chart (last 14 days)
    chart_data = []
    for i in range(13, -1, -1):
        day = now - timedelta(days=i)
        day_start = day.replace(hour=0, minute=0, second=0, microsecond=0)
        day_end = day_start + timedelta(days=1)

        result = await session.execute(
            select(func.count(User.id)).where(
                User.created_at >= day_start,
                User.created_at < day_end,
            )
        )
        count = result.scalar() or 0
        chart_data.append({
            "date": day_start.strftime("%Y-%m-%d"),
            "count": count,
        })

    return AdminStats(
        total_users=total_users,
        active_today=active_today,
        total_matches=total_matches,
        total_likes=total_likes,
        total_reports=total_reports,
        pending_reports=pending_reports,
        premium_users=premium_users,
        banned_users=banned_users,
        new_users_week=new_users_week,
        new_users_month=new_users_month,
        registrations_chart=chart_data,
    )


# ════════════════════════════════════════════════════════════════
#  USERS MANAGEMENT
# ════════════════════════════════════════════════════════════════

@router.get("/users", response_model=list[AdminUserBrief])
async def list_users(
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=50, ge=1, le=200),
    search: str = Query(default=""),
    banned_only: bool = Query(default=False),
    user: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    """Список пользователей с пагинацией и поиском."""

    query = select(User).order_by(desc(User.created_at))
    if banned_only:
        query = query.where(User.is_banned == True)
    if search:
        query = query.join(Profile).where(
            or_(
                Profile.display_name.ilike(f"%{search}%"),
                User.telegram_id.cast(String).ilike(f"%{search}%"),
            )
        )

    query = query.offset((page - 1) * limit).limit(limit)
    result = await session.execute(query)
    users = result.scalars().all()

    # Batch-load profiles
    user_ids = [u.id for u in users]
    if not user_ids:
        return []

    profiles_result = await session.execute(
        select(Profile).where(Profile.user_id.in_(user_ids))
    )
    profiles_map = {p.user_id: p for p in profiles_result.scalars().all()}

    items = []
    for u in users:
        p = profiles_map.get(u.id)
        age = None
        if p and p.birth_date:
            now = datetime.now(timezone.utc)
            age = now.year - p.birth_date.year

        items.append(AdminUserBrief(
            id=u.id,
            telegram_id=u.telegram_id,
            display_name=p.display_name if p else "",
            gender=p.gender if p else "other",
            age=age,
            city=p.city if p else "",
            role=u.role,
            is_banned=u.is_banned,
            is_verified=u.is_verified,
            created_at=u.created_at,
        ))

    return items


@router.post("/users/ban")
async def ban_user(
    data: BanRequest,
    user: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    """Заблокировать пользователя."""

    result = await session.execute(select(User).where(User.id == data.user_id))
    target = result.scalar_one_or_none()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")

    if target.role in ("admin", "owner"):
        raise HTTPException(status_code=403, detail="Cannot ban admin/owner")

    target.is_banned = True
    await session.flush()

    # Log the action
    # Send notification via Redis for bot to pick up
    try:
        from services.realtime import get_redis
        r = await get_redis()
        import json as _json
        await r.publish(
            f"dating:user:{data.user_id}",
            _json.dumps({"type": "banned", "reason": data.reason}),
        )
    except Exception:
        pass

    return {"success": True, "message": f"User {data.user_id} banned"}


@router.post("/users/unban")
async def unban_user(
    data: BanRequest,
    user: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    """Разблокировать пользователя."""

    result = await session.execute(select(User).where(User.id == data.user_id))
    target = result.scalar_one_or_none()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")

    target.is_banned = False
    await session.flush()

    return {"success": True, "message": f"User {data.user_id} unbanned"}


# ════════════════════════════════════════════════════════════════
#  REPORTS
# ════════════════════════════════════════════════════════════════

@router.get("/reports", response_model=list[AdminReport])
async def list_reports(
    status: str = Query(default="pending", pattern="^(pending|reviewed|resolved|dismissed|all)$"),
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=50, ge=1, le=200),
    user: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    """Список жалоб."""

    query = select(Report).order_by(desc(Report.created_at))
    if status != "all":
        query = query.where(Report.status == status)

    query = query.offset((page - 1) * limit).limit(limit)
    result = await session.execute(query)
    reports = result.scalars().all()

    # Batch-load user names
    user_ids = set()
    for r in reports:
        user_ids.add(r.reporter_id)
        user_ids.add(r.reported_id)

    profiles_result = await session.execute(
        select(Profile).where(Profile.user_id.in_(list(user_ids)))
    )
    profiles_map = {p.user_id: p for p in profiles_result.scalars().all()}

    items = []
    for r in reports:
        reporter_p = profiles_map.get(r.reporter_id)
        reported_p = profiles_map.get(r.reported_id)
        items.append(AdminReport(
            id=r.id,
            reporter_id=r.reporter_id,
            reporter_name=reporter_p.display_name if reporter_p else "Unknown",
            reported_id=r.reported_id,
            reported_name=reported_p.display_name if reported_p else "Unknown",
            reason=r.reason,
            description=r.description,
            status=r.status,
            created_at=r.created_at,
        ))

    return items


@router.post("/reports/action")
async def report_action(
    data: ReportAction,
    user: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    """Обработать жалобу: dismiss, resolve, или забанить нарушителя."""

    result = await session.execute(select(Report).where(Report.id == data.report_id))
    report = result.scalar_one_or_none()
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")

    if data.action == "ban_reported":
        target_result = await session.execute(
            select(User).where(User.id == report.reported_id)
        )
        target = target_result.scalar_one_or_none()
        if target:
            target.is_banned = True
        report.status = "resolved"
    elif data.action == "dismiss":
        report.status = "dismissed"
    elif data.action == "resolve":
        report.status = "resolved"
    else:
        raise HTTPException(status_code=400, detail="Invalid action")

    await session.flush()

    return {"success": True, "report_status": report.status}


# ════════════════════════════════════════════════════════════════
#  AI MODERATION LOGS
# ════════════════════════════════════════════════════════════════

@router.get("/moderation-logs", response_model=list[AdminModerationLog])
async def list_moderation_logs(
    result_filter: str = Query(default="all", pattern="^(all|safe|warning|blocked)$"),
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=50, ge=1, le=200),
    user: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    """Логи ИИ-модерации."""

    # Create table if not exists (for backward compatibility)
    try:
        from sqlalchemy import text as _text
        await session.execute(_text("""
            CREATE TABLE IF NOT EXISTS dating_ai_moderation_logs (
                id VARCHAR PRIMARY KEY DEFAULT gen_random_uuid(),
                user_id VARCHAR NOT NULL REFERENCES dating_users(id),
                content_type VARCHAR NOT NULL,
                content TEXT NOT NULL,
                result VARCHAR NOT NULL,
                action VARCHAR NOT NULL DEFAULT 'none',
                reason VARCHAR DEFAULT '',
                created_at TIMESTAMPTZ DEFAULT NOW()
            )
        """))
    except Exception:
        pass

    query = select(AiModerationLog).order_by(desc(AiModerationLog.created_at))
    if result_filter != "all":
        query = query.where(AiModerationLog.result == result_filter)

    query = query.offset((page - 1) * limit).limit(limit)
    result = await session.execute(query)
    logs = result.scalars().all()

    # Batch-load user names
    user_ids = list({l.user_id for l in logs})
    profiles_result = await session.execute(
        select(Profile).where(Profile.user_id.in_(user_ids))
    )
    profiles_map = {p.user_id: p for p in profiles_result.scalars().all()}

    items = []
    for log in logs:
        p = profiles_map.get(log.user_id)
        content_preview = (log.content[:100] + "...") if log.content and len(log.content) > 100 else (log.content or "")
        items.append(AdminModerationLog(
            id=log.id,
            user_id=log.user_id,
            user_name=p.display_name if p else "Unknown",
            content_type=log.content_type,
            content_preview=content_preview,
            result=log.result,
            action=log.action,
            reason=log.reason,
            created_at=log.created_at,
        ))

    return items
