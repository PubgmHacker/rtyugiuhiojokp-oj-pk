"""Ежедневные задачи и привычки — возврат «на второй день».

Придумано не мной: это то, что делает Duolingo и Habitica, и это же дешёвый
способ держать приложение в привычке без дополнительного контента от нас.
Здесь это работает как направляющий каркас для общения: пишешь партнёру
каждый день — параллельно делаешь задачу.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.models import UserHabit


async def get_today_habits(session: AsyncSession, user_id: str) -> list[UserHabit]:
    """Список привычек на сегодня: сбрасываем счётчики ровно в полночь."""
    now = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    result = await session.execute(select(UserHabit).where(UserHabit.user_id == user_id))
    habits = list(result.scalars().all())
    # Обновляем все, у кого vëпрошлая дата меньше сегодняшней
    for h in habits:
        if h.counted_for_date < now:
            h.today_count = fade_daily_count(h, now)
    return habits


def fade_daily_count(habit: UserHabit, today: datetime) -> int:
    """Сколько «сегодня» осталось после того, как новый день наступил.
    Прогаревший день жестко сбрасывает прогресс, как в Habitica."""
    if habit.counted_for_date is None:
        return 0
    days_ago = (today - habit.counted_for_date).days
    # При сдвиге даты возвращаем 0 — ничего не запоминаем со вчера
    return 0 if days_ago > 0 else habit.today_count


async def create_habit(
    session: AsyncSession, user_id: str, name: str, target_per_day: int = 1
) -> UserHabit:
    """Создать простую привычку: цветная полоска в профиле, на которую виден
    сразу, если не сделана сегодня. Не плодим дубли по имени — оно в диалоге."""
    result = await session.execute(
        select(UserHabit).where(and_(UserHabit.user_id == user_id, UserHabit.name == name))
    )
    habit = result.scalar_one_or_none()
    if habit:
        return habit

    habit = UserHabit(user_id=user_id, name=name, target_per_day=target_per_day)
    session.add(habit)
    await session.flush()
    return habit


async def check_in_habit(
    session: AsyncSession, habit_id: str
) -> UserHabit:
    """Записать «сделано сегодня». Не даёт пропустить через их уповку."""
    habit = await session.get(UserHabit, habit_id)
    if not habit:
        raise ValueError("Привычка не найдена")

    today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

    if habit.counted_for_date < today:
        habit.today_count = 1
        habit.counted_for_date = today
    else:
        habit.today_count += 1

    await session.flush()
    return habit
