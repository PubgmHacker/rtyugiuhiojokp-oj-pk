"""Кейсы — бонус подписки, награды только для оформления анкеты.

Кейсов три — по одному на набор наклеек (services/cases.py: CASES). Человек
выбирает кейс и получает наклейку его набора; с небольшим шансом из любого
кейса выпадает обложка карточки. Расходников (суперлайков, бустов) здесь нет.

Попытки общие на все кейсы и не хранятся счётчиком: считаются как «положено
по уровню минус открыто с начала месяца». Счётчик пришлось бы обнулять по
расписанию, и пропущенный запуск открыл бы безлимит — тот же приём, что у
суперлайков и бустов.

Выбор всегда идёт среди того, чего у человека ещё нет: редкая месячная
попытка не имеет права сгорать на дубликат. Повтор возможен только у
полностью собранного набора (и всех обложек) — там он честно помечается
`duplicate`.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import and_, func, select
from sqlalchemy import text as sa_text
from sqlalchemy.ext.asyncio import AsyncSession

from database.connection import get_session
from middleware.auth import get_current_user
from models.models import CaseOpening, DecorOwned, Profile, StickerOwned, User
from models.schemas import (
    CaseOpenIn, CaseOpenResult, CaseOut, CaseRewardOut, CaseStateOut,
    DecorCollectionOut, DecorOut, StickerCollectionOut, StickerOut, StickerSetOut,
)
from services.cases import (
    CASES, REWARD_DECOR, REWARD_STICKER, REWARDS, Case, case_by_code,
    начало_месяца, начало_следующего_месяца, openings_per_month, roll,
)
from services.decor import (
    ОФОРМЛЕНИЯ, Оформление, безопасный_код, выпала as обложка_выпала, по_коду,
)
from services.plans import TIER_ORDER
from services.premium import current_tier
from services.stickers import (
    Наклейка, выпала as наклейка_выпала, каталог, набор, шансы_по_редкости,
)

#: Порядок редкостей от ценной к обычной — для превью на плитке кейса.
_РАНГ_РЕДКОСТИ = {"legend": 0, "epic": 1, "rare": 2, "common": 3}

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
        set=н.set,
        owned=owned,
    )


def _обложка_наружу(о: Оформление, unlocked: bool = False) -> DecorOut:
    return DecorOut(
        code=о.code,
        title=о.title,
        rarity=о.rarity,
        rarity_title=о.rarity_title,
        unlocked=unlocked,
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


def _доля_наклейки() -> float:
    """Какая часть открытий вообще приводит к наклейке.

    Нужна, чтобы шансы на плитке были абсолютными. `шансы_по_редкости`
    нормирует веса внутри набора и даёт «условно, если выпала наклейка»; для
    человека это ловушка — он читает «Легендарная 10%», а на деле их 8%,
    потому что в пятой части открытий приходит обложка. Перемножать две
    таблицы в уме гача не должна заставлять: складываем за него.
    """
    return next((r.chance for r in REWARDS if r.code == REWARD_STICKER), 1.0)


def _кейс_наружу(кейс: Case, мои: set[str]) -> CaseOut:
    """Плитка кейса: набор, прогресс по нему и несколько картинок-приманок.

    В превью — самые ценные наклейки набора: витрина показывает, ради чего
    открывать, а прогресс «N из M» — сколько ещё собирать.
    """
    наклейки = набор(кейс.code)
    превью = sorted(наклейки, key=lambda н: _РАНГ_РЕДКОСТИ.get(н.rarity, 9))[:4]
    return CaseOut(
        code=кейс.code,
        title=кейс.title,
        hint=кейс.hint,
        accent=кейс.accent,
        total=len(наклейки),
        owned=sum(1 for н in наклейки if н.code in мои),
        preview=[н.image for н in превью],
        rarity_chances={
            р: round(доля * _доля_наклейки(), 1)
            for р, доля in шансы_по_редкости(кейс.code).items()
        },
    )


async def _мои_коды_наклеек(session: AsyncSession, user_id: str) -> set[str]:
    result = await session.execute(
        select(StickerOwned.code).where(StickerOwned.user_id == user_id)
    )
    return set(result.scalars().all())


def _минимальный_тариф() -> str:
    """Первый уровень, которому положены попытки, — для подписи на замке.

    Вычисляется из квот, а не зашит словом: фичи уже переезжали между
    уровнями, и зашитое имя соврало бы после переноса.
    """
    for имя in TIER_ORDER:
        if openings_per_month(имя):
            return имя
    return ""


async def _openings_left(session: AsyncSession, user_id: str, tier: str) -> int:
    since = начало_месяца(datetime.now(timezone.utc))
    result = await session.execute(
        select(func.count(CaseOpening.id)).where(and_(
            CaseOpening.user_id == user_id,
            CaseOpening.created_at >= since,
        ))
    )
    return max(0, openings_per_month(tier) - (result.scalar() or 0))


@router.get("", response_model=CaseStateOut)
async def get_case_state(
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """Сколько попыток осталось в этом месяце, какие кейсы есть и что в них."""
    tier = await current_tier(session, user.id)
    мои = await _мои_коды_наклеек(session, user.id)
    return CaseStateOut(
        left=await _openings_left(session, user.id, tier),
        per_month=openings_per_month(tier),
        resets_at=начало_следующего_месяца(datetime.now(timezone.utc)),
        rewards=_showcase(),
        cases=[_кейс_наружу(к, мои) for к in CASES],
        required_tier_name=_минимальный_тариф(),
    )


@router.post("/open", response_model=CaseOpenResult)
async def open_case(
    data: CaseOpenIn,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """Открыть выбранный кейс и записать выпавшее в коллекцию."""
    tier = await current_tier(session, user.id)
    per_month = openings_per_month(tier)
    if not per_month:
        raise HTTPException(status_code=403, detail="Кейсы доступны с подпиской Plus")

    кейс = case_by_code(data.case.strip())
    if кейс is None:
        raise HTTPException(status_code=400, detail="Такого кейса нет")

    # Лимит «столько-то в месяц» считается запросом и тут же подтверждается
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
        raise HTTPException(
            status_code=429, detail="Попытки этого месяца закончились"
        )

    result = await session.execute(select(Profile).where(Profile.user_id == user.id))
    profile = result.scalar_one_or_none()
    if not profile:
        raise HTTPException(status_code=400, detail="Сначала заполните анкету")

    # Что уже собрано — от этого зависит и выбор награды, и защита от дублей
    result = await session.execute(
        select(StickerOwned).where(StickerOwned.user_id == user.id)
    )
    мои_наклейки = {с.code: с for с in result.scalars().all()}
    result = await session.execute(
        select(DecorOwned.code).where(DecorOwned.user_id == user.id)
    )
    мои_обложки = set(result.scalars().all())

    # Редкая месячная попытка не сгорает на «уже есть»: если выпавший тип
    # собран целиком, отдаём другой. Наклейка — только из набора этого кейса.
    # Дубликат остаётся только человеку с полным набором и всеми обложками —
    # и он помечается честно.
    хочу = roll().code
    выпавшая_наклейка: Наклейка | None = None
    выпавшая_обложка: Оформление | None = None
    дубликат = False

    if хочу == REWARD_DECOR:
        выпавшая_обложка = обложка_выпала(мои_обложки)
        if выпавшая_обложка is None:
            хочу = REWARD_STICKER

    if хочу == REWARD_STICKER and выпавшая_обложка is None:
        выпавшая_наклейка = наклейка_выпала(
            исключая=мои_наклейки, набор_код=кейс.code
        )
        if выпавшая_наклейка is None:
            # Набор собран — пробуем обложку, прежде чем сдаться
            выпавшая_обложка = обложка_выпала(мои_обложки)
            if выпавшая_обложка is None:
                выпавшая_наклейка = наклейка_выпала(набор_код=кейс.code)
                if выпавшая_наклейка is None:
                    # Каталог недоступен (папку не выложили). Отказ, а не
                    # молча съеденная попытка: до записи открытия не дошло
                    logger.error(f"Набор {кейс.code} пуст — кейс не открыть")
                    raise HTTPException(
                        status_code=503, detail="Награды временно недоступны"
                    )
                дубликат = True

    if выпавшая_обложка is not None:
        итог_код = REWARD_DECOR
        session.add(DecorOwned(user_id=user.id, code=выпавшая_обложка.code))
    else:
        assert выпавшая_наклейка is not None
        итог_код = REWARD_STICKER
        if дубликат:
            мои_наклейки[выпавшая_наклейка.code].count += 1
        else:
            session.add(StickerOwned(user_id=user.id, code=выпавшая_наклейка.code))

    награда = next(r for r in REWARDS if r.code == итог_код)
    session.add(CaseOpening(
        user_id=user.id,
        reward=(выпавшая_обложка or выпавшая_наклейка).code,
        amount=1,
    ))
    await session.flush()

    out = CaseOpenResult(
        reward=CaseRewardOut(
            code=итог_код,
            title=(выпавшая_обложка or выпавшая_наклейка).title,
            amount=1,
            chance_percent=round(награда.chance * 100),
            sticker=_наклейка_наружу(выпавшая_наклейка) if выпавшая_наклейка else None,
            decor=_обложка_наружу(выпавшая_обложка, unlocked=True)
            if выпавшая_обложка else None,
        ),
        case=кейс.code,
        duplicate=дубликат,
        left=await _openings_left(session, user.id, tier),
        per_month=per_month,
        resets_at=начало_следующего_месяца(datetime.now(timezone.utc)),
    )
    await session.commit()
    logger.info(
        f"Кейс открыт: user={user.id} case={кейс.code} reward={итог_код} "
        f"code={(выпавшая_обложка or выпавшая_наклейка).code}"
    )
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
        sets=[
            StickerSetOut(
                code=к.code,
                title=к.title,
                owned=sum(1 for н in все if н.set == к.code and н.code in моё),
                total=sum(1 for н in все if н.set == к.code),
            )
            for к in CASES
        ],
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


async def _обложки_у(session: AsyncSession, user_id: str) -> set[str]:
    """Коды обложек в коллекции человека."""
    result = await session.execute(
        select(DecorOwned.code).where(DecorOwned.user_id == user_id)
    )
    return set(result.scalars().all())


@router.get("/decor", response_model=DecorCollectionOut)
async def my_decor(
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """Витрина обложек: и свои, и ещё не выпавшие.

    Недостающие показываем всегда — обложка, о которой не знаешь, не
    мотивирует открывать кейсы. Это ровно тот же приём, что с пустыми
    ячейками в коллекции наклеек.
    """
    свои = await _обложки_у(session, user.id)

    result = await session.execute(select(Profile).where(Profile.user_id == user.id))
    profile = result.scalar_one_or_none()

    return DecorCollectionOut(
        decors=[_обложка_наружу(о, unlocked=о.code in свои) for о in ОФОРМЛЕНИЯ],
        selected=безопасный_код(profile.decor if profile else None),
        owned=sum(1 for о in ОФОРМЛЕНИЯ if о.code in свои),
        total=len(ОФОРМЛЕНИЯ),
    )


@router.post("/decor/select", response_model=DecorCollectionOut)
async def select_decor(
    data: dict,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """Надеть обложку. Пустой код — снять.

    Право проверяем здесь, а не на клиенте: чужая обложка, поставленная
    запросом мимо интерфейса, обесценила бы её у всех, кому она выпала.
    Проверка — владение, как у наклеек: обложки лимитированные и достаются
    только из кейса.
    """
    код = str(data.get("code") or "").strip()

    result = await session.execute(select(Profile).where(Profile.user_id == user.id))
    profile = result.scalar_one_or_none()
    if not profile:
        raise HTTPException(status_code=400, detail="Сначала заполните анкету")

    if код:
        if по_коду(код) is None:
            raise HTTPException(status_code=400, detail="Неизвестная обложка")
        if код not in await _обложки_у(session, user.id):
            raise HTTPException(status_code=403, detail="Этой обложки у вас нет")

    profile.decor = код or None
    await session.commit()

    return await my_decor(session=session, user=user)
