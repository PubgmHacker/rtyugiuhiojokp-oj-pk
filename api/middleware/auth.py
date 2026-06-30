from __future__ import annotations

import hashlib
import hmac
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from config import get_settings
from database.connection import get_session
from models.models import User

settings = get_settings()
security = HTTPBearer()


def create_access_token(user_id: str, telegram_id: Optional[int] = None) -> str:
    expire = datetime.now(timezone.utc) + timedelta(hours=settings.JWT_ACCESS_EXPIRE_HOURS)
    payload = {
        "sub": user_id,
        "telegram_id": telegram_id,
        "exp": expire,
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def verify_access_token(token: str) -> dict:
    """Декодирует JWT, возвращает payload. Raises на невалидный токен."""
    try:
        return jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")


def verify_telegram_init_data(init_data: str) -> dict:
    """Верифицирует initData от Telegram WebApp."""
    from urllib.parse import parse_qs

    if not settings.BOT_TOKEN:
        # В dev-режиме без токена — пропускаем верификацию
        return parse_qs(init_data)

    params = parse_qs(init_data)
    hash_val = params.pop("hash", [""])[0]

    data_check_string = "\n".join(
        f"{k}={v[0]}" for k, v in sorted(params.items())
    )
    secret_key = hashlib.sha256(settings.BOT_TOKEN.encode()).digest()
    computed_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()

    if computed_hash != hash_val:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid Telegram hash")

    # Flattening parse_qs (lists → single values)
    result = {k: v[0] for k, v in params.items()}
    return result


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    session: AsyncSession = Depends(get_session),
) -> User:
    """FastAPI dependency: возвращает текущего пользователя по JWT."""
    payload = verify_access_token(credentials.credentials)
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="No user in token")

    result = await session.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    if user.is_banned:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User is banned")

    return user


async def get_current_user_id(
    user: User = Depends(get_current_user),
) -> str:
    return user.id
