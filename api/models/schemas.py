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
    #: Тип связи («с кем» — друзья/подруги/партнёр). Отдельная ось от `goal`
    #: («зачем»): пусто значит «не указано», как и у прочих нишевых полей.
    relation_type: str = ""
    filter_relation_type: str = ""
    # Заполняется только в списке «кто меня лайкнул»: текст, приложенный
    # к входящему лайку.
    like_message: str = ""
    #: Карточка скрыта до подписки: имя, фото и текст лайка не отданы.
    is_locked: bool = False
    has_location: bool = False
    #: Путь к картинке выбранной наклейки. Собирает сервер: код лежит в
    #: анкете, а клиенту нужен путь, и склейка на фронте разъехалась бы с
    #: папкой при первом же переносе.
    sticker: Optional[str] = None
    #: Код оформления карточки. Клиент рисует рамку сам (см. lib/decor.ts):
    #: CSS не гоняем по сети и не версионируем в базе.
    decor: Optional[str] = None
    #: Схема оформления приложения. Отдаётся только владельцу: другим она
    #: не видна и в публичной карточке ей места нет.
    app_theme: str = ""
    #: Привязанная почта — по ней можно вернуть аккаунт, если потерян Telegram.
    #: Отдаётся только владельцу (эндпоинты /profiles/me и /auth/me).
    email: Optional[str] = None
    invited_count: int = 0
    referral_boost: bool = False
    referral_target: int = 3
    referral_boost_percent: int = 12
    #: Голый юзернейм Telegram-канала (без @, без https://t.me/) — ссылку
    #: собирает клиент. Пусто — блока нет. Отдаётся, только если тариф
    #: разрешает `tg_channel` (см. services/plans.py, tier_allows).
    tg_channel: str = ""


class ProfileUpdate(BaseModel):
    display_name: Optional[str] = Field(None, max_length=50)
    bio: Optional[str] = Field(None, max_length=500)
    gender: Optional[str] = Field(None, pattern="^(male|female|other)$")
    birth_date: Optional[str] = None  # ISO format "YYYY-MM-DD"
    # Клиенту удобнее прислать возраст, чем дату рождения: точный день
    # мы всё равно не спрашиваем. Пересчитывается в birth_date на сервере.
    age: Optional[int] = Field(None, ge=16, le=99)
    city: Optional[str] = Field(None, max_length=100)
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    interests: Optional[list[str]] = None
    photos: Optional[list[str]] = None
    is_incognito: Optional[bool] = None
    hide_age: Optional[bool] = None
    hide_distance: Optional[bool] = None
    hide_from_visitors: Optional[bool] = None
    #: Пустая строка — «вернуть базовую схему», поэтому min_length не ставим.
    app_theme: Optional[str] = Field(None, max_length=24)
    looking_for: Optional[str] = Field(None, pattern="^(male|female|other|any)$")
    age_min: Optional[int] = Field(None, ge=16, le=99)
    age_max: Optional[int] = Field(None, ge=16, le=99)
    distance_max: Optional[int] = Field(None, ge=1, le=500)
    # Пустая строка — осознанное «сбросить», поэтому min_length не ставим.
    goal: Optional[str] = Field(None, max_length=32)
    subculture: Optional[str] = Field(None, max_length=32)
    # Тип связи («с кем») — как goal/subculture, без жёсткой валидации по
    # словарю: неизвестное значение просто не найдётся фильтром, а не 422.
    relation_type: Optional[str] = Field(None, max_length=32)
    filter_relation_type: Optional[str] = Field(None, max_length=32)
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
    # Валидация формата — на сервере (роутер), не здесь: юзер может прислать
    # "@name" или полную ссылку "https://t.me/name", и их надо сперва
    # ободрать до голого username, а Field(pattern=...) сырой ввод не чистит.
    tg_channel: Optional[str] = Field(None, max_length=100)


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
    #: "match" — взаимный лайк, "direct" — платное письмо без взаимности.
    #: Список чатов отличает их визуально (см. services/direct_messages.py).
    kind: str = "match"
    #: Кто написал первым в "direct"-беседе — своё письмо клиент показывает
    #: иначе, чем письмо от незнакомца.
    initiator_id: Optional[str] = None
    #: Ответил ли получатель на "direct"-письмо: пока False, инициатор не
    #: может отправить второе сообщение.
    direct_answered: bool = False

    # ── Огонёк общения ─────────────────────────────────────────────
    #: Сколько дней подряд уже общаются. Число получено из стрика на сервере,
    #: а не вычисляется клиентом — иначе часы и сетившие dev расходились бы.
    #: 0 — серии нет (общаемся только первым днём).
    streak_days: int = 0
    #: Эмодзи-уровень огонька: 🔥 (3+), ⚡ (10+), 💥 (30+), 🌟 (100+),
    #: 🏆 (200+). Клиент просто рисует — логика на сервере одна.
    streak_emoji: str = ""
    #: Сколько восстановлений осталось в текущем месяце у этой пары.
    streak_revives_left: int = 0
    #: Можно ли сейчас восстановить прогаревшую серию (после дня тишины):
    #: общее поле и для текста, и для видимости кнопки.
    streak_can_revive: bool = False
    #: Код последнего подарка, если этот платёж инициировал именно подарок.
    #: null — не показываем блок в UI, и не выводим в списке чатов напоминание.
    gift_code: Optional[str] = None


class DirectMessageRequest(BaseModel):
    """Написать человеку без взаимного лайка — платный крючок (см. Мимолёт)."""

    target_id: str
    text: str = Field(min_length=1, max_length=2000)


class DirectMessageResponse(BaseModel):
    match: MatchResponse


class DirectQuotaOut(BaseModel):
    """Остаток писем без взаимности на сегодня — для честного гейта в UI."""

    left: int = 0
    total: int = 0
    #: Тариф вовсе не позволяет — не вопрос лимита, а вопрос подписки.
    allowed: bool = False
    #: Название уровня, с которого фича открывается («Aurora»). Отдаём с
    #: сервера, а не пишем в клиенте словом: при переносе фичи на другой
    #: уровень зашитый текст молча остался бы врать.
    required_tier_name: str = ""


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
    #: Тип связи — показываем на карточке так же, как цель и субкультуру.
    relation_type: str = ""
    subculture: str = ""
    mbti: str = ""
    height_cm: Optional[int] = None
    #: Был в сети недавно. Не точное время, а флаг: «последний вход в 14:32» —
    #: это слежка, а «сейчас в сети» помогает решить, писать ли сегодня.
    #: Скрывшим себя (инкогнито, пауза) не показывается.
    is_online: bool = False
    #: Выбранная наклейка из коллекции — маленький знак характера на карточке.
    #: Путь к картинке собирает сервер (см. services/stickers.py).
    sticker: Optional[str] = None
    #: Код оформления карточки — рамка, заработанная коллекцией.
    decor: Optional[str] = None


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

class ReelForward(BaseModel):
    """Куда пересылаем ролик: в чат мэтча или в комнату. Одно из двух."""

    match_id: Optional[str] = None
    room_id: Optional[str] = None
    #: Подпись к пересылу. Лимит как у сообщения в комнате: один и тот же текст
    #: не должен проходить по одному пути и обрезаться по другому.
    text: str = Field(default="", max_length=500)


class ReelPreview(BaseModel):
    """Пересланный ролик внутри сообщения — и в личке, и в комнате.

    Одна схема на оба чата: разъехавшиеся превью пришлось бы разбирать на
    клиенте двумя ветками.
    """

    id: str
    video_url: str
    cover_url: str = ""
    caption: str = ""


class ReelReport(BaseModel):
    """Жалоба на ролик. Причины те же, что и у жалобы на анкету."""

    reason: str = Field(pattern="^(" + "|".join(REPORT_REASONS) + ")$")
    description: str = Field(default="", max_length=500)


class ReelCommentOut(BaseModel):
    """Комментарий под роликом вместе с автором."""

    id: str
    author_id: str
    author_name: str = ""
    author_photo: str = ""
    text: str
    is_mine: bool = False
    created_at: Optional[datetime] = None


class ReelComments(BaseModel):
    comments: list[ReelCommentOut] = Field(default_factory=list)


class ReelCommentSend(BaseModel):
    #: Короче, чем в личке: простыни под видео никто не читает.
    text: str = Field(min_length=1, max_length=300)


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
    comments_count: int = 0
    views_count: int = 0
    liked_by_me: bool = False
    is_mine: bool = False
    #: Снят с показа. Приходит только автору — в общей ленте таких нет.
    is_hidden: bool = False
    created_at: Optional[datetime] = None
    #: Сколько роликов автор уже опубликовал за последние 24 часа (для
    # светофора лимита на клиенте). Не секретно, автору видно.
    published_today: int = 0
    #: Порог для ежедневного лимита — нужен клиенту, иначе «закончилось»
    # он увидит только по 429, когда уже собрал кадры. Плохо.
    daily_limit: int = 0


class ReelsOut(BaseModel):
    """Страница ленты. `next_before` передаётся в следующий запрос."""

    reels: list[ReelOut] = Field(default_factory=list)
    next_before: Optional[str] = None


class SectionStat(BaseModel):
    """Один раздел в сводке. `users` важнее `opens`: один энтузиаст,
    открывший кейсы двести раз, не означает, что кейсы нужны продукту."""

    section: str
    users: int = 0
    opens: int = 0
    #: Какая доля людей вообще заходила в раздел.
    reach_percent: int = 0


class SectionStats(BaseModel):
    days: int = 30
    total_users: int = 0
    sections: list[SectionStat] = Field(default_factory=list)


class VoiceIceServers(BaseModel):
    """Параметры соединения для WebRTC. Отдаём с сервера: TURN-креденшелы
    меняются, а зашитые в бандл требовали бы пересборки приложения."""

    ice_servers: list[dict] = Field(default_factory=list)


class DailyCardOut(BaseModel):
    """Карта дня. Развлечение, а не предсказание — так и подписано на экране."""

    name: str
    meaning: str
    advice: str


class TarotCardOut(BaseModel):
    """Одна позиция расклада: название позиции + выпавшая карта."""

    position: str
    name: str
    meaning: str


class TarotSpreadOut(BaseModel):
    """Расклад целиком: карты + общая AI-интерпретация (либо заготовка).

    Развлечение, а не предсказание — дисклеймер обязателен в каждом ответе,
    иначе раздел легко читается как настоящее гадание.
    """

    spread: str
    title: str
    cards: list[TarotCardOut]
    interpretation: str
    disclaimer: str
    #: Открыты ли развёрнутые расклады на текущем тарифе. Едет вместе с картой
    #: дня, чтобы клиенту не приходилось выяснять это отдельным запросом:
    #: раньше он «пробовал» закрытый расклад ради 403 и из-за этого грузил
    #: карту дня дважды.
    spreads_open: bool = True
    #: Уровень, с которого расклады открываются. С сервера, а не словом в
    #: клиенте: фича уже переезжала между уровнями.
    required_tier_name: str = ""


class StickerOut(BaseModel):
    """Коллекционная наклейка.

    `image` собирает сервер: если папку с картинками однажды перенесут, фронт
    об этом не узнает и покажет битую картинку.
    """

    code: str
    title: str
    rarity: str
    rarity_title: str
    image: str
    #: Сколько раз выпала этому человеку. 0 — ещё нет в коллекции.
    owned: int = 0


class CaseRewardOut(BaseModel):
    """Награда из кейса. Шанс показываем честно: скрытые шансы — ровно то,
    за что гача-механики и не любят."""

    code: str
    title: str
    amount: int
    chance_percent: int
    #: Заполняется, только если выпала наклейка.
    sticker: Optional[StickerOut] = None


class CaseStateOut(BaseModel):
    left_today: int = 0
    per_day: int = 0
    rewards: list[CaseRewardOut] = Field(default_factory=list)


class CaseOpenResult(BaseModel):
    reward: CaseRewardOut
    left_today: int = 0
    per_day: int = 0
    boost_minutes: int = 30
    #: Такая наклейка уже была — вместо неё начислен суперлайк.
    duplicate: bool = False
    duplicate_superlikes: int = 0


class StickerCollectionOut(BaseModel):
    """Коллекция целиком: и собранные, и ещё не выпавшие.

    Показываем ВСЕ: пустые ячейки — половина смысла коллекции, без них не
    видно, что собирать.
    """

    stickers: list[StickerOut] = Field(default_factory=list)
    owned: int = 0
    total: int = 0
    #: Выбранная наклейка — её видят другие в анкете.
    selected: Optional[str] = None


class RoomOut(BaseModel):
    """Комната в списке."""

    id: str
    slug: str
    title: str
    description: str = ""
    city: str = ""
    #: Сообщений за сутки — по нему видно, где сейчас живо.
    messages_today: int = 0


class RoomsOut(BaseModel):
    rooms: list[RoomOut] = Field(default_factory=list)


class RoomMessageOut(BaseModel):
    id: str
    sender_id: str
    sender_name: str = ""
    sender_photo: str = ""
    text: str
    #: Пересланный ролик. Пусто у обычных сообщений и у роликов, снятых
    #: модерацией уже после пересыла.
    reel: Optional[ReelPreview] = None
    is_mine: bool = False
    created_at: Optional[datetime] = None


class RoomMessages(BaseModel):
    messages: list[RoomMessageOut] = Field(default_factory=list)
    next_before: Optional[str] = None


class RoomSend(BaseModel):
    #: Лимит короче, чем в личке: простыни в общем чате читать невозможно.
    text: str = Field(min_length=1, max_length=500)


class PhotoRatingTarget(BaseModel):
    """Чьё фото показать на оценку."""

    user_id: str
    display_name: str = ""
    photo: str


class PhotoRatingTargets(BaseModel):
    targets: list[PhotoRatingTarget] = Field(default_factory=list)


class PhotoRatingRequest(BaseModel):
    target_id: str
    #: Шкала 1–5, как у конкурента. Ноль означал бы «не оценил», а не оценку.
    score: int = Field(ge=1, le=5)


class MyPhotoRating(BaseModel):
    """Своя средняя оценка. `average=None` — оценок ещё нет."""

    photo: str = ""
    average: Optional[float] = None
    total: int = 0


class LeaderboardEntry(BaseModel):
    """Одна строка рейтинга."""

    place: int
    user_id: str
    display_name: str = ""
    photo: str = ""
    likes: int = 0
    is_me: bool = False


class LeaderboardOut(BaseModel):
    """Топ по лайкам за окно плюс своё место.

    `my_place_exact=false` — человек за пределами посчитанных мест: точный
    номер неизвестен, и выдумывать его нельзя.
    """

    window_days: int = 7
    #: Какой период реально посчитан — таб на клиенте подсвечивает его же
    period: str = "week"
    entries: list[LeaderboardEntry] = Field(default_factory=list)
    my_place: Optional[int] = None
    my_likes: int = 0
    my_place_exact: bool = False


class BoostOut(BaseModel):
    """Состояние буста показов."""

    active: bool = False
    until: Optional[datetime] = None
    #: Сколько минут даёт одно включение — для подписи на кнопке.
    minutes: int = 30
    #: Осталось включений сегодня.
    left_today: int = 0
    #: Сколько всего положено на уровне подписки.
    per_day: int = 0
    #: Имя уровня, который открывает буст — для подписи на кнопке, когда
    #: включений не положено вовсе. Клиент не должен писать его словом: гейт
    #: живёт в FEATURE_MIN_TIER, и зашитое имя соврёт после переноса фичи.
    required_tier_name: str = ""


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
    #: Период, за который посчитано ("today" | "week" | "all") — эхо запроса,
    #: чтобы клиент подсвечивал правильный таб.
    period: str = "all"


class PlanOut(BaseModel):
    """Один покупаемый вариант для витрины."""

    code: str
    tier: str
    title: str
    months: int
    price_rub: int
    price_per_month: int
    #: Цена за день. Ею длинный срок продаётся лучше всего: «4 ₽ в день»
    #: читается как мелочь, а «1290 ₽» — как крупная трата.
    price_per_day: int = 0
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
    #: Для подарка: ничего не отправляем — тогда обычная покупка себе.
    #: Если передан — это подарок, и создаётся код вместо начисления Premium.
    gift_recipient_id: Optional[str] = None


class IAPVerifyResponse(BaseModel):
    success: bool
    plan: str = "free"
    expires_at: str = ""
    # Транзакция уже была зачтена ранее — повторное начисление не произошло
    already_processed: bool = False
    #: Секрет подарочного кода, одноразовый. Не None только при
    # покупке-подарке: мы его не сохраняем plaintext, храним только хеш.
    gift_code: Optional[str] = None


# ════════════════════════════════════════════════════════════════
#  ТЕМА ЧАТА
# ════════════════════════════════════════════════════════════════

class ChatThemeOut(BaseModel):
    """Тема пары. `null` в цвете — «берём базовый токен интерфейса»."""
    match_id: str
    bubble_mine_color: Optional[str] = None
    bubble_theirs_color: Optional[str] = None
    background_color: Optional[str] = None
    pattern_key: Optional[str] = None


class ChatThemePreset(BaseModel):
    key: str
    name: str
    bubble_mine_color: str
    bubble_theirs_color: str
    background_color: str
    pattern_key: str
    min_tier: str
    #: Уровень подписки не позволяет выбрать. Показываем с замком, а не
    #: скрываем: непонятно, чего человек лишён, если темы не видно.
    locked: bool


class ChatThemePresets(BaseModel):
    presets: list[ChatThemePreset]
    tier: str
    #: Можно ли задавать произвольные цвета (уровень Plus и выше).
    custom_allowed: bool


class ChatThemeSet(BaseModel):
    """Либо `preset`, либо набор цветов. Оба сразу — 422."""
    preset: Optional[str] = Field(None, max_length=32)
    bubble_mine_color: Optional[str] = Field(None, max_length=7)
    bubble_theirs_color: Optional[str] = Field(None, max_length=7)
    background_color: Optional[str] = Field(None, max_length=7)
    pattern_key: Optional[str] = Field(None, max_length=16)


# ════════════════════════════════════════════════════════════════
#  ИСТОРИИ
# ════════════════════════════════════════════════════════════════

class StoryOut(BaseModel):
    id: str
    user_id: str
    display_name: str
    media_url: str
    caption: str
    audience: str
    created_at: datetime
    expires_at: datetime
    #: Просмотры отдаём только автору — чужой счётчик не его дело.
    views_count: Optional[int] = None
    seen: bool = False
    mine: bool = False


class StoryAuthorOut(BaseModel):
    user_id: str
    display_name: str
    avatar: Optional[str] = None
    count: int
    latest_at: datetime
    has_unseen: bool


class StoriesFeed(BaseModel):
    authors: list[StoryAuthorOut]
    #: Свои истории отдельным полем: в ленте они всегда первые, и
    #: клиенту не приходится выуживать себя из общего списка.
    mine: list[StoryOut]


class StoryViewerOut(BaseModel):
    user_id: str
    display_name: str
    avatar: Optional[str] = None
    viewed_at: datetime


class StoryViewers(BaseModel):
    viewers: list[StoryViewerOut]
    total: int


class StoryReplyTarget(BaseModel):
    """Куда клиенту идти с ответом на историю."""
    match_id: str
    #: Текст-затравка: цитировать нечего, история исчезнет, поэтому
    #: подставляем подпись или отметку о кадре.
    prefill: str


class DecorOut(BaseModel):
    code: str
    title: str
    #: Условие открытия человеческим языком.
    hint: str
    unlocked: bool
    #: Собрано из нужного. Оба нуля — условия по коллекции нет.
    have: int = 0
    need: int = 0


class DecorCollectionOut(BaseModel):
    decors: list[DecorOut] = Field(default_factory=list)
    #: Что надето сейчас. None — без рамки.
    selected: Optional[str] = None
    #: Наклеек в коллекции — то же число, что в условиях.
    stickers_owned: int = 0
