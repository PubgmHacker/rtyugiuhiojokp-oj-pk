from __future__ import annotations

import random
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
    text,
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
    #: Sign in with Apple: у бота не используется, но колонка обязана
    #: совпадать с api/models/models.py — бот тоже вызывает create_all() и,
    #: стартовав первым на пустой базе, создал бы таблицу без неё
    apple_id: Mapped[str | None] = mapped_column(String, unique=True, nullable=True)
    #: Почта для восстановления доступа. Единственный способ вернуться в свой
    #: аккаунт, если потерян Telegram: без неё вместе с ним теряется и
    #: оплаченная подписка. Подтверждается кодом, поэтому хранится уже
    #: проверенной; nullable — привязка добровольная.
    email: Mapped[str | None] = mapped_column(String, unique=True, nullable=True)
    phone: Mapped[str | None] = mapped_column(String, nullable=True)
    role: Mapped[str] = mapped_column(String, default="user")
    is_banned: Mapped[bool] = mapped_column(Boolean, default=False)
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class Profile(Base):
    __tablename__ = "dating_profiles"
    # Схема ДОЛЖНА совпадать с api/models/models.py
    __table_args__ = (
        Index(
            "ix_profile_sample",
            "sample_key",
            postgresql_where=text(
                "NOT is_incognito AND NOT is_paused AND display_name <> ''"
            ),
        ),
        Index(
            "ix_profile_subculture",
            "subculture",
            postgresql_where=text("subculture <> ''"),
        ),
        Index(
            "ix_profile_goal",
            "goal",
            postgresql_where=text("goal <> ''"),
        ),
    )

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
    goal: Mapped[str] = mapped_column(String, default="")
    subculture: Mapped[str] = mapped_column(String, default="")
    mbti: Mapped[str] = mapped_column(String, default="")
    height_cm: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_incognito: Mapped[bool] = mapped_column(Boolean, default=False)
    # Пауза аккаунта — отдельно от платного инкогнито, см. api/models/models.py
    is_paused: Mapped[bool] = mapped_column(Boolean, default=False)
    # Тонкие настройки приватности — см. api/models/models.py
    hide_age: Mapped[bool] = mapped_column(Boolean, default=False)
    hide_distance: Mapped[bool] = mapped_column(Boolean, default=False)
    hide_from_visitors: Mapped[bool] = mapped_column(Boolean, default=False)
    # Платный буст показов — см. api/models/models.py
    boost_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Суперлайки из кейсов — см. api/models/models.py
    bonus_superlikes: Mapped[int] = mapped_column(Integer, default=0)
    looking_for: Mapped[str] = mapped_column(String, default="any")
    age_min: Mapped[int] = mapped_column(Integer, default=18)
    age_max: Mapped[int] = mapped_column(Integer, default=99)
    distance_max: Mapped[int] = mapped_column(Integer, default=100)
    filter_goal: Mapped[str] = mapped_column(String, default="")
    filter_subculture: Mapped[str] = mapped_column(String, default="")
    filter_city: Mapped[str] = mapped_column(String, default="")
    filter_height_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    filter_height_max: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Случайное место анкеты в порядке выдачи деки — см. api/models/models.py
    sample_key: Mapped[float] = mapped_column(
        Float, default=random.random, server_default=text("random()"), nullable=False,
    )
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
    # Текст, приложенный к лайку: он показывается получателю до мэтча,
    # поэтому это единственный способ сказать что-то первым.
    message: Mapped[str] = mapped_column(String, default="")
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
    __table_args__ = (
        Index("ix_message_match_created", "match_id", "created_at"),
        Index("ix_dating_messages_reel", "reel_id"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    match_id: Mapped[str] = mapped_column(String, ForeignKey("dating_matches.id", ondelete="CASCADE"))
    sender_id: Mapped[str] = mapped_column(String, ForeignKey("dating_users.id", ondelete="CASCADE"))
    text: Mapped[str] = mapped_column(String, default="")
    image_url: Mapped[str | None] = mapped_column(String, nullable=True)
    #: Пересланный ролик — см. api/models/models.py. Бот пересыл не создаёт, но
    #: колонка обязана быть: create_all() бота может отработать первым.
    reel_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("dating_reels.id", ondelete="SET NULL"), nullable=True
    )
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


class BannedIdentity(Base):
    """Забаненные Telegram-аккаунты — см. api/models/models.py.
    Список переживает удаление аккаунта, иначе бан обходится удалением."""

    __tablename__ = "dating_banned_identities"
    __table_args__ = (UniqueConstraint("telegram_id", name="uq_banned_telegram"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    telegram_id: Mapped[int] = mapped_column(BigInteger)
    reason: Mapped[str] = mapped_column(String, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SectionOpen(Base):
    """Открытия разделов — см. api/models/models.py."""

    __tablename__ = "dating_section_opens"
    __table_args__ = (
        UniqueConstraint("user_id", "section", name="uq_section_open"),
        Index("ix_section_open_section", "section"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String, ForeignKey("dating_users.id", ondelete="CASCADE"))
    section: Mapped[str] = mapped_column(String)
    opens: Mapped[int] = mapped_column(Integer, default=1)
    last_open_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class VoiceCall(Base):
    """Журнал звонков рулетки — см. api/models/models.py."""

    __tablename__ = "dating_voice_calls"
    __table_args__ = (Index("ix_voice_call_created", "created_at"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    caller_id: Mapped[str] = mapped_column(String, ForeignKey("dating_users.id", ondelete="CASCADE"))
    callee_id: Mapped[str] = mapped_column(String, ForeignKey("dating_users.id", ondelete="CASCADE"))
    duration_seconds: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CaseOpening(Base):
    """Журнал открытий кейса — см. api/models/models.py."""

    __tablename__ = "dating_case_openings"
    __table_args__ = (Index("ix_case_user_created", "user_id", "created_at"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String, ForeignKey("dating_users.id", ondelete="CASCADE"))
    reward: Mapped[str] = mapped_column(String)
    amount: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Room(Base):
    """Групповой чат — см. api/models/models.py. Бот в комнаты не пишет, но
    обе схемы создают таблицы в одной БД."""

    __tablename__ = "dating_rooms"
    __table_args__ = (UniqueConstraint("slug", name="uq_room_slug"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    slug: Mapped[str] = mapped_column(String)
    title: Mapped[str] = mapped_column(String)
    description: Mapped[str] = mapped_column(String, default="")
    city: Mapped[str] = mapped_column(String, default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class RoomMessage(Base):
    """Сообщение в групповом чате — см. api/models/models.py."""

    __tablename__ = "dating_room_messages"
    __table_args__ = (
        Index("ix_room_message_created", "room_id", "created_at"),
        Index("ix_dating_room_messages_reel", "reel_id"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    room_id: Mapped[str] = mapped_column(String, ForeignKey("dating_rooms.id", ondelete="CASCADE"))
    sender_id: Mapped[str] = mapped_column(String, ForeignKey("dating_users.id", ondelete="CASCADE"))
    text: Mapped[str] = mapped_column(String)
    #: Пересланный ролик — см. Message.reel_id.
    reel_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("dating_reels.id", ondelete="SET NULL"), nullable=True
    )
    is_hidden: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PhotoRating(Base):
    """Оценка фото 1-5 — см. api/models/models.py. Бот оценки не принимает,
    но обе схемы создают таблицы в одной БД."""

    __tablename__ = "dating_photo_ratings"
    __table_args__ = (
        UniqueConstraint("rater_id", "target_id", name="uq_photo_rating"),
        Index("ix_photo_rating_target", "target_id"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    rater_id: Mapped[str] = mapped_column(String, ForeignKey("dating_users.id", ondelete="CASCADE"))
    target_id: Mapped[str] = mapped_column(String, ForeignKey("dating_users.id", ondelete="CASCADE"))
    score: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class BoostActivation(Base):
    """Журнал включений буста — см. api/models/models.py. Бот бусты не
    включает, но обе схемы создают таблицы в одной БД."""

    __tablename__ = "dating_boost_activations"
    __table_args__ = (Index("ix_boost_user_created", "user_id", "created_at"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String, ForeignKey("dating_users.id", ondelete="CASCADE"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ProfileVisit(Base):
    """Кто открывал чью анкету — раздел «Гости» в мини-аппе.
    Схема совпадает с api/models/models.py; бот визиты не пишет, но обе схемы
    создают таблицы в одной БД и обязаны совпадать."""

    __tablename__ = "dating_profile_visits"
    __table_args__ = (
        UniqueConstraint("visitor_id", "host_id", name="uq_visit_pair"),
        Index("ix_visit_host_seen", "host_id", "last_seen_at"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    visitor_id: Mapped[str] = mapped_column(String, ForeignKey("dating_users.id", ondelete="CASCADE"))
    host_id: Mapped[str] = mapped_column(String, ForeignKey("dating_users.id", ondelete="CASCADE"))
    visits: Mapped[int] = mapped_column(Integer, default=1)
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Reel(Base):
    """Короткое видео в ленте мини-аппа. Схема совпадает с
    api/models/models.py; бот ролики не публикует, но обе схемы создают
    таблицы в одной БД и обязаны совпадать."""

    __tablename__ = "dating_reels"
    __table_args__ = (
        Index("ix_reel_created", "created_at"),
        Index("ix_reel_author", "user_id"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String, ForeignKey("dating_users.id", ondelete="CASCADE"))
    video_url: Mapped[str] = mapped_column(String)
    cover_url: Mapped[str] = mapped_column(String, default="")
    caption: Mapped[str] = mapped_column(String, default="")
    likes_count: Mapped[int] = mapped_column(Integer, default=0)
    comments_count: Mapped[int] = mapped_column(Integer, default=0)
    views_count: Mapped[int] = mapped_column(Integer, default=0)
    is_hidden: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ReelComment(Base):
    """Комментарий к ролику — см. api/models/models.py."""

    __tablename__ = "dating_reel_comments"
    __table_args__ = (Index("ix_reel_comment_reel", "reel_id", "created_at"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    reel_id: Mapped[str] = mapped_column(String, ForeignKey("dating_reels.id", ondelete="CASCADE"))
    user_id: Mapped[str] = mapped_column(String, ForeignKey("dating_users.id", ondelete="CASCADE"))
    text: Mapped[str] = mapped_column(String)
    is_hidden: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ReelLike(Base):
    """Лайк ролика. Схема совпадает с api/models/models.py."""

    __tablename__ = "dating_reel_likes"
    __table_args__ = (
        UniqueConstraint("reel_id", "user_id", name="uq_reel_like"),
        Index("ix_reel_like_reel", "reel_id"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    reel_id: Mapped[str] = mapped_column(String, ForeignKey("dating_reels.id", ondelete="CASCADE"))
    user_id: Mapped[str] = mapped_column(String, ForeignKey("dating_users.id", ondelete="CASCADE"))
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


class DeviceToken(Base):
    """Токен устройства для пушей — см. api/models/models.py.

    Боту не нужен, но схема ДОЛЖНА совпадать с API: обе создают таблицы
    в одной БД.
    """

    __tablename__ = "dating_device_tokens"
    __table_args__ = (
        UniqueConstraint("token", name="uq_device_token"),
        Index("ix_device_user", "user_id"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String, ForeignKey("dating_users.id", ondelete="CASCADE"))
    token: Mapped[str] = mapped_column(String)
    platform: Mapped[str] = mapped_column(String, default="ios")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


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
