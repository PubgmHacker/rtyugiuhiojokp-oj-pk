from __future__ import annotations

import hashlib
import hmac
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import get_settings
from database.connection import get_session
from models.models import User

settings = get_settings()
# При отсутствии заголовка HTTPBearer по умолчанию отдаёт 403. Клиент Mini
# App трактует 401 как протухшую сессию и возвращает на экран входа, поэтому
# отсутствие/неверный Bearer должны иметь единый auth-ответ 401.
security = HTTPBearer(auto_error=False)

MAX_TELEGRAM_INIT_DATA_LENGTH = 8192

#: Машинный код бана в теле ответа. Тот же литерал ждёт перехватчик в
#: `web/src/lib/api.ts` — при правке менять оба места.
BANNED_CODE = "account_banned"


class AccountBannedError(HTTPException):
    """403 для заблокированного аккаунта — с машинным кодом в теле ответа.

    Отдельный класс, а не голый ``HTTPException``: в API десятки других 403
    («доступно на Plus», «это не ваш ролик», «расклады доступны на Ultra»), и
    клиент не должен отличать бан от гейта тарифа по тексту сообщения — иначе
    любая правка формулировки уводит человека с апсейла на экран блокировки.

    ``detail`` остаётся человеческой строкой: код добавляет обработчик в
    ``main.py`` отдельным полем, поэтому форма ответа для тех, кто читает
    только ``detail``, не меняется.

    ``banned_until`` — срок бана (None — вечный): обработчик кладёт его в тело
    ответа, клиент показывает таймер и «снять сейчас за 349 ₽» вместо глухого
    «доступ закрыт».
    """

    def __init__(
        self,
        detail: str = "User is banned",
        banned_until: Optional[datetime] = None,
    ) -> None:
        super().__init__(status_code=status.HTTP_403_FORBIDDEN, detail=detail)
        self.banned_until = banned_until


def create_access_token(user_id: str, telegram_id: Optional[int] = None) -> str:
    """Выпустить access-токен.

    `jti` и `iat` обязательны: по ним работает отзыв сессий
    (services/token_revocation.py) — без них конкретный токен погасить нельзя.
    """
    now = datetime.now(timezone.utc)
    expire = now + timedelta(hours=settings.JWT_ACCESS_EXPIRE_HOURS)
    payload = {
        "sub": user_id,
        "telegram_id": telegram_id,
        "iat": now,
        "jti": uuid.uuid4().hex,
        "exp": expire,
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def verify_access_token(token: str) -> dict:
    """Декодирует JWT, возвращает payload. Raises на невалидный токен."""
    try:
        return jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")


def verify_telegram_init_data(init_data: str, max_age_seconds: int = 86400) -> dict:
    """Верифицирует initData от Telegram WebApp (Mini App).

    Схема Mini Apps: secret_key = HMAC_SHA256(key="WebAppData", msg=BOT_TOKEN),
    hash = HMAC_SHA256(key=secret_key, msg=data_check_string).
    """
    from urllib.parse import parse_qsl

    if not isinstance(init_data, str) or not init_data:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid initData")
    if len(init_data) > MAX_TELEGRAM_INIT_DATA_LENGTH:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="initData too long")
    try:
        pairs = parse_qsl(
            init_data,
            keep_blank_values=True,
            strict_parsing=True,
        )
    except ValueError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid initData")
    if not pairs or len({key for key, _ in pairs}) != len(pairs):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid initData")
    params = dict(pairs)

    if not settings.BOT_TOKEN:
        if settings.DEBUG:
            # Только в dev-режиме без токена — пропускаем верификацию
            return params
        # В проде без BOT_TOKEN нельзя «доверять на слово» — иначе любой
        # может подделать initData (в т.ч. с admin telegram_id)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Telegram auth is not configured",
        )

    hash_val = params.pop("hash", "")
    if not hash_val:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="No hash in initData")

    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(params.items()))
    secret_key = hmac.new(b"WebAppData", settings.BOT_TOKEN.encode(), hashlib.sha256).digest()
    computed_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()

    if not hmac.compare_digest(computed_hash, hash_val):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid Telegram hash")

    # Защита от replay: initData не старше суток
    try:
        auth_date = int(params.get("auth_date", "0"))
    except (TypeError, ValueError):
        auth_date = 0
    now_ts = int(datetime.now(timezone.utc).timestamp())
    if auth_date <= 0:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid auth_date")
    if now_ts - auth_date > max_age_seconds or auth_date - now_ts > 300:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="initData expired")

    return params


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    session: AsyncSession = Depends(get_session),
) -> User:
    """FastAPI dependency: возвращает текущего пользователя по JWT."""
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authorization",
            headers={"WWW-Authenticate": "Bearer"},
        )
    payload = verify_access_token(credentials.credentials)
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="No user in token")

    # Сессия могла быть отозвана — выходом, баном или «выйти везде»
    from services.token_revocation import is_revoked

    if await is_revoked(payload):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token revoked")

    result = await session.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    if user.is_banned:
        # Временный бан истёк — снимаем прямо здесь, фонового джоба нет.
        # Первый же запрос после срока возвращает доступ без действий человека
        from services.enforcement import lift_ban_if_expired

        if not await lift_ban_if_expired(session, user):
            raise AccountBannedError(banned_until=user.banned_until)

    return user


async def get_current_token_payload(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
) -> dict:
    """Payload текущего токена — нужен, чтобы отозвать именно его при выходе."""
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authorization",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return verify_access_token(credentials.credentials)


async def get_current_user_id(
    user: User = Depends(get_current_user),
) -> str:
    return user.id
