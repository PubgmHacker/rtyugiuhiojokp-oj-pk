from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import and_, desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from database.connection import get_session
from middleware.auth import get_current_user
from models.models import User, Profile, Like, Match, Message, Reel
from models.schemas import (
    DirectMessageRequest, DirectMessageResponse, DirectQuotaOut, MatchResponse, UserProfile,
)
from services.ai_matchmaker import generate_icebreakers
from services.ai_moderation import log_moderation, moderate_text
from services.enforcement import enforce_text_verdict
from services.chat_delivery import (
    ДоставкаОтклонена, check_chat_flood, fan_out, media_preview, notify_text_for,
    нормализовать_медиа, превью_сообщения, reel_preview, save_message,
)
from services.streaks import (
    can_revive as стрик_оживим, revive_streak, streak_emoji, get_streaks_bulk,
)
from services.direct_messages import direct_quota_left, start_direct_message
from services.matching import ОНЛАЙН_МИНУТ
from services.plans import (
    FEATURE_MIN_TIER,
    TIERS,
    direct_messages_per_day,
    tier_allows,
)
from services.premium import current_tier
from services.quotas import match_views_state, open_match, opened_match_ids
from services.public_profile import публичный_возраст
from services.stickers import картинка_наклейки
from services.decor import безопасный_код
from utils import as_list, public_photos, public_videos

router = APIRouter(prefix="/matches", tags=["matches"])


async def _get_own_match(session: AsyncSession, match_id: str, user_id: str) -> Match:
    result = await session.execute(
        select(Match).where(and_(
            Match.id == match_id,
            or_(Match.user1_id == user_id, Match.user2_id == user_id),
            Match.is_active == True,
        ))
    )
    match = result.scalar_one_or_none()
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")
    return match


async def _открыть_мэтч(session: AsyncSession, match_id: str, user_id: str) -> None:
    """Списать суточное открытие мэтча или отказать со ссылкой на подписку.

    Зовётся из каждой точки, где человек реально попадает в беседу: история
    сообщений, отправка, айсбрейкеры, восстановление стрика и WebSocket. Одна
    незакрытая точка обнуляет лимит целиком — читать чат через `/messages`
    ничем не хуже, чем через список.

    Идемпотентно в пределах окна: открытый чат можно листать и обновлять
    сколько угодно, слот тратится один раз на мэтч (см. services/quotas.py).
    """
    итог = await open_match(session, user_id, match_id)
    if not итог.granted:
        raise HTTPException(
            status_code=429,
            detail=f"На бесплатном уровне открыто {итог.state.limit} мэтча в "
            "сутки. Оформите подписку, чтобы открыть все, или подождите.",
        )


async def _to_resp(session: AsyncSession, match: Match, partner_id: str) -> MatchResponse:
    """Собрать `MatchResponse` для только что созданной беседы (без превью
    переписки — она появится со следующим GET /matches)."""
    result = await session.execute(select(Profile).where(Profile.user_id == partner_id))
    profile = result.scalar_one_or_none()
    return MatchResponse(
        id=match.id,
        match_score=match.match_score,
        ai_reason=match.ai_reason,
        created_at=match.created_at,
        partner=UserProfile(
            id=partner_id,
            display_name=profile.display_name if profile else "",
            bio=profile.bio if profile else "",
            age=публичный_возраст(profile),
            city=profile.city if profile else "",
            photos=public_photos(profile.photos) if profile else [],
            videos=public_videos(profile.videos) if profile else [],
            interests=as_list(profile.interests) if profile else [],
            sticker=картинка_наклейки(profile.sticker if profile else None),
            decor=безопасный_код(profile.decor if profile else None),
        ),
        kind=match.kind,
        initiator_id=match.initiator_id,
        direct_answered=match.direct_answered,
    )


@router.get("", response_model=list[MatchResponse])
async def get_matches(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(
        select(Match)
        .where(and_(
            or_(Match.user1_id == user.id, Match.user2_id == user.id),
            Match.is_active == True,
        ))
        .order_by(desc(Match.created_at))
        # Потолок, а не пагинация: экран чатов листает первые десятки, а
        # без LIMIT один аккаунт с тысячей мэтчей собирал бы ответ на
        # мегабайты и держал соединение пула на всё это время.
        .limit(200)
    )
    matches = result.scalars().all()
    if not matches:
        return []

    # Профили и превью переписки берём пакетно: раньше на каждый мэтч
    # уходил отдельный запрос (N+1), и список чатов заметно тормозил
    partner_ids = [
        m.user2_id if m.user1_id == user.id else m.user1_id for m in matches
    ]
    match_ids = [m.id for m in matches]

    result = await session.execute(
        select(Profile).where(Profile.user_id.in_(partner_ids))
    )
    profiles = {p.user_id: p for p in result.scalars().all()}

    # Галочка и «в сети» — тем же пакетом: карточки людей в чатах читаются
    # как карточки деки, а там оба сигнала есть. Порог онлайна общий
    # (ОНЛАЙН_МИНУТ), чтобы сосед по экрану не спорил с декой.
    недавно = datetime.now(timezone.utc) - timedelta(minutes=ОНЛАЙН_МИНУТ)
    верифицированные: set[str] = set()
    онлайн: set[str] = set()
    result = await session.execute(
        select(User.id, User.is_verified, User.last_seen_at).where(
            User.id.in_(partner_ids)
        )
    )
    for uid, verified, last_seen in result.all():
        if verified:
            верифицированные.add(uid)
        if last_seen is not None and last_seen.tzinfo is None:
            last_seen = last_seen.replace(tzinfo=timezone.utc)
        if last_seen is not None and last_seen >= недавно:
            p = profiles.get(uid)
            # Инкогнито и пауза гасят флаг — то же правило, что в деке
            if p and not p.is_incognito and not p.is_paused:
                онлайн.add(uid)

    # Последнее сообщение каждого чата
    last_ts = (
        select(func.max(Message.created_at).label("ts"), Message.match_id)
        .where(Message.match_id.in_(match_ids))
        .group_by(Message.match_id)
        .subquery()
    )
    result = await session.execute(
        select(Message).join(
            last_ts,
            and_(
                Message.match_id == last_ts.c.match_id,
                Message.created_at == last_ts.c.ts,
            ),
        )
    )
    last_messages = {m.match_id: m for m in result.scalars().all()}

    # Непрочитанные — присланные партнёром и без отметки о прочтении
    result = await session.execute(
        select(Message.match_id, func.count(Message.id))
        .where(
            and_(
                Message.match_id.in_(match_ids),
                Message.sender_id != user.id,
                Message.read_at.is_(None),
            )
        )
        .group_by(Message.match_id)
    )
    unread = dict(result.all())

    # Суточный лимит открытых мэтчей (бесплатный уровень). Список отдаём
    # целиком — он и есть витрина подписки, — но у закрытых вычищаем данные
    # партнёра и превью переписки. Вычищаем на сервере: скрытие только в
    # интерфейсе обходится вкладкой «сеть» за один клик.
    #
    # Показ списка НЕ тратит квоту: иначе один заход в чаты сжигал бы все
    # суточные открытия сразу (см. services/quotas.py).
    tier = await current_tier(session, user.id)
    opened = await opened_match_ids(session, user.id)
    лимит_исчерпан = (await match_views_state(session, user.id, tier)).exhausted

    # Серии — одним запросом на весь список (внутри то же сгорание и
    # квота, что у get_streak; см. get_streaks_bulk)
    серии = await get_streaks_bulk(session, match_ids)

    responses = []
    for m in matches:
        partner_id = m.user2_id if m.user1_id == user.id else m.user1_id
        profile = profiles.get(partner_id)
        locked = лимит_исчерпан and m.id not in opened

        if locked:
            # Ни имени, ни фото, ни города: закрытый мэтч — это «есть кто-то»,
            # а не «вот кто». Счётчик непрочитанных оставляем — он честный и
            # он же главный повод оформить подписку.
            partner_profile = UserProfile(id=partner_id)
        else:
            partner_profile = UserProfile(
                id=partner_id,
                display_name=profile.display_name if profile else "",
                bio=profile.bio if profile else "",
                # «Скрыть возраст» действует и в списке чатов: настройка обещает
                # скрыть возраст от всех, а не только от тех, кто ещё не мэтч
                age=публичный_возраст(profile),
                city=profile.city if profile else "",
                photos=public_photos(profile.photos) if profile else [],
                videos=public_videos(profile.videos) if profile else [],
                interests=as_list(profile.interests) if profile else [],
                sticker=картинка_наклейки(profile.sticker if profile else None),
                decor=безопасный_код(profile.decor if profile else None),
                is_verified=partner_id in верифицированные,
                is_online=partner_id in онлайн,
            )

        last = last_messages.get(m.id)
        preview = None
        if last and not locked:
            preview = превью_сообщения(last)

        # Стрик из пакетного словаря — сгорание и окно revive применены
        # при чтении, как и раньше, но без запроса на каждый чат
        streak = серии.get(m.id)
        days = streak.streak_days if streak else 0
        emoji = streak_emoji(days) if days else ""
        # Кнопку показываем ровно по тому правилу, по которому её примет
        # `revive_streak`. Здесь стояла своя копия условия («сгорела именно
        # вчера»), и она расходилась с сервисом в обе стороны: кнопка была
        # там, где запрос вернёт 429, и пропадала на второй день, хотя
        # окно восстановления — месяц.
        can_revive = стрик_оживим(streak)
        revives_left = streak.revives_left if streak else 0

        responses.append(
            MatchResponse(
                id=m.id,
                match_score=m.match_score,
                ai_reason=m.ai_reason,
                created_at=m.created_at,
                partner=partner_profile,
                last_message=preview,
                last_message_at=last.created_at if last else None,
                unread_count=unread.get(m.id, 0),
                kind=m.kind,
                initiator_id=m.initiator_id,
                direct_answered=m.direct_answered,
                streak_days=days,
                streak_emoji=emoji,
                streak_can_revive=can_revive,
                streak_revives_left=revives_left,
                locked=locked,
            )
        )

    # Активные переписки и свежие мэтчи — вперёд
    responses.sort(
        key=lambda r: r.last_message_at or r.created_at or datetime.min,
        reverse=True,
    )
    return responses


@router.get("/{match_id}/messages")
async def get_messages(
    match_id: str, offset: int = 0, limit: int = 50,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    await _get_own_match(session, match_id, user.id)
    await _открыть_мэтч(session, match_id, user.id)

    # Последние `limit` сообщений (desc + reverse), не первые
    result = await session.execute(
        select(Message).where(Message.match_id == match_id)
        .order_by(desc(Message.created_at)).offset(offset).limit(limit)
    )
    messages = list(reversed(result.scalars().all()))

    # Превью пересланных роликов: без него получатель видит пустое сообщение.
    # Одним запросом на всю страницу, а не по ролику на сообщение
    reels: dict[str, Reel] = {}
    reel_ids = {m.reel_id for m in messages if m.reel_id}
    if reel_ids:
        result = await session.execute(select(Reel).where(Reel.id.in_(reel_ids)))
        reels = {r.id: r for r in result.scalars().all()}

    return [
        {"id": m.id, "sender_id": m.sender_id, "text": m.text,
         "image_url": m.image_url,
         "reel": reel_preview(reels.get(m.reel_id)) if m.reel_id else None,
         "media": media_preview(m),
         "read_at": m.read_at.isoformat() if m.read_at else None,
         "created_at": m.created_at.isoformat() if m.created_at else None}
        for m in messages
    ]


@router.post("/{match_id}/messages")
async def post_message(
    match_id: str,
    data: dict,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Отправить сообщение по HTTP — второй путь рядом с WebSocket-чатом.

    Проходит через тот же `services/chat_delivery` (save_message/fan_out), что
    и сокет: раньше в этом проекте парные пути расходились именно так — второй
    источник сообщения не повторял фан-аут и собеседник ничего не получал.

    Правила отправки («одно письмо до ответа», чужая картинка) роутер не
    проверяет сам — они внутри `save_message`, в одной транзакции с записью.
    Здесь только перевод отказа в HTTP-код.
    """
    match = await _get_own_match(session, match_id, user.id)
    await _открыть_мэтч(session, match_id, user.id)
    partner_id = match.user2_id if match.user1_id == user.id else match.user1_id

    text = str(data.get("text", "")).strip()[:2000]
    image_url = data.get("image_url")
    try:
        media = нормализовать_медиа(user.id, data.get("media"))
    except ДоставкаОтклонена as отказ:
        raise HTTPException(status_code=400, detail=отказ.detail)
    if not text and not image_url and not media:
        raise HTTPException(status_code=400, detail="Пустое сообщение")

    # Антифлуд до модерации: залп сообщений — это прежде всего залп платных
    # AI-запросов, отсекаем раньше, чем платим
    try:
        await check_chat_flood(user.id)
    except ДоставкаОтклонена as отказ:
        raise HTTPException(status_code=429, detail=отказ.detail)

    if text:
        verdict = await moderate_text(text)
        await log_moderation(user.id, "chat_message", text, verdict)
        ответ_бана = await enforce_text_verdict(
            session, user, verdict, "Сообщение нарушает правила"
        )
        if ответ_бана is not None:
            return ответ_бана

    # Мэтч читался этой сессией, а `save_message` пишет своей: без коммита её
    # транзакция не увидит незакоммиченных изменений (например, флага ответа)
    await session.commit()

    try:
        payload = await save_message(match_id, user.id, text, image_url, media=media)
    except ДоставкаОтклонена as отказ:
        # Чужая ссылка — ошибка запроса, остальное — запрет по правилам чата
        код = 400 if отказ.code in ("foreign_image", "foreign_media", "bad_media") else 403
        raise HTTPException(status_code=код, detail=отказ.detail)
    if payload is None:
        raise HTTPException(status_code=404, detail="Чат не найден")

    await fan_out(
        payload, match_id, user.id, partner_id, notify_text_for(text, image_url, media)
    )
    return payload


@router.get("/direct/quota", response_model=DirectQuotaOut)
async def get_direct_quota(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Остаток писем без взаимного лайка — честный гейт на клиенте: тариф не
    позволяет вовсе, или лимит на сегодня исчерпан — разные экраны."""
    tier = await current_tier(session, user.id)
    allowed = tier_allows(tier, "direct_messages")
    return DirectQuotaOut(
        left=await direct_quota_left(session, user.id) if allowed else 0,
        total=direct_messages_per_day(tier) if allowed else 0,
        allowed=allowed,
        required_tier_name=TIERS[FEATURE_MIN_TIER["direct_messages"]].name,
    )


@router.post("/direct", response_model=DirectMessageResponse)
async def send_direct_message(
    data: DirectMessageRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Написать без взаимного лайка — платный крючок (аналог «Мимолёта»).

    Заводит `Match(kind="direct")` и сразу отправляет первое сообщение через
    тот же `save_message`/`fan_out`, что и обычный чат — переписка сразу
    появляется в списке /matches и открывается в общем WS-чате.
    """
    text = data.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="Пустое сообщение")

    verdict = await moderate_text(text)
    await log_moderation(user.id, "direct_message", text, verdict)
    ответ_бана = await enforce_text_verdict(
        session, user, verdict, "Сообщение нарушает правила"
    )
    if ответ_бана is not None:
        return ответ_бана

    match = await start_direct_message(session, user.id, data.target_id)
    if not isinstance(match, Match):
        # DirectDenied — код стабилен для клиента, текст — для показа
        status = 429 if match.code == "limit" else 403
        raise HTTPException(status_code=status, detail=match.detail)

    match_id = match.id
    # save_message открывает СВОЮ сессию (services/chat_delivery.py читает
    # через async_session_factory, а не через эту Depends-сессию) — если не
    # закоммитить здесь, только что созданный Match в ней не виден
    await session.commit()
    try:
        payload = await save_message(match_id, user.id, text)
    except ДоставкаОтклонена as отказ:
        # Тут ловится второе письмо в уже заведённую беседу: `start_direct_message`
        # переиспользует её и лимит не списывает, так что без этой проверки путь
        # давал верхнему тарифу безлимитный канал к молчащему человеку
        raise HTTPException(status_code=403, detail=отказ.detail)
    if payload is None:
        raise HTTPException(status_code=404, detail="Чат не найден")

    partner_id = match.user2_id if match.user1_id == user.id else match.user1_id
    await fan_out(payload, match_id, user.id, partner_id, text)

    resp = await _to_resp(session, match, partner_id)
    return DirectMessageResponse(match=resp)


@router.post("/{match_id}/unmatch")
async def unmatch(
    match_id: str,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Размэтчиться: чат становится недоступен обоим.

    Удаляем и взаимные лайки — иначе любой новый лайк одной из сторон
    мгновенно реактивирует мэтч против воли второй.
    """
    match = await _get_own_match(session, match_id, user.id)
    match.is_active = False
    await session.execute(
        Like.__table__.delete().where(or_(
            and_(Like.liker_id == match.user1_id, Like.liked_id == match.user2_id),
            and_(Like.liker_id == match.user2_id, Like.liked_id == match.user1_id),
        ))
    )
    await session.flush()
    return {"success": True}


@router.get("/{match_id}/icebreakers")
async def get_icebreakers(
    match_id: str,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """AI-айсбрейкеры: 3 варианта первого сообщения под анкету партнёра."""
    match = await _get_own_match(session, match_id, user.id)
    await _открыть_мэтч(session, match_id, user.id)
    partner_id = match.user2_id if match.user1_id == user.id else match.user1_id
    icebreakers = await generate_icebreakers(session, user.id, partner_id)
    return {"icebreakers": icebreakers}


@router.post("/{match_id}/revive-streak")
async def revive_streak_route(
    match_id: str,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Восстановить серию общения после дня тишины.

    Не путать с покупкой стрика: возвращение к тому, что было вчера,
    имеет смысл только когда серия действительно прогорела из-за
    пропущенного дня. Если прогаревшая серия уже была на пике 300+
    (3 revive/месяц), а её не взяли — это осознанный отказ, а не баг.
    """
    match = await _get_own_match(session, match_id, user.id)
    await _открыть_мэтч(session, match_id, user.id)
    try:
        streak = await revive_streak(session, match.id)
    except ValueError as err:
        raise HTTPException(status_code=429, detail=str(err))
    await session.commit()
    return {
        "success": True,
        "streak_days": streak.streak_days,
        "revives_left": streak.revives_left,
        "streak_emoji": streak_emoji(streak.streak_days),
    }
