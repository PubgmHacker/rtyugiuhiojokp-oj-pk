from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Optional

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import JSONResponse
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from sqlalchemy import and_, or_
from sqlalchemy import text as sa_text

from config import get_settings
from database.connection import get_session
from middleware.auth import get_current_user
from models.models import (
    BoostActivation,
    User,
    Profile,
    Like,
    Match,
    Message,
    Referral,
)
from models.schemas import (
    BoostOut,
    DeckProfile,
    DeviceRegistration,
    ProfileUpdate,
    UserProfile,
    VisitorOut,
    VisitorsOut,
)
from services.matching import get_deck_profiles
from services.ai_moderation import log_moderation, moderate_text
from services.plans import (
    BOOST_MINUTES,
    FEATURE_MIN_TIER,
    TIERS,
    boosts_per_day,
    tier_allows,
)
from services.premium import current_tier, is_premium as _is_premium
from services.public_profile import в_utc, возраст_из_даты, наша_картинка, публичный_возраст
from services.stickers import картинка_наклейки
from services.push import register_device
from services.visits import count_visits, list_visitors, record_visit
from utils import as_list

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/profiles", tags=["profiles"])
settings = get_settings()


async def _deck_like_profile(
    session: AsyncSession, profile: Optional[Profile], user_id: str
) -> UserProfile:
    """Публичная часть чужой анкеты — то же, что видно на карточке в деке."""
    if not profile:
        return UserProfile(id=user_id)
    # Канал показываем только если ЕГО ВЛАДЕЛЕЦ на тарифе, который открывает
    # tg_channel — это фича гостя-визитёра, а не смотрящего, поэтому гейт
    # проверяем по тому, кому принадлежит анкета, а не по тому, кто читает
    tg_channel = profile.tg_channel or ""
    if tg_channel and not tier_allows(await current_tier(session, user_id), "tg_channel"):
        tg_channel = ""
    return UserProfile(
        id=user_id,
        display_name=profile.display_name or "",
        bio=profile.bio or "",
        gender=profile.gender or "other",
        # Настройка «скрыть возраст» действует и здесь: этот хелпер отдаёт
        # чужую анкету в разделе «Гости»
        age=публичный_возраст(profile),
        city=profile.city or "",
        photos=as_list(profile.photos),
        interests=as_list(profile.interests),
        goal=profile.goal or "",
        subculture=profile.subculture or "",
        mbti=profile.mbti or "",
        height_cm=profile.height_cm,
        sticker=картинка_наклейки(profile.sticker),
        tg_channel=tg_channel,
    )


@router.get("/deck", response_model=list[DeckProfile])
async def get_deck(
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
    limit: int = Query(default=10, ge=1, le=20),
):
    """Получить анкеты для свайпов."""
    # Отметка активности: без неё «сейчас в сети» показывалось бы только по
    # факту входа, а человек с долгой сессией числился бы offline, пока
    # свайпает. Запрос деки — самое частое действие, по нему и судим
    user.last_seen_at = datetime.now(timezone.utc)

    profiles = await get_deck_profiles(session, user.id, limit)
    await session.commit()
    return profiles


def _имя_уровня(feature: str) -> str:
    """Имя уровня, который открывает возможность — из тарифной линейки.

    Писать его словом в тексте отказа нельзя: гейт живёт в `FEATURE_MIN_TIER`,
    и после переноса возможности на другой уровень зашитое имя молча соврёт —
    человек купит не то, что ему предложили.
    """
    return TIERS[FEATURE_MIN_TIER[feature]].name


async def _требовать(session: AsyncSession, user_id: str, feature: str, что: str) -> None:
    """403, если уровень не открывает возможность.

    Тот же вопрос, что задаёт `_require_spreads` в routers/tarot.py, — но
    отдельной функцией: инкогнито проверяется внутри PATCH /me по содержимому
    тела запроса, а зависимость FastAPI про тело ничего не знает.
    """
    if not tier_allows(await current_tier(session, user_id), feature):
        raise HTTPException(status_code=403, detail=f"{что} доступен на {_имя_уровня(feature)}")


async def _require_boost(
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> User:
    """Пускает к бусту только с подходящим тарифом.

    Раньше право на буст выводилось из числа включений (`per_day == 0` — значит
    нельзя), то есть из `BOOSTS_PER_DAY`, а не из таблицы возможностей. Гейт
    работал лишь пока две таблицы случайно согласны: поставь бесплатному один
    пробный буст — и `deck_boost` открылся бы всем, хотя в `FEATURE_MIN_TIER`
    он платный.
    """
    await _требовать(session, user.id, "deck_boost", "Буст")
    return user


async def _boost_state(session: AsyncSession, user_id: str, profile: Optional[Profile]) -> BoostOut:
    tier = await current_tier(session, user_id)
    per_day = boosts_per_day(tier)

    since = datetime.now(timezone.utc) - timedelta(days=1)
    result = await session.execute(
        select(func.count(BoostActivation.id)).where(and_(
            BoostActivation.user_id == user_id,
            BoostActivation.created_at >= since,
        ))
    )
    used = result.scalar() or 0

    until = profile.boost_until if profile else None
    active = bool(until and until > datetime.now(timezone.utc))
    return BoostOut(
        active=active,
        until=until if active else None,
        minutes=BOOST_MINUTES,
        left_today=max(0, per_day - used),
        per_day=per_day,
        required_tier_name=_имя_уровня("deck_boost"),
    )


@router.get("/me/boost", response_model=BoostOut)
async def get_boost(
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """Состояние буста: активен ли и сколько включений осталось сегодня."""
    result = await session.execute(select(Profile).where(Profile.user_id == user.id))
    return await _boost_state(session, user.id, result.scalar_one_or_none())


@router.post("/me/boost", response_model=BoostOut)
async def activate_boost(
    session: AsyncSession = Depends(get_session),
    user: User = Depends(_require_boost),
):
    """Поднять анкету в выдаче на ограниченное время.

    Тариф проверяет `_require_boost` до входа сюда — здесь остаётся только
    суточный лимит. `Depends(get_session)` в обоих местах отдаёт одну и ту же
    сессию: FastAPI кеширует подзависимости в пределах запроса.

    Повторное включение поверх активного буста продлевает его от текущего
    окончания, а не с нуля: иначе оплаченные минуты сгорали бы.
    """
    result = await session.execute(select(Profile).where(Profile.user_id == user.id))
    profile = result.scalar_one_or_none()
    if not profile:
        raise HTTPException(status_code=400, detail="Сначала заполните анкету")

    # Суточный лимит проверяется запросом и подтверждается записью. Без
    # блокировки параллельные запросы читают «использовано 0» одновременно, и
    # один оплаченный буст включается несколько раз (см. routers/likes.py)
    await session.execute(
        sa_text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 0))"),
        {"k": f"dating:boost:{user.id}"},
    )

    state = await _boost_state(session, user.id, profile)
    if not state.left_today:
        raise HTTPException(status_code=429, detail="Бусты на сегодня закончились")

    now = datetime.now(timezone.utc)
    прежний = в_utc(profile.boost_until)
    base = прежний if (прежний and прежний > now) else now
    profile.boost_until = base + timedelta(minutes=BOOST_MINUTES)
    session.add(BoostActivation(user_id=user.id))
    await session.flush()

    fresh = await _boost_state(session, user.id, profile)
    await session.commit()
    return fresh


@router.post("/{profile_id}/visit", status_code=204)
async def record_profile_visit(
    profile_id: str,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """Отметить, что пользователь увидел эту анкету.

    Вызывается клиентом, когда карточка реально показана сверху деки, а не при
    выдаче деки: дека отдаёт десяток анкет вперёд, и записывать их все значило
    бы врать в разделе «Гости».

    Ответ пустой и ошибок не возвращает: статистика не должна ломать просмотр.
    """
    await record_visit(session, visitor_id=user.id, host_id=profile_id)
    await session.commit()
    return Response(status_code=204)


@router.get("/me/visitors", response_model=VisitorsOut)
async def get_my_visitors(
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
    period: str = Query(default="all", pattern="^(today|week|all)$"),
):
    """Раздел «Гости»: кто заходил в анкету.

    Число гостей отдаём всем, а вот кто именно — только на Ultra. Скрывать и
    число тоже значило бы не дать повода купить: человек не знает, что там
    вообще кто-то есть.

    Период фильтрует и то и другое одинаково — он не про гейт подписки, а про
    то, какое окно смотреть; сам гейт (посчитано/показано) логика периода не
    касается.
    """
    since = None
    now = datetime.now(timezone.utc)
    if period == "today":
        since = now.replace(hour=0, minute=0, second=0, microsecond=0)
    elif period == "week":
        since = now - timedelta(days=7)

    total = await count_visits(session, user.id, since=since)
    if not tier_allows(await current_tier(session, user.id), "visitors"):
        return VisitorsOut(total=total, revealed=False, visitors=[], period=period)

    visitors = [
        VisitorOut(
            profile=await _deck_like_profile(session, profile, visitor_id),
            visits=visits,
            last_seen_at=last_seen,
        )
        for profile, visitor_id, visits, last_seen in await list_visitors(
            session, user.id, since=since
        )
    ]
    return VisitorsOut(total=total, revealed=True, visitors=visitors, period=period)


@router.post("/deck/reset")
async def reset_deck(
    user: User = Depends(get_current_user),
):
    """Кнопка «Обновить» в деке.

    Ничего не сбрасывает на сервере и не должна: дека и так исключает
    только тех, кого пользователь уже оценил (таблица лайков), а порядок
    выдачи каждый раз новый. Эндпоинт оставлен, чтобы клиент старой
    версии не получал 404 — сама подгрузка идёт следующим запросом деки.
    """
    return {"success": True}


async def _referral_stats(session: AsyncSession, user_id: str) -> dict:
    result = await session.execute(
        select(func.count(Referral.id)).where(Referral.referrer_id == user_id)
    )
    invited = result.scalar() or 0
    return {
        "invited_count": invited,
        "referral_boost": invited >= settings.REFERRAL_MIN_INVITES,
        "referral_target": settings.REFERRAL_MIN_INVITES,
        "referral_boost_percent": settings.REFERRAL_BOOST_PERCENT,
    }


@router.get("/me", response_model=UserProfile)
async def get_my_profile(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Получить свою анкету."""
    result = await session.execute(select(Profile).where(Profile.user_id == user.id))
    profile = result.scalar_one_or_none()

    # Своя анкета: hide_age прячет возраст от других, а не от владельца
    age = возраст_из_даты(profile.birth_date) if profile else None

    return UserProfile(
        id=user.id,
        telegram_id=user.telegram_id,
        role=user.role,
        is_banned=user.is_banned,
        is_verified=user.is_verified,
        created_at=user.created_at,
        display_name=profile.display_name if profile else "",
        bio=profile.bio if profile else "",
        gender=profile.gender if profile else "other",
        age=age,
        city=profile.city if profile else "",
        photos=as_list(profile.photos) if profile else [],
        interests=as_list(profile.interests) if profile else [],
        ai_bio=profile.ai_bio if profile else None,
        looking_for=profile.looking_for if profile else "any",
        is_incognito=profile.is_incognito if profile else False,
        hide_age=profile.hide_age if profile else False,
        hide_distance=profile.hide_distance if profile else False,
        hide_from_visitors=profile.hide_from_visitors if profile else False,
        is_premium=await _is_premium(session, user.id),
        age_min=profile.age_min if profile else 18,
        age_max=profile.age_max if profile else 99,
        distance_max=profile.distance_max if profile else 100,
        goal=profile.goal if profile else "",
        subculture=profile.subculture if profile else "",
        mbti=profile.mbti if profile else "",
        height_cm=profile.height_cm if profile else None,
        filter_goal=profile.filter_goal if profile else "",
        filter_subculture=profile.filter_subculture if profile else "",
        filter_city=profile.filter_city if profile else "",
        filter_height_min=profile.filter_height_min if profile else None,
        filter_height_max=profile.filter_height_max if profile else None,
        has_location=bool(profile and profile.latitude is not None),
        # Только своя анкета: в чужой почте нет и быть не должно
        email=user.email,
        # Владелец видит свой канал вне зависимости от тарифа — гейт
        # решает, покажется ли он ДРУГИМ (см. _deck_like_profile), а не
        # прячет поле от самого человека в его же настройках
        tg_channel=profile.tg_channel if profile else "",
        **(await _referral_stats(session, user.id)),
    )


#: Юзернейм Telegram: латиница/цифры/подчёркивание, 5-32 символа, не
#: начинается с цифры — стандартные правила самого Telegram.
_TG_USERNAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{4,31}$")


def _нормализовать_tg_channel(raw: str) -> str:
    """Привести ввод к голому username или бросить 400.

    Человек может вставить «@username», «t.me/username» или полную ссылку —
    все варианты приходят с разных мест. Храним и отдаём только голый
    username: сборка ссылки — забота клиента (см. web/src/lib/api.ts), а не
    бэкенда.
    """
    username = raw.strip()
    if not username:
        return ""  # пустая строка — осознанный сброс канала

    username = re.sub(r"^https?://", "", username, flags=re.IGNORECASE)
    username = re.sub(r"^(t\.me|telegram\.me)/", "", username, flags=re.IGNORECASE)
    username = username.lstrip("@")
    username = username.split("?")[0].rstrip("/")

    if not _TG_USERNAME_RE.match(username):
        raise HTTPException(
            status_code=400,
            detail="Некорректный юзернейм канала: латиница, цифры и _, 5-32 символа, не начинается с цифры",
        )
    return username


def _проверить_фото(новые: list[str], прежние: list[str]) -> list[str]:
    """Фото в анкете — только наши, уже прошедшие модерацию.

    Модерация и срезание EXIF живут в `POST /upload/photo` и в боте. Но сама
    анкета обновляется через `PATCH /profiles/me`, и `photos` там — обычный
    список строк: без этой проверки можно было один раз честно загрузить
    фото, а потом подсунуть ссылку на любую картинку в интернете. Она попала
    бы в деку, лайки и превью чатов, не увидев ни AI-модерации, ни
    санитайзера, — и вдобавок утекала бы referer'ом на чужой сервер.

    Что принимаем:
    - URL из нашего R2 (их выдаёт только успешно отмодерированная загрузка);
    - значения, которые уже стоят в анкете, — иначе клиент не смог бы
      переставить или удалить существующие фото;
    - Telegram file_id — их кладёт бот, когда R2 не настроен (см.
      bot/handlers/registration.py), и они не URL вовсе.

    Строку, которой нет среди прежних и которая похожа на ссылку не к нам,
    отклоняем.
    """
    известные = set(прежние)

    for фото in новые:
        if фото in известные:
            continue
        if наша_картинка(фото):
            continue
        raise HTTPException(
            status_code=400,
            detail="Фото можно добавить только через загрузку: сторонние ссылки не принимаются",
        )

    return новые


@router.patch("/me", response_model=UserProfile)
async def update_my_profile(
    data: ProfileUpdate,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Обновить свою анкету."""
    result = await session.execute(select(Profile).where(Profile.user_id == user.id))
    profile = result.scalar_one_or_none()

    if not profile:
        profile = Profile(user_id=user.id)
        session.add(profile)
        await session.flush()

    update_fields = data.model_dump(exclude_unset=True)

    # Инкогнито-режим — платная фича (выключить может любой). Спрашиваем
    # таблицу возможностей, а не «есть ли вообще подписка»: `is_premium` — это
    # `plan != "free"`, и запись с чужим или испорченным значением уровня
    # открывала инкогнито, хотя `current_tier` считает такой уровень
    # бесплатным. Тот же разъезд включил бы фичу для всех платных, останься
    # она в FEATURE_MIN_TIER на верхнем уровне.
    if update_fields.get("is_incognito") is True:
        await _требовать(session, user.id, "incognito", "Инкогнито-режим")

    if update_fields.get("photos") is not None:
        update_fields["photos"] = _проверить_фото(
            update_fields["photos"], as_list(profile.photos)
        )

    if "tg_channel" in update_fields:
        # Фича платная (см. FEATURE_MIN_TIER["tg_channel"]) — без неё
        # молча игнорируем, а не 403: экрана с апсейлом под это поле нет,
        # и клиент его просто не показывает без подписки
        if tier_allows(await current_tier(session, user.id), "tg_channel"):
            update_fields["tg_channel"] = _нормализовать_tg_channel(
                update_fields["tg_channel"] or ""
            )
        else:
            update_fields.pop("tg_channel")

    if "birth_date" in update_fields and update_fields["birth_date"]:
        try:
            # Колонка DateTime(timezone=True) — храним datetime, не date
            update_fields["birth_date"] = datetime.strptime(
                update_fields["birth_date"], "%Y-%m-%d"
            ).replace(tzinfo=timezone.utc)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid birth_date format. Use YYYY-MM-DD")

    # Возраст переводим в дату рождения: точный день не спрашиваем,
    # для подбора по возрасту достаточно года. Явный birth_date главнее.
    age_value = update_fields.pop("age", None)
    if age_value and not update_fields.get("birth_date"):
        update_fields["birth_date"] = datetime(
            datetime.now(timezone.utc).year - int(age_value), 1, 1, tzinfo=timezone.utc
        )

    for key, value in update_fields.items():
        if value is None:
            continue  # explicit null не затирает non-nullable колонки (иначе 500)
        setattr(profile, key, value)

    if len(as_list(profile.photos)) > settings.MAX_PHOTOS:
        raise HTTPException(status_code=400, detail=f"Max {settings.MAX_PHOTOS} photos allowed")
    if len(profile.bio) > settings.MAX_BIO_LENGTH:
        raise HTTPException(status_code=400, detail=f"Bio must be under {settings.MAX_BIO_LENGTH} chars")

    if data.bio:
        mod_result = await moderate_text(profile.bio)
        await log_moderation(user.id, "bio", profile.bio, mod_result)
        if mod_result["blocked"]:
            raise HTTPException(status_code=422, detail="Bio violates content policy")

    # Имя проверяем наравне с био: оно видно чаще, чем анкета целиком — в деке,
    # в списке чатов, в комнатах и в уведомлениях. Через него уходили реклама,
    # контакты и брань, потому что модерация стояла только на био
    if data.display_name:
        mod_result = await moderate_text(profile.display_name)
        await log_moderation(user.id, "display_name", profile.display_name, mod_result)
        if mod_result["blocked"]:
            raise HTTPException(status_code=422, detail="Имя нарушает правила")

    # Канал — такой же публичный текст, как имя, только он ведёт вовне:
    # реклама и мошенничество через него утекали бы мимо модерации остальных полей
    if "tg_channel" in update_fields and profile.tg_channel:
        mod_result = await moderate_text(profile.tg_channel)
        await log_moderation(user.id, "tg_channel", profile.tg_channel, mod_result)
        if mod_result["blocked"]:
            raise HTTPException(status_code=422, detail="Канал нарушает правила")

    await session.flush()

    # Своя анкета — возраст показываем владельцу всегда
    age = возраст_из_даты(profile.birth_date)

    return UserProfile(
        id=user.id,
        telegram_id=user.telegram_id,
        role=user.role,
        is_banned=user.is_banned,
        is_verified=user.is_verified,
        created_at=user.created_at,
        display_name=profile.display_name,
        bio=profile.bio,
        gender=profile.gender,
        age=age,
        city=profile.city,
        photos=as_list(profile.photos),
        interests=as_list(profile.interests),
        ai_bio=profile.ai_bio,
        looking_for=profile.looking_for,
        is_incognito=profile.is_incognito,
        hide_age=profile.hide_age,
        hide_distance=profile.hide_distance,
        hide_from_visitors=profile.hide_from_visitors,
        is_premium=await _is_premium(session, user.id),
        age_min=profile.age_min,
        age_max=profile.age_max,
        distance_max=profile.distance_max,
        goal=profile.goal,
        subculture=profile.subculture,
        mbti=profile.mbti,
        height_cm=profile.height_cm,
        filter_goal=profile.filter_goal,
        filter_subculture=profile.filter_subculture,
        filter_city=profile.filter_city,
        filter_height_min=profile.filter_height_min,
        filter_height_max=profile.filter_height_max,
        has_location=profile.latitude is not None,
        tg_channel=profile.tg_channel,
        **(await _referral_stats(session, user.id)),
    )


@router.post("/me/devices")
async def register_push_device(
    data: DeviceRegistration,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Принять токен устройства для пуш-уведомлений из нативной обёртки."""
    await register_device(session, user.id, data.token, data.platform)
    return {"success": True}


@router.get("/me/export")
async def export_my_data(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Выгрузка своих данных одним JSON-файлом.

    Ожидаемая возможность для приватности: пользователь должен иметь
    доступ к тому, что о нём хранится.
    """
    result = await session.execute(select(Profile).where(Profile.user_id == user.id))
    profile = result.scalar_one_or_none()

    result = await session.execute(select(Like).where(Like.liker_id == user.id))
    likes = result.scalars().all()

    result = await session.execute(
        select(Match).where(or_(Match.user1_id == user.id, Match.user2_id == user.id))
    )
    matches = result.scalars().all()

    result = await session.execute(select(Message).where(Message.sender_id == user.id))
    messages = result.scalars().all()

    payload = {
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "account": {
            "id": user.id,
            "telegram_id": user.telegram_id,
            "created_at": user.created_at.isoformat() if user.created_at else None,
            "is_verified": user.is_verified,
        },
        "profile": {
            "display_name": profile.display_name if profile else "",
            "bio": profile.bio if profile else "",
            "gender": profile.gender if profile else "",
            "city": profile.city if profile else "",
            "birth_date": (
                profile.birth_date.isoformat() if profile and profile.birth_date else None
            ),
            "photos": as_list(profile.photos) if profile else [],
            "interests": as_list(profile.interests) if profile else [],
            "has_location": bool(profile and profile.latitude is not None),
        },
        "likes_given": [
            {"target_id": l.liked_id, "type": l.type, "at": l.created_at.isoformat() if l.created_at else None}
            for l in likes
        ],
        "matches": [
            {
                "id": m.id,
                "partner_id": m.user2_id if m.user1_id == user.id else m.user1_id,
                "at": m.created_at.isoformat() if m.created_at else None,
            }
            for m in matches
        ],
        "messages_sent": [
            {
                "match_id": msg.match_id,
                "text": msg.text,
                "at": msg.created_at.isoformat() if msg.created_at else None,
            }
            for msg in messages
        ],
    }

    filename = f"souldawn-data-{user.id[:8]}.json"
    return JSONResponse(
        content=payload,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.delete("/me", status_code=204)
async def delete_my_account(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Полное удаление аккаунта и всех связанных данных.

    Обязательная возможность по требованию App Store 5.1.1(v): удалять
    надо действительно, а не помечать флагом. Связанные таблицы
    вычищаются каскадом (ondelete="CASCADE" в моделях).
    """
    photo_urls: list[str] = []
    result = await session.execute(select(Profile).where(Profile.user_id == user.id))
    profile = result.scalar_one_or_none()
    if profile:
        photo_urls = [p for p in as_list(profile.photos) if isinstance(p, str)]

    result = await session.execute(select(User).where(User.id == user.id))
    db_user = result.scalar_one_or_none()
    if not db_user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    await session.delete(db_user)
    await session.commit()

    # Файлы в объектном хранилище каскад не удалит — чистим отдельно.
    # Сбой здесь не должен отменять уже выполненное удаление аккаунта.
    if photo_urls:
        try:
            from services.r2_storage import delete_photo_from_r2

            prefix = (settings.R2_PUBLIC_URL or "").rstrip("/") + "/"
            for url in photo_urls:
                # В базе хранятся публичные URL, а удаление принимает ключ
                # объекта; file_id из Telegram пропускаем
                if prefix != "/" and url.startswith(prefix):
                    await delete_photo_from_r2(url[len(prefix) :])
        except Exception as e:
            logger.warning(f"Не удалось удалить фото из R2 после удаления аккаунта: {e}")

    return Response(status_code=204)
