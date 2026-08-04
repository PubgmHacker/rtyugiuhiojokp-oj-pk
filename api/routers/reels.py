"""Видео-лента (reels) — второй формат знакомства помимо свайпов.

Модерация: разбирать видео на кадры на сервере значило бы тащить ffmpeg в
образ, поэтому обложку присылает клиент отдельным файлом, и проверяется
именно она. Без обложки ролик не публикуется — иначе в ленту попадёт что
угодно непроверенным.

Лимит публикаций суточный и считается по времени создания, а не счётчиком:
счётчик пришлось бы обнулять по расписанию, а пропущенный запуск открыл бы
безлимит.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from sqlalchemy import and_, delete, desc, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from database.connection import get_session
from middleware.auth import get_current_user
from models.models import Block, Profile, Reel, ReelLike, User
from models.schemas import ReelOut, ReelsOut
from services.ai_moderation import log_moderation, moderate_image
from services.image_sanitizer import ImageRejected, sanitize_image
from services.r2_storage import delete_photo_from_r2, upload_photo_to_r2
from utils import as_list

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/reels", tags=["reels"])

#: Больше — и лента превращается в файлообменник, а R2 в статью расходов.
MAX_VIDEO_BYTES = 50 * 1024 * 1024
#: Сколько роликов можно опубликовать за сутки.
DAILY_LIMIT = 3
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

    age: Optional[int] = None
    if profile and profile.birth_date:
        now = datetime.now()
        age = now.year - profile.birth_date.year
        if (now.month, now.day) < (profile.birth_date.month, profile.birth_date.day):
            age -= 1

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
        liked_by_me=liked,
        is_mine=reel.user_id == viewer_id,
        is_hidden=reel.is_hidden,
        created_at=reel.created_at,
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

    conditions = [Reel.is_hidden == False, User.is_banned == False]  # noqa: E712
    if before:
        try:
            conditions.append(Reel.created_at < datetime.fromisoformat(before))
        except ValueError:
            raise HTTPException(status_code=400, detail="Некорректный параметр before")

    result = await session.execute(
        select(Reel)
        .join(User, Reel.user_id == User.id)
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
    cover: UploadFile = File(..., description="Кадр из видео — его и модерируем"),
    caption: str = Form(default=""),
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """Опубликовать ролик.

    Обложка обязательна: сервер не разбирает видео на кадры, и проверить, что
    внутри, можно только по присланному клиентом кадру. Нет обложки — нет
    публикации.
    """
    if len(caption) > 300:
        raise HTTPException(status_code=400, detail="Подпись длиннее 300 символов")

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

    # Обложку перекодируем тем же санитайзером, что и фото профиля: он срезает
    # EXIF с координатами и отсекает файлы, притворяющиеся картинкой
    cover_bytes = await cover.read()
    try:
        cover_bytes, cover_type, cover_ext = sanitize_image(cover_bytes)
    except ImageRejected as exc:
        raise HTTPException(status_code=400, detail=f"Обложка: {exc}") from exc

    verdict = await moderate_image(cover_bytes)
    await log_moderation(user.id, "reel_cover", f"reel by {user.id}", verdict)
    if verdict["blocked"]:
        raise HTTPException(status_code=422, detail="Видео нарушает правила")

    if caption.strip():
        from services.ai_moderation import moderate_text

        text_verdict = await moderate_text(caption)
        await log_moderation(user.id, "reel_caption", caption, text_verdict)
        if text_verdict["blocked"]:
            raise HTTPException(status_code=422, detail="Подпись нарушает правила")

    base = f"reels/{user.id}/{uuid.uuid4()}"
    video_url = await upload_photo_to_r2(f"{base}.{ext}", data, video.content_type or "video/mp4")
    if not video_url:
        raise HTTPException(status_code=500, detail="Не удалось загрузить видео")

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
