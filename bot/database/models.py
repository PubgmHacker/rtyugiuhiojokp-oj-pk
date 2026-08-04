from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    mapped_column,
)
from sqlalchemy.dialects.postgresql import JSON


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "dating_users"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    telegram_id: Mapped[int | None] = mapped_column(BigInteger, unique=True, nullable=True)
    phone: Mapped[str | None] = mapped_column(String, nullable=True)
    role: Mapped[str] = mapped_column(String, default="user")
    is_banned: Mapped[bool] = mapped_column(Boolean, default=False)
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class Profile(Base):
    __tablename__ = "dating_profiles"

    user_id: Mapped[str] = mapped_column(String, ForeignKey("dating_users.id", ondelete="CASCADE"), primary_key=True)
    display_name: Mapped[str] = mapped_column(String, default="")
    bio: Mapped[str] = mapped_column(String, default="")
    gender: Mapped[str] = mapped_column(String, default="other")
    birth_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    city: Mapped[str] = mapped_column(String, default="")
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    photos: Mapped[dict | list] = mapped_column(JSON, default=list)
    interests: Mapped[dict | list] = mapped_column(JSON, default=list)
    ai_bio: Mapped[str | None] = mapped_column(String, nullable=True)
    verification_status: Mapped[str] = mapped_column(String, default="none")
    is_incognito: Mapped[bool] = mapped_column(Boolean, default=False)
    looking_for: Mapped[str] = mapped_column(String, default="any")
    age_min: Mapped[int] = mapped_column(Integer, default=18)
    age_max: Mapped[int] = mapped_column(Integer, default=99)
    distance_max: Mapped[int] = mapped_column(Integer, default=100)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class Like(Base):
    __tablename__ = "dating_likes"
    # Схема ДОЛЖНА совпадать с api/models/models.py — один лайк на пару пользователей
    __table_args__ = (
        UniqueConstraint("liker_id", "liked_id", name="uq_like_pair"),
        Index("ix_like_liker", "liker_id"),
        Index("ix_like_liked", "liked_id"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    liker_id: Mapped[str] = mapped_column(String, ForeignKey("dating_users.id", ondelete="CASCADE"))
    liked_id: Mapped[str] = mapped_column(String, ForeignKey("dating_users.id", ondelete="CASCADE"))
    type: Mapped[str] = mapped_column(String, default="like")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Match(Base):
    __tablename__ = "dating_matches"
    # Схема ДОЛЖНА совпадать с api/models/models.py — один мэтч на пару пользователей
    __table_args__ = (
        UniqueConstraint("user1_id", "user2_id", name="uq_match_pair"),
        Index("ix_match_user1", "user1_id"),
        Index("ix_match_user2", "user2_id"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user1_id: Mapped[str] = mapped_column(String, ForeignKey("dating_users.id", ondelete="CASCADE"))
    user2_id: Mapped[str] = mapped_column(String, ForeignKey("dating_users.id", ondelete="CASCADE"))
    match_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ai_reason: Mapped[str | None] = mapped_column(String, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Referral(Base):
    __tablename__ = "dating_referrals"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    referrer_id: Mapped[str] = mapped_column(String, ForeignKey("dating_users.id", ondelete="CASCADE"))
    invited_id: Mapped[str] = mapped_column(String, ForeignKey("dating_users.id", ondelete="CASCADE"), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Subscription(Base):
    __tablename__ = "dating_subscriptions"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String, ForeignKey("dating_users.id", ondelete="CASCADE"), unique=True)
    plan: Mapped[str] = mapped_column(String, default="free")
    stripe_id: Mapped[str | None] = mapped_column(String, nullable=True)
    features: Mapped[dict | list] = mapped_column(JSON, default=list)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Message(Base):
    __tablename__ = "dating_messages"
    __table_args__ = (Index("ix_message_match_created", "match_id", "created_at"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    match_id: Mapped[str] = mapped_column(String, ForeignKey("dating_matches.id", ondelete="CASCADE"))
    sender_id: Mapped[str] = mapped_column(String, ForeignKey("dating_users.id", ondelete="CASCADE"))
    text: Mapped[str] = mapped_column(String, default="")
    image_url: Mapped[str | None] = mapped_column(String, nullable=True)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# ─────────────────────────────────────────────────────────────────
# Ниже — модели, которые бот не использует напрямую (нет CRUD-функций
# в database/connection.py), но они объявлены в api/models/models.py.
# Схема БД общая для api и bot (оба вызывают create_all() при старте),
# поэтому таблицы должны быть объявлены здесь один в один с api,
# иначе при старте бота "первым" на пустой БД эти таблицы не создадутся.
# ─────────────────────────────────────────────────────────────────


class Report(Base):
    __tablename__ = "dating_reports"
    __table_args__ = (Index("ix_report_reported", "reported_id"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    reporter_id: Mapped[str] = mapped_column(String, ForeignKey("dating_users.id", ondelete="CASCADE"))
    reported_id: Mapped[str] = mapped_column(String, ForeignKey("dating_users.id", ondelete="CASCADE"))
    reason: Mapped[str] = mapped_column(String)
    description: Mapped[str] = mapped_column(String, default="")
    status: Mapped[str] = mapped_column(String, default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Block(Base):
    """Постоянная блокировка. Схема совпадает с api/models/models.py."""

    __tablename__ = "dating_blocks"
    __table_args__ = (
        UniqueConstraint("blocker_id", "blocked_id", name="uq_block_pair"),
        Index("ix_block_blocker", "blocker_id"),
        Index("ix_block_blocked", "blocked_id"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    blocker_id: Mapped[str] = mapped_column(String, ForeignKey("dating_users.id", ondelete="CASCADE"))
    blocked_id: Mapped[str] = mapped_column(String, ForeignKey("dating_users.id", ondelete="CASCADE"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ProcessedPayment(Base):
    """Журнал зачтённых платежей — защита от двойного начисления премиума.
    Схема совпадает с api/models/models.py."""

    __tablename__ = "dating_processed_payments"
    __table_args__ = (
        UniqueConstraint("provider", "external_id", name="uq_payment_external"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    provider: Mapped[str] = mapped_column(String)  # cryptobot | stars
    external_id: Mapped[str] = mapped_column(String)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("dating_users.id", ondelete="CASCADE"))
    days: Mapped[int] = mapped_column(Integer, default=30)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SwipeSession(Base):
    __tablename__ = "dating_swipe_sessions"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String, ForeignKey("dating_users.id", ondelete="CASCADE"), unique=True)
    viewed_ids: Mapped[dict | list] = mapped_column(JSON, default=list)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AiModerationLog(Base):
    __tablename__ = "dating_ai_moderation_logs"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String, ForeignKey("dating_users.id", ondelete="CASCADE"))
    content_type: Mapped[str] = mapped_column(String)  # photo | bio | message
    content: Mapped[str] = mapped_column(String)
    result: Mapped[str] = mapped_column(String)  # safe | warning | blocked
    action: Mapped[str] = mapped_column(String, default="none")  # none | warn | ban
    reason: Mapped[str] = mapped_column(String, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
