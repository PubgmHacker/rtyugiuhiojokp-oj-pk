"""Суточные лимиты бесплатного уровня: лайки и открытые мэтчи.

Числа живут в `services/plans.py` — здесь только подсчёт по базе. Считаем по
таблицам, а не по счётчику в Redis, по той же причине, по которой так сделана
квота суперлайков: лимит — это предмет продажи, и его расход не имеет права
теряться вместе с кешем. Сброс кеша не должен выдавать человеку второй десяток
лайков, а падение Redis — отбирать оплаченный безлимит.

Окно скользящее (`LIMIT_WINDOW_HOURS`), поэтому «подождать до завтра» на
практике означает «первый лайк вернётся через сутки после первого израсходован-
ного». Клиенту отдаём точное время возврата, чтобы шторка лимита не врала.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import and_, func, select, text as sa_text
from sqlalchemy.ext.asyncio import AsyncSession

from models.models import Like, MatchView
from services.plans import (
    LIMIT_WINDOW_HOURS,
    is_unlimited,
    likes_per_day,
    match_views_per_day,
)
from services.premium import current_tier


def _начало_окна() -> datetime:
    return datetime.now(timezone.utc) - timedelta(hours=LIMIT_WINDOW_HOURS)


@dataclass(frozen=True)
class QuotaState:
    """Состояние одного суточного лимита.

    `limit` = -1 и `unlimited` = True — платный уровень; `left` в этом случае
    не имеет смысла и равен -1, чтобы клиент не нарисовал «осталось 0».
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
    """Итог попытки открыть мэтч: разрешение отдельно от состояния квоты.

    Раньше `open_match` возвращал одно `QuotaState`, и «пустили или нет»
    вызывающий выводил из `exhausted`. Это два разных факта: последнее
    открытие внутри лимита (третье из трёх) проходит и оставляет `left = 0`,
    то есть выглядит как отказ. Человек платил за три мэтча, а получал два —
    и точно так же ломался повторный вход в уже открытый чат, когда квота
    была потрачена: слот не тратится, а состояние всё равно `exhausted`.

    `state` — состояние ПОСЛЕ записи: на нём строится «осталось N».
    """

    granted: bool
    state: QuotaState


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
    return QuotaState(
        limit, used, max(0, limit - used), False, _плюс_окно(самый_старый)
    )


# ── Открытые мэтчи ──────────────────────────────────────────────
#
# Поправки «этот лайк уже учтён» здесь нет намеренно. Оба места, где лимит
# лайков спрашивают, всё равно читают прежний `Like` — им он нужен для самой
# записи (`routers/likes.py`, `bot/database/connection.like_and_match`), и
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
    return QuotaState(
        limit, used, max(0, limit - used), False, _плюс_окно(самый_старый)
    )


async def open_match(
    session: AsyncSession, user_id: str, match_id: str, tier: Optional[str] = None
) -> MatchOpen:
    """Открыть мэтч и записать это в квоту.

    Возвращает `MatchOpen`: `granted = False` — открывать нельзя, запись не
    сделана. Идемпотентно: мэтч, уже открытый в этом окне, не тратит слот и
    только обновляет отметку.

    Решение отдаётся отдельным полем, а не выводится из `state.exhausted`:
    открытие, потратившее последний слот, разрешено — см. `MatchOpen`.

    Личный advisory-lock обязателен: без него два одновременных открытия читают
    «использовано 2 из 3» и оба проходят, то есть платный лимит раздаётся
    бесплатно. Порядок захвата — тот же личный ключ, что в `routers/likes.py`
    (`dating:likes:<id>`), и только он: брать здесь второй лок было бы новым
    порядком захвата, а это классический дедлок со встречным запросом.
    """
    уровень = await _tier(session, user_id, tier)
    if is_unlimited(match_views_per_day(уровень)):
        return MatchOpen(True, QuotaState(match_views_per_day(уровень), 0, -1, True, None))

    # Быстрый путь БЕЗ лока: мэтч уже открыт в текущем окне. Это самый частый
    # случай — каждое чтение переписки и каждая отправка проходят через
    # open_match, — а xact-лок держится до конца транзакции, то есть до конца
    # обработчика: с локом два параллельных запроса одного человека в один чат
    # выполнялись бы строго по очереди. Гонки здесь нет: повторное открытие
    # ничего не тратит, а запись в окне может только продлиться.
    result = await session.execute(
        select(MatchView).where(
            and_(MatchView.user_id == user_id, MatchView.match_id == match_id)
        )
    )
    просмотр = result.scalar_one_or_none()
    if просмотр is not None and _в_окне(просмотр.viewed_at):
        return MatchOpen(True, await match_views_state(session, user_id, уровень))

    await session.execute(
        sa_text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 0))"),
        {"k": f"dating:likes:{user_id}"},
    )

    # Перечитываем под локом: пока мы его брали, параллельный запрос мог
    # открыть этот же мэтч — тогда слот уже потрачен и тратить второй нельзя
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

    Нужен списку чатов: показ списка не должен тратить суточные открытия,
    иначе один заход в список сжигал бы всю квоту.
    """
    уровень = await _tier(session, user_id, tier)
    if is_unlimited(match_views_per_day(уровень)):
        return False
    if match_id in await opened_match_ids(session, user_id):
        return False
    return (await match_views_state(session, user_id, уровень)).exhausted


def _в_окне(момент: Optional[datetime]) -> bool:
    """Попадает ли отметка в текущее окно.

    Приведение к aware обязательно: Postgres отдаёт время с зоной, а запись,
    вставленная без неё (бэкфилл, миграция, чужой драйвер), сравнивается с
    aware-границей через TypeError — то есть 500 на открытии чата. Ровно на
    таком сравнении в этом проекте уже роняли начисление буста.
    """
    if момент is None:
        return False
    if момент.tzinfo is None:
        момент = момент.replace(tzinfo=timezone.utc)
    return момент >= _начало_окна()


def _плюс_окно(момент: Optional[datetime]) -> Optional[datetime]:
    """Когда вернётся слот, потраченный в `момент`. Копия bot/services/quotas.py."""
    if момент is None:
        return None
    if момент.tzinfo is None:
        момент = момент.replace(tzinfo=timezone.utc)
    return момент + timedelta(hours=LIMIT_WINDOW_HOURS)
