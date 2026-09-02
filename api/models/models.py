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
    #: Язык интерфейса, выбранный на первом шаге онбординга бота.
    #: Хранится на аккаунте, а не в анкете, по двум причинам: язык нужен
    #: уведомлениям (бан, итог жалобы), где анкета не загружена вовсе, и он
    #: остаётся при удалении и повторном заполнении анкеты — человек выбирал
    #: язык, а не оформлял им профиль. До появления колонки выбор жил только
    #: в FSM бота и терялся на первом же перезапуске: люди выбирали узбекский
    #: и получали русский интерфейс.
    locale: Mapped[str] = mapped_column(String, default="ru", server_default=text("'ru'"))
    role: Mapped[str] = mapped_column(String, default="user")
    is_banned: Mapped[bool] = mapped_column(Boolean, default=False)
    #: Срок бана. NULL при is_banned=True — вечный бан (катфишинг, ручной бан
    #: админом); дата — временный, после неё любой вход снимает бан сам
    #: (ленивое истечение в get_current_user и login-путях, фонового джоба нет).
    banned_until: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
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
    #: Видеоролики анкеты — публичные URL из R2 (profile-videos/{user_id}/…).
    #: Дополнение к фото, не замена: обязательное фото с лицом остаётся
    #: единственным медиа, которое проходит гейт «живой человек», поэтому
    #: полнота анкеты и превью в деке считаются по photos.
    videos: Mapped[str] = mapped_column(JSON, default=list)
    #: Опорное фото проверки: та фотография анкеты, с которой совпало лицо на
    #: живой съёмке (routers/verification.py). Пока она стоит в анкете, каждое
    #: новое фото сверяется с ней — заменить подтверждённый профиль на чужие
    #: снимки нельзя; убрали её — галочка снимается и проверка проходится
    #: заново (routers/profiles.py). Пустая строка — проверки не было.
    #: Это НЕ биометрия: здесь лежит URL уже публичного фото анкеты.
    verified_photo: Mapped[str] = mapped_column(String, default="")
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
    #: Не участвовать в оценке фото — ни оценивать, ни быть оценённым.
    #:
    #: Оценки по умолчанию видимы: владелец фото видит, кто и сколько
    #: поставил. Открытость симметрична: скрылся — не оцениваешь и тебя
    #: не оценивают, иначе очередь превращается в способ судить чужие
    #: фото, спрятавшись от суждения о своём.
    hide_from_ratings: Mapped[bool] = mapped_column(Boolean, default=False)
    #: До какого момента анкета поднята в выдаче (платный буст). Прошедшая
    #: дата равнозначна отсутствию буста, поэтому чистить поле не нужно.
    boost_until: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    #: Суперлайки, выпавшие из кейса. Отдельный пул, а не прибавка к суточной
    #: квоте: квота считается по факту расхода за сутки, и прибавка к ней
    #: возобновлялась бы каждый день сама.
    bonus_superlikes: Mapped[int] = mapped_column(Integer, default=0)
    #: Включения буста, купленные паком за Stars. Тот же принцип отдельного
    #: пула, что у bonus_superlikes: суточная квота считается по факту
    #: расхода и возобновляется сама, а купленное не сгорает в полночь.
    bonus_boosts: Mapped[int] = mapped_column(Integer, default=0)
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
    #: Показывать только анкеты с пройденной проверкой по видео (`User.is_verified`).
    #: Единственный фильтр, который человек включает не по вкусу, а ради
    #: безопасности: он отсекает не «неподходящих», а тех, кто не доказал, что
    #: он на своих фото. Поэтому он бесплатный — брать деньги за право
    #: разговаривать с подтверждёнными людьми нельзя.
    #:
    #: Живёт в анкете, а не в локальном хранилище: выбор безопасности обязан
    #: доехать до второго устройства и до бота, где дека собирается тем же
    #: кодом.
    filter_verified: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false"), nullable=False
    )
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
        # Квоты считают лайки за скользящее окно (quotas.likes_state,
        # _superlikes_left) — на КАЖДОМ свайпе. Без created_at в индексе
        # подсчёт «за последние 12 часов» читает всю историю лайков человека.
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


class MatchView(Base):
    """Какие мэтчи человек открывал — для суточного лимита бесплатного уровня.

    Строка на пару (кто смотрит, что открыл), а не запись на каждое открытие:
    лимит стоит на РАЗНЫХ мэтчах, поэтому повторный вход в уже открытый чат
    обязан быть бесплатным, а для этого достаточно одной отметки времени.
    Журнал всех открытий тут был бы и лишним объёмом, и лишним смыслом.

    Своя таблица, а не поле в `Match`: смотрят двое, и лимиты у них разные —
    один может платить, другой нет.
    """

    __tablename__ = "dating_match_views"
    __table_args__ = (
        UniqueConstraint("user_id", "match_id", name="uq_match_view"),
        # Квота считается как «сколько разных мэтчей я открыл за окно» —
        # это ровно (user_id, viewed_at)
        Index("ix_match_view_user_seen", "user_id", "viewed_at"),
        # Нужен для FK: без него удаление мэтча сканирует таблицу целиком
        Index("ix_match_view_match", "match_id"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String, ForeignKey("dating_users.id", ondelete="CASCADE"))
    match_id: Mapped[str] = mapped_column(String, ForeignKey("dating_matches.id", ondelete="CASCADE"))
    #: Когда открыт в последний раз. Обновляется, а не дублируется: окно
    #: скользящее, и запись старше окна должна продлеваться на месте.
    viewed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Message(Base):
    __tablename__ = "dating_messages"
    # История переписки грузится по match_id с сортировкой по времени —
    # самый частый запрос в продукте после деки. Индекс по reel_id нужен не
    # для чтения, а для удаления ролика: без него `SET NULL` сканирует всю
    # таблицу сообщений
    __table_args__ = (
        Index("ix_message_match_created", "match_id", "created_at"),
        Index("ix_dating_messages_reel", "reel_id"),
        # Непрочитанное — самый частый COUNT продукта: бейдж таббара, счётчики
        # в списке чатов, отметка прочтения. Полный индекс дублировал бы всю
        # таблицу; частичный держит только непрочитанные строки (их на порядки
        # меньше) и превращает COUNT в index-only scan. Для SQLite условие
        # задаётся отдельным ключом — тестовые базы получают тот же индекс.
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
    __table_args__ = (
        # COUNT приглашённых идёт на каждом GET /profiles/me и в ранжировании
        # деки — без индекса это Seq Scan по всем рефералам сервиса.
        Index("ix_referral_referrer", "referrer_id"),
    )

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
    """Забаненные личности — список, который переживает удаление аккаунта.

    Личность — это внешняя привязка входа: telegram_id для бота и Mini App,
    apple_id для нативного iOS. Хранится по одной на строку: у пришедшего из
    App Store нет Telegram, у забаненного в боте — Apple. Проверять надо ту,
    через которую человек заходит, поэтому колонки раздельные, а не одна.
    """

    __tablename__ = "dating_banned_identities"
    __table_args__ = (
        UniqueConstraint("telegram_id", name="uq_banned_telegram"),
        # Дубли apple-банов не нужны; строки без apple_id (баны через Telegram)
        # под ограничение не попадают
        Index(
            "uq_banned_apple",
            "apple_id",
            unique=True,
            postgresql_where=text("apple_id IS NOT NULL"),
        ),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    # Обе привязки необязательны и взаимоисключающи в пределах строки: NULL там,
    # где у человека такого входа нет
    telegram_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    apple_id: Mapped[str | None] = mapped_column(String, nullable=True)
    reason: Mapped[str] = mapped_column(String, default="")
    #: Срок бана привязки — копия users.banned_until на момент бана. Нужна
    #: своя: удалённый аккаунт срок унести с собой не может, а вернувшийся
    #: через повторную регистрацию должен получить остаток срока, а не вечность.
    #: NULL — вечный бан; истёкшие строки чистятся лениво при проверке.
    banned_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
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

    Награды — только коллекционные: лимитированная обложка карточки или
    наклейка. Расходники (суперлайки, буст) из кейса убраны: их тратят и
    забывают, а случайная выдача полезного делала кейс похожим на игровой
    автомат, а не на коллекцию.

    Попытки не храним счётчиком: они даются за подписку и считаются как
    «положено по уровню минус открыто с начала месяца» — тот же приём, что
    у суперлайков и бустов, он не ломается от пропущенной уборки.
    """

    __tablename__ = "dating_case_openings"
    __table_args__ = (Index("ix_case_user_created", "user_id", "created_at"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String, ForeignKey("dating_users.id", ondelete="CASCADE"))
    #: Что выпало: код конкретной наклейки или обложки.
    reward: Mapped[str] = mapped_column(String)
    #: Сколько начислено. Для коллекционных наград всегда 1; колонка
    #: осталась от расходников — в старых строках лежат их количества.
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


class DecorOwned(Base):
    """Обложка карточки, выпавшая человеку из кейса.

    Обложки лимитированные: их нельзя купить и нельзя открыть прогрессом —
    только вытащить из кейса, попытки которого даёт подписка. Владение
    поэтому хранится строкой, как у наклеек, а не выводится из числа
    наклеек: вычисляемое право исчезало бы при смене условий каталога.

    Счётчика повторов нет: кейс выбирает обложку среди НЕимеющихся, и дубль
    невозможен по построению. Когда собраны все, вместо обложки выпадает
    наклейка — см. routers/cases.py.
    """

    __tablename__ = "dating_decor_owned"
    __table_args__ = (
        UniqueConstraint("user_id", "code", name="uq_decor_owner"),
        Index("ix_decor_user", "user_id"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String, ForeignKey("dating_users.id", ondelete="CASCADE"))
    #: Код обложки из services/decor.py — рисуется CSS на клиенте.
    code: Mapped[str] = mapped_column(String)
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
    provider: Mapped[str] = mapped_column(String)  # cryptobot | stars | sbp | appstore
    external_id: Mapped[str] = mapped_column(String)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("dating_users.id", ondelete="CASCADE"))
    days: Mapped[int] = mapped_column(Integer, default=30)
    #: Сумма в минорных единицах валюты: XTR — звёзды, RUB — копейки,
    #: USDT — сотые. По этим полям админка считает выручку
    #: (/api/admin/metrics). NULL — сумма неизвестна: строки, записанные до
    #: появления колонок, и платежи App Store — их выручку считает Apple
    #: (валюта покупателя и комиссия магазина серверу не видны).
    amount: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    currency: Mapped[Optional[str]] = mapped_column(String, nullable=True)
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
    __table_args__ = (
        # Пишется на каждое сообщение чата — растёт быстрее всех таблиц.
        # (user_id, created_at): страйки и амнистия (services/enforcement.py)
        # ищут MAX(created_at) по человеку на каждом заблокированном тексте,
        # карточка юзера в админке листает его журнал. (created_at) — глобальный
        # листинг модерации в админке и будущая чистка старых записей.
        Index("ix_ai_moderation_user_created", "user_id", "created_at"),
        Index("ix_ai_moderation_created", "created_at"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String, ForeignKey("dating_users.id", ondelete="CASCADE"))
    content_type: Mapped[str] = mapped_column(String)  # photo | bio | message
    content: Mapped[str] = mapped_column(String)
    result: Mapped[str] = mapped_column(String)  # safe | warning | blocked
    action: Mapped[str] = mapped_column(String, default="none")  # none | warn | ban
    # Категория нарушения при result="blocked": ad | heavy | text (см.
    # TEXT_CATEGORIES в services/ai_moderation.py). По ней считаются страйки
    # и выбирается лестница бана. "" — safe-записи и вердикты без категории
    # (фото, старые строки до миграции).
    category: Mapped[str] = mapped_column(String, default="", server_default="")
    reason: Mapped[str] = mapped_column(String, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AdminAuditLog(Base):
    """Журнал действий админов: кто, что, с кем и когда сделал в админке.

    Ответ на вопрос «почему этот человек забанен/разбанен и кем» — без него
    любой спорный тикет упирается в память админов. Пишется в той же
    транзакции, что и само действие: откатилось действие — не будет и записи.

    Нарочно без внешних ключей: журнал обязан переживать удаление и админа,
    и цели, иначе каскад стёр бы историю ровно тогда, когда она нужнее всего
    (человек удалился после жалобы). Поэтому же имена лежат снапшотами —
    после удаления аккаунта строка остаётся читабельной.
    """

    __tablename__ = "dating_admin_audit"
    __table_args__ = (
        # Листинг читает хвост по времени, фильтр — по конкретному админу
        Index("ix_admin_audit_created", "created_at"),
        Index("ix_admin_audit_admin", "admin_id"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    admin_id: Mapped[str] = mapped_column(String)
    admin_name: Mapped[str] = mapped_column(String, default="")
    # ban | unban | set_verified | report_action | reel_action
    action: Mapped[str] = mapped_column(String)
    target_user_id: Mapped[str] = mapped_column(String, default="")
    target_name: Mapped[str] = mapped_column(String, default="")
    # Параметры действия как есть: срок и причина бана, вердикт по жалобе...
    details: Mapped[dict] = mapped_column(JSON, default=dict)
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


class VerificationAttempt(Base):
    """Попытка подтвердить профиль живой съёмкой (галочка).

    Сами кадры сюда НЕ попадают и вообще никуда не пишутся: это биометрия,
    её хранение — отдельная юридическая ответственность, а для продукта
    достаточно вердикта. Строка хранит только задание и итог.

    Жизненный цикл: `issued` (задание выдано) → `approved` / `rejected`.
    Выданное задание живёт ограниченное время (СРОК_ЗАДАНИЯ_МИНУТ в роутере);
    просроченное просто перестаёт приниматься — отдельного статуса не нужно.
    При недоступности AI строка остаётся `issued`: попытка не сожжена,
    человек повторяет отправку по тому же заданию.
    """

    __tablename__ = "dating_verification_attempts"
    __table_args__ = (
        # Суточный лимит отказов считается по (user_id, created_at)
        Index("ix_verification_user_created", "user_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(
        String, ForeignKey("dating_users.id", ondelete="CASCADE"), nullable=False
    )
    #: Заказанные позы по порядку, например ["straight", "left", "up"].
    #: Порядок — часть проверки: кадры обязаны следовать заданию.
    #: В провайдерском режиме (Sumsub) поз нет — пустой список.
    poses: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String, default="issued")
    #: Кто проверял: "builtin" (позы + GLM) или "sumsub" (WebSDK провайдера).
    provider: Mapped[str] = mapped_column(String, default="builtin")
    #: Идентификатор у провайдера (applicantId Sumsub) — для сверки и суппорта.
    provider_ref: Mapped[str] = mapped_column(String, default="")
    #: Причина отказа — человеку она показывается как есть.
    reason: Mapped[str] = mapped_column(String, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    decided_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class Broadcast(Base):
    """Рассылка через бота.

    Создаёт админка (routers/admin.py), исполняет бот
    (bot/services/broadcast.py): клиента к Telegram у API нет, а бот и так
    его держит и знает лимиты отправки. Строка — и задача, и отчёт: бот по
    ходу дела обновляет счётчики, и админка показывает прогресс без
    отдельного канала связи.

    Статусы: queued → running → done; error — рассылка не запустилась или
    упала целиком (сбои по отдельным получателям — счётчик failed, не статус).

    segment: "all" — всем живым с Telegram; "test" — только создателю,
    чтобы посмотреть сообщение глазами получателя до отправки всем.
    """

    __tablename__ = "dating_broadcasts"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    #: Без FK: история рассылок должна переживать удаление админа,
    #: поэтому рядом лежит имя-снапшот — как в AdminAuditLog.
    created_by: Mapped[str] = mapped_column(String)
    created_by_name: Mapped[str] = mapped_column(String, default="")
    text: Mapped[str] = mapped_column(String, nullable=False)
    segment: Mapped[str] = mapped_column(String, default="all")
    status: Mapped[str] = mapped_column(String, default="queued")
    total: Mapped[int] = mapped_column(Integer, default=0)
    sent: Mapped[int] = mapped_column(Integer, default=0)
    failed: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    started_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class PromoCode(Base):
    """Промокод на подписку. Выпускает админка, активирует пользователь.

    От подарочного кода (GiftSubscription) отличается принципиально:
    подарок — оплаченная одноразовая передача, промокод — маркетинговый
    инструмент с лимитом активаций. Один код могут активировать max_uses
    разных людей (0 — без лимита), но каждый — только один раз
    (uq_promo_activation).

    Код хранится открытым текстом, а не хешем, как у подарков: промокод —
    не секрет, он печатается в постах и рассылках, а админке нужно видеть
    и копировать его после выпуска.
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
    #: 0 — без лимита. Слот списывается атомарным UPDATE c проверкой
    #: остатка в WHERE — две одновременные активации не перепродадут
    #: последний слот (services/promo.py)
    max_uses: Mapped[int] = mapped_column(Integer, default=1)
    used_count: Mapped[int] = mapped_column(Integer, default=0)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    #: Выключенный код отвечает «не найден», а не «закончился»: админ гасит
    #: утёкший код, и подсказывать, что код настоящий, незачем
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    #: Зачем выпущен — админке при разборе, откуда пришла волна активаций
    comment: Mapped[str] = mapped_column(String, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PromoActivation(Base):
    """Кто и когда активировал промокод. Уникальность пары — защита от
    повторной активации тем же человеком, в том числе двумя одновременными
    запросами: второй INSERT падает на ключе и откатывает свою транзакцию
    вместе со списанным слотом."""

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
    """Центр уведомлений: события, у которых нет своего экрана с бейджем.

    Мэтчи, лайки и сообщения сюда не пишутся — их считает badges.py и
    показывают вкладки «Чаты» и «Лайки»; дубль в ленте был бы шумом. Здесь
    живёт то, что иначе терялось: итог жалобы (человек нажал
    «Пожаловаться» и заслужил узнать, чем кончилось) и галочка
    верификации, пришедшая вдогонку вебхуком, когда шторка давно закрыта.

    Тексты собирает клиент из kind + payload: API не знает языка
    интерфейса (та же доктрина, что у services/report_notify.py).
    Неизвестный kind клиент молча прячет — старое приложение не падает
    на событии нового вида.
    """

    __tablename__ = "dating_notifications"
    __table_args__ = (
        Index("ix_notification_user", "user_id", "created_at"),
        # Красная точка колокольчика — COUNT непрочитанных на каждом входе.
        # Лента растёт монотонно и не чистится, а непрочитанных единицы:
        # частичный индекс остаётся крошечным и закрывает заодно UPDATE
        # в mark_all_read.
        Index(
            "ix_notification_unread", "user_id",
            postgresql_where=text("read_at IS NULL"),
            sqlite_where=text("read_at IS NULL"),
        ),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String, ForeignKey("dating_users.id", ondelete="CASCADE"))
    #: report_outcome | verification_approved (services/notifications.py)
    kind: Mapped[str] = mapped_column(String)
    #: Детали для текста на клиенте: у report_outcome — {"outcome": "banned"}
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    #: Пусто — непрочитанное. Заполняется скопом при открытии центра
    read_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class AnalyticsEvent(Base):
    """Событие продуктовой воронки — от /start в боте до покупки.

    Аналитики не было вообще: ни воронку CPI → анкета → первый свайп → D1 →
    покупка, ни окупаемость канала посмотреть было нечем — платный трафик
    лился бы вслепую. Внешние трекеры дейтингу противопоказаны (передача
    данных третьим лицам — отдельный пункт согласия), поэтому события лежат
    в своём Postgres, а воронка считается обычным SQL
    (см. services/analytics.py).

    `dedup_key` делает событие вехой: у «первого свайпа» он `user:event`
    (одна строка на всю жизнь), у ежедневных `user:event:день` (одна строка
    в день — D1/D7 считаются по календарной сетке, а таблица не растёт от
    каждого пинга). UNIQUE игнорирует NULL и в Postgres, и в SQLite, поэтому
    события без дедупликации пишутся без ограничений.
    """

    __tablename__ = "dating_analytics_events"
    __table_args__ = (
        # Воронка режется по событию и окну дат
        Index("ix_analytics_event_created", "event", "created_at"),
        # Траектория человека: какие вехи прошёл и когда
        Index("ix_analytics_user_event", "user_id", "event"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String, ForeignKey("dating_users.id", ondelete="CASCADE"))
    #: bot_start | profile_created | app_open | first_swipe | first_match |
    #: first_message | paywall_view | purchase_started | purchase_completed
    #: (services/analytics.py — единственный список)
    event: Mapped[str] = mapped_column(String(64))
    #: Контекст события: у bot_start — {"source": метка канала},
    #: у purchase_completed — {"provider", "tier", "days", "amount", "currency"}
    props: Mapped[dict] = mapped_column(JSON, default=dict)
    dedup_key: Mapped[Optional[str]] = mapped_column(String, unique=True, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class OnboardingNudge(Base):
    """Очередь отложенных пушей онбординга — зеркало модели бота.

    Таблицей владеет бот (bot/services/nudges.py ставит и отправляет),
    API её не читает. Зеркало здесь потому, что оба сервиса зовут
    create_all на общей базе: кто первым стартует на пустой, тот и создаёт
    схему — и она обязана быть одинаковой с обеих сторон (это сверяют
    test_схема_бота_совпадает_с_api и test_колонки_совпадают_в_боте_и_api).
    Меняется только вместе с bot/database/models.py.
    """

    __tablename__ = "dating_onboarding_nudges"
    __table_args__ = (
        # Один пуш каждого вида на человека: повторное согласие двигает
        # срок существующей строки, а не плодит дубли
        UniqueConstraint("telegram_id", "stage", name="uq_onboarding_nudge"),
        # Тик очереди выбирает созревшее по due_at
        Index("ix_onboarding_nudge_due", "due_at"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    telegram_id: Mapped[int] = mapped_column(BigInteger)
    #: "style" (совет про субкультуру) | "email" (просьба привязать почту)
    stage: Mapped[str] = mapped_column(String(16))
    locale: Mapped[str] = mapped_column(String(8), default="ru")
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
