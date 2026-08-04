from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


# ════════════════════════════════════════════════════════════════
#  AUTH
# ════════════════════════════════════════════════════════════════

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
    hide_age: bool = False
    hide_distance: bool = False
    hide_from_visitors: bool = False
    is_premium: bool = False
    age_min: int = 18
    age_max: int = 99
    distance_max: int = 100
    # Нишевые поля анкеты и фильтры по ним. Пусто — не указано / не фильтруем.
    goal: str = ""
    subculture: str = ""
    mbti: str = ""
    height_cm: Optional[int] = None
    filter_goal: str = ""
    filter_subculture: str = ""
    filter_city: str = ""
    filter_height_min: Optional[int] = None
    filter_height_max: Optional[int] = None
    # Заполняется только в списке «кто меня лайкнул»: текст, приложенный
    # к входящему лайку.
    like_message: str = ""
    #: Карточка скрыта до подписки: имя, фото и текст лайка не отданы.
    is_locked: bool = False
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
    hide_age: Optional[bool] = None
    hide_distance: Optional[bool] = None
    hide_from_visitors: Optional[bool] = None
    looking_for: Optional[str] = Field(None, pattern="^(male|female|other|any)$")
    age_min: Optional[int] = Field(None, ge=18, le=99)
    age_max: Optional[int] = Field(None, ge=18, le=99)
    distance_max: Optional[int] = Field(None, ge=1, le=500)
    # Пустая строка — осознанное «сбросить», поэтому min_length не ставим.
    goal: Optional[str] = Field(None, max_length=32)
    subculture: Optional[str] = Field(None, max_length=32)
    # Пустая строка — «не указан»; иначе строго один из шестнадцати типов
    mbti: Optional[str] = Field(
        None, pattern=r"^$|^[EI][NS][FT][JP]$"
    )
    height_cm: Optional[int] = Field(None, ge=120, le=230)
    filter_goal: Optional[str] = Field(None, max_length=32)
    filter_subculture: Optional[str] = Field(None, max_length=32)
    filter_city: Optional[str] = Field(None, max_length=100)
    filter_height_min: Optional[int] = Field(None, ge=120, le=230)
    filter_height_max: Optional[int] = Field(None, ge=120, le=230)


# ════════════════════════════════════════════════════════════════
#  LIKES / MATCHES
# ════════════════════════════════════════════════════════════════

class LikeRequest(BaseModel):
    target_id: str
    type: str = Field(default="like", pattern="^(like|superlike|pass)$")
    # Пара слов вместе с лайком — их увидят до мэтча. Лимит короткий
    # намеренно: это повод для разговора, а не первое сообщение.
    message: str = Field(default="", max_length=200)


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
    goal: str = ""
    subculture: str = ""
    mbti: str = ""
    height_cm: Optional[int] = None


# ════════════════════════════════════════════════════════════════
#  MESSAGES / CHAT
# ════════════════════════════════════════════════════════════════

# ════════════════════════════════════════════════════════════════
#  REPORTS
# ════════════════════════════════════════════════════════════════

#: Причины жалобы. Набор общий для бота, мини-аппа и админки: жалоба с
#: причиной, которой нет в этом списке, не будет ни принята API, ни подписана
#: в админке — так и случилось с «fake», которую слал только бот.
REPORT_REASONS = (
    "spam",
    "harassment",
    "nudity",
    "scam",
    "fake",
    "underage",
    "drugs",
    "other",
)


class ReportRequest(BaseModel):
    reported_id: str
    reason: str = Field(pattern="^(" + "|".join(REPORT_REASONS) + ")$")
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


# ════════════════════════════════════════════════════════════════
#  IN-APP PURCHASES
# ════════════════════════════════════════════════════════════════

class ReelOut(BaseModel):
    """Ролик в ленте вместе с автором: отдельный запрос за анкетой на каждый
    ролик означал бы десяток запросов на один экран."""

    id: str
    author_id: str
    author_name: str = ""
    author_age: Optional[int] = None
    author_photo: str = ""
    video_url: str
    cover_url: str = ""
    caption: str = ""
    likes_count: int = 0
    liked_by_me: bool = False
    is_mine: bool = False
    #: Снят с показа. Приходит только автору — в общей ленте таких нет.
    is_hidden: bool = False
    created_at: Optional[datetime] = None


class ReelsOut(BaseModel):
    """Страница ленты. `next_before` передаётся в следующий запрос."""

    reels: list[ReelOut] = Field(default_factory=list)
    next_before: Optional[str] = None


class VisitorOut(BaseModel):
    """Один гость: анкета плюс когда и сколько раз заходил."""

    profile: UserProfile
    visits: int = 1
    last_seen_at: Optional[datetime] = None


class VisitorsOut(BaseModel):
    """Раздел «Гости». `revealed=false` — число видно, а кто именно нет."""

    total: int = 0
    revealed: bool = False
    visitors: list[VisitorOut] = Field(default_factory=list)


class PlanOut(BaseModel):
    """Один покупаемый вариант для витрины."""

    code: str
    tier: str
    title: str
    months: int
    price_rub: int
    price_per_month: int
    appstore_id: str = ""


class TierOut(BaseModel):
    """Уровень и что он даёт."""

    tier: str
    name: str
    superlikes: int
    perks: list[str] = Field(default_factory=list)
    plans: list[PlanOut] = Field(default_factory=list)


class PlansOut(BaseModel):
    """Витрина тарифов. `current_tier` — что действует у спросившего."""

    current_tier: str
    tiers: list[TierOut] = Field(default_factory=list)


class IAPProducts(BaseModel):
    """Что доступно к покупке. `available=false` — кнопку покупки не показываем."""

    available: bool
    product_ids: list[str] = Field(default_factory=list)


class IAPVerifyRequest(BaseModel):
    """Подписанная транзакция StoreKit 2 в формате JWS Compact.

    Длина не фиксирована: внутри лежит цепочка сертификатов Apple, поэтому
    строка занимает килобайты.
    """

    jws: str = Field(min_length=100, max_length=20000)


class IAPVerifyResponse(BaseModel):
    success: bool
    plan: str = "free"
    expires_at: str = ""
    # Транзакция уже была зачтена ранее — повторное начисление не произошло
    already_processed: bool = False
