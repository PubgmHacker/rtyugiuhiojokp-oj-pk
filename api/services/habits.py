"""Задачи на день — план, который ведут не выходя из переписки.

Механика Habitica и Duolingo: людям нравится улучшать себя, а не
заполнять анкету. Здесь это каркас для общения — пишешь партнёру, а
план дня идёт параллельно, и повод открыть приложение завтра
появляется сам, без нового контента от нас.

Граница дня — UTC-полночь, одна на весь сервис (та же, что у серии
общения в services/streaks.py): две разные границы дали бы задачу,
сгоревшую по одному правилу и живую по другому.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.models import UserHabit
from services.public_profile import в_utc

#: Больше — и план дня превращается в список, который не выполняют, а
#: пролистывают. Ограничение продуктовое, а не техническое.
MAX_HABITS = 12


class ЛимитПривычек(ValueError):
    """Больше задач в день человеку не нужно."""


def _today_utc() -> datetime:
    """Начало сегодняшних UTC-суток."""
    return datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )


def прогресс_на_сегодня(habit: UserHabit) -> int:
    """Сколько отметок у задачи ЗА СЕГОДНЯ.

    Чистая функция вместо правки объекта в GET: раньше список гасил
    вчерашние счётчики прямо в ORM-объектах без commit'а — запись,
    которая ничего не пишет, и лишний риск уехать в базу вместе с
    чужим commit'ом в том же сеансе.
    """
    if habit.counted_for_date is None:
        return 0
    return habit.today_count if в_utc(habit.counted_for_date) >= _today_utc() else 0


async def list_habits(session: AsyncSession, user_id: str) -> list[UserHabit]:
    """Задачи человека в порядке создания: план дня читается сверху вниз,
    и произвольный порядок в нём выглядит сбоем."""
    result = await session.execute(
        select(UserHabit)
        .where(UserHabit.user_id == user_id)
        .order_by(UserHabit.created_at)
    )
    return list(result.scalars().all())


async def create_habit(
    session: AsyncSession, user_id: str, name: str, target_per_day: int = 1
) -> UserHabit:
    """Создать задачу. Название придумывает человек: «позвонить маме»
    работает только тогда, когда это его формулировка, а не наша.

    Дубли по имени не плодим — вернём существующую: две одинаковые
    строки в плане дня человек считает багом, а не двумя задачами.
    """
    result = await session.execute(
        select(UserHabit).where(and_(
            UserHabit.user_id == user_id, UserHabit.name == name
        ))
    )
    habit = result.scalar_one_or_none()
    if habit:
        return habit

    result = await session.execute(
        select(func.count(UserHabit.id)).where(UserHabit.user_id == user_id)
    )
    if (result.scalar() or 0) >= MAX_HABITS:
        raise ЛимитПривычек(f"Больше {MAX_HABITS} задач за раз не ведём")

    habit = UserHabit(
        user_id=user_id,
        name=name,
        target_per_day=target_per_day,
        today_count=0,
        counted_for_date=_today_utc(),
    )
    session.add(habit)
    await session.flush()
    return habit


async def check_in_habit(session: AsyncSession, habit: UserHabit) -> UserHabit:
    """Отметить «сделано». Несколько раз в день — норма, а не ошибка:
    вода, которую пьют трижды, и считается трижды.

    Принимаем объект, а не id: владельца проверяет вызывающий, и
    повторная загрузка внутри давала бы шанс отметить чужое.
    """
    today = _today_utc()
    if habit.counted_for_date is None or в_utc(habit.counted_for_date) < today:
        habit.today_count = 1
        habit.counted_for_date = today
    else:
        habit.today_count += 1
    await session.flush()
    return habit


async def uncheck_habit(session: AsyncSession, habit: UserHabit) -> UserHabit:
    """Снять последнюю отметку. Промах по кнопке в плане дня — обычное
    дело, и без отмены человек остаётся с неправдой в списке."""
    today = _today_utc()
    if habit.counted_for_date is None or в_utc(habit.counted_for_date) < today:
        habit.today_count = 0
        habit.counted_for_date = today
    else:
        habit.today_count = max(0, habit.today_count - 1)
    await session.flush()
    return habit


async def delete_habit(session: AsyncSession, habit: UserHabit) -> None:
    """Удалить задачу. Право уйти из плана — базовое: список, из
    которого нельзя вычеркнуть, перестают открывать целиком."""
    await session.delete(habit)
    await session.flush()
