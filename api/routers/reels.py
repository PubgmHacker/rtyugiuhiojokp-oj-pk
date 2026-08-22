"""Видео-лента (reels) — второй формат знакомства помимо свайпов.

Модерация: разбирать видео на кадры на сервере значило бы тащить ffmpeg в
образ, поэтому кадры присылает клиент — не один, а несколько, снятых на
разных таймкодах (10/50/90% длительности). Так модерация видит начало,
середину и конец ролика, а не только специально подобранный первый кадр.
Каждый кадр проходит ту же модерацию, что и обложка фото профиля; средний
кадр становится обложкой ролика в ленте. Без кадров ролик не публикуется —
иначе в ленту попадёт что угодно непроверенным.

Лимит публикаций суточный и считается по времени создания, а не счётчиком:
счётчик пришлось бы обнулять по расписанию, а пропущенный запуск открыл бы
безлимит.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import (
    APIRouter, Depends, File, Form, HTTPException, Query, Response, UploadFile,
)
from sqlalchemy import and_, delete, desc, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from database.connection import get_session
from middleware.auth import get_current_user
from models.models import (
    Block, Match, Profile, Reel, ReelComment, ReelLike,
    Room, RoomMessage, User,
)
from models.schemas import (
    ContentReport,
    ReelCommentOut,
    ReelComments,
    ReelCommentSend,
    ReelForward,
    ReelOut,
    ReelsOut,
)
from routers.rooms import check_flood
from services.ai_moderation import log_moderation, moderate_image, moderate_text
from services.enforcement import enforce_text_verdict, register_content_strike
from services.content_reports import подать_жалобу_на_контент
from services.chat_delivery import (
    REEL_FALLBACK_TEXT, ДоставкаОтклонена, fan_out, save_message,
)
from services.image_sanitizer import ImageRejected, sanitize_image
from services.public_profile import публичный_возраст
from services.r2_storage import delete_photo_from_r2, upload_photo_to_r2
from utils import as_list

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/reels", tags=["reels"])

#: Больше — и лента превращается в файлообменник, а R2 в статью расходов.
MAX_VIDEO_BYTES = 50 * 1024 * 1024
#: Сколько роликов можно опубликовать за сутки.
DAILY_LIMIT = 3
#: Меньше — и модерация снова видит только один подобранный кадр, как обложка
#: раньше: начало ролика может быть безобидным, а нарушение — дальше по видео.
MIN_COVERS = 3
#: Что принимаем. Проверяем и заголовок, и сигнатуру файла: заголовок клиент
#: подставляет любой.
ALLOWED_VIDEO = {
    "video/mp4": "mp4",
    "video/quicktime": "mov",
    "video/webm": "webm",
}


def _looks_like_video(data: bytes) -> bool:
    """Сигнатура контейнера. Переименованный архив не должен пройти как видео.

    MP4 и MOV — ISO BMFF: на 4-м байте лежит 'ftyp'. WebM — Matroska с EBML.
    """
    if len(data) < 12:
        return False
    if data[4:8] == b"ftyp":
        return True
    return data[:4] == b"\x1a\x45\xdf\xa3"


async def _to_out(
    session: AsyncSession, reel: Reel, viewer_id: str
) -> ReelOut:
    result = await session.execute(select(Profile).where(Profile.user_id == reel.user_id))
    profile = result.scalar_one_or_none()

    result = await session.execute(
        select(ReelLike.id).where(and_(
            ReelLike.reel_id == reel.id, ReelLike.user_id == viewer_id
        ))
    )
    liked = result.scalar_one_or_none() is not None

    # Возраст — через общий помощник: он уважает hide_age. Своя копия формулы
    # здесь как раз и отдавала возраст мимо настройки
    age = публичный_возраст(profile)

    return ReelOut(
        id=reel.id,
        author_id=reel.user_id,
        author_name=profile.display_name if profile else "",
        author_age=age,
        author_photo=(as_list(profile.photos)[0] if profile and as_list(profile.photos) else ""),
        video_url=reel.video_url,
        cover_url=reel.cover_url,
        caption=reel.caption,
        likes_count=reel.likes_count,
        comments_count=reel.comments_count,
        views_count=reel.views_count,
        liked_by_me=liked,
        is_mine=reel.user_id == viewer_id,
        is_hidden=reel.is_hidden,
        created_at=reel.created_at,
        published_today=(
            await _published_today(session, reel.user_id)
            if reel.user_id == viewer_id else 0
        ),
        daily_limit=DAILY_LIMIT if reel.user_id == viewer_id else 0,
    )


@router.get("", response_model=ReelsOut)
async def list_reels(
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
    limit: int = Query(default=10, ge=1, le=30),
    before: Optional[str] = Query(default=None, description="ISO-время последнего показанного"),
):
    """Лента: свежие сверху, скрытые модерацией не показываются.

    Заблокированные в обе стороны исключены: жертва харассмента не должна
    видеть обидчика и в видео-ленте тоже.
    """
    result = await session.execute(select(Block.blocked_id).where(Block.blocker_id == user.id))
    hidden_authors = {row[0] for row in result.all()}
    result = await session.execute(select(Block.blocker_id).where(Block.blocked_id == user.id))
    hidden_authors |= {row[0] for row in result.all()}

    conditions = [
        Reel.is_hidden == False,  # noqa: E712
        User.is_banned == False,  # noqa: E712
        # Инкогнито и пауза убирают из ленты и ролики: иначе платная настройка
        # прячет анкету из деки, а видео с тем же лицом и именем остаётся
        # на виду — обещание «вас не видят» не выполнено.
        # NULL при outer join означает «анкеты нет», а не «скрыт»:
        # без is_(None) такой ролик молча выпал бы из ленты.
        or_(Profile.is_incognito.is_(None), Profile.is_incognito == False),  # noqa: E712
        or_(Profile.is_paused.is_(None), Profile.is_paused == False),  # noqa: E712
    ]
    if before:
        try:
            conditions.append(Reel.created_at < datetime.fromisoformat(before))
        except ValueError:
            raise HTTPException(status_code=400, detail="Некорректный параметр before")

    result = await session.execute(
        select(Reel)
        .join(User, Reel.user_id == User.id)
        # Анкета нужна только ради проверки инкогнито — outer join, чтобы
        # ролик без заполненной анкеты не выпал из ленты молча
        .outerjoin(Profile, Profile.user_id == Reel.user_id)
        .where(and_(*conditions))
        .order_by(desc(Reel.created_at))
        # Берём с запасом: часть отсеется по блокировкам уже здесь
        .limit(limit * 2)
    )
    reels = [r for r in result.scalars().all() if r.user_id not in hidden_authors][:limit]

    return ReelsOut(
        reels=[await _to_out(session, r, user.id) for r in reels],
        next_before=reels[-1].created_at.isoformat() if reels else None,
    )


@router.get("/mine", response_model=ReelsOut)
async def list_my_reels(
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """Свои ролики, включая снятые с показа: иначе автор решит, что загрузка
    не сработала, и загрузит то же самое снова."""
    result = await session.execute(
        select(Reel).where(Reel.user_id == user.id).order_by(desc(Reel.created_at))
    )
    reels = list(result.scalars().all())
    return ReelsOut(
        reels=[await _to_out(session, r, user.id) for r in reels],
        next_before=None,
    )


async def _published_today(session: AsyncSession, user_id: str) -> int:
    since = datetime.now(timezone.utc) - timedelta(days=1)
    result = await session.execute(
        select(func.count(Reel.id)).where(and_(
            Reel.user_id == user_id, Reel.created_at >= since
        ))
    )
    return result.scalar() or 0


@router.post("", response_model=ReelOut, status_code=201)
async def create_reel(
    video: UploadFile = File(...),
    covers: list[UploadFile] = File(
        ..., description="Кадры с разных таймкодов видео — их и модерируем"
    ),
    caption: str = Form(default=""),
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """Опубликовать ролик.

    Кадры обязательны: сервер не разбирает видео на кадры сам, и проверить,
    что внутри, можно только по присланным клиентом кадрам с разных
    таймкодов. Меньше MIN_COVERS кадров — публикации нет: одного кадра
    (например, только начала ролика) недостаточно, чтобы поручиться за всё
    видео целиком.
    """
    if len(caption) > 300:
        raise HTTPException(status_code=400, detail="Подпись длиннее 300 символов")

    if len(covers) < MIN_COVERS:
        raise HTTPException(
            status_code=400,
            detail=f"Нужно как минимум {MIN_COVERS} кадра из разных моментов видео",
        )

    if await _published_today(session, user.id) >= DAILY_LIMIT:
        raise HTTPException(
            status_code=429,
            detail=f"Не больше {DAILY_LIMIT} роликов в сутки",
        )

    ext = ALLOWED_VIDEO.get(video.content_type or "")
    if not ext:
        raise HTTPException(status_code=400, detail="Поддерживаются MP4, MOV и WebM")

    data = await video.read()
    if not data:
        raise HTTPException(status_code=400, detail="Пустой файл")
    if len(data) > MAX_VIDEO_BYTES:
        raise HTTPException(
            status_code=400,
            detail=f"Видео больше {MAX_VIDEO_BYTES // (1024 * 1024)} МБ",
        )
    if not _looks_like_video(data):
        raise HTTPException(status_code=400, detail="Файл не похож на видео")

    # Каждый кадр перекодируем тем же санитайзером, что и фото профиля: он
    # срезает EXIF с координатами и отсекает файлы, притворяющиеся картинкой.
    # Один заблокированный кадр — весь ролик не публикуется, даже если
    # остальные кадры чистые: нарушение может быть в любой части видео.
    sanitized: list[tuple[bytes, str, str]] = []
    for i, cover in enumerate(covers):
        raw = await cover.read()
        try:
            cover_bytes, cover_type, cover_ext = sanitize_image(raw)
        except ImageRejected as exc:
            raise HTTPException(status_code=400, detail=f"Кадр {i + 1}: {exc}") from exc
        sanitized.append((cover_bytes, cover_type, cover_ext))

    for i, (cover_bytes, _cover_type, _cover_ext) in enumerate(sanitized):
        verdict = await moderate_image(cover_bytes)
        await log_moderation(user.id, "reel_cover", f"reel by {user.id} frame {i + 1}", verdict)
        if verdict.get("unavailable"):
            # Сервис проверки лежит — видео не виновато: 503 и «позже», не 422
            raise HTTPException(
                status_code=503,
                detail="Проверка видео сейчас недоступна — попробуйте через пару минут",
            )
        # Реклама в кадре — тот же страйк, что за рекламный текст; первый же
        # такой кадр завершает запрос (отказ или бан), остальные не смотрим.
        # Только "ad": блок с пустой категорией — отказ без страйка
        if verdict.get("category") == "ad":
            ответ_бана = await enforce_text_verdict(
                session, user, verdict, "Видео нарушает правила"
            )
            if ответ_бана is not None:
                return ответ_бана
        if verdict["blocked"]:
            raise HTTPException(status_code=422, detail="Видео нарушает правила")

    if caption.strip():
        text_verdict = await moderate_text(caption)
        await log_moderation(user.id, "reel_caption", caption, text_verdict)
        ответ_бана = await enforce_text_verdict(
            session, user, text_verdict, "Подпись нарушает правила"
        )
        if ответ_бана is not None:
            return ответ_бана

    base = f"reels/{user.id}/{uuid.uuid4()}"
    video_url = await upload_photo_to_r2(f"{base}.{ext}", data, video.content_type or "video/mp4")
    if not video_url:
        raise HTTPException(status_code=500, detail="Не удалось загрузить видео")

    # Средний по времени кадр — обложка ролика в ленте.
    cover_bytes, cover_type, cover_ext = sanitized[len(sanitized) // 2]
    cover_url = await upload_photo_to_r2(f"{base}.cover.{cover_ext}", cover_bytes, cover_type)

    reel = Reel(
        user_id=user.id,
        video_url=video_url,
        cover_url=cover_url or "",
        caption=caption.strip(),
    )
    session.add(reel)
    await session.flush()
    out = await _to_out(session, reel, user.id)
    await session.commit()
    return out


@router.post("/{reel_id}/like", response_model=ReelOut)
async def toggle_reel_like(
    reel_id: str,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """Поставить или снять лайк. Повторный тап снимает свой же лайк.

    `likes_count` меняем тем же запросом, что и лайк: считать COUNT на каждый
    показ ленты дороже, а расходиться счётчику не даёт уникальный ключ пары.
    """
    result = await session.execute(select(Reel).where(Reel.id == reel_id))
    reel = result.scalar_one_or_none()
    if not reel or (reel.is_hidden and reel.user_id != user.id):
        raise HTTPException(status_code=404, detail="Ролик не найден")

    result = await session.execute(
        select(ReelLike).where(and_(ReelLike.reel_id == reel_id, ReelLike.user_id == user.id))
    )
    existing = result.scalar_one_or_none()

    if existing:
        await session.execute(delete(ReelLike).where(ReelLike.id == existing.id))
        reel.likes_count = max(0, reel.likes_count - 1)
    else:
        session.add(ReelLike(reel_id=reel_id, user_id=user.id))
        try:
            await session.flush()
        except IntegrityError:
            # Двойной тап в один момент: лайк уже есть, счётчик не трогаем
            await session.rollback()
            result = await session.execute(select(Reel).where(Reel.id == reel_id))
            reel = result.scalar_one_or_none()
            if not reel:
                raise HTTPException(status_code=404, detail="Ролик не найден")
            return await _to_out(session, reel, user.id)
        reel.likes_count += 1

    await session.flush()
    out = await _to_out(session, reel, user.id)
    await session.commit()
    return out


@router.delete("/{reel_id}", status_code=204)
async def delete_reel(
    reel_id: str,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """Удалить свой ролик. Файлы из R2 убираем тоже — иначе платим за то,
    чего уже нет в приложении."""
    result = await session.execute(select(Reel).where(Reel.id == reel_id))
    reel = result.scalar_one_or_none()
    if not reel:
        raise HTTPException(status_code=404, detail="Ролик не найден")
    if reel.user_id != user.id:
        raise HTTPException(status_code=403, detail="Это не ваш ролик")

    for url in (reel.video_url, reel.cover_url):
        if not url:
            continue
        # Ключ — всё после домена: ровно то, что мы сами составили при загрузке
        key = url.split("/", 3)[-1] if url.startswith("http") else url
        if key.startswith("reels/"):
            await delete_photo_from_r2(key)

    await session.execute(delete(Reel).where(Reel.id == reel_id))
    await session.commit()


# ── Комментарии ─────────────────────────────────────────────────
#
# Здесь ролики и превращаются в знакомства: под видео написать проще, чем в
# личку первым. Без этого лента остаётся просмотром.

#: Антифлуд по комментариям: лимит в middleware общий по пути, а этот — про
#: поведение под одним роликом.
COMMENTS_PER_MINUTE = 5


@router.get("/{reel_id}/comments", response_model=ReelComments)
async def list_comments(
    reel_id: str,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
    limit: int = Query(default=50, ge=1, le=100),
):
    """Комментарии к ролику, свежие снизу.

    Комментарии заблокированных не показываем: человек заблокировал обидчика
    именно чтобы его не видеть, и лента роликов не исключение.
    """
    result = await session.execute(select(Reel).where(Reel.id == reel_id))
    reel = result.scalar_one_or_none()
    if not reel or (reel.is_hidden and reel.user_id != user.id):
        raise HTTPException(status_code=404, detail="Ролик не найден")

    result = await session.execute(select(Block.blocked_id).where(Block.blocker_id == user.id))
    hidden = {row[0] for row in result.all()}
    result = await session.execute(select(Block.blocker_id).where(Block.blocked_id == user.id))
    hidden |= {row[0] for row in result.all()}

    result = await session.execute(
        select(ReelComment)
        .where(and_(
            ReelComment.reel_id == reel_id,
            ReelComment.is_hidden == False,  # noqa: E712
        ))
        .order_by(desc(ReelComment.created_at))
        .limit(limit * 2)
    )
    rows = [c for c in result.scalars().all() if c.user_id not in hidden][:limit]

    profiles: dict[str, Profile] = {}
    if rows:
        result = await session.execute(
            select(Profile).where(Profile.user_id.in_({c.user_id for c in rows}))
        )
        profiles = {p.user_id: p for p in result.scalars().all()}

    # Разворачиваем: запрашивали свежие сверху, а читать удобнее снизу вверх
    rows.reverse()

    return ReelComments(
        comments=[
            ReelCommentOut(
                id=c.id,
                author_id=c.user_id,
                author_name=(profiles[c.user_id].display_name if c.user_id in profiles else ""),
                author_photo=(
                    as_list(profiles[c.user_id].photos)[0]
                    if c.user_id in profiles and as_list(profiles[c.user_id].photos)
                    else ""
                ),
                text=c.text,
                is_mine=c.user_id == user.id,
                created_at=c.created_at,
            )
            for c in rows
        ]
    )


@router.post("/{reel_id}/comments", response_model=ReelCommentOut, status_code=201)
async def add_comment(
    reel_id: str,
    data: ReelCommentSend,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """Написать комментарий под роликом."""
    text = data.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="Пустой комментарий")

    result = await session.execute(select(Reel).where(Reel.id == reel_id))
    reel = result.scalar_one_or_none()
    if not reel or reel.is_hidden:
        raise HTTPException(status_code=404, detail="Ролик не найден")

    # Автор ролика мог заблокировать этого человека — под своим видео он его
    # видеть не должен
    result = await session.execute(
        select(Block.id).where(or_(
            and_(Block.blocker_id == reel.user_id, Block.blocked_id == user.id),
            and_(Block.blocker_id == user.id, Block.blocked_id == reel.user_id),
        ))
    )
    if result.scalar_one_or_none():
        raise HTTPException(status_code=403, detail="Комментировать нельзя")

    since = datetime.now(timezone.utc) - timedelta(minutes=1)
    result = await session.execute(
        select(func.count(ReelComment.id)).where(and_(
            ReelComment.user_id == user.id,
            ReelComment.created_at >= since,
        ))
    )
    if (result.scalar() or 0) >= COMMENTS_PER_MINUTE:
        raise HTTPException(status_code=429, detail="Слишком много комментариев подряд")

    # Комментарий виден всем, кто смотрит ролик — модерируем как публичный текст
    verdict = await moderate_text(text)
    await log_moderation(user.id, "reel_comment", text, verdict)
    ответ_бана = await enforce_text_verdict(
        session, user, verdict, "Комментарий нарушает правила"
    )
    if ответ_бана is not None:
        return ответ_бана

    comment = ReelComment(reel_id=reel_id, user_id=user.id, text=text)
    session.add(comment)
    reel.comments_count += 1
    await session.flush()

    result = await session.execute(select(Profile).where(Profile.user_id == user.id))
    profile = result.scalar_one_or_none()

    out = ReelCommentOut(
        id=comment.id,
        author_id=user.id,
        author_name=profile.display_name if profile else "",
        author_photo=(as_list(profile.photos)[0] if profile and as_list(profile.photos) else ""),
        text=comment.text,
        is_mine=True,
        created_at=comment.created_at,
    )
    await session.commit()
    return out


@router.delete("/{reel_id}/comments/{comment_id}", status_code=204)
async def delete_comment(
    reel_id: str,
    comment_id: str,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """Удалить комментарий.

    Может автор комментария и владелец ролика: под своим видео человек должен
    иметь право убрать чужую грубость, не дожидаясь модератора.
    """
    result = await session.execute(
        select(ReelComment).where(and_(
            ReelComment.id == comment_id, ReelComment.reel_id == reel_id
        ))
    )
    comment = result.scalar_one_or_none()
    if not comment:
        raise HTTPException(status_code=404, detail="Комментарий не найден")

    result = await session.execute(select(Reel).where(Reel.id == reel_id))
    reel = result.scalar_one_or_none()

    if comment.user_id != user.id and (not reel or reel.user_id != user.id):
        raise HTTPException(status_code=403, detail="Нельзя удалить этот комментарий")

    await session.execute(delete(ReelComment).where(ReelComment.id == comment_id))
    if reel:
        reel.comments_count = max(0, reel.comments_count - 1)
    await session.commit()


@router.post("/{reel_id}/view", status_code=204)
async def record_view(
    reel_id: str,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """Отметить просмотр.

    Счётчик, а не журнал: «сколько посмотрели» — единственное, что нужно
    автору, а таблица на каждый просмотр стала бы самой большой в базе.
    Свои просмотры не считаем: автор накрутил бы сам себе, просто листая ленту.
    """
    result = await session.execute(select(Reel).where(Reel.id == reel_id))
    reel = result.scalar_one_or_none()
    if not reel or reel.user_id == user.id:
        return Response(status_code=204)

    reel.views_count += 1
    await session.commit()
    return Response(status_code=204)


@router.post("/{reel_id}/report", status_code=204)
async def report_reel(
    reel_id: str,
    data: ContentReport,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """Пожаловаться на ролик.

    Своя ручка, а не общая жалоба на пользователя: та требует, чтобы люди
    контактировали (защита от травли жалобами), а ролик видят все — и именно
    случайный зритель заметит нарушение первым.

    Порог ниже, чем у анкеты: видео с нарушением успевает посмотреть больше
    людей, чем статичную анкету, поэтому три жалобы снимают его с показа сразу.
    """
    result = await session.execute(select(Reel).where(Reel.id == reel_id))
    reel = result.scalar_one_or_none()
    if not reel:
        raise HTTPException(status_code=404, detail="Ролик не найден")
    if reel.user_id == user.id:
        raise HTTPException(status_code=400, detail="Это ваш ролик")

    порог = await подать_жалобу_на_контент(
        session,
        reporter_id=user.id,
        author_id=reel.user_id,
        reason=data.reason,
        description=data.description,
        метка=f"reel:{reel_id}",
        порог=3,
    )
    if порог and not reel.is_hidden:
        reel.is_hidden = True
        await register_content_strike(session, reel.user_id, f"reel:{reel_id}")
        logger.warning(f"Ролик {reel_id} снят с показа по жалобам")

    await session.commit()
    return Response(status_code=204)


@router.post("/{reel_id}/comments/{comment_id}/report", status_code=204)
async def report_comment(
    reel_id: str,
    comment_id: str,
    data: ContentReport,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """Пожаловаться на комментарий под роликом.

    Комментарий публичен, как и сам ролик, поэтому у зрителя должна быть
    жалоба, а не только у владельца видео кнопка «удалить»: владелец может
    не заходить сутками, а грубость под его роликом всё это время читают все.
    """
    result = await session.execute(
        select(ReelComment).where(and_(
            ReelComment.id == comment_id, ReelComment.reel_id == reel_id,
        ))
    )
    comment = result.scalar_one_or_none()
    if not comment or comment.is_hidden:
        raise HTTPException(status_code=404, detail="Комментарий не найден")
    if comment.user_id == user.id:
        raise HTTPException(status_code=400, detail="Это ваш комментарий")

    порог = await подать_жалобу_на_контент(
        session,
        reporter_id=user.id,
        author_id=comment.user_id,
        reason=data.reason,
        description=data.description,
        метка=f"reelcomment:{comment_id}",
        порог=3,
    )
    if порог:
        comment.is_hidden = True
        await register_content_strike(
            session, comment.user_id, f"reelcomment:{comment_id}"
        )
        # Счётчик показывает видимые комментарии — снятый уходит и из него,
        # как при удалении
        result = await session.execute(select(Reel).where(Reel.id == reel_id))
        reel = result.scalar_one_or_none()
        if reel:
            reel.comments_count = max(0, reel.comments_count - 1)
        logger.warning(f"Комментарий {comment_id} снят с показа по жалобам")

    await session.commit()
    return Response(status_code=204)


@router.post("/{reel_id}/forward", status_code=204)
async def forward_reel(
    reel_id: str,
    data: ReelForward,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """Переслать ролик в личный чат мэтча или в комнату по интересам.

    Наружу не шарим: в Telegram Mini App ссылку всё равно откроют внутри
    Telegram, а вне него она бесполезна. Зато показать конкретному человеку или
    закинуть в общий чат — то, ради чего репост и нужен.

    Скрытый модерацией ролик не пересылается: иначе снятое с показа видео
    продолжало бы ходить по чатам.
    """
    result = await session.execute(select(Reel).where(Reel.id == reel_id))
    reel = result.scalar_one_or_none()
    if not reel or reel.is_hidden:
        raise HTTPException(status_code=404, detail="Ролик не найден")

    # Автор ролика мог заблокировать этого человека — как и под комментарием,
    # чужое видео он растаскивать по чатам не должен
    result = await session.execute(
        select(Block.id).where(or_(
            and_(Block.blocker_id == reel.user_id, Block.blocked_id == user.id),
            and_(Block.blocker_id == user.id, Block.blocked_id == reel.user_id),
        ))
    )
    if result.scalar_one_or_none():
        raise HTTPException(status_code=403, detail="Переслать нельзя")

    caption = (data.text or "").strip()
    if caption:
        verdict = await moderate_text(caption)
        await log_moderation(user.id, "reel_forward", caption, verdict)
        ответ_бана = await enforce_text_verdict(
            session, user, verdict, "Сообщение нарушает правила"
        )
        if ответ_бана is not None:
            return ответ_бана

    if data.match_id:
        # Мэтч должен быть свой и живой: иначе можно писать в чужую переписку.
        # Блокировка гасит is_active, так что заблокированная пара сюда не дойдёт
        result = await session.execute(
            select(Match).where(and_(
                Match.id == data.match_id,
                Match.is_active == True,  # noqa: E712
                or_(Match.user1_id == user.id, Match.user2_id == user.id),
            ))
        )
        match = result.scalar_one_or_none()
        if not match:
            raise HTTPException(status_code=404, detail="Чат не найден")

        partner_id = match.user2_id if match.user1_id == user.id else match.user1_id

        # Через общий сервис, а не своим session.add: иначе собеседник с
        # открытым чатом не получит события, а офлайн — ни пуша, ни Telegram.
        # Он же проверяет правила: пересылка ролика — такое же сообщение, и
        # обходить ею лимит «одно письмо до ответа» нельзя
        try:
            payload = await save_message(
                data.match_id, user.id, caption, reel_id=reel_id,
            )
        except ДоставкаОтклонена as отказ:
            raise HTTPException(status_code=403, detail=отказ.detail)
        if payload is None:
            raise HTTPException(status_code=404, detail="Чат не найден")
        await fan_out(
            payload, data.match_id, user.id, partner_id,
            caption or REEL_FALLBACK_TEXT,
        )
        return Response(status_code=204)

    if data.room_id:
        result = await session.execute(
            select(Room).where(and_(
                Room.id == data.room_id,
                Room.is_active == True,  # noqa: E712
            ))
        )
        if not result.scalar_one_or_none():
            raise HTTPException(status_code=404, detail="Комната не найдена")

        # Тот же антифлуд, что у обычной отправки: без него комнату можно было
        # залить роликами в обход лимита на сообщения
        await check_flood(session, user.id)

        session.add(RoomMessage(
            room_id=data.room_id,
            sender_id=user.id,
            # В комнате текст обязателен по схеме, поэтому подставляем понятную
            # подпись: пустое сообщение с одним превью читается как сбой
            text=caption or "поделился видео",
            reel_id=reel_id,
        ))
        await session.commit()
        return Response(status_code=204)

    raise HTTPException(status_code=400, detail="Укажите чат или комнату")
