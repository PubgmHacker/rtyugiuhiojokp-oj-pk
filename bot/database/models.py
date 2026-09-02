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
    #: Язык интерфейса с первого шага онбординга — см. api/models/models.py.
    #: Схема обязана совпадать: бот тоже вызывает create_all() и, стартовав
    #: первым на пустой базе, создал бы таблицу без этой колонки.
    locale: Mapped[str] = mapped_column(String, default="ru", server_default=text("'ru'"))
    role: Mapped[str] = mapped_column(String, default="user")
    is_banned: Mapped[bool] = mapped_column(Boolean, default=False)
    #: Срок бана — см. api/models/models.py. NULL при is_banned=True — вечный;
    #: истечение снимает бан лениво (get_or_create_user при любом апдейте).
    banned_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
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
        Index(
            "ix_profile_relation_type",
            "relation_type",
            postgresql_where=text("relation_type <> ''"),
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
    # Видеоролики анкеты — дополнение к фото, см. api/models/models.py.
    # Публичные URL из R2 либо, когда R2 не настроен, Telegram file_id.
    videos: Mapped[dict | list] = mapped_column(JSON, default=list)
    # Опорное фото проверки — см. api/models/models.py: URL фото анкеты,
    # с которым совпало лицо на живой съёмке. Бот сверяет с ним новые фото
    # подтверждённых пользователей и снимает галочку, если его убрали.
    verified_photo: Mapped[str] = mapped_column(String, default="")
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
    #: Не участвовать в оценке фото: ни оценивать, ни быть оценённым.
    hide_from_ratings: Mapped[bool] = mapped_column(Boolean, default=False)
    # Платный буст показов — см. api/models/models.py
    boost_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Суперлайки из кейсов — см. api/models/models.py
    bonus_superlikes: Mapped[int] = mapped_column(Integer, default=0)
    # Включения буста, купленные паком за Stars — см. api/models/models.py
    bonus_boosts: Mapped[int] = mapped_column(Integer, default=0)
    #: Выбранная наклейка из коллекции — единственная, которую видят другие.
    #: Показывать все значило бы превратить карточку в витрину достижений, а
    #: смотрят на неё ради человека. Пусто — ничего не выбрано.
    sticker: Mapped[str | None] = mapped_column(String, nullable=True)
    #: Оформление карточки и схема приложения. Боту они не нужны, но обе
    #: схемы создают таблицы в одной базе — расхождение роняет того, кто
    #: поднялся вторым, на первом же запросе к отсутствующей колонке.
    decor: Mapped[str | None] = mapped_column(String, nullable=True)
    app_theme: Mapped[str] = mapped_column(String, default="", server_default="")
    #: Telegram-канал в анкете (платно) — см. api/models/models.py.
    #: Хранится голым юзернеймом, без @ и без https://t.me/.
    tg_channel: Mapped[str] = mapped_column(String, default="")
    #: Тип искомой связи и фильтр по нему — см. api/models/models.py
    relation_type: Mapped[str] = mapped_column(String, default="")
    filter_relation_type: Mapped[str] = mapped_column(String, default="")
    looking_for: Mapped[str] = mapped_column(String, default="any")
    age_min: Mapped[int] = mapped_column(Integer, default=18)
    age_max: Mapped[int] = mapped_column(Integer, default=99)
    distance_max: Mapped[int] = mapped_column(Integer, default=100)
    filter_goal: Mapped[str] = mapped_column(String, default="")
    filter_subculture: Mapped[str] = mapped_column(String, default="")
    filter_city: Mapped[str] = mapped_column(String, default="")
    filter_height_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    filter_height_max: Mapped[int | None] = mapped_column(Integer, nullable=True)
    #: Только подтверждённые анкеты в выдаче — см. api/models/models.py.
    #: Обе стороны звонят create_all(), поэтому колонка обязана быть здесь
    #: тоже: иначе бот пересоздаст таблицу без неё.
    filter_verified: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false"), nullable=False
    )
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
        # Квоты API считают лайки за скользящее окно на каждом свайпе —
        # индекс зеркалит api/models/models.py на случай, если create_all
        # бота отработает на чистой базе первым
        Index("ix_like_liker_created", "liker_id", "created_at"),
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
        Index("ix_match_initiator_created", "initiator_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user1_id: Mapped[str] = mapped_column(String, ForeignKey("dating_users.id", ondelete="CASCADE"))
    user2_id: Mapped[str] = mapped_column(String, ForeignKey("dating_users.id", ondelete="CASCADE"))
    match_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ai_reason: Mapped[str | None] = mapped_column(String, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    #: Тип беседы и поля платного письма без взаимности —
    #: см. api/models/models.py и api/services/direct_messages.py
    kind: Mapped[str] = mapped_column(String, default="match", server_default=text("'match'"))
    initiator_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("dating_users.id", ondelete="CASCADE"), nullable=True
    )
    direct_answered: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false")
    )
    direct_letter_sent: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class MatchView(Base):
    """Какие мэтчи человек открывал — суточный лимит бесплатного уровня.

    Схема ДОЛЖНА совпадать с api/models/models.py::MatchView. Бот пишет сюда
    сам (открытие чата из списка мэтчей — такое же открытие, как в мини-аппе),
    поэтому таблица здесь не «на всякий случай», а рабочая.
    """

    __tablename__ = "dating_match_views"
    __table_args__ = (
        UniqueConstraint("user_id", "match_id", name="uq_match_view"),
        Index("ix_match_view_user_seen", "user_id", "viewed_at"),
        Index("ix_match_view_match", "match_id"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String, ForeignKey("dating_users.id", ondelete="CASCADE"))
    match_id: Mapped[str] = mapped_column(String, ForeignKey("dating_matches.id", ondelete="CASCADE"))
    #: Когда открыт в последний раз. Обновляется на месте, а не дублируется:
    #: окно скользящее, и запись старше окна должна продлеваться.
    viewed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Referral(Base):
    __tablename__ = "dating_referrals"
    __table_args__ = (
        # Зеркало api/models/models.py: COUNT приглашённых на каждом
        # GET /profiles/me
        Index("ix_referral_referrer", "referrer_id"),
    )

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
        # Частичный индекс непрочитанных — зеркало api/models/models.py
        Index(
            "ix_message_unread", "match_id", "sender_id",
            postgresql_where=text("read_at IS NULL"),
            sqlite_where=text("read_at IS NULL"),
        ),
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
    __table_args__ = (
        Index("ix_report_reported", "reported_id"),
        # Дедуп жалобы и антифлуд фильтруют по автору: без индекса каждая
        # новая жалоба сканировала таблицу целиком, и с ростом она тормозила
        # самый чувствительный путь (routers/report.py, routers/reels.py)
        Index("ix_report_reporter", "reporter_id"),
    )

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
    """Забаненные личности — см. api/models/models.py.

    Список переживает удаление аккаунта, иначе бан обходится удалением.
    Обе схемы (бот и API) создают одну и ту же таблицу и обязаны совпадать
    по колонкам — иначе запись падает на неизвестном поле. Бот пишет только
    telegram_id, apple_id остаётся NULL, но колонка нужна для совпадения схем.
    """

    __tablename__ = "dating_banned_identities"
    __table_args__ = (
        UniqueConstraint("telegram_id", name="uq_banned_telegram"),
        Index(
            "uq_banned_apple",
            "apple_id",
            unique=True,
            postgresql_where=text("apple_id IS NOT NULL"),
        ),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    telegram_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    apple_id: Mapped[str | None] = mapped_column(String, nullable=True)
    reason: Mapped[str] = mapped_column(String, default="")
    #: Срок бана привязки — см. api/models/models.py: NULL — вечный,
    #: дата — остаток срока для вернувшегося после удаления аккаунта.
    banned_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
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


class StickerOwned(Base):
    """Наклейка, выпавшая человеку из кейса.

    Зачем коллекция вообще: прежде из кейса выпадали только суперлайки и минуты
    буста — их тратят и забывают, и повода открыть кейс завтра не остаётся.
    Наклейка остаётся навсегда и её видно в анкете, поэтому у кейса появляется
    второй смысл: собрать набор.

    Дубликаты не храним отдельными строками: считаем, сколько раз выпала.
    Иначе таблица растёт линейно от числа открытий, а показать надо ровно один
    значок с числом.
    """

    __tablename__ = "dating_stickers_owned"
    __table_args__ = (
        UniqueConstraint("user_id", "code", name="uq_sticker_owner"),
        Index("ix_sticker_user", "user_id"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String, ForeignKey("dating_users.id", ondelete="CASCADE"))
    #: Код наклейки из services/stickers.py — он же имя файла в web/public/stickers.
    code: Mapped[str] = mapped_column(String)
    #: Сколько раз выпала. Первое выпадение — 1.
    count: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class DecorOwned(Base):
    """Лимитированная обложка карточки — см. api/models/models.py."""

    __tablename__ = "dating_decor_owned"
    __table_args__ = (
        UniqueConstraint("user_id", "code", name="uq_decor_owner"),
        Index("ix_decor_user", "user_id"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String, ForeignKey("dating_users.id", ondelete="CASCADE"))
    code: Mapped[str] = mapped_column(String)
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
    provider: Mapped[str] = mapped_column(String)  # cryptobot | stars | sbp | appstore
    external_id: Mapped[str] = mapped_column(String)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("dating_users.id", ondelete="CASCADE"))
    days: Mapped[int] = mapped_column(Integer, default=30)
    #: Сумма в минорных единицах валюты (XTR — звёзды, RUB — копейки,
    #: USDT — сотые); по ней админка считает выручку. NULL — сумма неизвестна
    amount: Mapped[int | None] = mapped_column(Integer, nullable=True)
    currency: Mapped[str | None] = mapped_column(String, nullable=True)
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
    __table_args__ = (
        # Зеркало api/models/models.py: журнал пишется на каждое сообщение,
        # страйки ищут MAX(created_at) по человеку, админка листает по времени
        Index("ix_ai_moderation_user_created", "user_id", "created_at"),
        Index("ix_ai_moderation_created", "created_at"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String, ForeignKey("dating_users.id", ondelete="CASCADE"))
    content_type: Mapped[str] = mapped_column(String)  # photo | bio | message
    content: Mapped[str] = mapped_column(String)
    result: Mapped[str] = mapped_column(String)  # safe | warning | blocked
    action: Mapped[str] = mapped_column(String, default="none")  # none | warn | ban
    # Категория нарушения при result="blocked": ad | heavy | text — зеркало
    # api/models/models.py, по ней API считает страйки.
    category: Mapped[str] = mapped_column(String, default="", server_default="")
    reason: Mapped[str] = mapped_column(String, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ChatThemeSettings(Base):
    """Оформление чата пары — см. api/models/models.py.

    Боту не нужна, но схема ДОЛЖНА совпадать с API: обе создают таблицы
    в одной БД.
    """

    __tablename__ = "dating_chat_themes"
    __table_args__ = (
        UniqueConstraint("match_id", name="uq_chat_theme_match"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    match_id: Mapped[str] = mapped_column(String, ForeignKey("dating_matches.id", ondelete="CASCADE"))
    bubble_mine_color: Mapped[str | None] = mapped_column(String, nullable=True)
    bubble_theirs_color: Mapped[str | None] = mapped_column(String, nullable=True)
    background_color: Mapped[str | None] = mapped_column(String, nullable=True)
    pattern_key: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class UserHabit(Base):
    """Привычка человека — см. api/models/models.py."""

    __tablename__ = "dating_habits"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String, ForeignKey("dating_users.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String)
    target_per_day: Mapped[int] = mapped_column(Integer, default=1, server_default=text("1"))
    today_count: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    counted_for_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ChatStreak(Base):
    """Серия дней общения в паре — см. api/models/models.py."""

    __tablename__ = "dating_chat_streaks"
    __table_args__ = (
        UniqueConstraint("match_id", name="uq_chat_streak_match"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    match_id: Mapped[str] = mapped_column(String, ForeignKey("dating_matches.id", ondelete="CASCADE"))
    streak_days: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    last_counted_for: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revives_left: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    revives_refreshed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    burnt_from_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    burnt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class GiftSubscription(Base):
    """Подарок подписки — см. api/models/models.py.

    Боту нужна по-настоящему: подписку дарят и через Telegram Stars, и
    активирует код тоже бот.
    """

    __tablename__ = "dating_gift_subscriptions"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    buyer_user_id: Mapped[str] = mapped_column(String, ForeignKey("dating_users.id", ondelete="CASCADE"))
    recipient_user_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("dating_users.id", ondelete="CASCADE"), nullable=True
    )
    plan: Mapped[str] = mapped_column(String)
    months: Mapped[int] = mapped_column(Integer, default=1)
    code_hash: Mapped[str] = mapped_column(String)
    payment_id: Mapped[str | None] = mapped_column(String, nullable=True)
    paid: Mapped[bool] = mapped_column(Boolean, default=False)
    redeemed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Story(Base):
    """История на сутки — см. api/models/models.py."""

    __tablename__ = "dating_stories"
    __table_args__ = (
        Index("ix_story_author_created", "user_id", "created_at"),
        Index("ix_story_expires", "expires_at"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(
        String, ForeignKey("dating_users.id", ondelete="CASCADE"), nullable=False
    )
    media_url: Mapped[str] = mapped_column(String, nullable=False)
    object_key: Mapped[str] = mapped_column(String, default="", server_default="")
    caption: Mapped[str] = mapped_column(String, default="", server_default="")
    audience: Mapped[str] = mapped_column(
        String, default="matches", server_default="matches", nullable=False
    )
    views_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    replies_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    is_hidden: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class StoryView(Base):
    """Просмотр истории — см. api/models/models.py."""

    __tablename__ = "dating_story_views"
    __table_args__ = (
        UniqueConstraint("story_id", "viewer_id", name="uq_story_view"),
        Index("ix_story_view_viewer", "viewer_id", "story_id"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    story_id: Mapped[str] = mapped_column(
        String, ForeignKey("dating_stories.id", ondelete="CASCADE"), nullable=False
    )
    viewer_id: Mapped[str] = mapped_column(
        String, ForeignKey("dating_users.id", ondelete="CASCADE"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class VerificationAttempt(Base):
    """Попытка живой проверки профиля (галочка) — см. api/models/models.py.

    Кадры проверки в БД не попадают никогда: хранится только задание и итог.
    Бот эту таблицу не читает, класс здесь ради совпадения схем: обе стороны
    вызывают create_all() в одну базу.
    """

    __tablename__ = "dating_verification_attempts"
    __table_args__ = (
        Index("ix_verification_user_created", "user_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(
        String, ForeignKey("dating_users.id", ondelete="CASCADE"), nullable=False
    )
    poses: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String, default="issued")
    reason: Mapped[str] = mapped_column(String, default="")
    # Кто проводил проверку: "builtin" (позы + автоматика) или "sumsub"
    # (провайдер живости); provider_ref — id заявителя на стороне провайдера
    provider: Mapped[str] = mapped_column(String, default="builtin")
    provider_ref: Mapped[str] = mapped_column(String, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AdminAuditLog(Base):
    """Журнал действий админов — см. api/models/models.py.

    Бот эту таблицу не пишет и не читает, класс здесь ради совпадения схем:
    обе стороны вызывают create_all() в одну базу. Нарочно без внешних
    ключей — журнал обязан переживать удаление и админа, и цели, иначе
    каскад стёр бы историю ровно тогда, когда она нужна.
    """

    __tablename__ = "dating_admin_audit"
    __table_args__ = (
        Index("ix_admin_audit_created", "created_at"),
        Index("ix_admin_audit_admin", "admin_id"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    admin_id: Mapped[str] = mapped_column(String)
    admin_name: Mapped[str] = mapped_column(String, default="")
    action: Mapped[str] = mapped_column(String)
    target_user_id: Mapped[str] = mapped_column(String, default="")
    target_name: Mapped[str] = mapped_column(String, default="")
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Broadcast(Base):
    """Рассылка через бота — см. api/models/models.py.

    Единственная общая таблица, которую бот ПИШЕТ: админка создаёт задачу,
    бот (services/broadcast.py) рассылает и обновляет счётчики — прогресс
    виден в админке без отдельного канала связи. Без FK на создателя:
    история рассылок переживает удаление админа, имя лежит снапшотом.
    """

    __tablename__ = "dating_broadcasts"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    created_by: Mapped[str] = mapped_column(String)
    created_by_name: Mapped[str] = mapped_column(String, default="")
    text: Mapped[str] = mapped_column(String, nullable=False)
    #: "all" — всем живым с Telegram; "test" — только создателю
    segment: Mapped[str] = mapped_column(String, default="all")
    status: Mapped[str] = mapped_column(String, default="queued")
    total: Mapped[int] = mapped_column(Integer, default=0)
    sent: Mapped[int] = mapped_column(Integer, default=0)
    failed: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class PromoCode(Base):
    """Промокод на подписку — копия api/models/models.py::PromoCode.

    Выпускает только админка через API; бот лишь активирует, поэтому
    механика лимита (атомарный UPDATE со слотом в WHERE) повторена в
    database/connection.py::activate_promo_code.
    """

    __tablename__ = "dating_promo_codes"
    __table_args__ = (
        UniqueConstraint("code", name="uq_promo_code"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    #: Всегда в верхнем регистре: активация нормализует ввод так же
    code: Mapped[str] = mapped_column(String)
    tier: Mapped[str] = mapped_column(String, default="plus")
    days: Mapped[int] = mapped_column(Integer, default=7)
    #: 0 — без лимита
    max_uses: Mapped[int] = mapped_column(Integer, default=1)
    used_count: Mapped[int] = mapped_column(Integer, default=0)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    #: Выключенный код отвечает «не найден», а не «закончился»
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    comment: Mapped[str] = mapped_column(String, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PromoActivation(Base):
    """Кто и когда активировал промокод — копия из api/models/models.py.
    Уникальность пары не даёт активировать один код дважды."""

    __tablename__ = "dating_promo_activations"
    __table_args__ = (
        UniqueConstraint("promo_id", "user_id", name="uq_promo_activation"),
        Index("ix_promo_activation_user", "user_id"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    promo_id: Mapped[str] = mapped_column(String, ForeignKey("dating_promo_codes.id", ondelete="CASCADE"))
    user_id: Mapped[str] = mapped_column(String, ForeignKey("dating_users.id", ondelete="CASCADE"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Notification(Base):
    """Копия api/models/models.py::Notification — мета-тест сверяет колонки.

    Бот в центр уведомлений пока не пишет: оба вида событий (итог жалобы,
    галочка вебхуком) рождаются на стороне API. Копия нужна, чтобы схема
    у бота и API не разъехалась.
    """

    __tablename__ = "dating_notifications"
    __table_args__ = (
        Index("ix_notification_user", "user_id", "created_at"),
        # Частичный индекс красной точки — зеркало api/models/models.py
        Index(
            "ix_notification_unread", "user_id",
            postgresql_where=text("read_at IS NULL"),
            sqlite_where=text("read_at IS NULL"),
        ),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String, ForeignKey("dating_users.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AnalyticsEvent(Base):
    """Копия api/models/models.py::AnalyticsEvent — мета-тест сверяет колонки.

    Бот пишет свои события воронки сам (/start, конец анкеты, счета и
    начисления Stars/CryptoBot): они рождаются на его стороне, а таблица
    общая — отчёты в services/analytics.py читают обе половины воронки.
    """

    __tablename__ = "dating_analytics_events"
    __table_args__ = (
        Index("ix_analytics_event_created", "event", "created_at"),
        Index("ix_analytics_user_event", "user_id", "event"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String, ForeignKey("dating_users.id", ondelete="CASCADE"))
    event: Mapped[str] = mapped_column(String(64))
    props: Mapped[dict] = mapped_column(JSON, default=dict)
    dedup_key: Mapped[str | None] = mapped_column(String, unique=True, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class OnboardingNudge(Base):
    """Отложенный завлекающий пуш онбординга: одна строка — один несосланный.

    Раньше рассылки про субкультуру и почту уходили прямо в онбординге, сразу
    после согласия с политикой — человек получал три сообщения подряд и читал
    это как спам. Теперь согласие и конец анкеты только СТАВЯТ пуш (upsert по
    telegram_id+stage со сдвигом due_at), а services/nudges.py отправляет его,
    когда человек уже помолчал. Отправленные и безнадёжные строки удаляются —
    таблица держит только очередь, потому её нет в api/models/models.py:
    create_all API своих таблиц не трогает, а бот создаёт её сам.
    """

    __tablename__ = "dating_onboarding_nudges"
    __table_args__ = (
        UniqueConstraint("telegram_id", "stage", name="uq_onboarding_nudge"),
        Index("ix_onboarding_nudge_due", "due_at"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    telegram_id: Mapped[int] = mapped_column(BigInteger)
    #: Какой пуш: "style" — субкультура/стиль, "email" — привязка почты
    stage: Mapped[str] = mapped_column(String(16))
    locale: Mapped[str] = mapped_column(String(8), default="ru")
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
