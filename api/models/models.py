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
    #: Идентификатор Sign in with Apple (поле `sub` в токене). Нужен вторым
    #: способом входа: App Store требует его там, где вход идёт через сторонний
    #: сервис (Guideline 4.8), а у пришедшего из App Store telegram_id может не
    #: быть вовсе — поэтому оба поля nullable, но хотя бы одно обязано быть.
    apple_id: Mapped[Optional[str]] = mapped_column(String, unique=True, nullable=True)
    #: Почта для восстановления доступа. Единственный способ вернуться в свой
    #: аккаунт, если потерян Telegram: без неё вместе с ним теряется и
    #: оплаченная подписка. Подтверждается кодом, поэтому хранится уже
    #: проверенной; nullable — привязка добровольная.
    email: Mapped[Optional[str]] = mapped_column(String, unique=True, nullable=True)
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
    purchased_gifts: Mapped[List["GiftSubscription"]] = relationship(
        back_populates="buyer", foreign_keys="[GiftSubscription.buyer_user_id]"
    )
    received_gifts: Mapped[List["GiftSubscription"]] = relationship(
        back_populates="recipient", foreign_keys="[GiftSubscription.recipient_user_id]"
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
            postgresql_where=text(
                "NOT is_incognito AND NOT is_paused AND display_name <> ''"
            ),
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
        # Тип связи — тот же случай: пустых («не указано») большинство.
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
    # Полное скрытие из выдачи. Флаг перегружен по смыслу: им же работает
    # автоскрытие по жалобам, поэтому тонкие настройки приватности ниже
    # сделаны отдельными полями.
    is_incognito: Mapped[bool] = mapped_column(Boolean, default=False)
    #: Пауза аккаунта: человек сам убрал анкету из поиска.
    #:
    #: Отдельно от `is_incognito`, хотя из деки убирают оба. Инкогнито — платная
    #: функция Plus («вас видят только те, кого лайкнули вы»), а пауза — базовое
    #: право уйти, и брать за него деньги нельзя. Пока они делили одно поле,
    #: команда /pause в боте бесплатно давала то, что в мини-аппе стоит денег.
    is_paused: Mapped[bool] = mapped_column(Boolean, default=False)
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
    #: Суперлайки, выпавшие из кейса. Отдельный пул, а не прибавка к суточной
    #: квоте: квота считается по факту расхода за сутки, и прибавка к ней
    #: возобновлялась бы каждый день сама.
    bonus_superlikes: Mapped[int] = mapped_column(Integer, default=0)
    #: Выбранная наклейка из коллекции — единственная, которую видят другие.
    #: Показывать все значило бы превратить карточку в витрину достижений, а
    #: смотрят на неё ради человека. Пусто — ничего не выбрано.
    sticker: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    #: Код оформления карточки из services/decor.py. Не путь и не CSS:
    #: рисует клиент, сервер отвечает только за право носить.
    decor: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    #: Выбранная схема оформления приложения (см. services/appearance.py).
    #:
    #: Хранится на сервере, хотя видна только владельцу: настройка внешнего
    #: вида, теряющаяся при переустановке, воспринимается как потеря данных.
    #: Пусто — базовая схема.
    app_theme: Mapped[str] = mapped_column(String, default="", server_default="")
    #: Ссылка на свой Telegram-канал в анкете (платная возможность).
    #:
    #: Хранится «голым» юзернеймом без @ и без https://t.me/ — так его нельзя
    #: подменить ссылкой на произвольный хост, а собрать адрес для показа
    #: тривиально. Пусто — блока в анкете нет.
    tg_channel: Mapped[str] = mapped_column(String, default="")
    #: Тип искомой связи: см. `services/relations.py`.
    #:
    #: Отдельно от `goal` (у того смысл «зачем»: отношения, дружба, общение) —
    #: здесь «с кем»: друзья, подруги, партнёр. Разделено потому, что у
    #: конкурента это два независимых фильтра, и совмещать их в одном поле
    #: значило бы плодить пары вида «дружба_подруги».
    relation_type: Mapped[str] = mapped_column(String, default="")
    #: Фильтр по типу связи. Пусто — фильтр выключен.
    filter_relation_type: Mapped[str] = mapped_column(String, default="")
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
        # Суточный лимит платных писем считается по паре (кто, когда). Индекс
        # нужен ещё и для FK: без него удаление пользователя сканировало бы
        # таблицу мэтчей целиком.
        Index("ix_match_initiator_created", "initiator_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user1_id: Mapped[str] = mapped_column(String, ForeignKey("dating_users.id", ondelete="CASCADE"))
    user2_id: Mapped[str] = mapped_column(String, ForeignKey("dating_users.id", ondelete="CASCADE"))
    match_score: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    ai_reason: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    #: Как возникла беседа: "match" — взаимный лайк, "direct" — платное письмо
    #: без взаимности (см. `services/direct_messages.py`).
    #:
    #: Сделано полем существующего мэтча, а не отдельной таблицей, сознательно:
    #: чат, сообщения, доставка, пуши, жалобы, блокировки и удаление аккаунта
    #: уже завязаны на `match_id`. Вторая таблица беседы означала бы вторую
    #: копию всего этого — а в этом проекте парные пути расходятся регулярно.
    kind: Mapped[str] = mapped_column(String, default="match", server_default=text("'match'"))
    #: Кто написал первым в беседе типа "direct". Нужен, чтобы отличать
    #: отправителя от получателя после того, как беседа создана: у получателя
    #: свои права (закрыть, пожаловаться), а лимит расходуется у отправителя.
    initiator_id: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("dating_users.id", ondelete="CASCADE"), nullable=True
    )
    #: Ответил ли получатель. До ответа отправитель ограничен одним письмом —
    #: иначе платная функция превращается в канал для спама.
    #:
    #: Держим флагом, а не считаем сообщения запросом: проверка идёт на каждое
    #: сообщение, в том числе в WebSocket, и лишний COUNT там неуместен.
    direct_answered: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false")
    )
    #: Отправил ли инициатор своё письмо в ТЕКУЩЕМ раунде. Раунд — это одна
    #: пара «письмо → ответ»: строка `Match` у пары одна и переиспользуется
    #: (`services/direct_messages.start_direct_message`), поэтому «письмо уже
    #: было» нельзя определить ни по существованию беседы, ни по её сообщениям
    #: — старая закрытая переписка оставляет и то, и другое.
    direct_letter_sent: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user1: Mapped["User"] = relationship(back_populates="matches1", foreign_keys=[user1_id])
    user2: Mapped["User"] = relationship(back_populates="matches2", foreign_keys=[user2_id])
    messages: Mapped[List["Message"]] = relationship(back_populates="match", cascade="all, delete-orphan")



class Message(Base):
    __tablename__ = "dating_messages"
    # История переписки грузится по match_id с сортировкой по времени —
    # самый частый запрос в продукте после деки. Индекс по reel_id нужен не
    # для чтения, а для удаления ролика: без него `SET NULL` сканирует всю
    # таблицу сообщений
    __table_args__ = (
        Index("ix_message_match_created", "match_id", "created_at"),
        Index("ix_dating_messages_reel", "reel_id"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    match_id: Mapped[str] = mapped_column(String, ForeignKey("dating_matches.id", ondelete="CASCADE"))
    sender_id: Mapped[str] = mapped_column(String, ForeignKey("dating_users.id", ondelete="CASCADE"))
    text: Mapped[str] = mapped_column(String, default="")
    image_url: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    #: Пересланный ролик. `SET NULL` при удалении: сообщение остаётся в
    #: переписке, просто превью пропадает — вырезать чужую реплику из истории
    #: только потому, что автор удалил видео, неправильно.
    reel_id: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("dating_reels.id", ondelete="SET NULL"), nullable=True
    )
    read_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    match: Mapped["Match"] = relationship(back_populates="messages")
    sender: Mapped["User"] = relationship(back_populates="messages")


class Report(Base):
    __tablename__ = "dating_reports"
    # Эскалация считает разных жалобщиков по одной цели
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


class GiftSubscription(Base):
    """Подарок подписки: как в Telegram, но с точной привязкой к платежу.

    Создаётся до покупки, активируется после 3DS/подтверждения. Код одноразовый,
    показывается только создателю — иначе письмо превратится в раздачу.
    """
    __tablename__ = "dating_gift_subscriptions"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    buyer_user_id: Mapped[str] = mapped_column(String, ForeignKey("dating_users.id", ondelete="CASCADE"))
    recipient_user_id: Mapped[Optional[str]] = mapped_column(String, ForeignKey("dating_users.id", ondelete="CASCADE"), nullable=True)
    plan: Mapped[str] = mapped_column(String)  # plus | ultra | aurora
    months: Mapped[int] = mapped_column(Integer, default=1)
    # Код показываем создателю один раз и не пишем plaintext: шифруем до
    # того, как дойдёт до лог-записи продюсера
    code_hash: Mapped[str] = mapped_column(String)
    # Заплатили? Код активируется только после оплаты — иначе print-ссылка
    # станет бесплатным подарочным кодом
    paid: Mapped[bool] = mapped_column(Boolean, default=False)
    # Использован? Отработанный код уже нельзя ввести повторно
    redeemed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    #: Идентификатор транзакции магазина. Ключ идемпотентности: Apple
    #: повторяет доставку чека, и без него один платёж выдавал бы новый
    #: подарочный код на каждую повторную проверку. NULL у подарков, купленных
    #: не через магазин, поэтому уникальность частичная.
    payment_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    buyer: Mapped["User"] = relationship(back_populates="purchased_gifts", foreign_keys="GiftSubscription.buyer_user_id")
    recipient: Mapped[Optional["User"]] = relationship(back_populates="received_gifts", foreign_keys="GiftSubscription.recipient_user_id")


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


# ── Темы чата в паре ─────────────────────────────────────────────────
# Тема влияет на цвет своих пузырей, цвет чужих и фон чата для ОБОИХ участников.
# Может настраиваться одинаково у них обоих, как в Telegram — иначе подпись
# «у Ани красные, у Бори синие» потребовала бы поддержки дважды.
class ChatThemeSettings(Base):
    __tablename__ = "dating_chat_themes"
    __table_args__ = (
        # Тема одна: паре не нужен выбор из двух наборов одновременно,
        # иначе каждая правка превращалась бы в окно опций, а не в краску.
        UniqueConstraint("match_id", name="uq_chat_theme_match"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    match_id: Mapped[str] = mapped_column(String, ForeignKey("dating_matches.id", ondelete="CASCADE"))
    # Произвольный цвет пузыря своих сообщений (hex). По умолчанию null —
    # чтобы пустая тема не затирала переменные оформления приложения.
    bubble_mine_color: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    bubble_theirs_color: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    # Фон на весь чат. Полõhex или ссылка на предзаполненный шаблон.
    background_color: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    # Метка эмодзи-темы, какие показываем в пикере (day/night/rainbow/...).
    # Нужна статистика, а не понятия — одинаковыми картинками набора не совместимы.
    pattern_key: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


# ── Задачи и привычки ──────────────────────────────────────────────
# Собираем простую to-do ленту прямо в профиле: важен не список, а что он
# виден там, где уже ищут внимание. Способствует возврату ежедневно — и это
# работает на паритет с дейтингом, потому что общая привычка формирует
# повод для диалога.
class UserHabit(Base):
    __tablename__ = "dating_habits"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String, ForeignKey("dating_users.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String)
    # Количество целей в день (обычно 1). В карточке это шаг прогресса
    # полоски («0/3»), а не абстраktный коричневый понт..
    target_per_day: Mapped[int] = mapped_column(Integer, default=1, server_default=text("1"))
    # Сколько сегодня сделано. На весь период не длится — хватает push в полночь.
    today_count: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    # За какой календарным днём показываем полоску: чтобы после 00:00 начать заново.
    counted_for_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class BannedIdentity(Base):
    """Забаненные Telegram-аккаунты — список, который переживает удаление."""

    __tablename__ = "dating_banned_identities"
    __table_args__ = (
        UniqueConstraint("telegram_id", name="uq_banned_telegram"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    telegram_id: Mapped[int] = mapped_column(BigInteger)
    reason: Mapped[str] = mapped_column(String, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SectionOpen(Base):
    """Открытия разделов — чтобы решать по цифрам, а не по вкусу.

    Спор «эта фича нужна или лишняя» бесконечен, пока нет данных: каждый
    судит по себе. Здесь копится ровно то, что нужно для решения — кто и
    какой раздел открывал.

    Одна строка на пару «человек + раздел» с обновлением счётчика: журнал
    каждого тапа вырос бы в самую большую таблицу в базе, а для ответа
    «сколько людей вообще заходит в кейсы» нужны уникальные посетители.
    """

    __tablename__ = "dating_section_opens"
    __table_args__ = (
        UniqueConstraint("user_id", "section", name="uq_section_open"),
        # Сводка читается по разделу
        Index("ix_section_open_section", "section"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String, ForeignKey("dating_users.id", ondelete="CASCADE"))
    #: Код раздела: reels | rooms | voice | photo_ratings | cases | leaderboard | daily
    section: Mapped[str] = mapped_column(String)
    opens: Mapped[int] = mapped_column(Integer, default=1)
    last_open_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class VoiceCall(Base):
    """Журнал пар голосовой рулетки.

    Записи разговора нет и быть не должно. Журнал нужен, чтобы по жалобе
    понимать, кто с кем говорил: без этого жалоба на голос неразбираема —
    пожаловавшийся даже не знает имени собеседника.
    """

    __tablename__ = "dating_voice_calls"
    __table_args__ = (Index("ix_voice_call_created", "created_at"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    caller_id: Mapped[str] = mapped_column(String, ForeignKey("dating_users.id", ondelete="CASCADE"))
    callee_id: Mapped[str] = mapped_column(String, ForeignKey("dating_users.id", ondelete="CASCADE"))
    #: Сколько секунд длился разговор. Ноль — не соединились.
    duration_seconds: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CaseOpening(Base):
    """Журнал открытий кейса и выпавших наград.

    Награды — то, что уже работает в продукте: суперлайки и минуты буста.
    Коллекционные картинки, как у конкурента, потребовали бы шестидесяти
    рисунков, а ценность бы имели только для того, кто их собирает.

    Попытки не храним счётчиком: они даются за подписку и считаются как
    «положено по уровню минус открыто за сутки» — тот же приём, что у
    суперлайков и бустов, он не ломается от пропущенной уборки.
    """

    __tablename__ = "dating_case_openings"
    __table_args__ = (Index("ix_case_user_created", "user_id", "created_at"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String, ForeignKey("dating_users.id", ondelete="CASCADE"))
    #: Код награды из services/cases.py: superlike | boost.
    reward: Mapped[str] = mapped_column(String)
    #: Сколько начислено — суперлайков или минут буста.
    amount: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Room(Base):
    """Групповой чат по городу или интересу.

    Комнаты создаём мы, а не пользователи: пользовательские комнаты — это
    отдельный продукт с модерацией названий, владельцами и правами, а нужен
    здесь способ познакомиться до мэтча.

    Ключ `slug` — по нему комната находится в ссылке и в тестах; название
    можно переписать, не ломая ссылки.
    """

    __tablename__ = "dating_rooms"
    __table_args__ = (UniqueConstraint("slug", name="uq_room_slug"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    slug: Mapped[str] = mapped_column(String)
    title: Mapped[str] = mapped_column(String)
    description: Mapped[str] = mapped_column(String, default="")
    #: Комната привязана к городу («Москва») или пуста — тогда она общая.
    city: Mapped[str] = mapped_column(String, default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class RoomMessage(Base):
    """Сообщение в групповом чате.

    Отдельно от `Message`: то привязано к мэтчу и имеет отметку прочтения на
    двоих, а здесь читателей много и отметка прочтения смысла не имеет.
    """

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
    reel_id: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("dating_reels.id", ondelete="SET NULL"), nullable=True
    )
    #: Снято модератором. Не удаляем: по жалобе нужно понимать, за что снято.
    is_hidden: Mapped[bool] = mapped_column(Boolean, default=False)
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


class StickerOwned(Base):
    """Наклейка, выпавшая человеку из кейса.

    Зачем коллекция вообще: прежде из кейса выпадали только суперлайки и минуты
    буста — их тратят и забывают, и повода открыть кейс завтра не остаётся.
    Наклейка остаётся навсегда и её видно в анкете, поэтому у кейса появляется
    второй смысл: собрать набор.

    Дубликаты не храним отдельными строками: считаем, сколько раз выпала.
    Иначе таблица растёт линейно от числа открытий, а показать надо ровно один
    значок с числом.

    Полезность за дубликат начисляется сразу при выпадении (суперлайк), поэтому
    повтор не воспринимается как пустая трата попытки.
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


class Reel(Base):
    """Короткое видео в ленте — альтернатива свайпам.

    Кадры с нескольких таймкодов присылает клиент, и именно они проходят
    AI-модерацию: разбирать видео на кадры на сервере значило бы тащить
    ffmpeg в образ. Средний по времени кадр сохраняется как cover_url —
    остальные нужны только модерации и не хранятся.

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
    #: Счётчики рядом с роликом по той же причине, что и лайки: лента
    #: сортируется и показывает их на каждой карточке, а COUNT по двум
    #: таблицам на каждый ролик — это лишний проход на каждый запрос ленты.
    comments_count: Mapped[int] = mapped_column(Integer, default=0)
    views_count: Mapped[int] = mapped_column(Integer, default=0)
    #: Снят с показа модератором или автомодерацией. Автор свой ролик видит:
    #: иначе он решит, что загрузка не сработала, и загрузит снова.
    is_hidden: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ReelComment(Base):
    """Комментарий к ролику.

    Здесь ролики и превращаются в знакомства: под видео написать проще, чем в
    личку первым, и разговор начинается сам. Без комментариев лента остаётся
    просмотром — самое сильное впечатление от видео никуда не ведёт.

    Автор комментария виден всем, поэтому текст модерируется как публичный:
    в личке собеседника можно заблокировать, а под роликом грубость читают все.
    """

    __tablename__ = "dating_reel_comments"
    __table_args__ = (
        # Лента комментариев читается по ролику, свежие снизу
        Index("ix_reel_comment_reel", "reel_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    reel_id: Mapped[str] = mapped_column(String, ForeignKey("dating_reels.id", ondelete="CASCADE"))
    user_id: Mapped[str] = mapped_column(String, ForeignKey("dating_users.id", ondelete="CASCADE"))
    text: Mapped[str] = mapped_column(String)
    #: Снят модератором. Не удаляем: по жалобе нужно понимать, за что снято.
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


# ── Стрик общения в паре ───────────────────────────────────────────
# Виден в чате и в списке чатов как огонёк. Считается по паре, а не по
# пользователю: стрик — про двоих, и если он прогорел, обидно обоим.
class ChatStreak(Base):
    """Серия общения в паре — огонёк, который держит пару в переписке.

    Устроено как в TikTok: считаем не сообщения, а ДНИ, в которые оба
    написали. Один день молчания — серия сгорает. Дальше два поля решают
    судьбу: `burnt_from_days` помнит, какой длины была серия на момент
    смерти, `burnt_at` — когда она умерла. Без первого восстановление
    возвращало бы серию к единице, то есть продавало бы пустоту; без
    второго можно было бы оживить серию, забытую полгода назад.
    """
    __tablename__ = "dating_chat_streaks"
    __table_args__ = (UniqueConstraint("match_id", name="uq_chat_streak_match"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    match_id: Mapped[str] = mapped_column(
        String, ForeignKey("dating_matches.id", ondelete="CASCADE"), nullable=False
    )

    streak_days: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"), nullable=False)
    last_counted_for: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Длина серии на момент сгорания и момент сгорания. Живая серия держит
    # здесь 0 и NULL — это и есть признак «гореть ещё нечему».
    burnt_from_days: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"), nullable=False)
    burnt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    revives_left: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"), nullable=False)
    # NULL, а не now(): «квота ни разу не выдавалась» и «выдана в этом
    # месяце» — разные состояния, и server_default=now() их склеивал,
    # из-за чего месячная квота не начислялась никогда.
    revives_refreshed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
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


class Story(Base):
    """История — фотография на сутки.

    Зачем в дейтинге: анкета статична, а история показывает человека
    сегодня. Это единственный вид контента, который люди производят сами
    и охотно — нам не нужно ни закупать его, ни генерировать.

    Живёт ровно 24 часа. Срок — не техническое ограничение, а причина
    выкладывать: то, что исчезнет, публикуют без отбора и правок.
    """

    __tablename__ = "dating_stories"
    __table_args__ = (
        Index("ix_story_author_created", "user_id", "created_at"),
        #: Лента и уборка ходят по сроку — индекс обязателен, иначе оба
        #: запроса переходят в полный проход по таблице на второй неделе.
        Index("ix_story_expires", "expires_at"),
    )

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(
        String, ForeignKey("dating_users.id", ondelete="CASCADE"), nullable=False
    )

    media_url: Mapped[str] = mapped_column(String, nullable=False)
    #: Ключ объекта в R2. Держим отдельно от ссылки: по ссылке файл не
    #: удалить, а истёкшие истории обязаны уносить за собой и файл.
    object_key: Mapped[str] = mapped_column(String, default="", server_default="")

    caption: Mapped[str] = mapped_column(String, default="", server_default="")

    #: "matches" — видят только пары; "everyone" — ещё и любой, кто открыл
    #: анкету. Значение по умолчанию закрытое: аудиторию расширяют
    #: осознанно, а не по недосмотру.
    audience: Mapped[str] = mapped_column(
        String, default="matches", server_default="matches", nullable=False
    )

    views_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    replies_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    #: Скрыта модерацией. Не удаляем: удалённую историю нельзя показать
    #: поддержке, когда автор придёт спорить.
    is_hidden: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false")
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


class StoryView(Base):
    """Кто посмотрел историю.

    Отдельная таблица, а не счётчик: автору важно именно «кто», это
    половина смысла публикации. Уникальность по паре — повторный заход
    не должен накручивать просмотры.
    """

    __tablename__ = "dating_story_views"
    __table_args__ = (
        UniqueConstraint("story_id", "viewer_id", name="uq_story_view"),
        Index("ix_story_view_viewer", "viewer_id", "story_id"),
    )

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    story_id: Mapped[str] = mapped_column(
        String, ForeignKey("dating_stories.id", ondelete="CASCADE"), nullable=False
    )
    viewer_id: Mapped[str] = mapped_column(
        String, ForeignKey("dating_users.id", ondelete="CASCADE"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
