from __future__ import annotations

import html
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select, func, or_, desc, case, String
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from database.connection import get_session
from middleware.admin_auth import require_admin
from models.models import (
    User, Profile, Like, Match, Reel, Report, Story, Subscription,
    AiModerationLog, AdminAuditLog, Broadcast, ProcessedPayment,
    PromoCode, VerificationAttempt,
)
from services.audit import write_audit
from services.plans import TIER_AURORA, TIER_PLUS, TIER_ULTRA
from services.promo import generate_promo_code, normalize_code, валидный_кастомный_код
from services.ban_memory import forgive
from services.enforcement import (
    CONTENT_STRIKE_LIMIT,
    CONTENT_STRIKE_WINDOW,
    TEXT_STRIKE_RULES,
    ban_user_for_violation,
    prior_ban_count,
    text_strike_count,
)
from services.report_notify import notify_report_outcome
from services.notifications import записать_уведомление
from services.token_revocation import clear_user_revocation
from utils import as_list

logger = logging.getLogger(__name__)

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
    banned_until: datetime | None = None
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


class AdminStrikeBlock(BaseModel):
    """Один счётчик страйков: сколько набрано из скольких и за какое окно."""
    count: int
    limit: int
    window_days: int


class AdminVerification(BaseModel):
    status: str
    provider: str
    reason: str
    decided_at: datetime | None


class AdminUserCard(BaseModel):
    """Досье одного пользователя — всё, что нужно разбору тикета, одним экраном."""

    # Аккаунт
    id: str
    telegram_id: int | None
    role: str
    locale: str
    is_banned: bool
    banned_until: datetime | None
    is_verified: bool
    created_at: datetime | None
    last_seen_at: datetime | None
    #: Флаги привязок вместо самих значений: почта и apple_id — PII, а для
    #: разбора достаточно знать, СМОЖЕТ ли человек восстановить доступ.
    has_apple: bool
    has_email: bool

    # Анкета
    display_name: str
    gender: str
    age: int | None
    city: str
    bio: str
    photos: list[str]
    interests: list[str]
    is_incognito: bool
    is_paused: bool

    # Подписка
    plan: str
    plan_expires_at: datetime | None

    # Активность
    matches_count: int
    likes_sent: int
    likes_received: int
    reels_count: int
    stories_count: int

    # Модерация
    strikes: dict[str, AdminStrikeBlock]
    prior_bans: int
    reports_against: int
    reports_pending: int
    reports_by: int
    last_verification: AdminVerification | None
    recent_moderation: list[AdminModerationLog]


class BanRequest(BaseModel):
    user_id: str
    reason: str = ""
    #: Срок в часах; None — вечный (прежнее поведение кнопки «Забанить»).
    #: Явный срок идёт мимо лестницы: админ решает сам.
    duration_hours: int | None = None


class SetVerifiedRequest(BaseModel):
    user_id: str
    verified: bool


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
            banned_until=u.banned_until,
            is_verified=u.is_verified,
            created_at=u.created_at,
        ))

    return items


@router.get("/users/{user_id}", response_model=AdminUserCard)
async def get_user_card(
    user_id: str,
    user: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    """Досье одного пользователя.

    Разбор тикета — всегда одни и те же вопросы: кто это, платит ли, сколько
    страйков и банов, что за жалобы, почему его не видно в деке. Без карточки
    админ собирал бы ответ из четырёх вкладок и журнала.
    """
    result = await session.execute(select(User).where(User.id == user_id))
    target = result.scalar_one_or_none()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")

    result = await session.execute(select(Profile).where(Profile.user_id == user_id))
    profile = result.scalar_one_or_none()

    result = await session.execute(
        select(Subscription).where(Subscription.user_id == user_id)
    )
    sub = result.scalar_one_or_none()

    async def _count(stmt) -> int:
        return (await session.execute(stmt)).scalar() or 0

    matches_count = await _count(
        select(func.count(Match.id)).where(
            or_(Match.user1_id == user_id, Match.user2_id == user_id),
            Match.is_active == True,  # noqa: E712
        )
    )
    likes_sent = await _count(
        select(func.count(Like.id)).where(
            Like.liker_id == user_id, Like.type != "pass"
        )
    )
    likes_received = await _count(
        select(func.count(Like.id)).where(
            Like.liked_id == user_id, Like.type != "pass"
        )
    )
    reels_count = await _count(
        select(func.count(Reel.id)).where(Reel.user_id == user_id)
    )
    stories_count = await _count(
        select(func.count(Story.id)).where(Story.user_id == user_id)
    )

    reports_against = await _count(
        select(func.count(Report.id)).where(Report.reported_id == user_id)
    )
    reports_pending = await _count(
        select(func.count(Report.id)).where(
            Report.reported_id == user_id, Report.status == "pending"
        )
    )
    reports_by = await _count(
        select(func.count(Report.id)).where(Report.reporter_id == user_id)
    )

    # Счёт — теми же функциями и окнами, которыми банит автоматика: карточка
    # обязана показывать ровно то, из чего сложится следующий бан, включая
    # обрезку окна разбаном (амнистию). Свой пересчёт здесь разошёлся бы
    # с services/enforcement.py при первом же изменении правил.
    strikes: dict[str, AdminStrikeBlock] = {}
    for категория, (лимит, окно) in TEXT_STRIKE_RULES.items():
        strikes[категория] = AdminStrikeBlock(
            count=await text_strike_count(user_id, категория, окно),
            limit=лимит,
            window_days=окно.days,
        )
    strikes["content"] = AdminStrikeBlock(
        count=await text_strike_count(user_id, "content", CONTENT_STRIKE_WINDOW),
        limit=CONTENT_STRIKE_LIMIT,
        window_days=CONTENT_STRIKE_WINDOW.days,
    )

    result = await session.execute(
        select(VerificationAttempt)
        .where(VerificationAttempt.user_id == user_id)
        .order_by(desc(VerificationAttempt.created_at))
        .limit(1)
    )
    attempt = result.scalars().first()

    result = await session.execute(
        select(AiModerationLog)
        .where(AiModerationLog.user_id == user_id)
        .order_by(desc(AiModerationLog.created_at))
        .limit(10)
    )
    logs = result.scalars().all()

    age = None
    if profile and profile.birth_date:
        age = datetime.now(timezone.utc).year - profile.birth_date.year

    имя = profile.display_name if profile else ""
    return AdminUserCard(
        id=target.id,
        telegram_id=target.telegram_id,
        role=target.role,
        locale=target.locale,
        is_banned=target.is_banned,
        banned_until=target.banned_until,
        is_verified=target.is_verified,
        created_at=target.created_at,
        last_seen_at=target.last_seen_at,
        has_apple=bool(target.apple_id),
        has_email=bool(target.email),
        display_name=имя,
        gender=profile.gender if profile else "other",
        age=age,
        city=profile.city if profile else "",
        bio=profile.bio if profile else "",
        photos=as_list(profile.photos) if profile else [],
        interests=as_list(profile.interests) if profile else [],
        is_incognito=bool(profile and profile.is_incognito),
        is_paused=bool(profile and profile.is_paused),
        plan=sub.plan if sub else "free",
        plan_expires_at=sub.expires_at if sub else None,
        matches_count=matches_count,
        likes_sent=likes_sent,
        likes_received=likes_received,
        reels_count=reels_count,
        stories_count=stories_count,
        strikes=strikes,
        prior_bans=await prior_ban_count(user_id),
        reports_against=reports_against,
        reports_pending=reports_pending,
        reports_by=reports_by,
        last_verification=(
            AdminVerification(
                status=attempt.status,
                provider=attempt.provider,
                reason=attempt.reason,
                decided_at=attempt.decided_at,
            )
            if attempt
            else None
        ),
        recent_moderation=[
            AdminModerationLog(
                id=l.id,
                user_id=l.user_id,
                user_name=имя,
                content_type=l.content_type,
                content_preview=(
                    (l.content[:100] + "...")
                    if l.content and len(l.content) > 100
                    else (l.content or "")
                ),
                result=l.result,
                action=l.action,
                reason=l.reason,
                created_at=l.created_at,
            )
            for l in logs
        ],
    )


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

    # Полный набор действий (флаг, память банов, отзыв токенов, уведомление
    # боту) собран в одном сервисе — он же банит за катфишинг на верификации.
    # duration_hours=None оставляет вечный бан (лестница категории manual)
    await ban_user_for_violation(
        session,
        target,
        data.reason or "бан админом",
        category="manual",
        duration_hours=data.duration_hours,
    )

    await write_audit(
        session, user, "ban",
        target=target,
        details={
            "reason": data.reason or "бан админом",
            "duration_hours": data.duration_hours,
        },
    )

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
    target.banned_until = None
    await session.flush()

    # Без этого разбан работал бы только до первого удаления аккаунта: сам
    # пользователь разбанен, а его привязки остались в списке. Чистим обе
    await forgive(session, telegram_id=target.telegram_id, apple_id=target.apple_id)

    # Иначе отметка отзыва из бана продолжала бы гасить свежие токены
    await clear_user_revocation(data.user_id)

    # Амнистия страйков: разбан начинает счёт заново (services/enforcement.py,
    # AMNESTY_TYPES). Без записи старые страйки жили бы дальше, и первый же
    # спорный кадр после разбана банил бы обратно — разбан был бы фикцией.
    from services.ai_moderation import log_moderation

    await log_moderation(
        data.user_id, "unban_admin", "", {"safe": True, "reason": "разбан администратором"}
    )

    await write_audit(session, user, "unban", target=target)

    return {"success": True, "message": f"User {data.user_id} unbanned"}


@router.post("/users/set-verified")
async def set_verified(
    data: SetVerifiedRequest,
    user: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    """Ручное управление галочкой — для разборов поддержки.

    Обычный путь один: живая проверка (routers/verification.py). Эта ручка —
    для двух исключений: снять галочку с аккаунта, который после проверки
    сменил фото на чужие, и выдать её человеку, которого AI стабильно не
    узнаёт (шрам, гетерохромия, возрастные изменения), а поддержка проверила
    вручную. Решение пишется в журнал попыток, чтобы след остался.
    """
    result = await session.execute(select(User).where(User.id == data.user_id))
    target = result.scalar_one_or_none()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")

    target.is_verified = data.verified
    session.add(
        VerificationAttempt(
            user_id=target.id,
            poses=[],
            status="approved" if data.verified else "rejected",
            reason=f"вручную админом {user.id}",
            decided_at=datetime.now(timezone.utc),
        )
    )
    await write_audit(
        session, user, "set_verified",
        target=target,
        details={"verified": data.verified},
    )
    await session.flush()
    return {"success": True, "is_verified": target.is_verified}


# ════════════════════════════════════════════════════════════════
#  VERIFICATION QUEUE
# ════════════════════════════════════════════════════════════════

class AdminVerificationQueueItem(BaseModel):
    user_id: str
    display_name: str
    photos: list[str]
    age: int | None
    city: str
    attempts_total: int
    rejected_total: int
    rejected_24h: int
    #: Суточный потолок отказов (routers/verification.py) — UI показывает
    #: «M из N за сутки», чтобы было видно, упёрся ли человек в лимит
    daily_limit: int
    last_status: str
    last_reason: str
    last_provider: str
    last_attempt_at: datetime | None


@router.get("/verification-queue", response_model=list[AdminVerificationQueueItem])
async def verification_queue(
    days: int = Query(default=14, ge=1, le=90),
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=50, ge=1, le=200),
    user: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    """Кто застрял в живой проверке: отказы есть, галочки нет.

    Единственный ручной участок верификации: кадры проверки — биометрия и не
    хранятся (routers/verification.py), поэтому админ смотрит фото анкеты и
    причины отказов AI, а решает ручкой set-verified. Кому она нужна, видно
    отсюда: наверху те, кто споткнулся больше всех раз.

    Отдельного статуса «разобрано» нет нарочно: очередь описывает реальность,
    а не процесс, и рассасывается сама — галочка выдана, проверка пройдена
    или попытки ушли за окно days. Забаненные скрыты: их разбор живёт в
    жалобах и карточке, проверку они всё равно не пройдут.
    """
    граница = datetime.now(timezone.utc) - timedelta(days=days)
    отказы = func.sum(case((VerificationAttempt.status == "rejected", 1), else_=0))
    агрегат = (
        select(
            VerificationAttempt.user_id.label("uid"),
            func.count(VerificationAttempt.id).label("attempts"),
            отказы.label("rejected"),
            func.max(VerificationAttempt.created_at).label("last_at"),
        )
        .where(VerificationAttempt.created_at >= граница)
        .group_by(VerificationAttempt.user_id)
        .subquery()
    )

    # Последняя попытка достаётся джойном по (uid, max(created_at)): её статус
    # и причина говорят, обо что человек споткнулся в последний раз
    query = (
        select(User, агрегат.c.attempts, агрегат.c.rejected, VerificationAttempt)
        .join(агрегат, агрегат.c.uid == User.id)
        .join(
            VerificationAttempt,
            (VerificationAttempt.user_id == агрегат.c.uid)
            & (VerificationAttempt.created_at == агрегат.c.last_at),
        )
        .where(
            User.is_verified.is_(False),
            User.is_banned.is_(False),
            агрегат.c.rejected > 0,
        )
        .order_by(desc(агрегат.c.rejected), desc(агрегат.c.last_at))
        .offset((page - 1) * limit)
        .limit(limit)
    )
    строки = (await session.execute(query)).all()

    # Две попытки тик в тик дали бы дубль строки — первая выигрывает
    по_юзеру: dict[str, tuple] = {}
    for строка in строки:
        по_юзеру.setdefault(строка[0].id, строка)

    uids = list(по_юзеру)
    профили: dict[str, Profile] = {}
    отказов_за_сутки: dict[str, int] = {}
    if uids:
        result = await session.execute(
            select(Profile).where(Profile.user_id.in_(uids))
        )
        профили = {p.user_id: p for p in result.scalars().all()}
        сутки_назад = datetime.now(timezone.utc) - timedelta(hours=24)
        result = await session.execute(
            select(VerificationAttempt.user_id, func.count(VerificationAttempt.id))
            .where(
                VerificationAttempt.user_id.in_(uids),
                VerificationAttempt.status == "rejected",
                VerificationAttempt.created_at >= сутки_назад,
            )
            .group_by(VerificationAttempt.user_id)
        )
        отказов_за_сутки = {uid: int(n) for uid, n in result.all()}

    from routers.verification import СУТОЧНЫЙ_ЛИМИТ_ОТКАЗОВ

    items = []
    for uid, (цель, попыток, отказов, последняя) in по_юзеру.items():
        p = профили.get(uid)
        age = None
        if p and p.birth_date:
            age = datetime.now(timezone.utc).year - p.birth_date.year
        items.append(AdminVerificationQueueItem(
            user_id=uid,
            display_name=p.display_name if p else "",
            photos=as_list(p.photos) if p else [],
            age=age,
            city=(p.city or "") if p else "",
            attempts_total=int(попыток),
            rejected_total=int(отказов),
            rejected_24h=отказов_за_сутки.get(uid, 0),
            daily_limit=СУТОЧНЫЙ_ЛИМИТ_ОТКАЗОВ,
            last_status=последняя.status,
            last_reason=последняя.reason or "",
            last_provider=последняя.provider or "builtin",
            last_attempt_at=последняя.created_at,
        ))
    return items


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

    # Цель нужна любой ветке: бану — чтобы забанить, аудиту — чтобы записать,
    # над кем разбирали жалобу. None — цель уже удалилась, это не ошибка
    target_result = await session.execute(
        select(User).where(User.id == report.reported_id)
    )
    target = target_result.scalar_one_or_none()

    if data.action == "ban_reported":
        # Тот же бан, что и в ban_user: флаг, память банов, отзыв токенов
        # (иначе открытый сокет забаненного живёт до истечения токена).
        # Итог для жалобщика берём из результата, а не из действия: автоматика
        # не банит админов и владельцев, и обещать бан, которого не было, нельзя
        забанен = bool(
            target and await ban_user_for_violation(session, target, "бан по жалобе")
        )
        report.status = "resolved"
        итог = "banned" if забанен else "resolved"
    elif data.action == "dismiss":
        report.status = "dismissed"
        итог = "dismissed"
    elif data.action == "resolve":
        report.status = "resolved"
        итог = "resolved"
    else:
        raise HTTPException(status_code=400, detail="Invalid action")

    await write_audit(
        session, user, "report_action",
        target=target,
        details={
            "report_id": report.id,
            # Если цель удалилась, target пуст — id из жалобы сохраняет след
            "reported_id": report.reported_id,
            "action": data.action,
            "outcome": итог,
            "note": data.note,
        },
    )
    await session.flush()

    # Человек, нажавший «Пожаловаться», обязан узнать, чем это закончилось —
    # включая «нарушения не нашли». Молчащая модерация читается как
    # неработающая кнопка (services/report_notify.py). Запись в центр
    # уведомлений — в этой же сессии: пуш и бот-сообщение доходят не до всех
    # входов, а лента хранит итог для любого
    await записать_уведомление(
        session, report.reporter_id, "report_outcome", {"outcome": итог}
    )
    await notify_report_outcome([report.reporter_id], итог)

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


# ════════════════════════════════════════════════════════════════
#  РОЛИКИ
# ════════════════════════════════════════════════════════════════

class AdminReel(BaseModel):
    id: str
    author_id: str
    author_name: str = ""
    video_url: str
    cover_url: str = ""
    caption: str = ""
    likes_count: int = 0
    is_hidden: bool = False
    created_at: datetime | None = None


class ReelModerationAction(BaseModel):
    reel_id: str
    #: hide — снять с показа, show — вернуть в ленту
    action: str


@router.get("/reels", response_model=list[AdminReel])
async def list_reels_for_moderation(
    only_visible: bool = Query(default=False),
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=50, ge=1, le=200),
    user: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    """Ролики для проверки, свежие сверху.

    AI-модерация смотрит только первый кадр, поэтому ручной просмотр нужен:
    то, что начинается прилично, дальше может быть любым.
    """
    query = select(Reel).order_by(desc(Reel.created_at))
    if only_visible:
        query = query.where(Reel.is_hidden == False)  # noqa: E712

    result = await session.execute(query.offset((page - 1) * limit).limit(limit))
    reels = list(result.scalars().all())

    result = await session.execute(
        select(Profile).where(Profile.user_id.in_({r.user_id for r in reels}))
    )
    profiles = {p.user_id: p for p in result.scalars().all()}

    return [
        AdminReel(
            id=r.id,
            author_id=r.user_id,
            author_name=(profiles[r.user_id].display_name if r.user_id in profiles else ""),
            video_url=r.video_url,
            cover_url=r.cover_url,
            caption=r.caption,
            likes_count=r.likes_count,
            is_hidden=r.is_hidden,
            created_at=r.created_at,
        )
        for r in reels
    ]


@router.post("/reels/action")
async def moderate_reel(
    data: ReelModerationAction,
    user: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    """Снять ролик с показа или вернуть его.

    Ролик не удаляем: жалоба могла быть ложной, и вернуть удалённое видео
    автору уже нечем. Автор свой скрытый ролик видит и понимает, что он
    снят, — иначе он решит, что загрузка не сработала.
    """
    if data.action not in ("hide", "show"):
        raise HTTPException(status_code=400, detail="action: hide или show")

    result = await session.execute(select(Reel).where(Reel.id == data.reel_id))
    reel = result.scalar_one_or_none()
    if not reel:
        raise HTTPException(status_code=404, detail="Ролик не найден")

    reel.is_hidden = data.action == "hide"

    автор_result = await session.execute(select(User).where(User.id == reel.user_id))
    await write_audit(
        session, user, "reel_action",
        target=автор_result.scalar_one_or_none(),
        details={"reel_id": reel.id, "action": data.action},
    )
    await session.commit()
    return {"success": True, "is_hidden": reel.is_hidden}


# ════════════════════════════════════════════════════════════════
#  ИСТОРИИ
# ════════════════════════════════════════════════════════════════

class AdminStory(BaseModel):
    id: str
    author_id: str
    author_name: str = ""
    media_url: str
    caption: str = ""
    #: matches / everyone — модератору важно, сколько людей это видело
    audience: str = "matches"
    views_count: int = 0
    is_hidden: bool = False
    created_at: datetime | None = None
    #: По нему UI помечает «истекла»: такая история уже не показывается
    #: и ждёт уборки, снимать её с показа поздно и незачем
    expires_at: datetime | None = None


class StoryModerationAction(BaseModel):
    story_id: str
    #: hide — снять с показа, show — вернуть
    action: str


@router.get("/stories", response_model=list[AdminStory])
async def list_stories_for_moderation(
    only_visible: bool = Query(default=False),
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=50, ge=1, le=200),
    user: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    """Истории для проверки, свежие сверху.

    Автоматика тут двойная — AI на загрузке и снятие по двум жалобам, — но
    история живёт сутки, и жалобы от аудитории «пары» может не собрать
    вовсе. Ручной просмотр закрывает эту щель, пока кадр ещё показывается.
    """
    query = select(Story).order_by(desc(Story.created_at))
    if only_visible:
        query = query.where(Story.is_hidden == False)  # noqa: E712

    result = await session.execute(query.offset((page - 1) * limit).limit(limit))
    stories = list(result.scalars().all())

    result = await session.execute(
        select(Profile).where(Profile.user_id.in_({s.user_id for s in stories}))
    )
    profiles = {p.user_id: p for p in result.scalars().all()}

    return [
        AdminStory(
            id=s.id,
            author_id=s.user_id,
            author_name=(profiles[s.user_id].display_name if s.user_id in profiles else ""),
            media_url=s.media_url,
            caption=s.caption,
            audience=s.audience,
            views_count=s.views_count,
            is_hidden=s.is_hidden,
            created_at=s.created_at,
            expires_at=s.expires_at,
        )
        for s in stories
    ]


@router.post("/stories/action")
async def moderate_story(
    data: StoryModerationAction,
    user: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    """Снять историю с показа или вернуть её.

    Не удаляем по той же причине, что и ролик: жалоба могла быть ложной,
    а удалённый кадр нечем показать поддержке, когда автор придёт спорить.
    Страйк здесь не ставится — страйки копит автоматика по жалобам, ручное
    решение админа их не дублирует.
    """
    if data.action not in ("hide", "show"):
        raise HTTPException(status_code=400, detail="action: hide или show")

    result = await session.execute(select(Story).where(Story.id == data.story_id))
    story = result.scalar_one_or_none()
    if not story:
        raise HTTPException(status_code=404, detail="История не найдена")

    story.is_hidden = data.action == "hide"

    автор_result = await session.execute(select(User).where(User.id == story.user_id))
    await write_audit(
        session, user, "story_action",
        target=автор_result.scalar_one_or_none(),
        details={"story_id": story.id, "action": data.action},
    )
    await session.commit()
    return {"success": True, "is_hidden": story.is_hidden}


# ════════════════════════════════════════════════════════════════
#  РАССЫЛКА
# ════════════════════════════════════════════════════════════════

#: Потолок Telegram на текст сообщения. Меряем ПОСЛЕ экранирования: бот
#: шлёт текст через html.escape (у него parse_mode=HTML по умолчанию, и
#: сырые < > & ломали бы отправку), а экранирование удлиняет текст.
TELEGRAM_MAX_LEN = 4096


class BroadcastCreate(BaseModel):
    text: str
    #: "all" — всем живым с Telegram; "test" — только себе, посмотреть
    #: сообщение глазами получателя до отправки всем
    segment: str = "all"


class BroadcastOut(BaseModel):
    id: str
    created_by: str
    created_by_name: str
    text: str
    segment: str
    status: str
    total: int
    sent: int
    failed: int
    created_at: datetime | None
    started_at: datetime | None
    finished_at: datetime | None


@router.post("/broadcast", response_model=BroadcastOut)
async def create_broadcast(
    data: BroadcastCreate,
    user: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    """Создать рассылку и разбудить бота.

    API только ставит задачу: клиента к Telegram у него нет, шлёт бот
    (bot/services/broadcast.py, событие в dating:bot:events — тот же канал,
    что у бана). Строка коммитится ДО публикации, иначе бот мог бы получить
    событие раньше, чем увидит задачу. Прогресс бот пишет в ту же строку —
    админка просто перечитывает список.
    """
    текст = data.text.strip()
    if not текст:
        raise HTTPException(status_code=400, detail="Текст пуст")
    if len(html.escape(текст, quote=False)) > TELEGRAM_MAX_LEN:
        raise HTTPException(
            status_code=400,
            detail=f"Слишком длинно: Telegram принимает до {TELEGRAM_MAX_LEN} "
                   "символов с учётом экранирования",
        )
    if data.segment not in ("all", "test"):
        raise HTTPException(status_code=400, detail="segment: all или test")

    имя_result = await session.execute(
        select(Profile.display_name).where(Profile.user_id == user.id)
    )
    рассылка = Broadcast(
        created_by=user.id,
        created_by_name=имя_result.scalar_one_or_none() or "",
        text=текст,
        segment=data.segment,
    )
    session.add(рассылка)
    # flush до аудита: id рассылки рождается на INSERT, а он нужен в details
    await session.flush()
    await write_audit(
        session, user, "broadcast",
        details={
            "broadcast_id": рассылка.id,
            "segment": data.segment,
            "chars": len(текст),
        },
    )
    await session.commit()

    try:
        from services.realtime import get_redis

        r = await get_redis()
        await r.publish(
            "dating:bot:events",
            json.dumps({"type": "broadcast", "broadcast_id": рассылка.id}),
        )
    except Exception as e:
        # Бот о задаче не узнал — честный error вместо вечного queued
        logger.error(f"Рассылка {рассылка.id} не доставлена боту: {e}")
        рассылка.status = "error"
        await session.commit()
        raise HTTPException(
            status_code=503, detail="Бот недоступен — рассылка не запущена"
        ) from e

    return _broadcast_out(рассылка)


@router.get("/broadcasts", response_model=list[BroadcastOut])
async def list_broadcasts(
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
    user: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    """Рассылки, свежие сверху. Пока бот шлёт, счётчики в строке растут —
    админка перечитывает список и видит прогресс."""
    result = await session.execute(
        select(Broadcast)
        .order_by(desc(Broadcast.created_at))
        .offset((page - 1) * limit)
        .limit(limit)
    )
    return [_broadcast_out(b) for b in result.scalars().all()]


def _broadcast_out(b: Broadcast) -> BroadcastOut:
    return BroadcastOut(
        id=b.id,
        created_by=b.created_by,
        created_by_name=b.created_by_name,
        text=b.text,
        segment=b.segment,
        status=b.status,
        total=b.total,
        sent=b.sent,
        failed=b.failed,
        created_at=b.created_at,
        started_at=b.started_at,
        finished_at=b.finished_at,
    )


# ════════════════════════════════════════════════════════════════
#  МЕТРИКИ
# ════════════════════════════════════════════════════════════════

class RetentionCohort(BaseModel):
    """Недельная когорта регистраций и доли вернувшихся."""

    week: str  # понедельник ISO-недели, "2026-08-17"
    size: int
    #: Доля вернувшихся спустя N дней и позже (0..1). None — окно ещё не
    #: закрыто (последний из когорты не прожил свои N дней) или когорта пуста
    d1: float | None
    d7: float | None
    d30: float | None


class RevenueRow(BaseModel):
    """Выручка одной валюты. Суммы в минорных единицах: XTR — звёзды,
    RUB — копейки, USDT — сотые."""

    currency: str
    count_30d: int
    amount_30d: int
    count_total: int
    amount_total: int
    payers_total: int  # уникальных плативших за всё время


class AdminMetrics(BaseModel):
    dau: int
    wau: int
    mau: int
    stickiness: float  # dau/mau; 0 при пустом mau
    cohorts: list[RetentionCohort]
    revenue: list[RevenueRow]
    #: С какого момента платежи пишутся с суммами; None — таких ещё нет.
    #: Старые строки журнала и платежи App Store сумм не имеют — их выручка
    #: здесь не видна (Apple считает её в App Store Connect)
    revenue_since: datetime | None


def _к_utc(dt: datetime | None) -> datetime | None:
    """К aware UTC для арифметики в Python: SQLite отдаёт server_default-даты
    naive, а вставленные из кода — aware, и сравнивать их между собой нельзя."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


@router.get("/metrics", response_model=AdminMetrics)
async def get_admin_metrics(
    user: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    """DAU/WAU/MAU, недельный retention и выручка.

    Активность — вход в мини-апп (`last_seen_at` обновляется в auth), люди,
    живущие только в боте, сюда не попадают. dN — классический unbounded
    retention: доля вернувшихся спустя N дней или позже, поэтому снапшота
    последнего визита достаточно и журнал посещений не нужен.

    Retention и когорты считаются в Python по парам (created_at,
    last_seen_at): датная арифметика в SQL у SQLite и Postgres разная
    (julianday против interval), а когортных строк — сотни, не миллионы.

    Read-only: в аудит не пишется.
    """
    now = datetime.now(timezone.utc)

    # ── Активность ────────────────────────────────────────────────
    # count(case) не считает NULL от else, поэтому одна строка вместо
    # трёх запросов
    result = await session.execute(
        select(
            func.count(case((User.last_seen_at >= now - timedelta(days=1), 1))),
            func.count(case((User.last_seen_at >= now - timedelta(days=7), 1))),
            func.count(case((User.last_seen_at >= now - timedelta(days=30), 1))),
        )
    )
    dau, wau, mau = result.one()

    # ── Retention: 8 недельных когорт, текущая и семь до неё ──────
    понедельник = now.replace(
        hour=0, minute=0, second=0, microsecond=0
    ) - timedelta(days=now.weekday())
    старт = понедельник - timedelta(weeks=7)

    result = await session.execute(
        select(User.created_at, User.last_seen_at).where(User.created_at >= старт)
    )

    счёт = [{"size": 0, "d1": 0, "d7": 0, "d30": 0} for _ in range(8)]
    for created, seen in result.all():
        created, seen = _к_utc(created), _к_utc(seen)
        индекс = (created - старт).days // 7
        if not 0 <= индекс < 8:
            continue
        корзина = счёт[индекс]
        корзина["size"] += 1
        if seen is not None:
            for имя, дней in (("d1", 1), ("d7", 7), ("d30", 30)):
                if seen >= created + timedelta(days=дней):
                    корзина[имя] += 1

    cohorts = []
    for i, корзина in enumerate(счёт):
        начало = старт + timedelta(weeks=i)
        строка = RetentionCohort(
            week=начало.strftime("%Y-%m-%d"),
            size=корзина["size"],
            d1=None, d7=None, d30=None,
        )
        for имя, дней in (("d1", 1), ("d7", 7), ("d30", 30)):
            # Окно закрыто, когда даже зарегистрировавшийся в последнюю
            # секунду недели прожил свои N дней — иначе доля была бы
            # занижена, и честнее показать «ещё рано»
            if корзина["size"] and начало + timedelta(weeks=1, days=дней) <= now:
                setattr(строка, имя, round(корзина[имя] / корзина["size"], 3))
        cohorts.append(строка)

    # ── Выручка: по валютам, всё время и последние 30 дней ────────
    месяц_назад = now - timedelta(days=30)
    result = await session.execute(
        select(
            ProcessedPayment.currency,
            func.count(ProcessedPayment.id),
            func.coalesce(func.sum(ProcessedPayment.amount), 0),
            func.count(func.distinct(ProcessedPayment.user_id)),
            func.count(case((ProcessedPayment.created_at >= месяц_назад, 1))),
            func.coalesce(
                func.sum(case(
                    (ProcessedPayment.created_at >= месяц_назад,
                     ProcessedPayment.amount),
                    else_=0,
                )),
                0,
            ),
        )
        .where(ProcessedPayment.amount.is_not(None))
        .group_by(ProcessedPayment.currency)
        .order_by(ProcessedPayment.currency)
    )
    revenue = [
        RevenueRow(
            currency=валюта or "",
            count_total=count_total,
            amount_total=int(amount_total),
            payers_total=payers_total,
            count_30d=count_30d,
            amount_30d=int(amount_30d),
        )
        for валюта, count_total, amount_total, payers_total,
            count_30d, amount_30d in result.all()
    ]

    result = await session.execute(
        select(func.min(ProcessedPayment.created_at)).where(
            ProcessedPayment.amount.is_not(None)
        )
    )
    revenue_since = result.scalar()

    return AdminMetrics(
        dau=dau,
        wau=wau,
        mau=mau,
        stickiness=round(dau / mau, 3) if mau else 0.0,
        cohorts=cohorts,
        revenue=revenue,
        revenue_since=revenue_since,
    )


# ════════════════════════════════════════════════════════════════
#  ADMIN AUDIT
# ════════════════════════════════════════════════════════════════

class AdminAuditEntry(BaseModel):
    id: str
    admin_id: str
    admin_name: str
    action: str
    target_user_id: str
    target_name: str
    details: dict
    created_at: datetime | None


@router.get("/audit", response_model=list[AdminAuditEntry])
async def list_audit(
    action: str = Query(
        default="all",
        pattern="^(all|ban|unban|set_verified|report_action|reel_action|story_action|broadcast)$",
    ),
    admin_id: str = Query(default=""),
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=50, ge=1, le=200),
    user: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    """Журнал действий админов: свежие сверху.

    Читают его все админы, не только владелец: журнал append-only, править
    его из админки нечем, а взаимная видимость действий в маленькой команде
    дисциплинирует лучше, чем скрытый надзор.
    """
    query = select(AdminAuditLog).order_by(desc(AdminAuditLog.created_at))
    if action != "all":
        query = query.where(AdminAuditLog.action == action)
    if admin_id:
        query = query.where(AdminAuditLog.admin_id == admin_id)

    query = query.offset((page - 1) * limit).limit(limit)
    result = await session.execute(query)

    return [
        AdminAuditEntry(
            id=row.id,
            admin_id=row.admin_id,
            admin_name=row.admin_name,
            action=row.action,
            target_user_id=row.target_user_id,
            target_name=row.target_name,
            details=row.details or {},
            created_at=row.created_at,
        )
        for row in result.scalars().all()
    ]


# ════════════════════════════════════════════════════════════════
#  ПРОМОКОДЫ
# ════════════════════════════════════════════════════════════════

class PromoCreateRequest(BaseModel):
    """Выпуск промокода. code пустой — сгенерируем сами."""
    tier: str
    days: int
    #: 0 — без лимита активаций
    max_uses: int = 1
    code: str = ""
    expires_at: Optional[datetime] = None
    comment: str = ""


class PromoPatchRequest(BaseModel):
    """Гашение и повторное включение кода."""
    is_active: bool


class PromoOut(BaseModel):
    """Строка промокода. Код открыт: промокод — не секрет, он печатается
    в постах, а админу нужно копировать его и после выпуска."""
    id: str
    code: str
    tier: str
    days: int
    max_uses: int
    used_count: int
    expires_at: Optional[str] = None
    is_active: bool
    comment: str
    created_at: Optional[str] = None


def _promo_out(p: PromoCode) -> PromoOut:
    return PromoOut(
        id=p.id,
        code=p.code,
        tier=p.tier,
        days=p.days,
        max_uses=p.max_uses,
        used_count=p.used_count,
        expires_at=p.expires_at.isoformat() if p.expires_at else None,
        is_active=p.is_active,
        comment=p.comment or "",
        created_at=p.created_at.isoformat() if p.created_at else None,
    )


@router.post("/promos", response_model=PromoOut)
async def create_promo(
    data: PromoCreateRequest,
    user: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    """Выпустить промокод.

    Тариф и срок проверяются здесь, а не Pydantic-границами: список тарифов
    живёт в services/plans.py, и вторая копия в схеме разъехалась бы с ним.
    """
    if data.tier not in (TIER_PLUS, TIER_ULTRA, TIER_AURORA):
        raise HTTPException(status_code=400, detail="Неизвестный тариф")
    if not 1 <= data.days <= 3650:
        raise HTTPException(status_code=400, detail="Срок: от 1 до 3650 дней")
    if not 0 <= data.max_uses <= 1_000_000:
        raise HTTPException(status_code=400, detail="Лимит: от 0 (без лимита) до 1 000 000")

    if data.code:
        код = normalize_code(data.code)
        if not валидный_кастомный_код(код):
            raise HTTPException(
                status_code=400,
                detail="Код: 4–32 знака, только латиница и цифры",
            )
    else:
        код = generate_promo_code()

    промо = PromoCode(
        code=код,
        tier=data.tier,
        days=data.days,
        max_uses=data.max_uses,
        expires_at=data.expires_at,
        comment=data.comment.strip()[:500],
    )
    session.add(промо)
    try:
        # flush ловит дубль кода сейчас, а не при коммите после ответа.
        # Разыгранный код перевыпускать нельзя: старые активации повисли бы
        # на новом смысле кода
        await session.flush()
    except IntegrityError:
        raise HTTPException(status_code=409, detail="Такой код уже есть")

    await write_audit(
        session, user, "promo_create",
        details={
            "promo_id": промо.id,
            "code": код,
            "tier": data.tier,
            "days": data.days,
            "max_uses": data.max_uses,
        },
    )
    return _promo_out(промо)


@router.get("/promos", response_model=list[PromoOut])
async def list_promos(
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=50, ge=1, le=200),
    user: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    """Промокоды, свежие сверху. used_count в строке — живой счётчик
    активаций, отдельного журнала админке не нужно."""
    result = await session.execute(
        select(PromoCode)
        .order_by(desc(PromoCode.created_at))
        .offset((page - 1) * limit)
        .limit(limit)
    )
    return [_promo_out(p) for p in result.scalars().all()]


@router.patch("/promos/{promo_id}", response_model=PromoOut)
async def patch_promo(
    promo_id: str,
    data: PromoPatchRequest,
    user: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    """Погасить или снова включить код. Удаления нет намеренно: на коде
    висят активации, и история «кто по какому коду пришёл» должна жить."""
    промо = await session.get(PromoCode, promo_id)
    if not промо:
        raise HTTPException(status_code=404, detail="Промокод не найден")

    промо.is_active = data.is_active
    await session.flush()
    await write_audit(
        session, user, "promo_toggle",
        details={"promo_id": промо.id, "code": промо.code, "is_active": data.is_active},
    )
    return _promo_out(промо)
