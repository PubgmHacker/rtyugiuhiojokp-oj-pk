from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import get_settings
from database.connection import get_session
from middleware.auth import (
    create_access_token,
    get_current_token_payload,
    get_current_user,
    verify_telegram_init_data,
)
from models.models import User, Profile
from models.schemas import AuthResponse, UserProfile
from services.ban_memory import is_banned_identity
from services.apple_auth import AppleAuthError, verify_identity_token
from services.email_recovery import (
    можно_отправлять,
    нормализовать,
    почта_похожа_на_настоящую,
    проверить_код,
    сгенерировать_код,
    запомнить_код,
)
from services.mailer import отправить_код
from services.link_codes import redeem_code
from services.token_revocation import revoke_all_for_user, revoke_token
from utils import as_list

router = APIRouter(prefix="/auth", tags=["auth"])
settings = get_settings()
logger = logging.getLogger(__name__)


def _user_to_profile(user: User, profile: Profile | None) -> UserProfile:
    age = None
    if profile and profile.birth_date:
        now = datetime.now(timezone.utc)
        age = now.year - profile.birth_date.year
        if (now.month, now.day) < (profile.birth_date.month, profile.birth_date.day):
            age -= 1

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
    )


@router.post("/telegram", response_model=AuthResponse)
async def auth_telegram(
    data: dict,
    session: AsyncSession = Depends(get_session),
):
    """Авторизация через Telegram initData."""
    init_data = data.get("initData", "")
    if not init_data:
        return AuthResponse(success=False, token="", user=UserProfile())

    tg_data = verify_telegram_init_data(init_data)

    user_str = tg_data.get("user", "{}")
    if isinstance(user_str, str):
        tg_user = json.loads(user_str)
    else:
        tg_user = user_str

    tg_id = int(tg_user.get("id", 0))
    # username из Telegram не храним: он меняется владельцем в любой момент,
    # а имя в анкете человек задаёт сам
    first_name = tg_user.get("first_name", "")
    last_name = tg_user.get("last_name", "")

    # Upsert user
    result = await session.execute(select(User).where(User.telegram_id == tg_id))
    user = result.scalar_one_or_none()

    if not user:
        # Забаненный мог удалить аккаунт и прийти заново тем же Telegram:
        # удаление каскадом стирает бан, поэтому проверяем отдельный список.
        # Создаём его сразу забаненным, а не отказываем — иначе он поймёт, что
        # обход не сработал, и начнёт искать другой способ
        previously_banned = await is_banned_identity(session, telegram_id=tg_id)

        user = User(
            telegram_id=tg_id,
            role="user",
            is_banned=previously_banned,
        )
        session.add(user)
        await session.flush()
        if previously_banned:
            logger.warning(f"Повторная регистрация забаненного telegram_id={tg_id}")
        # Create empty profile
        profile = Profile(
            user_id=user.id,
            display_name=f"{first_name} {last_name}".strip(),
        )
        session.add(profile)
    else:
        user.last_seen_at = datetime.now(timezone.utc)

    await session.flush()

    # Check ADMIN_IDS -> promote
    if tg_id in settings.admin_id_list and user.role not in ("admin", "owner"):
        user.role = "owner"

    await session.flush()

    # Get profile
    result = await session.execute(select(Profile).where(Profile.user_id == user.id))
    profile = result.scalar_one_or_none()

    token = create_access_token(user.id, user.telegram_id)

    return AuthResponse(
        success=True,
        token=token,
        user=_user_to_profile(user, profile),
    )


@router.post("/dev", response_model=AuthResponse)
async def auth_dev(
    data: dict,
    session: AsyncSession = Depends(get_session),
):
    """Dev/гостевой вход без Telegram (только при DEBUG=true).

    Принимает {"device_id": "...", "name": "..."} — device_id хранится в phone,
    чтобы гость возвращался в свой же аккаунт.
    """
    if not settings.DEBUG:
        return AuthResponse(success=False, token="", user=UserProfile(id=""))

    device_id = str(data.get("device_id", "")).strip()[:64]
    name = str(data.get("name", "")).strip()[:50]
    if not device_id:
        return AuthResponse(success=False, token="", user=UserProfile(id=""))

    result = await session.execute(select(User).where(User.phone == f"dev:{device_id}"))
    user = result.scalar_one_or_none()

    if not user:
        user = User(phone=f"dev:{device_id}", role="user")
        session.add(user)
        await session.flush()
        session.add(Profile(user_id=user.id, display_name=name))
    else:
        user.last_seen_at = datetime.now(timezone.utc)

    await session.flush()

    result = await session.execute(select(Profile).where(Profile.user_id == user.id))
    profile = result.scalar_one_or_none()

    token = create_access_token(user.id, user.telegram_id)
    return AuthResponse(success=True, token=token, user=_user_to_profile(user, profile))


@router.post("/link", response_model=AuthResponse)
async def auth_link_code(
    data: dict,
    session: AsyncSession = Depends(get_session),
):
    """Вход по одноразовому коду из бота — для нативного iOS-приложения.

    В Mini App личность даёт initData, но в нативной сборке его нет, и это
    единственный рабочий способ войти: пользователь берёт код командой
    `/link` у бота и вводит здесь. Код одноразовый и живёт минуты.
    """
    code = str(data.get("code", ""))
    user_id = await redeem_code(code)
    if not user_id:
        return AuthResponse(success=False, token="", user=UserProfile(id=""))

    result = await session.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user or user.is_banned:
        return AuthResponse(success=False, token="", user=UserProfile(id=""))

    user.last_seen_at = datetime.now(timezone.utc)
    await session.flush()

    result = await session.execute(select(Profile).where(Profile.user_id == user.id))
    profile = result.scalar_one_or_none()

    token = create_access_token(user.id, user.telegram_id)
    return AuthResponse(success=True, token=token, user=_user_to_profile(user, profile))


@router.post("/apple", response_model=AuthResponse)
async def auth_apple(
    data: dict,
    session: AsyncSession = Depends(get_session),
):
    """Вход через Sign in with Apple — второй способ входа для iOS.

    App Store требует его там, где вход идёт через сторонний сервис
    (Guideline 4.8): для дейтинга это частая причина отклонения. У пришедшего
    из App Store человека Telegram может не быть вовсе, поэтому аккаунт
    создаётся с одним `apple_id`, без `telegram_id`.

    Имя Apple присылает только при ПЕРВОМ входе и только если человек его
    разрешил, поэтому анкету заполняем тем, что дали, а дальше он правит её сам.
    """
    try:
        payload = await verify_identity_token(str(data.get("identity_token", "")))
    except AppleAuthError as exc:
        # Наружу не рассказываем, что именно не сошлось: подсказка помогает
        # подбирать токен, а человеку она всё равно ничего не даёт
        logger.warning(f"Вход через Apple отклонён: {exc}")
        return AuthResponse(success=False, token="", user=UserProfile(id=""))

    apple_id = str(payload["sub"])

    result = await session.execute(select(User).where(User.apple_id == apple_id))
    user = result.scalar_one_or_none()

    if not user:
        # Забаненный не должен получать чистую историю, зайдя через Apple:
        # список банов живёт отдельно от аккаунта (см. auth_telegram). Ключ —
        # именованный: apple_id строковый, и по колонке telegram_id он не искал
        previously_banned = await is_banned_identity(session, apple_id=apple_id)

        user = User(apple_id=apple_id, role="user", is_banned=previously_banned)
        session.add(user)
        await session.flush()
        if previously_banned:
            logger.warning(f"Повторная регистрация забаненного apple_id={apple_id}")

        имя = str(data.get("full_name") or "").strip()
        session.add(Profile(user_id=user.id, display_name=имя))
    else:
        user.last_seen_at = datetime.now(timezone.utc)

    await session.flush()

    result = await session.execute(select(Profile).where(Profile.user_id == user.id))
    profile = result.scalar_one_or_none()

    token = create_access_token(user.id, user.telegram_id)
    return AuthResponse(success=True, token=token, user=_user_to_profile(user, profile))


@router.get("/me", response_model=UserProfile)
async def get_me(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Получить текущего пользователя."""
    result = await session.execute(select(Profile).where(Profile.user_id == user.id))
    profile = result.scalar_one_or_none()
    return _user_to_profile(user, profile)


@router.post("/logout")
async def logout(
    payload: dict = Depends(get_current_token_payload),
    user: User = Depends(get_current_user),
):
    """Выход: гасит текущий токен, остальные устройства продолжают работать."""
    revoked = await revoke_token(payload)
    return {"success": revoked}


@router.post("/logout-all")
async def logout_all(
    user: User = Depends(get_current_user),
):
    """Выход со всех устройств — для угнанного аккаунта.

    Гасит все токены, выданные до этого момента, включая текущий: продолжить
    работу с украденным токеном нельзя, нужен повторный вход.
    """
    revoked = await revoke_all_for_user(user.id)
    return {"success": revoked}


# ── Почта: восстановление доступа ───────────────────────────────
#
# Аккаунт держался на одном Telegram: потерял его — потерял анкету и
# оплаченную подписку, и вернуть их было нечем. Почта — единственный способ
# доказать, что аккаунт твой. Хранится только подтверждённой: непроверенная
# хуже, чем никакой, потому что ошибка в букве отдаёт доступ постороннему.


@router.post("/email/attach")
async def attach_email(
    data: dict,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Шаг 1: запросить код на почту.

    Сама почта в аккаунт пока не пишется — только после подтверждения кодом.
    """
    адрес = нормализовать(str(data.get("email", "")))
    if not почта_похожа_на_настоящую(адрес):
        raise HTTPException(status_code=400, detail="Проверьте адрес почты")

    # Занятая почта не должна подсказывать, что аккаунт существует: иначе
    # эндпоинт превращается в проверку «есть ли тут такой человек»
    result = await session.execute(select(User).where(User.email == адрес))
    чужой = result.scalar_one_or_none()
    if чужой and чужой.id != user.id:
        logger.warning(f"Попытка привязать занятую почту (user={user.id})")
        return {"sent": True}

    if not await можно_отправлять(user.id):
        raise HTTPException(
            status_code=429, detail="Слишком много писем. Попробуйте через час"
        )

    код = сгенерировать_код()
    await запомнить_код(адрес, код, user.id)

    if not await отправить_код(адрес, код):
        raise HTTPException(status_code=503, detail="Не удалось отправить письмо")

    return {"sent": True}


@router.post("/email/confirm")
async def confirm_email(
    data: dict,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Шаг 2: подтвердить код и привязать почту к аккаунту."""
    адрес = нормализовать(str(data.get("email", "")))
    владелец = await проверить_код(адрес, str(data.get("code", "")))

    if not владелец or владелец != user.id:
        raise HTTPException(status_code=400, detail="Код неверный или устарел")

    result = await session.execute(select(User).where(User.email == адрес))
    чужой = result.scalar_one_or_none()
    if чужой and чужой.id != user.id:
        raise HTTPException(status_code=409, detail="Эта почта уже занята")

    user.email = адрес
    await session.commit()
    logger.info(f"Почта привязана: user={user.id}")
    return {"email": адрес}


@router.post("/email/request")
async def request_recovery(
    data: dict,
    session: AsyncSession = Depends(get_session),
):
    """Потерян Telegram: запросить код входа на привязанную почту.

    Отвечаем одинаково независимо от того, есть такая почта или нет: иначе по
    ответу можно узнать, зарегистрирован ли человек в дейтинг-сервисе, — а это
    само по себе чувствительный факт.
    """
    адрес = нормализовать(str(data.get("email", "")))
    if not почта_похожа_на_настоящую(адрес):
        return {"sent": True}

    result = await session.execute(select(User).where(User.email == адрес))
    владелец = result.scalar_one_or_none()
    if not владелец:
        return {"sent": True}

    if not await можно_отправлять(владелец.id):
        return {"sent": True}

    код = сгенерировать_код()
    await запомнить_код(адрес, код, владелец.id)
    await отправить_код(адрес, код)
    return {"sent": True}


@router.post("/email/login", response_model=AuthResponse)
async def login_by_email(
    data: dict,
    session: AsyncSession = Depends(get_session),
):
    """Вход по коду с почты — когда Telegram недоступен."""
    адрес = нормализовать(str(data.get("email", "")))
    владелец = await проверить_код(адрес, str(data.get("code", "")))
    if not владелец:
        return AuthResponse(success=False, token="", user=UserProfile(id=""))

    result = await session.execute(select(User).where(User.id == владелец))
    user = result.scalar_one_or_none()
    # Забаненному вход по почте не даёт обхода: проверка та же, что везде
    if not user or user.is_banned or user.email != адрес:
        return AuthResponse(success=False, token="", user=UserProfile(id=""))

    user.last_seen_at = datetime.now(timezone.utc)
    await session.flush()

    result = await session.execute(select(Profile).where(Profile.user_id == user.id))
    profile = result.scalar_one_or_none()

    token = create_access_token(user.id, user.telegram_id)
    await session.commit()
    return AuthResponse(success=True, token=token, user=_user_to_profile(user, profile))
