"""Привычки и задачи — делаем возвращение частью дня, не из дейтинга.

По Habitica людям себя нравится улучшать, а не строить анкету. Здесь это
работает как направляющий каркас: пишешь партнёру, пока параллельно прогресс
идёт. Выгода обоюдная: и вовлечение, и продвижение в чат — без просадки
болтливости.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from database.connection import get_session
from middleware.auth import get_current_user
from models.models import UserHabit, User
from services.habits import get_today_habits, create_habit, check_in_habit

router = APIRouter(prefix="/habits", tags=["habits"])


class HabitCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    target_per_day: int = 1


class HabitOut(BaseModel):
    """Простая привычка с прогрессом на сегодня. Ключи здесь по-русски читают
    же, поэтому пустые строки не скрываем, а пишем как `null`."""
    id: str
    name: str
    target_per_day: int
    today_count: int


@router.get("")
async def list_habits(
    user=Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Список привычек на сегодня — уже сброшенных в полночь."""
    habits = await get_today_habits(session, user.id)
    return {"habits": [HabitOut(
        id=h.id, name=h.name, target_per_day=h.target_per_day, today_count=h.today_count,
    ) for h in habits]}


@router.post("")
async def new_habit(
    data: HabitCreate,
    user=Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> HabitOut:
    """Завести привычку. Название вводит человек: «позвонить маме» имеет
    силу только когда её придумал он сам."""
    habit = await create_habit(session, user.id, data.name.strip(), data.target_per_day)
    await session.commit()
    return HabitOut(
        id=habit.id, name=habit.name,
        target_per_day=habit.target_per_day, today_count=habit.today_count,
    )


@router.post("/{habit_id}/check")
async def check_habit(
    habit_id: str,
    user=Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> HabitOut:
    """Отметить «сделано сегодня». Несколько раз в день — норма, а не
    ошибка: вода, которую пьют трижды, также считается трижды."""
    try:
        habit = await check_in_habit(session, habit_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    if habit.user_id != user.id:
        raise HTTPException(status_code=403, detail="Не ваша привычка")
    await session.commit()
    return HabitOut(
        id=habit.id, name=habit.name,
        target_per_day=habit.target_per_day, today_count=habit.today_count,
    )
