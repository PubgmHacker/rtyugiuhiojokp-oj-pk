from __future__ import annotations

from fastapi import Depends, HTTPException, status

from middleware.auth import get_current_user
from models.models import User


async def require_admin(user: User = Depends(get_current_user)) -> User:
    """FastAPI dependency: проверяет что пользователь — admin или owner."""
    if user.role not in ("admin", "owner"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    return user


async def require_owner(user: User = Depends(get_current_user)) -> User:
    """FastAPI dependency: проверяет что пользователь — owner."""
    if user.role != "owner":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Owner access required",
        )
    return user
