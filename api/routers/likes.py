from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, and_, desc, func, not_, or_, text as sa_text
from sqlalchemy.ext.asyncio import AsyncSession

from config import get_settings
from database.connection import async_session_factory, get_session
from middleware.auth import get_current_user
from models.models import User, Profile, Like, Match, Block
from models.schemas import (
    DailyLimits,
    LikeRequest,
    LikeResponse,
    MatchResponse,
    SuperlikeQuota,
    UserProfile,
)
from services.realtime import publish_match, publish_new_like, publish_new_match_for_bot
from services.ai_matchmaker import score_match
from services.analytics import EVENT_FIRST_MATCH, EVENT_FIRST_SWIPE, track
from services.ai_moderation import log_moderation, moderate_text
from services.enforcement import enforce_text_verdict
from services.matching import ОНЛАЙН_МИНУТ
from services.public_profile import публичный_возраст
from services.stickers import картинка_наклейки
from services.decor import безопасный_код
from services.premium import current_tier
from services.plans import superlikes_for, tier_allows
from services.quotas import likes_state, match_views_state
from services.push import is_configured, notify_new_match
from utils import as_list, public_photos, public_videos

router = APIRouter(prefix="/likes", tags=["likes"])
settings = get_settings()
logger = logging.getLogger(__name__)


def _pair(a: str, b: str) -> tuple[str, str]:
    """Нормализованная пара для Match — исключает дубликаты (A,B)/(B,A)."""
    return (a, b) if a < b else (b, a)


async def _find_match(session: AsyncSession, a: str, b: str) -> Optional[Match]:
    u1, u2 = _pair(a, b)
    result = await session.execute(
        select(Match).where(and_(Match.user1_id == u1, Match.user2_id == u2))
    )
    return result.scalar_one_or_none()


async def _profile_to_user(
    session: AsyncSession,
    profile: Optional[Profile],
    user_id: str,
    like_message: str = "",
    *,
    is_verified: bool = False,
    is_online: bool = False,
) -> UserProfile:
    if not profile:
        return UserProfile(id=user_id, like_message=like_message)
    # Канал виден только если у ВЛАДЕЛЬЦА анкеты открыт tg_channel — это его
    # фича, не читающего; иначе доступ по подписке зависел бы от того, кто
    # смотрит, а не у кого включена ссылка
    tg_channel = profile.tg_channel or ""
    if tg_channel and not tier_allows(await current_tier(session, user_id), "tg_channel"):
        tg_channel = ""
    return UserProfile(
        id=user_id,
        display_name=profile.display_name or "",
        bio=profile.bio or "",
        gender=profile.gender or "other",
        # Настройка «скрыть возраст» действует всюду, где видно чужую анкету,
        # а не только в деке: иначе интерфейс говорит «скрыто», а любой, кто
        # вас лайкнул, возраст всё равно видит
        age=публичный_возраст(profile),
        city=profile.city or "",
        photos=public_photos(profile.photos),
        videos=public_videos(profile.videos),
        interests=as_list(profile.interests),
        goal=profile.goal or "",
        subculture=profile.subculture or "",
        mbti=profile.mbti or "",
        height_cm=profile.height_cm,
        sticker=картинка_наклейки(profile.sticker),
        decor=безопасный_код(profile.decor),
        like_message=like_message,
        tg_channel=tg_channel,
        is_verified=is_verified,
        # «В сети» не выдаёт спрятавшихся: инкогнито и пауза гасят флаг —
        # то же правило, что в деке (services/matching.py)
        is_online=is_online and not profile.is_incognito and not profile.is_paused,
    )


async def _to_resp(session: AsyncSession, match: Match, partner_id: str) -> MatchResponse:
    result = await session.execute(select(Profile).where(Profile.user_id == partner_id))
    profile = result.scalar_one_or_none()
    return MatchResponse(
        id=match.id, match_score=match.match_score,
        ai_reason=match.ai_reason, created_at=match.created_at,
        partner=await _profile_to_user(session, profile, partner_id),
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


@router.get("/limits", response_model=DailyLimits)
async def get_daily_limits(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Остаток суточных лимитов: лайки и открытия мэтчей.

    Отдельная ручка, а не поля в ответе на лайк: счётчик нужен деке ещё до
    первого свайпа, а шторке лимита — точное время возврата. Клиент зовёт её
    после 429, чтобы показать, сколько ждать, вместо голого «попробуйте позже».
    """
    tier = await current_tier(session, user.id)
    likes = await likes_state(session, user.id, tier)
    views = await match_views_state(session, user.id, tier)
    return DailyLimits(
        likes_left=likes.left,
        likes_total=likes.limit,
        likes_reset_at=likes.reset_at,
        matches_left=views.left,
        matches_total=views.limit,
        matches_reset_at=views.reset_at,
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

    # Блокировка действует в обе стороны и здесь тоже: заблокированный не должен
    # снова выйти на того, кто его закрыл, — ни лайком, ни суперлайком с текстом,
    # ни повторным мэтчем. Дека таких уже прячет (services/matching), но прямой
    # POST её минует. Отвечаем 404, как на бан: существование блокировки наружу
    # не подтверждаем.
    result = await session.execute(
        select(Block.id).where(
            or_(
                and_(Block.blocker_id == user.id, Block.blocked_id == data.target_id),
                and_(Block.blocker_id == data.target_id, Block.blocked_id == user.id),
            )
        )
    )
    if result.scalar_one_or_none() is not None:
        raise HTTPException(status_code=404, detail="Profile not found")

    u1, u2 = _pair(user.id, data.target_id)
    # Два лока, и всегда в этом порядке: сначала личный, потом парный.
    #
    # Личный нужен суперлайкам: квота суточная и считается по всем целям сразу,
    # поэтому парный лок её не защищает — два одновременных суперлайка РАЗНЫМ
    # людям берут разные парные ключи, оба читают «использовано 0 из 1» и оба
    # проходят. Платная вещь раздавалась бы вдвое.
    #
    # Парный нужен мэтчу: без него два встречных лайка в параллельных
    # транзакциях не видят друг друга (READ COMMITTED) и мэтч теряется навсегда.
    #
    # Порядок фиксирован глобально (личный → парный) и повторён в
    # `services/direct_messages.start_direct_message`. Разный порядок захвата в
    # двух путях — это классический дедлок: встречные запросы упёрлись бы друг
    # в друга насмерть.
    await session.execute(
        sa_text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 0))"),
        {"k": f"dating:likes:{user.id}"},
    )
    await session.execute(
        sa_text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 0))"),
        {"k": f"dating:pair:{u1}:{u2}"},
    )

    result = await session.execute(
        select(Like).where(and_(Like.liker_id == user.id, Like.liked_id == data.target_id))
    )
    existing = result.scalar_one_or_none()

    # Суточный лимит лайков — под тем же личным локом и по тем же причинам,
    # что квота суперлайков ниже. Тратят его только НОВЫЕ лайки:
    #
    #  • пропуск не тратит ничего — иначе лимит запрещал бы листать деку;
    #  • повторный лайк той же анкеты (смена типа, повтор после обрыва сети)
    #    уже лежит в подсчёте, и отказ по нему отобрал бы израсходованное.
    #
    # Суперлайк лимит тратит: это тоже лайк, просто с отдельной квотой сверху.
    if data.type != "pass" and (existing is None or existing.type == "pass"):
        лимит = await likes_state(session, user.id)
        if лимит.exhausted:
            raise HTTPException(
                status_code=429,
                detail=f"Лайки на сегодня закончились — {лимит.limit} в сутки "
                "на бесплатном уровне. Оформите подписку или подождите.",
            )

    # Квота суперлайков — уже под локом, и только для НОВОГО суперлайка:
    # повторный запрос с тем же типом ничего не тратит, а его суперлайк уже
    # лежит в подсчёте — проверяя и его, мы отказывали бы человеку в том, что
    # он купил и получил
    if (
        data.type == "superlike"
        and (existing is None or existing.type != "superlike")
        and not await _superlikes_left(session, user.id)
    ):
        raise HTTPException(
            status_code=429,
            detail="Суперлайки на сегодня закончились",
        )

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
        ответ_бана = await enforce_text_verdict(
            session, user, verdict, "Сообщение нарушает правила"
        )
        if ответ_бана is not None:
            return ответ_бана

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

    # Веха воронки: человек начал пользоваться декой. pass — тоже решение
    # по анкете, поэтому точка стоит до ранних веток. Повторы гасит dedup_key
    await track(session, user.id, EVENT_FIRST_SWIPE, once=True)

    # Бонусный суперлайк списываем после записи лайка: до неё непонятно,
    # укладывается ли он в суточную квоту
    if data.type == "superlike":
        await _spend_bonus_superlike(session, user.id)

    if data.type == "pass":
        # Коммитить здесь не нужно: get_session коммитит после успешного
        # обработчика (database/connection.py). Ранний return из этого не
        # выпадает — зависимость доводит транзакцию до конца сама
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
    if match and match.kind == "direct":
        # Беседа началась с платного письма, а теперь есть взаимные лайки —
        # это обычный мэтч, и держать пару под правилом «одно письмо до
        # ответа» больше нельзя: получатель уже сказал «да» лайком, а
        # отправитель до этого молчал бы, пока тот не напишет первым.
        #
        # Флаги раунда (`direct_answered`, `direct_letter_sent`) НЕ трогаем: они
        # читаются только у бесед типа "direct" и гасятся там, где раунд
        # начинается заново, — в `start_direct_message`. Сбрасывать их и здесь
        # значило бы завести второе место, где живёт то же правило, а такие
        # пары в этом проекте расходятся.
        match.kind = "match"
        is_new_match = not match.is_active
        match.is_active = True
    elif match and not match.is_active:
        match.is_active = True
        is_new_match = True
    elif not match:
        match_score, ai_reason = await score_match(session, user.id, data.target_id)
        match = Match(user1_id=u1, user2_id=u2,
                      match_score=match_score, ai_reason=ai_reason, is_active=True)
        session.add(match)
        await session.flush()
        is_new_match = True

    # Веха обоим: «первый мэтч» случился у каждого из пары, а не только у
    # того, чей свайп его замкнул. Повторы (и реактивацию после unmatch у
    # ветеранов) гасит dedup_key. До commit ниже — в транзакции мэтча
    if is_new_match:
        await track(session, user.id, EVENT_FIRST_MATCH, once=True)
        await track(session, data.target_id, EVENT_FIRST_MATCH, once=True)

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
        await _push_match_notifications(user.id, data.target_id, match_id)

    return response


async def _push_match_notifications(
    user_id: str,
    partner_id: str,
    match_id: str,
) -> None:
    """Пуши обоим участникам мэтча: каждому — имя собеседника.

    Сессия своя и закрывается до разговора с Apple: сессия запроса держала бы
    занятым соединение из пула всё время, пока отвечает APNs, — а мэтч к этому
    моменту уже закоммичен, и продолжать его транзакцию незачем.
    """
    if not is_configured():
        return
    try:
        async with async_session_factory() as session:
            result = await session.execute(
                select(Profile.user_id, Profile.display_name).where(
                    Profile.user_id.in_([user_id, partner_id])
                )
            )
            names = {row[0]: row[1] or "" for row in result.all()}
    except Exception as e:
        logger.error(f"Match push names failed ({match_id}): {e}")
        return

    await notify_new_match(user_id, names.get(partner_id, ""), match_id)
    await notify_new_match(partner_id, names.get(user_id, ""), match_id)


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
        select(Like, User.is_verified, User.last_seen_at)
        .join(User, Like.liker_id == User.id)
        .where(and_(
            Like.liked_id == user.id,
            Like.type != "pass",
            User.is_banned == False,
            # Заблокированные — в любую сторону — не должны всплывать в «кто меня
            # лайкнул»: иначе заблокированный шлёт суперлайк с текстом, и тот
            # доходит до платного получателя, обходя саму блокировку
            not_(
                select(Block.id)
                .where(
                    or_(
                        and_(Block.blocker_id == user.id, Block.blocked_id == Like.liker_id),
                        and_(Block.blocker_id == Like.liker_id, Block.blocked_id == user.id),
                    )
                )
                .exists()
            ),
        ))
        .order_by(desc(Like.created_at))
        .limit(50)
    )
    rows = result.all()

    # Кто именно лайкнул — платная возможность. Бесплатному аккаунту отдаём
    # карточки без имени, фото и текста: количество он видит честно, а вот
    # «кто» — за подписку. Пустой список тут был бы обманом: человеку
    # показалось бы, что его никто не лайкал.
    revealed = tier_allows(await current_tier(session, user.id), "see_who_liked")

    # Порог «в сети» — общий с декой: два разных представления об «онлайне»
    # на соседних экранах читались бы как баг
    недавно = datetime.now(timezone.utc) - timedelta(minutes=ОНЛАЙН_МИНУТ)

    out: list[UserProfile] = []
    for lk, verified, last_seen in rows:
        if lk.liker_id in my_rated:
            continue
        if not revealed:
            out.append(UserProfile(id=lk.liker_id, is_locked=True))
            continue
        result = await session.execute(select(Profile).where(Profile.user_id == lk.liker_id))
        profile = result.scalar_one_or_none()
        if last_seen is not None and last_seen.tzinfo is None:
            last_seen = last_seen.replace(tzinfo=timezone.utc)
        out.append(await _profile_to_user(
            session, profile, lk.liker_id, lk.message or "",
            is_verified=bool(verified),
            is_online=last_seen is not None and last_seen >= недавно,
        ))
    return out
