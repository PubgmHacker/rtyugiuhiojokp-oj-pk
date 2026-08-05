from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, and_, or_, desc, func, text as sa_text
from sqlalchemy.ext.asyncio import AsyncSession

from config import get_settings
from database.connection import get_session
from middleware.auth import get_current_user
from models.models import User, Profile, Like, Match, Subscription
from models.schemas import (
    LikeRequest,
    LikeResponse,
    MatchResponse,
    SuperlikeQuota,
    UserProfile,
)
from services.realtime import publish_match, publish_new_like, publish_new_match_for_bot
from services.ai_matchmaker import score_match
from services.ai_moderation import log_moderation, moderate_text
from services.premium import current_tier, is_premium as _is_premium
from services.plans import superlikes_for, tier_allows
from services.push import notify_new_match
from utils import as_list

router = APIRouter(prefix="/likes", tags=["likes"])
settings = get_settings()


def _pair(a: str, b: str) -> tuple[str, str]:
    """Нормализованная пара для Match — исключает дубликаты (A,B)/(B,A)."""
    return (a, b) if a < b else (b, a)


async def _find_match(session: AsyncSession, a: str, b: str) -> Optional[Match]:
    u1, u2 = _pair(a, b)
    result = await session.execute(
        select(Match).where(and_(Match.user1_id == u1, Match.user2_id == u2))
    )
    return result.scalar_one_or_none()


def _calc_age(birth_date) -> Optional[int]:
    if not birth_date:
        return None
    now = datetime.now()
    age = now.year - birth_date.year
    if (now.month, now.day) < (birth_date.month, birth_date.day):
        age -= 1
    return age


def _profile_to_user(
    profile: Optional[Profile], user_id: str, like_message: str = ""
) -> UserProfile:
    if not profile:
        return UserProfile(id=user_id, like_message=like_message)
    return UserProfile(
        id=user_id,
        display_name=profile.display_name or "",
        bio=profile.bio or "",
        gender=profile.gender or "other",
        # Настройка «скрыть возраст» действует всюду, где видно чужую анкету,
        # а не только в деке: иначе интерфейс говорит «скрыто», а любой, кто
        # вас лайкнул, возраст всё равно видит
        age=None if profile.hide_age else _calc_age(profile.birth_date),
        city=profile.city or "",
        photos=as_list(profile.photos),
        interests=as_list(profile.interests),
        goal=profile.goal or "",
        subculture=profile.subculture or "",
        mbti=profile.mbti or "",
        height_cm=profile.height_cm,
        like_message=like_message,
    )


async def _to_resp(session: AsyncSession, match: Match, partner_id: str) -> MatchResponse:
    result = await session.execute(select(Profile).where(Profile.user_id == partner_id))
    profile = result.scalar_one_or_none()
    return MatchResponse(
        id=match.id, match_score=match.match_score,
        ai_reason=match.ai_reason, created_at=match.created_at,
        partner=_profile_to_user(profile, partner_id),
    )


async def _superlikes_left(session: AsyncSession, user_id: str) -> int:
    """Сколько суперлайков осталось: суточная квота плюс бонусные из кейсов.

    Суточную часть считаем по таблице лайков, а не по счётчику в Redis:
    суперлайк — вещь, за которую платят, и его расход не должен теряться
    вместе с кешем. Бонусные лежат в анкете и не возобновляются.
    """
    quota = superlikes_for(await current_tier(session, user_id))
    since = datetime.now(timezone.utc) - timedelta(days=1)
    result = await session.execute(
        select(func.count(Like.id)).where(and_(
            Like.liker_id == user_id,
            Like.type == "superlike",
            Like.created_at >= since,
        ))
    )
    used = result.scalar() or 0

    result = await session.execute(
        select(Profile.bonus_superlikes).where(Profile.user_id == user_id)
    )
    bonus = result.scalar_one_or_none() or 0

    return max(0, quota - used) + bonus


async def _spend_bonus_superlike(session: AsyncSession, user_id: str) -> None:
    """Списать бонусный суперлайк, если суточные уже израсходованы.

    Порядок именно такой: сначала тратится то, что и так обновится завтра, а
    выпавшее из кейса остаётся на потом — иначе награда сгорала бы первой.
    """
    quota = superlikes_for(await current_tier(session, user_id))
    since = datetime.now(timezone.utc) - timedelta(days=1)
    result = await session.execute(
        select(func.count(Like.id)).where(and_(
            Like.liker_id == user_id,
            Like.type == "superlike",
            Like.created_at >= since,
        ))
    )
    # Текущий лайк уже записан, поэтому суточные исчерпаны при used > quota
    if (result.scalar() or 0) <= quota:
        return

    result = await session.execute(select(Profile).where(Profile.user_id == user_id))
    profile = result.scalar_one_or_none()
    if profile and profile.bonus_superlikes > 0:
        profile.bonus_superlikes -= 1


@router.get("/superlikes", response_model=SuperlikeQuota)
async def get_superlike_quota(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Остаток суперлайков — для счётчика на кнопке в деке."""
    tier = await current_tier(session, user.id)
    return SuperlikeQuota(
        left=await _superlikes_left(session, user.id),
        total=superlikes_for(tier),
        is_premium=tier != "free",
    )


@router.post("", response_model=LikeResponse)
async def create_like(
    data: LikeRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    if data.target_id == user.id:
        raise HTTPException(status_code=400, detail="Cannot like yourself")

    result = await session.execute(select(User).where(User.id == data.target_id))
    target = result.scalar_one_or_none()
    if not target or target.is_banned:
        raise HTTPException(status_code=404, detail="Profile not found")

    if data.type == "superlike" and not await _superlikes_left(session, user.id):
        raise HTTPException(
            status_code=429,
            detail="Суперлайки на сегодня закончились",
        )

    u1, u2 = _pair(user.id, data.target_id)
    # Advisory-lock на пару: без него два встречных лайка в параллельных
    # транзакциях не видят друг друга (READ COMMITTED) и мэтч теряется навсегда.
    await session.execute(
        sa_text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 0))"),
        {"k": f"dating:pair:{u1}:{u2}"},
    )

    result = await session.execute(
        select(Like).where(and_(Like.liker_id == user.id, Like.liked_id == data.target_id))
    )
    existing = result.scalar_one_or_none()

    # Новый лайк или апгрейд с pass — событие «вы понравились»
    notify_new_like = (
        data.type != "pass"
        and (existing is None or existing.type == "pass")
    )

    # Текст к лайку модерируем как любой публичный текст: получатель увидит
    # его до мэтча, то есть до того, как сможет заблокировать отправителя.
    like_message = (data.message or "").strip() if data.type != "pass" else ""
    if like_message:
        verdict = await moderate_text(like_message)
        await log_moderation(user.id, "like_message", like_message, verdict)
        if verdict["blocked"]:
            raise HTTPException(status_code=422, detail="Сообщение нарушает правила")

    if existing:
        if existing.type != data.type:
            # Смена решения (rewind): pass → like, like → superlike и т.п.
            existing.type = data.type
        # Пустым текстом прежний не затираем: человек мог лайкнуть с
        # сообщением, а потом просто поменять тип лайка
        if like_message:
            existing.message = like_message
    else:
        session.add(Like(
            liker_id=user.id,
            liked_id=data.target_id,
            type=data.type,
            message=like_message,
        ))
    await session.flush()

    # Бонусный суперлайк списываем после записи лайка: до неё непонятно,
    # укладывается ли он в суточную квоту
    if data.type == "superlike":
        await _spend_bonus_superlike(session, user.id)

    if data.type == "pass":
        return LikeResponse(liked=False, matched=False)

    # Взаимность? (лайк уже под advisory-lock — гонки нет)
    result = await session.execute(
        select(Like).where(
            and_(Like.liker_id == data.target_id, Like.liked_id == user.id, Like.type != "pass")
        )
    )
    mutual_like = result.scalar_one_or_none()

    if not mutual_like:
        await session.commit()  # события — строго после коммита
        if notify_new_like:
            await publish_new_like(data.target_id, user.id)
        return LikeResponse(liked=True, matched=False)

    # Мэтч: берём существующую строку пары (unique constraint), реактивируем
    # после unmatch или создаём новую. Ветка также «лечит» пары, у которых
    # взаимные лайки есть, а мэтча нет.
    match = await _find_match(session, user.id, data.target_id)
    is_new_match = False
    if match and not match.is_active:
        match.is_active = True
        is_new_match = True
    elif not match:
        match_score, ai_reason = await score_match(session, user.id, data.target_id)
        match = Match(user1_id=u1, user2_id=u2,
                      match_score=match_score, ai_reason=ai_reason, is_active=True)
        session.add(match)
        await session.flush()
        is_new_match = True

    response = LikeResponse(liked=True, matched=True,
                            match=await _to_resp(session, match, data.target_id))
    match_id, match_score, ai_reason = match.id, match.match_score, match.ai_reason

    await session.commit()  # бот читает БД сразу по событию — коммитим до publish

    if is_new_match:
        await publish_match(user.id, data.target_id, match_id, match_score, ai_reason)
        await publish_match(data.target_id, user.id, match_id, match_score, ai_reason)
        # Уведомление обоим в Telegram через бота
        await publish_new_match_for_bot(match_id, u1, u2)
        # И пуш в iOS-приложение — тем, кто зарегистрировал устройство
        await _push_match_notifications(session, user.id, data.target_id, match_id)

    return response


async def _push_match_notifications(
    session: AsyncSession,
    user_id: str,
    partner_id: str,
    match_id: str,
) -> None:
    """Пуши обоим участникам мэтча: каждому — имя собеседника."""
    result = await session.execute(
        select(Profile.user_id, Profile.display_name).where(
            Profile.user_id.in_([user_id, partner_id])
        )
    )
    names = {row[0]: row[1] or "" for row in result.all()}

    await notify_new_match(session, user_id, names.get(partner_id, ""), match_id)
    await notify_new_match(session, partner_id, names.get(user_id, ""), match_id)
    # Мёртвые токены могли быть вычищены при отправке
    await session.commit()


@router.get("/received", response_model=list[UserProfile])
async def get_likes_received(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """«Кто меня лайкнул»: входящие лайки без взаимности (и без мэтча)."""
    # Кого я уже оценил (лайк или пасс) — их не показываем
    result = await session.execute(select(Like.liked_id).where(Like.liker_id == user.id))
    my_rated = {row[0] for row in result.all()}

    result = await session.execute(
        select(Like)
        .join(User, Like.liker_id == User.id)
        .where(and_(
            Like.liked_id == user.id,
            Like.type != "pass",
            User.is_banned == False,
        ))
        .order_by(desc(Like.created_at))
        .limit(50)
    )
    likes = result.scalars().all()

    # Кто именно лайкнул — платная возможность. Бесплатному аккаунту отдаём
    # карточки без имени, фото и текста: количество он видит честно, а вот
    # «кто» — за подписку. Пустой список тут был бы обманом: человеку
    # показалось бы, что его никто не лайкал.
    revealed = tier_allows(await current_tier(session, user.id), "see_who_liked")

    out: list[UserProfile] = []
    for lk in likes:
        if lk.liker_id in my_rated:
            continue
        if not revealed:
            out.append(UserProfile(id=lk.liker_id, is_locked=True))
            continue
        result = await session.execute(select(Profile).where(Profile.user_id == lk.liker_id))
        profile = result.scalar_one_or_none()
        out.append(_profile_to_user(profile, lk.liker_id, lk.message or ""))
    return out
