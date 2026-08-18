"""Суточные лимиты бесплатного уровня в боте: лайки и открытые мэтчи.

Копия `api/services/quotas.py` — бот отдельный сервис в отдельном venv и
импортировать код API не может (та же причина, что у `services/plans.py`).
Имена функций держим те же, чтобы расхождение читалось глазами. Числа берём
из `services/plans.py`, здесь только подсчёт по базе.

Зачем лимит нужен и в боте: свайпы в боте пишут лайки напрямую через
`database/connection.like_and_match`, минуя HTTP API. Лимит, проверяемый
только в API, обходился бы кнопкой «❤️» в чате с ботом — то есть не
существовал бы.

Считаем по таблицам, а не по счётчику в Redis: лимит — это предмет продажи, и
его расход не имеет права теряться вместе с кешем. Сброс кеша не должен
выдавать второй десяток лайков, а падение Redis — отбирать оплаченный безлимит.

Функции принимают открытую сессию: и лайк, и открытие мэтча обязаны считать
квоту внутри той же транзакции, под тем же advisory-локом, что и сама запись.
Считать отдельной сессией значило бы читать «использовано» до лока — ровно та
гонка, от которой лок и защищает.

Окно скользящее (`LIMIT_WINDOW_HOURS`), а не календарные сутки: часового пояса
пользователя у нас нет, а «в полночь по Москве» для половины базы неправда.
Поэтому наружу отдаём точное время возврата слота.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import and_, func, or_, select, text as sa_text
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import Like, MatchView, Subscription
from services.plans import (
    LIMIT_WINDOW_HOURS,
    TIER_FREE,
    is_unlimited,
    likes_per_day,
    match_views_per_day,
    tier_from_plan,
)


def _начало_окна() -> datetime:
    return datetime.now(timezone.utc) - timedelta(hours=LIMIT_WINDOW_HOURS)


@dataclass(frozen=True)
class QuotaState:
    """Состояние одного суточного лимита. Копия api/services/quotas.py.

    `limit` = -1 и `unlimited` = True — платный уровень; `left` в этом случае
    не имеет смысла и равен -1, чтобы текст не сказал «осталось 0».
    """

    limit: int
    used: int
    left: int
    unlimited: bool
    reset_at: Optional[datetime]

    @property
    def exhausted(self) -> bool:
        return not self.unlimited and self.left <= 0


@dataclass(frozen=True)
class MatchOpen:
    """Итог попытки открыть мэтч. Копия api/services/quotas.py.

    Разрешение отдельно от состояния квоты: раньше `open_match` возвращал одно
    `QuotaState`, и «пустили или нет» вызывающий выводил из `exhausted`. Это
    два разных факта — открытие, потратившее последний слот, проходит и
    оставляет `left = 0`, то есть выглядит как отказ. Третий мэтч из трёх
    приходил под замком, и точно так же ломался повторный вход в уже открытый
    чат при потраченной квоте: слот не тратится, а состояние `exhausted`.

    `state` — состояние ПОСЛЕ записи: на нём строится «осталось N».
    """

    granted: bool
    state: QuotaState


async def current_tier(session: AsyncSession, user_id: str) -> str:
    """Действующий уровень подписки внутри уже открытой сессии.

    Аналог `api/services/premium.current_tier`, включая семантику истечения:
    просроченная запись — это `free`, иначе человек платил бы один раз.

    Своя реализация, а не `database.get_active_subscription`: та открывает
    собственную сессию, а внутри транзакции с захваченным локом это второе
    соединение из пула на тот же запрос — при полном пуле бот встал бы сам на
    себе. Читаем `plan` через `tier_from_plan`, ровно как API: иначе легаси
    `plan="premium"` дал бы в боте 10 лайков, а в мини-аппе безлимит.
    """
    result = await session.execute(
        select(Subscription.plan).where(
            and_(
                Subscription.user_id == user_id,
                or_(
                    Subscription.expires_at.is_(None),
                    Subscription.expires_at > datetime.now(timezone.utc),
                ),
            )
        )
    )
    return tier_from_plan(result.scalars().first())


async def _tier(session: AsyncSession, user_id: str, tier: Optional[str]) -> str:
    return tier if tier is not None else await current_tier(session, user_id)


# ── Лайки ───────────────────────────────────────────────────────

def _counted_likes(user_id: str, since: datetime):
    """Что считается расходом лайка.

    Пропуск не считается: лимит на «👎» превратил бы его в запрет листать
    деку. Суперлайк считается — это тоже лайк, и у него сверху есть своя
    отдельная квота.
    """
    return and_(
        Like.liker_id == user_id,
        Like.type != "pass",
        Like.created_at >= since,
    )


async def likes_state(
    session: AsyncSession, user_id: str, tier: Optional[str] = None
) -> QuotaState:
    limit = likes_per_day(await _tier(session, user_id, tier))
    if is_unlimited(limit):
        return QuotaState(limit, 0, -1, True, None)

    since = _начало_окна()
    result = await session.execute(
        select(func.count(Like.id), func.min(Like.created_at)).where(
            _counted_likes(user_id, since)
        )
    )
    used, самый_старый = result.one()
    used = used or 0
    reset_at = _плюс_окно(самый_старый)
    return QuotaState(limit, used, max(0, limit - used), False, reset_at)


# ── Открытые мэтчи ──────────────────────────────────────────────
#
# Поправки «этот лайк уже учтён» здесь нет намеренно. Оба места, где лимит
# лайков спрашивают, всё равно читают прежний `Like` — им он нужен для самой
# записи (`database/connection.like_and_match`, `api/routers/likes.py`), и
# проверка стоит там же, под тем же локом. Отдельная функция рядом была третьей
# копией того же правила, которую никто не звал: разъехаться с обоими
# вызывающими она могла молча, а поймать это было бы нечем.

async def opened_match_ids(session: AsyncSession, user_id: str) -> set[str]:
    """Мэтчи, открытые в текущем окне. Они остаются доступными до конца окна."""
    result = await session.execute(
        select(MatchView.match_id).where(
            and_(MatchView.user_id == user_id, MatchView.viewed_at >= _начало_окна())
        )
    )
    return set(result.scalars().all())


async def match_views_state(
    session: AsyncSession, user_id: str, tier: Optional[str] = None
) -> QuotaState:
    limit = match_views_per_day(await _tier(session, user_id, tier))
    if is_unlimited(limit):
        return QuotaState(limit, 0, -1, True, None)

    since = _начало_окна()
    result = await session.execute(
        select(func.count(MatchView.id), func.min(MatchView.viewed_at)).where(
            and_(MatchView.user_id == user_id, MatchView.viewed_at >= since)
        )
    )
    used, самый_старый = result.one()
    used = used or 0
    reset_at = _плюс_окно(самый_старый)
    return QuotaState(limit, used, max(0, limit - used), False, reset_at)


async def open_match(
    session: AsyncSession, user_id: str, match_id: str, tier: Optional[str] = None
) -> MatchOpen:
    """Открыть мэтч и записать это в квоту.

    Возвращает `MatchOpen`: `granted = False` — открывать нельзя, запись не
    сделана. Идемпотентно: мэтч, уже открытый в этом окне, слот не тратит и
    только обновляет отметку — иначе выход и повторный вход в тот же чат съедал
    бы квоту, и три мэтча превращались бы в три нажатия.

    Решение отдаётся отдельным полем, а не выводится из `state.exhausted`:
    открытие, потратившее последний слот, разрешено — см. `MatchOpen`.

    Личный advisory-lock обязателен: без него два одновременных открытия читают
    «использовано 2 из 3» и оба проходят, то есть платное раздаётся бесплатно.
    Ключ и порядок — те же, что в API (`dating:likes:<id>`), и только он:
    второй лок здесь означал бы новый порядок захвата, а это классический
    дедлок со встречным запросом. Тот же ключ раньше берёт и `like_and_match`.
    """
    уровень = await _tier(session, user_id, tier)
    if is_unlimited(match_views_per_day(уровень)):
        return MatchOpen(True, QuotaState(match_views_per_day(уровень), 0, -1, True, None))

    await session.execute(
        sa_text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 0))"),
        {"k": f"dating:likes:{user_id}"},
    )

    result = await session.execute(
        select(MatchView).where(
            and_(MatchView.user_id == user_id, MatchView.match_id == match_id)
        )
    )
    просмотр = result.scalar_one_or_none()
    сейчас = datetime.now(timezone.utc)

    if просмотр is not None and _в_окне(просмотр.viewed_at):
        # Уже открыт в этом окне — бесплатно, слот не тратим
        return MatchOpen(True, await match_views_state(session, user_id, уровень))

    состояние = await match_views_state(session, user_id, уровень)
    if состояние.exhausted:
        return MatchOpen(False, состояние)

    if просмотр is None:
        session.add(MatchView(user_id=user_id, match_id=match_id, viewed_at=сейчас))
    else:
        # Запись за пределами окна: продлеваем, а не создаём вторую — пара
        # (user_id, match_id) уникальна
        просмотр.viewed_at = сейчас
    await session.flush()
    return MatchOpen(True, await match_views_state(session, user_id, уровень))


async def match_locked(
    session: AsyncSession, user_id: str, match_id: str, tier: Optional[str] = None
) -> bool:
    """Закрыт ли мэтч прямо сейчас — без записи в квоту.

    Нужен списку мэтчей: показ списка не должен тратить суточные открытия,
    иначе один заход в список сжигал бы всю квоту.
    """
    уровень = await _tier(session, user_id, tier)
    if is_unlimited(match_views_per_day(уровень)):
        return False
    if match_id in await opened_match_ids(session, user_id):
        return False
    return (await match_views_state(session, user_id, уровень)).exhausted


async def limits_summary(session: AsyncSession, user_id: str) -> dict:
    """Оба лимита разом — для текстов бота («осталось N лайков»).

    Уровень читаем один раз и передаём дальше: два независимых вызова
    сходили бы за подпиской дважды на каждое сообщение.
    """
    уровень = await current_tier(session, user_id)
    лайки = await likes_state(session, user_id, уровень)
    мэтчи = await match_views_state(session, user_id, уровень)
    return {
        "tier": уровень,
        "likes": лайки,
        "matches": мэтчи,
        "free": уровень == TIER_FREE,
    }


def _в_окне(момент: Optional[datetime]) -> bool:
    """Попадает ли отметка в текущее окно.

    Приведение к aware обязательно: Postgres отдаёт время с зоной, а записи,
    вставленные без неё, сравниваются с aware-границей через TypeError. Ровно
    на таком сравнении в этом проекте уже роняли начисление буста.
    """
    if момент is None:
        return False
    if момент.tzinfo is None:
        момент = момент.replace(tzinfo=timezone.utc)
    return момент >= _начало_окна()


def _плюс_окно(момент: Optional[datetime]) -> Optional[datetime]:
    """Когда вернётся слот, потраченный в `момент`."""
    if момент is None:
        return None
    if момент.tzinfo is None:
        момент = момент.replace(tzinfo=timezone.utc)
    return момент + timedelta(hours=LIMIT_WINDOW_HOURS)
