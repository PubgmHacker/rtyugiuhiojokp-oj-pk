"""Привычки и задачи — возвращение становится частью дня, а не дейтинга.

Каркас для общения: пишешь партнёру, пока план дня идёт параллельно.
Выгода обоюдная — и вовлечение, и продвижение в чат, без просадки
болтливости.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from database.connection import get_session
from middleware.auth import get_current_user
from models.models import User, UserHabit
from services.habits import (
    MAX_HABITS, ЛимитПривычек, check_in_habit, create_habit, delete_habit,
    list_habits, прогресс_на_сегодня, uncheck_habit,
)

router = APIRouter(prefix="/habits", tags=["habits"])


class HabitCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    #: Сколько раз за день считается выполнением. Больше десяти — уже не
    #: задача, а счётчик, и полоска прогресса перестаёт читаться.
    target_per_day: int = Field(default=1, ge=1, le=10)


class HabitOut(BaseModel):
    id: str
    name: str
    target_per_day: int
    today_count: int
    #: Норма на сегодня закрыта. Считает сервер: клиентов трое (веб, iOS,
    #: бот), и формула, размноженная по ним, разъедется.
    done_today: bool


class HabitsOut(BaseModel):
    habits: list[HabitOut]
    #: Отдаём лимит, чтобы клиент прятал кнопку «добавить» заранее, а не
    #: показывал ошибку после набранного текста.
    limit: int


def _out(habit: UserHabit) -> HabitOut:
    count = прогресс_на_сегодня(habit)
    return HabitOut(
        id=habit.id,
        name=habit.name,
        target_per_day=habit.target_per_day,
        today_count=count,
        done_today=count >= habit.target_per_day,
    )


async def _своя(session: AsyncSession, habit_id: str, user_id: str) -> UserHabit:
    """Достать задачу, убедившись, что она этого человека.

    Владельца проверяем ДО любой записи: раньше `check_in_habit`
    успевал сдвинуть счётчик чужой задачи, и 403 приходил уже после.

    404 на чужую задачу, а не 403: существование чужой записи — тоже
    сведения, и подбором id их получать не следует.
    """
    habit = await session.get(UserHabit, habit_id)
    if habit is None or habit.user_id != user_id:
        raise HTTPException(status_code=404, detail="Задача не найдена")
    return habit


@router.get("", response_model=HabitsOut)
async def list_my_habits(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """План на сегодня. Вчерашний прогресс гасится в ответе, не в базе."""
    habits = await list_habits(session, user.id)
    return HabitsOut(habits=[_out(h) for h in habits], limit=MAX_HABITS)


@router.post("", response_model=HabitOut)
async def new_habit(
    data: HabitCreate,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Завести задачу."""
    name = data.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="Название не может быть пустым")

    try:
        habit = await create_habit(session, user.id, name, data.target_per_day)
    except ЛимитПривычек as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    await session.commit()
    return _out(habit)


@router.post("/{habit_id}/check", response_model=HabitOut)
async def check_habit(
    habit_id: str,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Отметить «сделано сегодня»."""
    habit = await _своя(session, habit_id, user.id)
    habit = await check_in_habit(session, habit)
    await session.commit()
    return _out(habit)


@router.post("/{habit_id}/uncheck", response_model=HabitOut)
async def uncheck(
    habit_id: str,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Снять последнюю отметку — промах по кнопке."""
    habit = await _своя(session, habit_id, user.id)
    habit = await uncheck_habit(session, habit)
    await session.commit()
    return _out(habit)


@router.delete("/{habit_id}", status_code=204)
async def remove_habit(
    habit_id: str,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Убрать задачу из плана."""
    habit = await _своя(session, habit_id, user.id)
    await delete_habit(session, habit)
    await session.commit()
    return Response(status_code=204)
