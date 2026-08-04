from __future__ import annotations

import random
import uuid
from datetime import datetime
from typing import List, Optional

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
    relationship,
)
from sqlalchemy.dialects.postgresql import JSON


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "dating_users"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    telegram_id: Mapped[Optional[int]] = mapped_column(BigInteger, unique=True, nullable=True)
    phone: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    role: Mapped[str] = mapped_column(String, default="user")
    is_banned: Mapped[bool] = mapped_column(Boolean, default=False)
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    last_seen_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relations
    # passive_deletes=True обязателен: иначе при удалении пользователя
    # SQLAlchemy пытается обнулить внешние ключи (liked_id NOT NULL —
    # и удаление аккаунта падает). Каскад выполняет сама БД,
    # ondelete="CASCADE" объявлен на колонках ниже.
    profile: Mapped[Optional["Profile"]] = relationship(
        back_populates="user",
        uselist=False,
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    likes_given: Mapped[List["Like"]] = relationship(
        back_populates="liker", foreign_keys="[Like.liker_id]", passive_deletes=True
    )
    likes_received: Mapped[List["Like"]] = relationship(
        back_populates="liked", foreign_keys="[Like.liked_id]", passive_deletes=True
    )
    matches1: Mapped[List["Match"]] = relationship(
        back_populates="user1", foreign_keys="[Match.user1_id]", passive_deletes=True
    )
    matches2: Mapped[List["Match"]] = relationship(
        back_populates="user2", foreign_keys="[Match.user2_id]", passive_deletes=True
    )
    messages: Mapped[List["Message"]] = relationship(
        back_populates="sender", passive_deletes=True
    )
    subscription: Mapped[Optional["Subscription"]] = relationship(
        back_populates="user",
        uselist=False,
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class Profile(Base):
    __tablename__ = "dating_profiles"
    __table_args__ = (
        # Дека выбирает кандидатов по случайной точке этого ключа вместо
        # ORDER BY RANDOM(), которому нужна сортировка всей таблицы.
        # Индекс частичный: анкеты-невидимки и незаполненные в деку не идут,
        # поэтому и в индексе им места нет.
        Index(
            "ix_profile_sample",
            "sample_key",
            postgresql_where=text("NOT is_incognito AND display_name <> ''"),
        ),
        # Нишевые фильтры: в индексе держим только заполненные значения —
        # большинство анкет субкультуру и цель не укажет, искать будут по тем,
        # кто указал.
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
    birth_date: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    city: Mapped[str] = mapped_column(String, default="")
    latitude: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    longitude: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    photos: Mapped[str] = mapped_column(JSON, default=list)
    interests: Mapped[str] = mapped_column(JSON, default=list)
    ai_bio: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    # Нишевые поля анкеты: по ним ищут не «кого-нибудь рядом», а своих.
    # Пустая строка означает «не указано» и в фильтр не попадает — иначе
    # незаполненные анкеты вымывались бы из выдачи.
    goal: Mapped[str] = mapped_column(String, default="")
    subculture: Mapped[str] = mapped_column(String, default="")
    #: Тип личности MBTI («INFJ» и т.п.). Пусто — не указан.
    mbti: Mapped[str] = mapped_column(String, default="")
    height_cm: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # Полное скрытие из выдачи. Флаг перегружен по смыслу: им же работают
    # пауза аккаунта (`set_profile_hidden`) и автоскрытие по жалобам, поэтому
    # тонкие настройки приватности ниже сделаны отдельными полями.
    is_incognito: Mapped[bool] = mapped_column(Boolean, default=False)
    #: Не показывать возраст в карточке. Подбор по возрасту продолжает
    #: работать — иначе анкета выпала бы из фильтров у всех.
    hide_age: Mapped[bool] = mapped_column(Boolean, default=False)
    #: Не показывать расстояние. Город остаётся: без него непонятно, где человек.
    hide_distance: Mapped[bool] = mapped_column(Boolean, default=False)
    #: Не попадать в чужой раздел «Гости» при просмотре анкет.
    hide_from_visitors: Mapped[bool] = mapped_column(Boolean, default=False)
    #: До какого момента анкета поднята в выдаче (платный буст). Прошедшая
    #: дата равнозначна отсутствию буста, поэтому чистить поле не нужно.
    boost_until: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    looking_for: Mapped[str] = mapped_column(String, default="any")
    age_min: Mapped[int] = mapped_column(Integer, default=18)
    age_max: Mapped[int] = mapped_column(Integer, default=99)
    distance_max: Mapped[int] = mapped_column(Integer, default=100)
    # Фильтры поиска по нишевым полям. Пусто — фильтр выключен, а не «искать
    # пустое»: человек, который не выбрал цель, должен видеть всех.
    filter_goal: Mapped[str] = mapped_column(String, default="")
    filter_subculture: Mapped[str] = mapped_column(String, default="")
    filter_city: Mapped[str] = mapped_column(String, default="")
    filter_height_min: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    filter_height_max: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # Случайное место анкеты в порядке выдачи деки: выборка идёт от случайной
    # точки этого ключа по индексу, а не сортировкой всей таблицы.
    sample_key: Mapped[float] = mapped_column(
        Float, default=random.random, server_default=text("random()"), nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    user: Mapped["User"] = relationship(back_populates="profile")


class Like(Base):
    __tablename__ = "dating_likes"
    __table_args__ = (
        UniqueConstraint("liker_id", "liked_id", name="uq_like_pair"),
        # Дека собирает exclude_ids по liker_id, «кто меня лайкнул» — по liked_id
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

    liker: Mapped["User"] = relationship(back_populates="likes_given", foreign_keys=[liker_id])
    liked: Mapped["User"] = relationship(back_populates="likes_received", foreign_keys=[liked_id])


class Match(Base):
    __tablename__ = "dating_matches"
    # user1_id/user2_id всегда хранятся в лексикографическом порядке (см. likes.py)
    __table_args__ = (
        UniqueConstraint("user1_id", "user2_id", name="uq_match_pair"),
        # Список чатов ищет мэтчи пользователя с любой стороны пары
        Index("ix_match_user1", "user1_id"),
        Index("ix_match_user2", "user2_id"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user1_id: Mapped[str] = mapped_column(String, ForeignKey("dating_users.id", ondelete="CASCADE"))
    user2_id: Mapped[str] = mapped_column(String, ForeignKey("dating_users.id", ondelete="CASCADE"))
    match_score: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    ai_reason: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user1: Mapped["User"] = relationship(back_populates="matches1", foreign_keys=[user1_id])
    user2: Mapped["User"] = relationship(back_populates="matches2", foreign_keys=[user2_id])
    messages: Mapped[List["Message"]] = relationship(back_populates="match", cascade="all, delete-orphan")


class Message(Base):
    __tablename__ = "dating_messages"
    # История переписки грузится по match_id с сортировкой по времени —
    # самый частый запрос в продукте после деки
    __table_args__ = (Index("ix_message_match_created", "match_id", "created_at"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    match_id: Mapped[str] = mapped_column(String, ForeignKey("dating_matches.id", ondelete="CASCADE"))
    sender_id: Mapped[str] = mapped_column(String, ForeignKey("dating_users.id", ondelete="CASCADE"))
    text: Mapped[str] = mapped_column(String, default="")
    image_url: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    read_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    match: Mapped["Match"] = relationship(back_populates="messages")
    sender: Mapped["User"] = relationship(back_populates="messages")


class Report(Base):
    __tablename__ = "dating_reports"
    # Эскалация считает разных жалобщиков по одной цели
    __table_args__ = (Index("ix_report_reported", "reported_id"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    reporter_id: Mapped[str] = mapped_column(String, ForeignKey("dating_users.id", ondelete="CASCADE"))
    reported_id: Mapped[str] = mapped_column(String, ForeignKey("dating_users.id", ondelete="CASCADE"))
    reason: Mapped[str] = mapped_column(String)
    description: Mapped[str] = mapped_column(String, default="")
    status: Mapped[str] = mapped_column(String, default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Subscription(Base):
    __tablename__ = "dating_subscriptions"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String, ForeignKey("dating_users.id", ondelete="CASCADE"), unique=True)
    plan: Mapped[str] = mapped_column(String, default="free")
    stripe_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    features: Mapped[str] = mapped_column(JSON, default=list)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped["User"] = relationship(back_populates="subscription")


class Referral(Base):
    """Приглашение по реферальной ссылке t.me/bot?start=ref_<user_id>."""
    __tablename__ = "dating_referrals"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    referrer_id: Mapped[str] = mapped_column(String, ForeignKey("dating_users.id", ondelete="CASCADE"))
    # Каждый приглашённый засчитывается ровно один раз
    invited_id: Mapped[str] = mapped_column(String, ForeignKey("dating_users.id", ondelete="CASCADE"), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Block(Base):
    """Постоянная блокировка: заблокированный больше никогда не попадёт в деку
    и не сможет связаться с тем, кто его заблокировал. Требование App Store
    Guideline 1.2 — блокировка обязана быть необратимой для второй стороны,
    в отличие от размэтча, который лишь удаляет лайки."""

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


class PhotoRating(Base):
    """Оценка чужого фото по шкале 1–5.

    Одна оценка на пару «кто оценил + чью анкету»: оценивается первое фото
    анкеты, а не каждое по отдельности — иначе один человек мог бы наставить
    шесть оценок одному и тому же лицу.

    Переоценить можно: повторный голос обновляет прежний, но не добавляет
    новый. Средняя оценка считается запросом по этой таблице, а не хранится
    в анкете: оценок на человека немного, а расходящийся кеш пришлось бы
    пересчитывать.
    """

    __tablename__ = "dating_photo_ratings"
    __table_args__ = (
        UniqueConstraint("rater_id", "target_id", name="uq_photo_rating"),
        # Свои оценки читаются по target_id
        Index("ix_photo_rating_target", "target_id"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    rater_id: Mapped[str] = mapped_column(String, ForeignKey("dating_users.id", ondelete="CASCADE"))
    target_id: Mapped[str] = mapped_column(String, ForeignKey("dating_users.id", ondelete="CASCADE"))
    #: 1..5. Ограничение проверяется схемой запроса: в БД оно потребовало бы
    #: миграции при каждом изменении шкалы.
    score: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class BoostActivation(Base):
    """Журнал включений буста — по нему считается суточный остаток.

    Считаем по времени, а не счётчиком в анкете: счётчик пришлось бы обнулять
    по расписанию, и пропущенный запуск открыл бы безлимит. Тот же подход, что
    у суперлайков.
    """

    __tablename__ = "dating_boost_activations"
    __table_args__ = (Index("ix_boost_user_created", "user_id", "created_at"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String, ForeignKey("dating_users.id", ondelete="CASCADE"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ProfileVisit(Base):
    """Кто открывал чью анкету — раздел «Гости».

    Одна строка на пару с обновлением времени, а не журнал всех заходов:
    открыть анкету можно десятки раз за вечер, и полный журнал распухал бы
    без пользы. В разделе всё равно показывается «кто заходил», а не
    «сколько раз».

    Инкогнито здесь не хранится: анкета невидимки просто не попадает в деку,
    поэтому и визитов от неё не будет.
    """

    __tablename__ = "dating_profile_visits"
    __table_args__ = (
        UniqueConstraint("visitor_id", "host_id", name="uq_visit_pair"),
        # Раздел «Гости» читает свои визиты по host_id, свежие сверху
        Index("ix_visit_host_seen", "host_id", "last_seen_at"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    visitor_id: Mapped[str] = mapped_column(String, ForeignKey("dating_users.id", ondelete="CASCADE"))
    host_id: Mapped[str] = mapped_column(String, ForeignKey("dating_users.id", ondelete="CASCADE"))
    #: Сколько раз заходил — для подписи «заходил 5 раз».
    visits: Mapped[int] = mapped_column(Integer, default=1)
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Reel(Base):
    """Короткое видео в ленте — альтернатива свайпам.

    Обложку присылает клиент отдельным файлом, и именно она проходит
    AI-модерацию: разбирать видео на кадры на сервере значило бы тащить
    ffmpeg в образ, а без модерации первого кадра в ленту попадёт что угодно.

    Счётчик лайков держим прямо здесь: лента сортируется по нему, а COUNT по
    таблице лайков на каждый ролик — это лишний проход на каждый запрос.
    """

    __tablename__ = "dating_reels"
    __table_args__ = (
        # Лента: свежие сверху, скрытые модерацией не показываются
        Index("ix_reel_created", "created_at"),
        Index("ix_reel_author", "user_id"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String, ForeignKey("dating_users.id", ondelete="CASCADE"))
    video_url: Mapped[str] = mapped_column(String)
    cover_url: Mapped[str] = mapped_column(String, default="")
    caption: Mapped[str] = mapped_column(String, default="")
    likes_count: Mapped[int] = mapped_column(Integer, default=0)
    #: Снят с показа модератором или автомодерацией. Автор свой ролик видит:
    #: иначе он решит, что загрузка не сработала, и загрузит снова.
    is_hidden: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ReelLike(Base):
    """Лайк ролика. Один на пару — повторный тап снимает свой же лайк."""

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
    """Журнал зачтённых платежей. Уникальный ключ (provider, external_id) —
    единственная надёжная защита от двойного начисления премиума: инвойс
    CryptoBot остаётся оплаченным навсегда, а кнопку «Проверить оплату»
    можно нажать сколько угодно раз."""

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
    """Токен устройства для пуш-уведомлений.

    Токен уникален: APNs выдаёт его на пару «приложение + устройство», и он
    может переехать к другому пользователю, если на телефоне сменили аккаунт.
    Тогда запись просто переписывается на нового владельца — иначе пуши
    продолжали бы уходить предыдущему.
    """

    __tablename__ = "dating_device_tokens"
    __table_args__ = (
        UniqueConstraint("token", name="uq_device_token"),
        # Отправка ищет все устройства пользователя
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
