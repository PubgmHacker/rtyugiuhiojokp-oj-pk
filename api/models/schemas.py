from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


# ════════════════════════════════════════════════════════════════
#  AUTH
# ════════════════════════════════════════════════════════════════

class TelegramAuthRequest(BaseModel):
    initData: str


class AuthResponse(BaseModel):
    success: bool
    token: str
    user: UserProfile


# ════════════════════════════════════════════════════════════════
#  USER / PROFILE
# ════════════════════════════════════════════════════════════════

class UserProfile(BaseModel):
    id: str
    telegram_id: Optional[int] = None
    role: str = "user"
    is_banned: bool = False
    is_verified: bool = False
    created_at: Optional[datetime] = None

    # Profile fields (can be null if profile not created yet)
    display_name: str = ""
    bio: str = ""
    gender: str = "other"
    age: Optional[int] = None
    city: str = ""
    photos: list[str] = Field(default_factory=list)
    interests: list[str] = Field(default_factory=list)
    ai_bio: Optional[str] = None
    looking_for: str = "any"
    is_incognito: bool = False
    is_premium: bool = False
    age_min: int = 18
    age_max: int = 99
    distance_max: int = 100
    has_location: bool = False
    invited_count: int = 0
    referral_boost: bool = False
    referral_target: int = 3
    referral_boost_percent: int = 12


class ProfileUpdate(BaseModel):
    display_name: Optional[str] = Field(None, max_length=50)
    bio: Optional[str] = Field(None, max_length=500)
    gender: Optional[str] = Field(None, pattern="^(male|female|other)$")
    birth_date: Optional[str] = None  # ISO format "YYYY-MM-DD"
    # Клиенту удобнее прислать возраст, чем дату рождения: точный день
    # мы всё равно не спрашиваем. Пересчитывается в birth_date на сервере.
    age: Optional[int] = Field(None, ge=18, le=99)
    city: Optional[str] = Field(None, max_length=100)
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    interests: Optional[list[str]] = None
    photos: Optional[list[str]] = None
    is_incognito: Optional[bool] = None
    looking_for: Optional[str] = Field(None, pattern="^(male|female|other|any)$")
    age_min: Optional[int] = Field(None, ge=18, le=99)
    age_max: Optional[int] = Field(None, ge=18, le=99)
    distance_max: Optional[int] = Field(None, ge=1, le=500)


# ════════════════════════════════════════════════════════════════
#  LIKES / MATCHES
# ════════════════════════════════════════════════════════════════

class LikeRequest(BaseModel):
    target_id: str
    type: str = Field(default="like", pattern="^(like|superlike|pass)$")


class LikeResponse(BaseModel):
    liked: bool = False
    matched: bool = False
    match: Optional[MatchResponse] = None


class SuperlikeQuota(BaseModel):
    """Остаток суперлайков на сутки — счётчик на кнопке в деке."""

    left: int = 0
    total: int = 0
    is_premium: bool = False


class MatchResponse(BaseModel):
    id: str
    match_score: Optional[int] = None
    ai_reason: Optional[str] = None
    created_at: Optional[datetime] = None
    partner: UserProfile
    # Превью для списка чатов: иначе клиенту пришлось бы запрашивать
    # переписку отдельно по каждому мэтчу
    last_message: Optional[str] = None
    last_message_at: Optional[datetime] = None
    unread_count: int = 0


class DeckProfile(BaseModel):
    """Анкета для показа в свайп-деке."""
    id: str
    display_name: str
    age: Optional[int] = None
    city: str = ""
    bio: str = ""
    photos: list[str] = Field(default_factory=list)
    interests: list[str] = Field(default_factory=list)
    ai_bio: Optional[str] = None
    distance: Optional[int] = None  # км от текущего пользователя
    match_score: Optional[int] = None
    match_reason: Optional[str] = None


# ════════════════════════════════════════════════════════════════
#  MESSAGES / CHAT
# ════════════════════════════════════════════════════════════════

class MessageOut(BaseModel):
    id: str
    match_id: str
    sender_id: str
    text: str = ""
    image_url: Optional[str] = None
    read_at: Optional[datetime] = None
    created_at: Optional[datetime] = None


class SendMessage(BaseModel):
    text: str = Field(default="", max_length=2000)
    image_url: Optional[str] = None


# ════════════════════════════════════════════════════════════════
#  REPORTS
# ════════════════════════════════════════════════════════════════

class ReportRequest(BaseModel):
    reported_id: str
    reason: str = Field(pattern="^(spam|harassment|nudity|scam|other)$")
    description: str = Field(default="", max_length=1000)


class ReportResponse(BaseModel):
    success: bool
    message: str = ""


# ════════════════════════════════════════════════════════════════
#  PUSH NOTIFICATIONS
# ════════════════════════════════════════════════════════════════

class DeviceRegistration(BaseModel):
    """Токен устройства из нативной обёртки. APNs-токен — 64 hex-символа,
    но лимит взят с запасом: формат задаёт Apple, и он менялся."""

    token: str = Field(min_length=32, max_length=200)
    platform: str = Field(default="ios", pattern="^(ios|android)$")
