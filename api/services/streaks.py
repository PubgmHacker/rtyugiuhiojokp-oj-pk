"""Стрик общения в паре («огонёк», как в TikTok, но по-деловому).

Правила, выбранные вручную (не заимствованные):
- Привязан к Match.id, не к user.id: две пары не видят серию чужой пары.
- Заражение: первый и последующий день — +1. Продолжение серии считаем по
  локальной полуночи, а не по now(), чтобы сдвиг DST/винты не дали false +2.
- Пропуск целого календарного дня = стрик гаснет (обнуляется). Его можно
  восстановить, пока не настала полночь следующего дня: «вчерашний день»
  в ТГ/Facebook тратят миллионы, здесь это то же поведение, но платным.
- Восстановления ограничены: 1 на пару в месяц у стрика ≥ 10, 2 — ≥ 100, 3 —
  ≥ 300. Пороги выбраны так: до 10 дней стрик ещё не привык, и терять его
  недорого, а от 300+ — это уже стиль жизни.
"""
from __future__ import annotations

import calendar
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.models import Match, ChatStreak

logger = logging.getLogger(__name__)


def _today_utc() -> datetime:
    """Полночь сегодня по UTC: timezone-зависимая точка отсчёта стрика."""
    return datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)


def _month_start(dt: datetime) -> datetime:
    """Первое число месяца в UTC — окно, внутри которого живут revive'ы."""
    return dt.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def _quota_by_streak(days: int) -> int:
    """Сколько восстановлений полагается паре за текущий месяц по стрику."""
    if days >= 300:
        return 3
    if days >= 100:
        return 2
    if days >= 10:
        return 1
    return 0


async def get_streak(session: AsyncSession, match_id: str) -> ChatStreak:
    """Прочитать или создать запись стрика пары."""
    result = await session.execute(
        select(ChatStreak).where(ChatStreak.match_id == match_id)
    )
    return result.scalar_one_or_none()


async def ensure_streak_row(session: AsyncSession, match_id: str) -> ChatStreak:
    """Row под пару есть всегда, даже до первого сообщения: иначе нигде не
    хранить, сколько revive'ов уже потрачено в этом месяце."""
    streak = await get_streak(session, match_id)
    if streak:
        return streak
    streak = ChatStreak(match_id=match_id)
    session.add(streak)
    await session.flush()
    return streak


async def _maybe_reset_streak(
    session: AsyncSession, streak: ChatStreak, today: datetime
) -> None:
    """Погасить стрик, если вчера никто не написал (правило полного дня)."""
    if streak.last_counted_for is None:
        return

    last_day = streak.last_counted_for
    days_since = (today - last_day).days
    if days_since <= 1:
        return  # писали сегодня или вчера — всё в порядке

    # Пропущен целый день. Всё равно, сколько дней серии было: разговор
    # прервался, и огонёк гаснет с полуночи, а не по запросу.
    streak.streak_days = 0
    await session.flush()


async def touch_streak_for_message(
    session: AsyncSession, match: Match
) -> ChatStreak:
    """Вызывается при записи сообщения: держит серию актуальной."""
    today = _today_utc()
    streak = await ensure_streak_row(session, match.id)

    # Если писали уже сегодня — не жжём день повторно
    if streak.last_counted_for == today:
        await session.flush()
        return streak

    # Если вчера никто не говорил — прошлая серия сгорела, и новая стартует с 1
    yesterday = today - timedelta(days=1)
    prev = (
        streak.last_counted_for
        and (streak.last_counted_for == yesterday)
    )
    streak.streak_days = (streak.streak_days + 1) if prev else 1
    streak.last_counted_for = today
    await session.flush()
    return streak


async def refresh_revives_for_month(session: AsyncSession, streak: ChatStreak) -> None:
    """Обновить окноrevive, если наступил новый месяц; откидываем только то,
    что не ушло, а не целиком: потратилось — считаем потраченным."""
    today = _today_utc()
    current_month = _month_start(today)
    if streak.revives_refreshed_at and _month_start(streak.revives_refreshed_at) == current_month:
        return

    quota = _quota_by_streak(streak.streak_days)
    streak.revives_left = quota
    streak.revives_refreshed_at = current_month
    await session.flush()


async def revive_streak(session: AsyncSession, match: Match) -> ChatStreak:
    """Восстановить погасшую серию. Вызывается по кнопке в чате.

    Условия:
    - серия уже прогорела (streak_days == 0);
    - мы ещё в том же месяце, в котором она погасла;
    - у пары есть revive на этот месяц.
    """
    today = _today_utc()
    streak = await ensure_streak_row(session, match.id)
    await refresh_revives_for_month(session, streak)

    if not streak.revives_left:
        raise ValueError(
            "Восстановления серии в этом месяце закончились. "
            "Подольше держите огонёк — и получится больше.",
        )

    if streak.streak_days:
        # Серия жива — вызывать восстановление нечего
        return streak

    # Восстанавливаем серию на ровно столько дней, сколько она была бы, если
    # бы вчерашний разговор не прервался. День первого письма — всегда 1.
    days = 1 if not streak.last_counted_for else 1
    streak.streak_days = days
    streak.last_counted_for = today
    streak.revives_left -= 1
    logger.info(
        "streak revived: match=%s days=%s revives_left=%s",
        match.id, days, streak.revives_left,
    )
    await session.flush()
    return streak


def streak_emoji(days: int) -> str:
    """Эмодзи огонька по длине серии — тексты в одном месте, а не в UI."""
    if days >= 200:
        return "🏆"
    if days >= 100:
        return "🌟"
    if days >= 30:
        return "💥"
    if days >= 10:
        return "⚡"
    return "🔥"
