"""Ручки историй.

Загрузка идёт тем же путём, что и фотографии анкеты: очистка метаданных,
модерация, запись в журнал. Отдельная дорога для историй означала бы, что
кадр с геометкой уезжает в R2 нетронутым — ровно то, чего очистка EXIF и
должна не допускать.
"""
from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from database.connection import get_session
from middleware.auth import get_current_user
from models.models import Match, Profile, Story, User
from models.schemas import (
    ContentReport, StoriesFeed, StoryAuthorOut, StoryOut, StoryReplyTarget,
    StoryViewerOut, StoryViewers,
)
from services import stories as S
from services.ai_moderation import log_moderation, moderate_image, moderate_text
from services.content_reports import подать_жалобу_на_контент
from services.enforcement import enforce_text_verdict, register_content_strike
from services.image_sanitizer import ImageRejected, sanitize_image
from services.r2_storage import upload_photo_to_r2, uploads_available

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/stories", tags=["stories"])

#: Тот же предел, что у фотографий анкеты. Разные пределы на одном
#: устройстве человек читает как случайный сбой.
MAX_BYTES = 10 * 1024 * 1024


def _out(story: Story, *, name: str, mine: bool, seen: bool) -> StoryOut:
    return StoryOut(
        id=story.id,
        user_id=story.user_id,
        display_name=name,
        media_url=story.media_url,
        caption=story.caption,
        audience=story.audience,
        created_at=story.created_at,
        expires_at=story.expires_at,
        views_count=story.views_count if mine else None,
        seen=seen,
        mine=mine,
    )


async def _имя(session: AsyncSession, user_id: str) -> str:
    result = await session.execute(
        select(Profile.display_name).where(Profile.user_id == user_id)
    )
    return result.scalar_one_or_none() or "Без имени"


@router.post("", response_model=StoryOut)
async def publish_story(
    file: UploadFile = File(...),
    caption: str = Form(""),
    audience: str = Form(S.AUDIENCE_MATCHES),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Выложить историю на сутки."""
    if not uploads_available():
        raise HTTPException(
            status_code=503,
            detail="Загрузка медиа временно недоступна — хранилище не настроено",
        )
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="Нужна картинка")

    contents = await file.read()
    if len(contents) > MAX_BYTES:
        raise HTTPException(status_code=400, detail="Файл больше 10 МБ")

    try:
        contents, content_type, file_ext = sanitize_image(contents)
    except ImageRejected as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    mod = await moderate_image(contents)
    await log_moderation(user.id, "story", file.filename or "story", mod)
    if mod.get("unavailable"):
        # Сервис проверки лежит — кадр не виноват: 503 и «позже», а не 422
        raise HTTPException(
            status_code=503,
            detail="Проверка кадра сейчас недоступна — попробуйте через пару минут",
        )
    # Реклама в кадре (юзернеймы, ссылки, QR) — тот же страйк, что за рекламный
    # текст. Только "ad": блок с пустой категорией — отказ без страйка, иначе
    # enforce_text_verdict нормализовал бы её в "text" и копил бы шаги к бану
    if mod.get("category") == "ad":
        ответ_бана = await enforce_text_verdict(
            session, user, mod, "Кадр нарушает правила"
        )
        if ответ_бана is not None:
            return ответ_бана
    if mod["blocked"]:
        raise HTTPException(status_code=422, detail="Кадр нарушает правила")

    # Подпись модерируем отдельно: картинка чистая, а текст поверх неё —
    # тот же публичный контент, и проверять его надо тем же порядком.
    caption = (caption or "").strip()
    if caption:
        tmod = await moderate_text(caption)
        await log_moderation(user.id, "story_caption", caption[:64], tmod)
        ответ_бана = await enforce_text_verdict(
            session, user, tmod, "Подпись нарушает правила"
        )
        if ответ_бана is not None:
            return ответ_бана

    object_key = f"stories/{user.id}/{uuid.uuid4()}.{file_ext}"
    url = await upload_photo_to_r2(object_key, contents, content_type)
    if not url:
        raise HTTPException(status_code=503, detail="Хранилище недоступно")

    try:
        story = await S.создать(
            session, user.id,
            media_url=url, object_key=object_key,
            caption=caption, audience=audience,
        )
    except S.ИсторияОтклонена as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    await session.commit()
    return _out(story, name=await _имя(session, user.id), mine=True, seen=True)


@router.get("/feed", response_model=StoriesFeed)
async def stories_feed(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Лента: партнёры по парам плюс свои истории."""
    авторы = await S.лента(session, user.id)
    мои = await S.свои(session, user.id)
    имя = await _имя(session, user.id)

    return StoriesFeed(
        authors=[
            StoryAuthorOut(
                user_id=a.user_id, display_name=a.display_name, avatar=a.avatar,
                count=a.count, latest_at=a.latest_at, has_unseen=a.has_unseen,
            )
            for a in авторы
        ],
        mine=[_out(s, name=имя, mine=True, seen=True) for s in мои],
    )


@router.get("/user/{user_id}", response_model=list[StoryOut])
async def user_stories(
    user_id: str,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Истории конкретного человека — для просмотрщика.

    404 вместо 403, когда доступа нет: разница между «историй нет» и
    «истории есть, но не для тебя» — тоже сведения о человеке.
    """
    if not await S.доступ_к_автору(session, user.id, user_id):
        raise HTTPException(status_code=404, detail="Историй нет")

    items = await S.истории_автора(session, user.id, user_id)
    if not items:
        raise HTTPException(status_code=404, detail="Историй нет")

    seen = await S.просмотренные(session, user.id, [s.id for s in items])
    имя = await _имя(session, user_id)
    свои = user_id == user.id
    return [
        _out(s, name=имя, mine=свои, seen=свои or s.id in seen) for s in items
    ]


@router.post("/{story_id}/view", status_code=204)
async def mark_viewed(
    story_id: str,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Отметить кадр просмотренным."""
    story = await session.get(Story, story_id)
    if story is None:
        raise HTTPException(status_code=404, detail="Историй нет")
    if not await S.доступ_к_автору(session, user.id, story.user_id):
        raise HTTPException(status_code=404, detail="Историй нет")

    await S.отметить_просмотр(session, story_id, user.id)
    await session.commit()
    return Response(status_code=204)


@router.get("/{story_id}/viewers", response_model=StoryViewers)
async def story_viewers(
    story_id: str,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Список зрителей — только автору."""
    story = await session.get(Story, story_id)
    if story is None or story.user_id != user.id:
        raise HTTPException(status_code=404, detail="Историй нет")

    rows = await S.зрители(session, story_id)
    return StoryViewers(
        viewers=[
            StoryViewerOut(user_id=uid, display_name=name, avatar=avatar, viewed_at=at)
            for uid, name, avatar, at in rows
        ],
        total=story.views_count,
    )


@router.post("/{story_id}/reply", response_model=StoryReplyTarget)
async def reply_target(
    story_id: str,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Куда идти с ответом на историю.

    Сообщение здесь не создаём: ответ должен лечь в переписку обычным
    текстом и остаться после того, как история исчезнет. Отдельный вид
    сообщения «ответ на историю» через сутки стал бы ссылкой в пустоту.
    """
    story = await session.get(Story, story_id)
    if story is None or story.user_id == user.id:
        raise HTTPException(status_code=404, detail="Историй нет")

    result = await session.execute(
        select(Match.id).where(
            and_(
                or_(
                    and_(Match.user1_id == user.id, Match.user2_id == story.user_id),
                    and_(Match.user1_id == story.user_id, Match.user2_id == user.id),
                ),
                Match.is_active == True,  # noqa: E712
            )
        )
    )
    match_id = result.scalar_one_or_none()
    if not match_id:
        raise HTTPException(
            status_code=403, detail="Ответить можно только тому, с кем есть пара"
        )

    story.replies_count += 1
    await session.commit()

    затравка = f"«{story.caption}» — " if story.caption else "Про твою историю: "
    return StoryReplyTarget(match_id=match_id, prefill=затравка)


@router.delete("/{story_id}", status_code=204)
async def remove_story(
    story_id: str,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Снять свою историю раньше срока."""
    story = await session.get(Story, story_id)
    if story is None or story.user_id != user.id:
        raise HTTPException(status_code=404, detail="Историй нет")

    await S.удалить(session, story)
    await session.commit()
    return Response(status_code=204)


@router.post("/{story_id}/report", status_code=204)
async def report_story(
    story_id: str,
    data: ContentReport,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Пожаловаться на историю.

    Порог снятия ниже, чем у ролика: историю с аудиторией «пары» видят
    считанные люди, и трёх разных жалобщиков нарушение могло бы не собрать
    за все свои сутки. Модератор при этом видит каждую жалобу сразу —
    порог решает только автоматическое снятие с показа.
    """
    story = await session.get(Story, story_id)
    if story is None:
        raise HTTPException(status_code=404, detail="История не найдена")
    if story.user_id == user.id:
        raise HTTPException(status_code=400, detail="Это ваша история")

    порог = await подать_жалобу_на_контент(
        session,
        reporter_id=user.id,
        author_id=story.user_id,
        reason=data.reason,
        description=data.description,
        метка=f"story:{story_id}",
        порог=2,
    )
    if порог and not story.is_hidden:
        story.is_hidden = True
        await register_content_strike(session, story.user_id, f"story:{story_id}")
        logger.warning(f"История {story_id} снята с показа по жалобам")

    await session.commit()
    return Response(status_code=204)
