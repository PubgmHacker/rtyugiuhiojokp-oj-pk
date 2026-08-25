from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Optional

import logging

import httpx
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
from services.ai_moderation import log_moderation, moderate_text, verify_person_in_photo
from services.analytics import EVENT_APP_OPEN, EVENT_PROFILE_CREATED, track
from services.enforcement import (
    TEXT_BAN_REASONS,
    banned_response,
    register_identity_strike,
    register_text_strike,
)
from services.appearance import DEFAULT_THEME, доступна, нормализовать
from services.plans import (
    BOOST_MINUTES,
    FEATURE_MIN_TIER,
    TIERS,
    boosts_per_day,
    tier_allows,
)
from services.premium import current_tier, is_premium as _is_premium
from services.public_profile import в_utc, возраст_из_даты, публичный_возраст
from services.stickers import картинка_наклейки
from services.decor import безопасный_код
from services.push import register_device
from services.visits import count_visits, list_visitors, record_visit
from utils import as_list, public_videos

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/profiles", tags=["profiles"])
settings = get_settings()


async def _deck_like_profile(
    session: AsyncSession,
    profile: Optional[Profile],
    user_id: str,
    *,
    is_verified: bool = False,
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
        videos=public_videos(profile.videos),
        interests=as_list(profile.interests),
        goal=profile.goal or "",
        subculture=profile.subculture or "",
        mbti=profile.mbti or "",
        height_cm=profile.height_cm,
        sticker=картинка_наклейки(profile.sticker),
        decor=безопасный_код(profile.decor),
        tg_channel=tg_channel,
        # Галочка — там же, где сама анкета: раздел «Гости» её тоже показывает.
        # Хелпер уже получает is_verified, но раньше не клал его в ответ — тот
        # же разнобой «в одном месте из трёх», которым болел hide_age.
        is_verified=is_verified,
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
    """Пускает к бусту с подходящим тарифом — или с купленным паком.

    Раньше право на буст выводилось из числа включений (`per_day == 0` — значит
    нельзя), то есть из `BOOSTS_PER_DAY`, а не из таблицы возможностей. Гейт
    работал лишь пока две таблицы случайно согласны: поставь бесплатному один
    пробный буст — и `deck_boost` открылся бы всем, хотя в `FEATURE_MIN_TIER`
    он платный.

    Бонусные включения (пак за Stars в боте) — сами себе оплата: закрывать
    их тарифным гейтом значило бы продать бесплатному уровню пак, которым
    нельзя воспользоваться.
    """
    result = await session.execute(
        select(Profile.bonus_boosts).where(Profile.user_id == user.id)
    )
    if (result.scalar_one_or_none() or 0) > 0:
        return user
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
    bonus = profile.bonus_boosts if profile else 0

    # в_utc — как у «прежний» в activate_boost: SQLite отдаёт поле naive,
    # и сравнение с aware-временем падало бы TypeError
    until = в_utc(profile.boost_until) if profile else None
    active = bool(until and until > datetime.now(timezone.utc))
    return BoostOut(
        active=active,
        until=until if active else None,
        minutes=BOOST_MINUTES,
        # Суточные плюс купленные паком: у обоих пулов одна кнопка
        left_today=max(0, per_day - used) + bonus,
        per_day=per_day,
        bonus=bonus,
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
    # Суточные тратятся первыми — они и так вернутся завтра, а купленный пак
    # остаётся на потом (тот же порядок, что у _spend_bonus_superlike в
    # routers/likes.py). Суточных не осталось — списываем бонусное включение.
    if state.left_today - state.bonus <= 0:
        profile.bonus_boosts -= 1
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
            profile=await _deck_like_profile(
                session, profile, visitor_id, is_verified=is_verified
            ),
            visits=visits,
            last_seen_at=last_seen,
        )
        for profile, visitor_id, visits, last_seen, is_verified in await list_visitors(
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

    # Дневная сетка D1/D7: клиент грузит свою анкету при каждом старте —
    # это и есть «открыл приложение» для iOS с сохранённым токеном, который
    # идёт мимо /auth/telegram. Повторы дня гасит dedup_key
    await track(session, user.id, EVENT_APP_OPEN, daily=True)

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
        videos=as_list(profile.videos) if profile else [],
        interests=as_list(profile.interests) if profile else [],
        ai_bio=profile.ai_bio if profile else None,
        looking_for=profile.looking_for if profile else "any",
        is_incognito=profile.is_incognito if profile else False,
        is_paused=profile.is_paused if profile else False,
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
        filter_verified=profile.filter_verified if profile else False,
        has_location=bool(profile and profile.latitude is not None),
        # Своё оформление владелец видит всегда: схему он выбирал сам, и
        # прятать её от него в его же настройках нечего.
        app_theme=profile.app_theme if profile else "",
        decor=безопасный_код(profile.decor if profile else None),
        # Только своя анкета: в чужой почте нет и быть не должно
        email=user.email,
        # Владелец видит свой канал вне зависимости от тарифа — гейт
        # решает, покажется ли он ДРУГИМ (см. _deck_like_profile), а не
        # прячет поле от самого человека в его же настройках
        tg_channel=profile.tg_channel if profile else "",
        # Только владельцу: по нему клиент предупреждает, что удаление
        # этого фото снимет галочку верификации
        verified_photo=(profile.verified_photo or "") if profile else "",
        # Язык с аккаунта, а не с анкеты: у человека без анкеты он тоже есть,
        # и мини-апп обязан открыться на нём с первого экрана
        locale=user.locale,
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


def _проверить_фото(новые: list[str], прежние: list[str], user_id: str) -> list[str]:
    """Фото в анкете — только свои, уже прошедшие модерацию.

    Модерация и срезание EXIF живут в `POST /upload/photo` и в боте. Но сама
    анкета обновляется через `PATCH /profiles/me`, и `photos` там — обычный
    список строк: без этой проверки можно было один раз честно загрузить
    фото, а потом подсунуть ссылку на любую картинку в интернете. Она попала
    бы в деку, лайки и превью чатов, не увидев ни AI-модерации, ни
    санитайзера, — и вдобавок утекала бы referer'ом на чужой сервер.

    Что принимаем:
    - URL из СВОЕЙ папки нашего R2 (`photos/{user_id}/…`) — их выдаёт только
      собственная успешно отмодерированная загрузка. Просто «наш R2»
      недостаточно: фото чужих анкет публичны, и их URL можно скопировать из
      выдачи — так чужая внешность попадала бы в анкету мимо всех проверок;
    - значения, которые уже стоят в анкете, — иначе клиент не смог бы
      переставить или удалить существующие фото.

    Telegram file_id (не-URL, их кладёт бот без R2) принимаются только среди
    прежних: легального пути ПРИСЛАТЬ НОВЫЙ file_id через PATCH нет — бот
    пишет фото своим слоем, а веб загружает через /upload/photo.
    """
    известные = set(прежние)
    свой_префикс = (settings.R2_PUBLIC_URL or "").rstrip("/") + f"/photos/{user_id}/"

    for фото in новые:
        if фото in известные:
            continue
        if settings.R2_PUBLIC_URL and фото.startswith(свой_префикс):
            continue
        raise HTTPException(
            status_code=400,
            detail="Фото можно добавить только через загрузку: сторонние ссылки не принимаются",
        )

    return новые


def _проверить_видео(новые: list[str], прежние: list[str], user_id: str) -> list[str]:
    """Видео в анкете — те же правила происхождения, что у фото.

    Принимаем только URL из своей видео-папки R2 (`profile-videos/{user_id}/…`,
    их выдаёт единственно `POST /upload/video` после модерации кадров) и
    значения, уже стоящие в анкете (file_id бота — только среди прежних).
    Префикс нарочно свой, не общий с фото: иначе PATCH позволил бы поставить
    видео-URL в `photos` и наоборот — а у фото есть гейт «живой человек» и
    опорный снимок верификации, которые видео не проходит.
    """
    известные = set(прежние)
    свой_префикс = (
        (settings.R2_PUBLIC_URL or "").rstrip("/") + f"/profile-videos/{user_id}/"
    )

    for видео in новые:
        if видео in известные:
            continue
        if settings.R2_PUBLIC_URL and видео.startswith(свой_префикс):
            continue
        raise HTTPException(
            status_code=400,
            detail="Видео можно добавить только через загрузку: сторонние ссылки не принимаются",
        )

    return новые


async def _скачать_фото(url: str) -> bytes:
    """Фото анкеты из R2 — сервер забирает его сам, клиенту не доверяем."""
    async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
        ответ = await client.get(url)
        ответ.raise_for_status()
        return ответ.content


async def _сверить_с_опорным(
    session: AsyncSession, user: User, profile: Profile, новые_фото: list[str]
) -> JSONResponse | None:
    """Держать галочку честной при правке списка фото.

    Галочка «проверенный» привязана к опорному фото (см. Profile.verified_photo
    и routers/verification.py): живая съёмка подтвердила, что владелец — тот,
    кто на нём. Отсюда два правила:

    * опорное фото убрали из анкеты — совпадение больше нечем подтвердить,
      галочка снимается (пройти проверку заново можно всегда);
    * добавленные фото сверяются с опорным: на каждом должен быть человек,
      прошедший живую проверку. Иначе подтверждённая анкета наполнялась бы
      чужими фотографиями — бейдж превращался в инструмент катфишинга.

    Отказ — страйк photo_identity; страйки копятся в бан (см.
    services/enforcement.py). Возвращает готовый 403-ответ, если бан
    применён (вернуть как есть: JSONResponse коммитит сессию, исключение
    откатило бы бан), иначе None. Сверяются публичные фото анкеты между
    собой — биометрии здесь нет, скачанные байты живут только в этом вызове.
    """
    if not user.is_verified:
        return None

    if not (profile.verified_photo or ""):
        # Галочка без опорного фото — аномальное состояние (нормальный путь
        # всегда пишет их парой). Сверять добавленное не с чем, поэтому
        # закрываем по-честному: состав фото растёт — галочка снимается,
        # живая проверка вернёт её вместе с опорным фото.
        прежние = set(as_list(profile.photos))
        if any(ф not in прежние for ф in новые_фото):
            user.is_verified = False
        return None

    if profile.verified_photo not in новые_фото:
        user.is_verified = False
        profile.verified_photo = ""
        return None

    прежние = set(as_list(profile.photos))
    добавленные = [ф for ф in новые_фото if ф not in прежние]
    if not добавленные:
        return None

    try:
        референс = await _скачать_фото(profile.verified_photo)
    except Exception as exc:
        logger.error(f"Сверка с опорным фото: референс не скачался: {exc}")
        raise HTTPException(
            status_code=503,
            detail="Проверка фото сейчас недоступна — попробуйте через пару минут",
        ) from exc

    for фото in добавленные:
        try:
            кандидат = await _скачать_фото(фото)
        except Exception as exc:
            logger.error(f"Сверка с опорным фото: не скачалось новое фото: {exc}")
            raise HTTPException(
                status_code=503,
                detail="Проверка фото сейчас недоступна — попробуйте через пару минут",
            ) from exc
        вердикт = await verify_person_in_photo(референс, кандидат)
        del кандидат
        if вердикт.get("unavailable"):
            # Fail-closed: без вердикта фото в подтверждённую анкету не входит
            raise HTTPException(
                status_code=503,
                detail="Проверка фото сейчас недоступна — попробуйте через пару минут",
            )
        if not вердикт.get("present"):
            бан = await register_identity_strike(
                session, user, "photo_identity", фото, вердикт.get("reason", "")
            )
            if бан is not None:
                return бан
            raise HTTPException(
                status_code=422,
                detail=(
                    "На добавленном фото не найден владелец анкеты — "
                    "в подтверждённую анкету можно добавлять только свои фото"
                ),
            )
    del референс
    return None


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

    # Схему оформления проверяем до записи: платные схемы иначе включались
    # бы правкой запроса, а незнакомый ключ приехал бы в базу и вернулся
    # клиенту, который его не понимает.
    if "app_theme" in update_fields:
        желаемая = нормализовать(update_fields["app_theme"])
        if желаемая != DEFAULT_THEME:
            tier = await current_tier(session, user.id)
            if not доступна(желаемая, tier):
                raise HTTPException(
                    status_code=403,
                    detail="Эта схема оформления доступна с подпиской Plus",
                )
        update_fields["app_theme"] = желаемая

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
            update_fields["photos"], as_list(profile.photos), user.id
        )
        # Подтверждённая анкета: убрали опорное фото — галочка снимается,
        # добавили новые — на каждом должен быть прошедший проверку человек.
        # Готовый ответ означает бан за чужие фото — вернуть немедленно.
        ответ_бана = await _сверить_с_опорным(
            session, user, profile, update_fields["photos"]
        )
        if ответ_бана is not None:
            return ответ_бана

    # Видео — та же проверка происхождения, что у фото; сверка с опорным
    # снимком не нужна: галочка привязана к фото, видео её не трогает.
    if update_fields.get("videos") is not None:
        update_fields["videos"] = _проверить_видео(
            update_fields["videos"], as_list(profile.videos), user.id
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

        # Возрастные границы поля age (pydantic, 18..99) явная дата обходила:
        # прямой PATCH с birth_date мог записать несовершеннолетнего или дату
        # из будущего. Полные годы считаем тем же хелпером, что и витрина.
        полных_лет = возраст_из_даты(update_fields["birth_date"])
        if полных_лет < settings.MIN_AGE or полных_лет > settings.MAX_AGE:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Age must be between {settings.MIN_AGE} and {settings.MAX_AGE}"
                ),
            )

    # Возраст переводим в дату рождения: точный день не спрашиваем,
    # для подбора по возрасту достаточно года. Явный birth_date главнее.
    age_value = update_fields.pop("age", None)
    if age_value and not update_fields.get("birth_date"):
        update_fields["birth_date"] = datetime(
            datetime.now(timezone.utc).year - int(age_value), 1, 1, tzinfo=timezone.utc
        )

    # Язык — колонка аккаунта, а не анкеты, поэтому забираем его из набора
    # ДО общего цикла ниже. Иначе `setattr(profile, "locale", ...)` тихо
    # повесил бы атрибут на объект анкеты: ошибки нет, ответ выглядит
    # успешным, а в базу не уходит ничего.
    язык = update_fields.pop("locale", None)
    if язык:
        user.locale = язык

    # Прежние значения текстовых полей — модерация идёт ПОСЛЕ setattr-цикла,
    # и нарушивший текст надо откатывать руками: ответ с баном или с
    # автоудалением рекламы отдаётся чистым JSONResponse (исключение откатило
    # бы бан), а чистый выход коммитит всё, что осталось в объекте.
    прежние_тексты = {
        поле: getattr(profile, поле)
        for поле in ("bio", "display_name", "tg_channel")
    }

    # Явный null в PATCH — осознанное «стереть значение», но разрешён только
    # там, где колонка nullable и другого способа стереть нет: рост из анкеты
    # («Оставьте пустым» на экране редактирования) и границы фильтра по росту
    # (тумблер «Не важен» в Discover всегда слал null — и до этого списка он
    # молча не долетал до базы). Строковые поля (goal, mbti, bio…) сбрасываются
    # пустой строкой, а null для остальных по-прежнему пропускается: Optional
    # в схеме значит «поле можно не присылать», и явный null не должен ронять
    # 500 на NOT NULL-колонке.
    СБРАСЫВАЕМЫЕ = {"height_cm", "filter_height_min", "filter_height_max"}
    for key, value in update_fields.items():
        if value is None and key not in СБРАСЫВАЕМЫЕ:
            continue
        setattr(profile, key, value)

    if len(as_list(profile.photos)) > settings.MAX_PHOTOS:
        raise HTTPException(status_code=400, detail=f"Max {settings.MAX_PHOTOS} photos allowed")
    if len(as_list(profile.videos)) > settings.MAX_PROFILE_VIDEOS:
        raise HTTPException(
            status_code=400,
            detail=f"Максимум {settings.MAX_PROFILE_VIDEOS} видео в анкете",
        )
    if len(profile.bio) > settings.MAX_BIO_LENGTH:
        raise HTTPException(status_code=400, detail=f"Bio must be under {settings.MAX_BIO_LENGTH} chars")

    # Текстовые поля анкеты. Имя и канал проверяются наравне с био: имя видно
    # чаще анкеты (дека, чаты, комнаты, уведомления), канал ведёт вовне —
    # через них уходили реклама, контакты и брань, пока модерация стояла
    # только на био. Каждое нарушение — страйк (register_text_strike):
    # предупреждение со счётом, рекламный текст автоудаляется из анкеты,
    # с порога — блокировка аккаунта.
    нарушения: list[tuple[str, object]] = []
    бан = None
    for поле, отказ, проверять in (
        ("bio", "Описание нарушает правила", bool(data.bio)),
        ("display_name", "Имя нарушает правила", bool(data.display_name)),
        (
            "tg_channel",
            "Канал нарушает правила",
            "tg_channel" in update_fields and bool(profile.tg_channel),
        ),
    ):
        if not проверять:
            continue
        значение = getattr(profile, поле)
        mod_result = await moderate_text(значение)
        await log_moderation(user.id, поле, значение, mod_result)
        if not mod_result["blocked"]:
            continue
        исход = None
        if бан is None:
            исход = await register_text_strike(session, user, mod_result)
            if исход is not None and исход.banned:
                бан = исход
        # Нарушивший текст в анкете не остаётся: поле возвращается к прежнему
        # чистому значению (пустым display_name оставлять нельзя). Ответы ниже
        # без исключения коммитят сессию, поэтому откат — руками и для КАЖДОГО
        # нарушившего поля, не только первого.
        setattr(profile, поле, прежние_тексты[поле])
        нарушения.append((отказ, исход))

    if бан is not None:
        return banned_response(
            user, f"Аккаунт заблокирован. {TEXT_BAN_REASONS[бан.category]}"
        )
    if нарушения:
        ad_исход = next(
            (и for _, и in нарушения if и is not None and и.category == "ad"), None
        )
        if ad_исход is not None:
            # Реклама: поле очищено, остальные правки сохраняются — это и есть
            # «автоудаление рекламы с изменением анкеты». Чистый JSONResponse,
            # чтобы очистка закоммитилась.
            return JSONResponse(
                status_code=422,
                content={
                    "detail": (
                        "Реклама запрещена — текст удалён из анкеты. "
                        + ad_исход.warning_text()
                    ),
                    "code": "ad_removed",
                },
            )
        отказ, исход = нарушения[0]
        счёт = f" {исход.warning_text()}" if исход is not None else ""
        # Не-рекламные нарушения отклоняют PATCH целиком, как раньше:
        # исключение откатит и правки, страйк в журнале живёт своей сессией
        raise HTTPException(status_code=422, detail=f"{отказ}.{счёт}")

    await session.flush()

    # Анкета впервые стала полной (имя и фото — минимум, с которым её видно
    # в деке) — веха воронки. Порог, а не факт INSERT: анкету заполняют за
    # несколько PATCH, и строка Profile появляется раньше готовности.
    # Повторные сохранения гасит dedup_key
    if profile.display_name and as_list(profile.photos):
        await track(session, user.id, EVENT_PROFILE_CREATED, once=True)

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
        videos=as_list(profile.videos),
        interests=as_list(profile.interests),
        ai_bio=profile.ai_bio,
        looking_for=profile.looking_for,
        is_incognito=profile.is_incognito,
        is_paused=profile.is_paused,
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
        filter_verified=profile.filter_verified,
        has_location=profile.latitude is not None,
        tg_channel=profile.tg_channel,
        verified_photo=profile.verified_photo or "",
        # Отдаём сохранённый язык обратно: без этого поля ответ на смену языка
        # приезжал бы со значением по умолчанию, и клиент, доверяющий ответу,
        # тут же откатил бы выбор на русский
        locale=user.locale,
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
            "videos": as_list(profile.videos) if profile else [],
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

    filename = f"simp-data-{user.id[:8]}.json"
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
        # Видео анкеты чистятся тем же списком: ниже из URL вырезается ключ
        # объекта, а каким префиксом он начинается — photos/ или
        # profile-videos/ — удалению без разницы.
        photo_urls = [
            p
            for p in as_list(profile.photos) + as_list(profile.videos)
            if isinstance(p, str)
        ]

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
