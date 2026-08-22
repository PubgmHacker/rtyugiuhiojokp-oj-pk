from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from database.connection import get_session
from middleware.auth import get_current_user
from models.models import User, Report
from models.schemas import ReportRequest, ReportResponse
from services.enforcement import ban_user_for_violation
from services.report_notify import notify_report_outcome
from services.notifications import записать_уведомление

router = APIRouter(prefix="/report", tags=["report"])


@router.post("", response_model=ReportResponse)
async def create_report(
    data: ReportRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Жалоба на пользователя (App Store requirement)."""
    if data.reported_id == user.id:
        raise HTTPException(status_code=400, detail="Cannot report yourself")

    result = await session.execute(select(User).where(User.id == data.reported_id))
    target = result.scalar_one_or_none()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")

    # Check duplicate report
    result = await session.execute(
        select(Report).where(and_(
            Report.reporter_id == user.id,
            Report.reported_id == data.reported_id,
            Report.status == "pending",
        ))
    )
    existing = result.scalar_one_or_none()
    if existing:
        return ReportResponse(success=True, message="Report already submitted")

    report = Report(
        reporter_id=user.id,
        reported_id=data.reported_id,
        reason=data.reason,
        description=data.description,
    )
    session.add(report)
    await session.flush()

    # Эскалация по числу РАЗНЫХ жалобщиков (одного зациклить нельзя):
    # 3+ — профиль скрывается из выдачи до решения модератора,
    # 5+ — автобан. Полный бан руками — в админке.
    #
    # В счёт идут только жалобы от тех, кто реально пересекался с целью
    # (лайк в любую сторону или мэтч). Без этого пять свежесозданных
    # Telegram-аккаунтов банили любого пользователя за секунды, ни разу
    # не открыв его анкету — дешёвая и полностью автоматизируемая атака.
    from sqlalchemy import or_
    from models.models import Profile, Like, Match

    interacted = (
        select(Like.liker_id)
        .where(and_(Like.liked_id == data.reported_id, Like.liker_id == Report.reporter_id))
        .exists()
    )
    liked_by_target = (
        select(Like.liked_id)
        .where(and_(Like.liker_id == data.reported_id, Like.liked_id == Report.reporter_id))
        .exists()
    )
    matched = (
        select(Match.id)
        .where(or_(
            and_(Match.user1_id == data.reported_id, Match.user2_id == Report.reporter_id),
            and_(Match.user2_id == data.reported_id, Match.user1_id == Report.reporter_id),
        ))
        .exists()
    )

    # Забираем сами id, а не COUNT: те же жалобщики получат ответ о том, чем
    # их жалоба закончилась (services/report_notify.py)
    result = await session.execute(
        select(Report.reporter_id)
        .where(
            and_(
                Report.reported_id == data.reported_id,
                Report.status == "pending",
                or_(interacted, liked_by_target, matched),
            )
        )
        .distinct()
    )
    reporter_ids = list(result.scalars().all())
    distinct_reporters = len(reporter_ids)

    # Итог рассылаем на ПЕРЕХОДЕ через порог, а не при каждой жалобе выше него:
    # иначе шестая жалоба прислала бы «аккаунт заблокирован» предыдущим пятерым
    # по второму разу, а вместе с ней и бот повторил бы бан-уведомление цели
    итог = ""

    if distinct_reporters >= 5:
        if not target.is_banned:
            # Через общий ban_user_for_violation, а не флагом руками: он держит
            # весь бан целиком — память банов (переживает удаление аккаунта),
            # отзыв токенов (иначе жертва харассмента продолжает получать
            # сообщения через уже открытый сокет обидчика) и уведомление цели
            # в Telegram. И он же не даёт автоматике снести админа: пять
            # сговорившихся аккаунтов не должны блокировать команду
            if await ban_user_for_violation(
                session, target, "автобан по жалобам", category="reports"
            ):
                итог = "banned"
    elif distinct_reporters >= 3:
        result = await session.execute(
            select(Profile).where(Profile.user_id == data.reported_id)
        )
        reported_profile = result.scalar_one_or_none()
        if reported_profile:
            reported_profile.is_incognito = True  # скрыт из деки до ревью модератором
        if distinct_reporters == 3:
            итог = "hidden"
    await session.flush()

    if итог:
        # В центр уведомлений — каждому жаловавшемуся, в этой же сессии:
        # бот-сообщение живёт только у Telegram-входа, пуш — только в
        # нативке, а лента доступна всем и не теряется
        for reporter_id in reporter_ids:
            await записать_уведомление(
                session, reporter_id, "report_outcome", {"outcome": итог}
            )
        await notify_report_outcome(reporter_ids, итог)

    return ReportResponse(success=True, message="Report submitted. Thank you for keeping our community safe.")
