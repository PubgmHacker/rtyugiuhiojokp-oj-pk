"""Жалоба на единицу контента: ролик, историю, сообщение комнаты, комментарий.

App Store (Guideline 1.2, UGC) требует, чтобы пожаловаться можно было на
каждую поверхность с чужим контентом — не только на анкету. Механизм один
для всех поверхностей, поэтому живёт в сервисе, а не копируется по роутерам:
разъехавшиеся копии означали бы, что порог снятия и антифлуд у историй и
комментариев со временем начнут отличаться молча.

Жалоба ложится в общую таблицу Report — модератор разбирает всё в одной
очереди. Какой именно контент смотреть, кодируется меткой в description
(`reel:{id}`, `story:{id}`, `roommsg:{id}`, `reelcomment:{id}`): отдельное
поле ради этого заводить незачем, а по метке же считается дедупликация
и порог снятия.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.models import Report

#: Жалоб в час от одного человека — на все виды контента разом. Общий лимит
#: по пути в middleware тут не работает: id стоит в середине пути, а правила
#: подбираются по префиксу. Жалоба ведёт к снятию контента с показа, поэтому
#: спам ею бесплатным быть не должен.
МАКС_ЖАЛОБ_В_ЧАС = 10


async def подать_жалобу_на_контент(
    session: AsyncSession,
    *,
    reporter_id: str,
    author_id: str,
    reason: str,
    description: str,
    метка: str,
    порог: int,
) -> bool:
    """Записать жалобу; True — порог разных жалобщиков достигнут.

    Вызывающий по True снимает контент с показа (is_hidden) и коммитит:
    сервис не знает, какая таблица прячется за меткой, и знать не должен.

    Повторная жалоба того же человека на тот же контент — тихий успех без
    новой записи: накрутить порог с одного аккаунта нельзя, а сообщать
    жалобщику «вы уже жаловались» незачем.
    """
    # Антифлуд: считаем жалобы автора за час по всей таблице, а не по метке —
    # спамер, размазывающий жалобы по разным роликам, тоже должен упереться
    час_назад = datetime.now(timezone.utc) - timedelta(hours=1)
    result = await session.execute(
        select(func.count(Report.id)).where(and_(
            Report.reporter_id == reporter_id,
            Report.created_at >= час_назад,
        ))
    )
    if (result.scalar() or 0) >= МАКС_ЖАЛОБ_В_ЧАС:
        raise HTTPException(status_code=429, detail="Слишком много жалоб подряд")

    # Одна жалоба от человека на единицу контента
    result = await session.execute(
        select(Report.id).where(and_(
            Report.reporter_id == reporter_id,
            Report.reported_id == author_id,
            Report.description.like(f"{метка}%"),
        ))
    )
    уже_было = result.scalar_one_or_none() is not None
    if not уже_было:
        session.add(Report(
            reporter_id=reporter_id,
            reported_id=author_id,
            reason=reason,
            # Метка контента — в начале описания: модератору нужно знать,
            # что именно смотреть, и по ней же считается порог
            description=f"{метка} {description}".strip()[:1000],
        ))
        await session.flush()

    result = await session.execute(
        select(func.count(func.distinct(Report.reporter_id))).where(and_(
            Report.reported_id == author_id,
            Report.description.like(f"{метка}%"),
        ))
    )
    return (result.scalar() or 0) >= порог
