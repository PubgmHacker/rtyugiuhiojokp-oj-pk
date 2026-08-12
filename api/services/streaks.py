"""Серия общения в паре — огонёк, который жалко потерять.

Механика взята у TikTok и Duolingo, потому что она работает: считаем не
сообщения, а ДНИ, в которые пара переписывалась. Пропустил день — серия
сгорела. Сгоревшую можно оживить 1–3 раза в месяц, и чем длиннее была
серия, тем больше попыток — за длинную серию человек держится сильнее,
и терять её из-за одной командировки обидно до удаления приложения.

Ключевой инвариант: живая серия держит `burnt_from_days = 0` и
`burnt_at = NULL`. Сгоревшая переносит длину в `burnt_from_days`,
ставит `burnt_at` и обнуляет `streak_days`. Восстановление читает
`burnt_from_days` — именно поэтому длину и запоминаем, иначе оживление
возвращало бы серию к одному дню, то есть продавало бы ничто.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.models import ChatStreak
from services.public_profile import в_utc

# Дольше месяца сгоревшую серию не оживляем: к этому моменту это уже не
# «серия», а воспоминание, и восстанавливать её — обманывать обоих.
REVIVE_WINDOW_DAYS = 31


def _today_utc() -> datetime:
    """Начало сегодняшних UTC-суток. Границу дня держим одну для всех,
    иначе пара в разных часовых поясах спорила бы, сгорел ли день."""
    return datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)


def _month_start(moment: datetime) -> datetime:
    """Начало месяца, к которому относится момент."""
    return moment.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def _quota_by_streak(days: int) -> int:
    """Сколько восстановлений в месяц даёт серия такой длины.

    Пороги растут вместе с ценностью серии: за 300 дней переписки не
    жалко дать три попытки, за 10 — одну, короче десяти дней терять
    почти нечего.
    """
    if days >= 300:
        return 3
    if days >= 100:
        return 2
    if days >= 10:
        return 1
    return 0


def streak_emoji(days: int) -> str:
    """Иконка серии. Меняется на порогах, чтобы прогресс был виден
    глазом, а не только цифрой рядом."""
    if days >= 200:
        return "🏆"
    if days >= 100:
        return "🌟"
    if days >= 30:
        return "💥"
    if days >= 10:
        return "⚡"
    return "🔥"


async def get_streak(session: AsyncSession, match_id: str) -> ChatStreak | None:
    """Прочитать серию пары и привести её к сегодняшнему дню.

    Именно здесь вызывается сгорание: раньше сброс жил в функции,
    которую никто не звал, и огонёк показывал вчерашнее значение до
    первого нового сообщения. Читаем — значит показываем правду.
    """
    result = await session.execute(select(ChatStreak).where(ChatStreak.match_id == match_id))
    streak = result.scalar_one_or_none()
    if streak is None:
        return None

    _maybe_reset_streak(streak)
    refresh_revives_for_month(streak)
    return streak


async def ensure_streak_row(session: AsyncSession, match_id: str) -> ChatStreak:
    """Взять строку серии или создать её. На новой строке квота
    восстановлений нулевая — серии ещё нет, оживлять нечего."""
    result = await session.execute(select(ChatStreak).where(ChatStreak.match_id == match_id))
    streak = result.scalar_one_or_none()
    if streak is None:
        streak = ChatStreak(match_id=match_id, streak_days=0, revives_left=0)
        session.add(streak)
        await session.flush()
    return streak


def _maybe_reset_streak(streak: ChatStreak) -> None:
    """Сжечь серию, если пропущен целый день.

    Считаем разрыв в сутках от последнего зачтённого дня. Ноль — день
    уже зачтён, единица — вчера писали, серия жива и ждёт сегодняшнего
    сообщения. Два и больше — между последним днём и сегодняшним лежит
    полный день молчания, серия сгорает.

    Длину перед обнулением сохраняем: без неё восстановление не имеет
    что восстанавливать.

    Время из базы читаем только через `в_utc`: Postgres отдаёт aware, а
    SQLite — naive, и прямое вычитание падает TypeError в обработчике
    запроса. Список чатов ложился целиком именно здесь.
    """
    if streak.last_counted_for is None or streak.streak_days <= 0:
        return

    последний = в_utc(streak.last_counted_for)
    gap_days = (_today_utc() - последний).days
    if gap_days < 2:
        return

    streak.burnt_from_days = streak.streak_days
    streak.burnt_at = последний + timedelta(days=1)
    streak.streak_days = 0


def refresh_revives_for_month(streak: ChatStreak) -> None:
    """Начислить месячную квоту восстановлений, если она ещё не выдана.

    `revives_refreshed_at = NULL` означает «не выдавалась ни разу» — до
    правки колонка имела `server_default=now()`, из-за чего первый же
    вызов считал текущий месяц обработанным и выходил, а `revives_left`
    навсегда оставался нулём. Квоту считаем по ЖИВОЙ длине серии, а
    если серия уже сгорела — по запомненной: иначе после сброса квота
    всегда выходила нулевой и оживить было нечем.
    """
    now = datetime.now(timezone.utc)
    current_month = _month_start(now)

    if streak.revives_refreshed_at is not None:
        if _month_start(в_utc(streak.revives_refreshed_at)) >= current_month:
            return

    reference_days = streak.streak_days if streak.streak_days > 0 else streak.burnt_from_days
    streak.revives_left = _quota_by_streak(reference_days)
    streak.revives_refreshed_at = now


async def touch_streak_for_message(session: AsyncSession, match_id: str) -> ChatStreak:
    """Зачесть сегодняшний день паре. Вызывается на каждое сообщение.

    Второе сообщение за день ничего не добавляет — считаем дни, не
    активность, иначе серию можно было бы накрутить болтливостью.
    """
    streak = await ensure_streak_row(session, match_id)
    _maybe_reset_streak(streak)

    today = _today_utc()

    if streak.last_counted_for is None:
        streak.streak_days = 1
    else:
        gap_days = (today - в_utc(streak.last_counted_for)).days
        if gap_days == 0:
            refresh_revives_for_month(streak)
            await session.flush()
            return streak
        if gap_days == 1:
            streak.streak_days += 1
        else:
            # Сюда попадаем только если серия была нулевой (иначе её
            # сжёг _maybe_reset_streak) — начинаем заново.
            streak.streak_days = 1

    streak.last_counted_for = today
    # День зачтён — серия снова живая, память о сгорании больше не нужна.
    streak.burnt_from_days = 0
    streak.burnt_at = None

    refresh_revives_for_month(streak)
    await session.flush()
    return streak


def can_revive(streak: ChatStreak | None) -> bool:
    """Можно ли оживить серию прямо сейчас: она сгорела, сгорела
    недавно, и попытки в этом месяце ещё остались."""
    if streak is None or streak.burnt_from_days <= 0 or streak.burnt_at is None:
        return False
    if streak.streak_days > 0:
        return False
    if streak.revives_left <= 0:
        return False
    return (datetime.now(timezone.utc) - в_utc(streak.burnt_at)).days <= REVIVE_WINDOW_DAYS


async def revive_streak(session: AsyncSession, match_id: str) -> ChatStreak:
    """Оживить сгоревшую серию, вернув её прежнюю длину.

    Возвращаем именно `burnt_from_days` — то, что было. Раньше здесь
    стояло `days = 1 if not streak.last_counted_for else 1`: обе ветки
    давали единицу, и серия на 200 дней восстанавливалась в один день.

    Пропущенные дни не докручиваем: восстановление возвращает то, что
    было, а не выдаёт бонус за молчание. `last_counted_for` ставим на
    вчера — серия жива и ждёт сегодняшнего сообщения.
    """
    streak = await ensure_streak_row(session, match_id)
    _maybe_reset_streak(streak)
    refresh_revives_for_month(streak)

    if streak.burnt_from_days <= 0 or streak.burnt_at is None:
        raise ValueError("Серия не сгорела — восстанавливать нечего")
    if streak.streak_days > 0:
        raise ValueError("Серия уже активна")
    if streak.revives_left <= 0:
        raise ValueError("Восстановления на этот месяц закончились")
    if (datetime.now(timezone.utc) - в_utc(streak.burnt_at)).days > REVIVE_WINDOW_DAYS:
        raise ValueError("Серия сгорела слишком давно — её уже не вернуть")

    streak.streak_days = streak.burnt_from_days
    streak.last_counted_for = _today_utc() - timedelta(days=1)
    streak.revives_left -= 1
    streak.burnt_from_days = 0
    streak.burnt_at = None

    await session.flush()
    return streak
