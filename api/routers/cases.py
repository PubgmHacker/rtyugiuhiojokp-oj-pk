"""Кейсы — бонус подписки.

Попытки не хранятся счётчиком: считаются как «положено по уровню минус открыто
за сутки». Счётчик пришлось бы обнулять по расписанию, и пропущенный запуск
открыл бы безлимит — тот же приём, что у суперлайков и бустов.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import and_, func, select
from sqlalchemy import text as sa_text
from sqlalchemy.ext.asyncio import AsyncSession

from database.connection import get_session
from middleware.auth import get_current_user
from models.models import CaseOpening, Profile, StickerOwned, User
from models.schemas import (
    CaseOpenResult, CaseRewardOut, CaseStateOut, StickerCollectionOut, StickerOut,
)
from services.cases import (
    REWARD_BOOST, REWARD_STICKER, REWARDS, Reward, REWARD_SUPERLIKE,
    openings_per_day, roll,
)
from services.stickers import (
    СУПЕРЛАЙК_ЗА_ДУБЛЬ, Наклейка, выпала as стикер_выпал, каталог,
)
from services.plans import BOOST_MINUTES
from services.premium import current_tier

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/cases", tags=["cases"])


def _наклейка_наружу(н: Наклейка, owned: int = 0) -> StickerOut:
    """Наклейка в виде, пригодном для клиента.

    Путь к картинке собираем на сервере: если папку однажды перенесут, фронт
    об этом не узнает и покажет битую картинку.
    """
    return StickerOut(
        code=н.code,
        title=н.title,
        rarity=н.rarity,
        rarity_title=н.rarity_title,
        image=н.image,
        owned=owned,
    )


def _showcase() -> list[CaseRewardOut]:
    """Витрина «что можно выиграть». Шансы показываем честно: скрытые шансы —
    ровно то, за что гача-механики и не любят."""
    return [
        CaseRewardOut(
            code=r.code,
            title=r.title,
            amount=r.amount,
            chance_percent=round(r.chance * 100),
        )
        for r in REWARDS
    ]


async def _openings_left(session: AsyncSession, user_id: str, tier: str) -> int:
    since = datetime.now(timezone.utc) - timedelta(days=1)
    result = await session.execute(
        select(func.count(CaseOpening.id)).where(and_(
            CaseOpening.user_id == user_id,
            CaseOpening.created_at >= since,
        ))
    )
    return max(0, openings_per_day(tier) - (result.scalar() or 0))


@router.get("", response_model=CaseStateOut)
async def get_case_state(
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """Сколько попыток осталось и что можно выиграть."""
    tier = await current_tier(session, user.id)
    return CaseStateOut(
        left_today=await _openings_left(session, user.id, tier),
        per_day=openings_per_day(tier),
        rewards=_showcase(),
    )


@router.post("/open", response_model=CaseOpenResult)
async def open_case(
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """Открыть кейс и начислить награду."""
    tier = await current_tier(session, user.id)
    per_day = openings_per_day(tier)
    if not per_day:
        raise HTTPException(status_code=403, detail="Кейсы доступны в Plus")

    # Лимит «столько-то в сутки» считается запросом и тут же подтверждается
    # записью. Без блокировки пять параллельных запросов успевают прочитать
    # «использовано 0» раньше, чем любой из них закоммитится, и оплаченная
    # одна попытка превращается в пять наград. Тот же приём, что для встречных
    # лайков в routers/likes.py
    await session.execute(
        sa_text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 0))"),
        {"k": f"dating:case:{user.id}"},
    )

    left = await _openings_left(session, user.id, tier)
    if not left:
        raise HTTPException(status_code=429, detail="Попытки на сегодня закончились")

    result = await session.execute(select(Profile).where(Profile.user_id == user.id))
    profile = result.scalar_one_or_none()
    if not profile:
        raise HTTPException(status_code=400, detail="Сначала заполните анкету")

    reward = roll()

    # Наклейка: выбираем конкретную по редкости и записываем в коллекцию.
    # Дубликат не оставляем пустым — за него идёт суперлайк, иначе повтор
    # ощущается как отобранная попытка
    выпавшая = None
    дубликат = False
    if reward.code == REWARD_STICKER:
        выпавшая = стикер_выпал()
        if выпавшая is None:
            # Каталог недоступен (папка не выложена) — не отнимаем попытку
            # молча, отдаём полезную награду вместо коллекционной
            logger.error("Каталог наклеек пуст, выдаю суперлайк вместо наклейки")
            reward = Reward(REWARD_SUPERLIKE, 1, reward.chance, "1 суперлайк")
        else:
            result = await session.execute(
                select(StickerOwned).where(and_(
                    StickerOwned.user_id == user.id,
                    StickerOwned.code == выпавшая.code,
                ))
            )
            уже_есть = result.scalar_one_or_none()
            if уже_есть:
                уже_есть.count += 1
                дубликат = True
                profile.bonus_superlikes += СУПЕРЛАЙК_ЗА_ДУБЛЬ
            else:
                session.add(StickerOwned(user_id=user.id, code=выпавшая.code))

    if reward.code == REWARD_STICKER:
        pass
    elif reward.code == REWARD_BOOST:
        # Продлеваем от текущего окончания, а не с нуля: иначе выпавшие минуты
        # сожгли бы уже действующий буст
        now = datetime.now(timezone.utc)
        base = profile.boost_until if (profile.boost_until and profile.boost_until > now) else now
        profile.boost_until = base + timedelta(minutes=reward.amount)
    else:
        profile.bonus_superlikes += reward.amount

    session.add(CaseOpening(
        user_id=user.id,
        reward=выпавшая.code if выпавшая else reward.code,
        amount=reward.amount,
    ))
    await session.flush()

    out = CaseOpenResult(
        reward=CaseRewardOut(
            code=reward.code,
            title=выпавшая.title if выпавшая else reward.title,
            amount=reward.amount,
            chance_percent=round(reward.chance * 100),
            sticker=_наклейка_наружу(выпавшая) if выпавшая else None,
        ),
        duplicate=дубликат,
        duplicate_superlikes=СУПЕРЛАЙК_ЗА_ДУБЛЬ if дубликат else 0,
        left_today=await _openings_left(session, user.id, tier),
        per_day=per_day,
        boost_minutes=BOOST_MINUTES,
    )
    await session.commit()
    logger.info(f"Кейс открыт: user={user.id} reward={reward.code} amount={reward.amount}")
    return out


@router.get("/stickers", response_model=StickerCollectionOut)
async def my_stickers(
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """Коллекция целиком: и собранные, и ещё не выпавшие.

    Показываем ВСЕ наклейки, а не только свои: пустые ячейки — половина смысла
    коллекции, без них не видно, что собирать и сколько осталось.
    """
    result = await session.execute(
        select(StickerOwned).where(StickerOwned.user_id == user.id)
    )
    моё = {с.code: с.count for с in result.scalars().all()}

    result = await session.execute(select(Profile).where(Profile.user_id == user.id))
    profile = result.scalar_one_or_none()

    все = каталог()
    return StickerCollectionOut(
        stickers=[_наклейка_наружу(н, моё.get(н.code, 0)) for н in все],
        owned=len(моё),
        total=len(все),
        selected=profile.sticker if profile else None,
    )


@router.post("/stickers/select", response_model=StickerCollectionOut)
async def select_sticker(
    data: dict,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """Выбрать наклейку для анкеты. Пустой код — снять выбор.

    Ставить можно только свою: иначе любой поставил бы легендарную, не открыв
    ни одного кейса, и коллекция потеряла бы смысл.
    """
    код = str(data.get("code") or "").strip()

    result = await session.execute(select(Profile).where(Profile.user_id == user.id))
    profile = result.scalar_one_or_none()
    if not profile:
        raise HTTPException(status_code=400, detail="Сначала заполните анкету")

    if код:
        result = await session.execute(
            select(StickerOwned).where(and_(
                StickerOwned.user_id == user.id,
                StickerOwned.code == код,
            ))
        )
        if result.scalar_one_or_none() is None:
            raise HTTPException(status_code=403, detail="Этой наклейки у вас нет")

    profile.sticker = код or None
    await session.commit()

    return await my_stickers(session=session, user=user)
