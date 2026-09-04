from __future__ import annotations

import uuid
from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile, File
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import get_settings
from database.connection import get_session
from middleware.auth import get_current_user
from models.models import Profile, User
from services.r2_storage import upload_photo_to_r2, delete_photo_from_r2, uploads_available
from services.ai_moderation import log_moderation, moderate_image, verify_profile_photo
from services.enforcement import enforce_text_verdict
from services.image_sanitizer import ImageRejected, sanitize_image
from services.media_notes import (
    ALLOWED_AUDIO,
    MAX_NOTE_BYTES,
    MAX_VOICE_BYTES,
    looks_like_audio,
    разобрать_длительность,
    чистый_тип,
)
from services.video_validation import (
    ALLOWED_VIDEO,
    looks_like_video,
    модерировать_кадры,
    прочитать_видео,
)
from utils import as_list

router = APIRouter(prefix="/upload", tags=["upload"])

settings = get_settings()


@router.post("/photo")
async def upload_photo(
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Загрузить фото профиля в R2 с AI-модерацией."""
    if not uploads_available():
        raise HTTPException(
            status_code=503,
            detail="Загрузка медиа временно недоступна — хранилище не настроено",
        )
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="Only images are allowed")

    contents = await file.read()
    if len(contents) > 10 * 1024 * 1024:  # 10 MB
        raise HTTPException(status_code=400, detail="Image too large (max 10MB)")

    # Перекодирование до модерации и до R2: срезает EXIF с GPS-координатами
    # (для дейтинга это домашний адрес) и отсекает файлы, которые лишь
    # притворяются картинкой через заголовок Content-Type.
    try:
        contents, content_type, file_ext = sanitize_image(contents)
    except ImageRejected as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # AI Moderation
    mod_result = await moderate_image(contents)
    # В журнал уходит не картинка, а имя файла — читать бинарь в админке
    # бессмысленно, а разобрать спорную блокировку по имени можно.
    await log_moderation(user.id, "photo", file.filename or "photo", mod_result)
    if mod_result.get("unavailable"):
        # Проверка не состоялась — фото не «нарушает правила», сервису нужно
        # время. 503, а не 422: человек должен повторить, а не менять снимок
        raise HTTPException(
            status_code=503,
            detail="Проверка фото сейчас недоступна — попробуйте через пару минут",
        )
    # Реклама на снимке (category "ad": юзернеймы, ссылки, QR в кадре) — тот же
    # страйк, что за рекламный текст. Только "ad": прочие блокировки фото идут
    # с пустой категорией, а enforce_text_verdict нормализовал бы её в "text"
    # и превратил каждый отказ по фото в шаг к бану
    if mod_result.get("category") == "ad":
        ответ_бана = await enforce_text_verdict(
            session, user, mod_result, "Image violates content policy"
        )
        if ответ_бана is not None:
            return ответ_бана
    if mod_result["blocked"]:
        raise HTTPException(status_code=422, detail="Image violates content policy")

    # Гейт анкеты: модерация выше отвечает «нет ли запрещённого», а анкете
    # нужен живой человек — кот, чёрный фон, пейзаж и скриншот из интернета
    # модерацию проходят, но в выдачу попасть не должны.
    gate = await verify_profile_photo(contents)
    if gate.get("unavailable"):
        raise HTTPException(
            status_code=503,
            detail="Проверка фото сейчас недоступна — попробуйте через пару минут",
        )
    if not gate.get("face"):
        await log_moderation(
            user.id, "photo_gate", file.filename or "photo",
            {"blocked": True, "reason": gate.get("reason", "no face")},
        )
        raise HTTPException(
            status_code=422,
            detail="На фото анкеты должно быть хорошо видно ваше лицо",
        )
    if not gate.get("authentic"):
        await log_moderation(
            user.id, "photo_gate", file.filename or "photo",
            {"blocked": True, "reason": gate.get("reason", "not authentic")},
        )
        raise HTTPException(
            status_code=422,
            detail="Похоже, это не ваша фотография — загрузите собственный снимок, а не картинку из интернета",
        )

    object_key = f"photos/{user.id}/{uuid.uuid4()}.{file_ext}"

    url = await upload_photo_to_r2(object_key, contents, content_type)
    if not url:
        raise HTTPException(status_code=500, detail="Upload failed")

    return {"url": url, "key": object_key}


@router.post("/video")
async def upload_profile_video(
    file: UploadFile = File(...),
    covers: list[UploadFile] = File(
        ..., description="Кадры с разных таймкодов видео — их и модерируем"
    ),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Загрузить видеоролик анкеты в R2 с AI-модерацией по кадрам.

    Контракт тот же, что у публикации ролика в ленте (routers/reels.py):
    сервер видео не декодирует (ffmpeg в контейнере нет), поэтому клиент
    присылает вместе с файлом кадры с разных таймкодов — их санитайзит и
    смотрит модерация. Гейт «живой человек» (лицо на снимке) к видео не
    применяется: он остаётся на фото, видео — дополнение к анкете, а не
    замена фото.

    Возвращает `{"url", "key"}` — как /upload/photo; в анкету URL кладёт
    клиент через `PATCH /profiles/me` (поле videos), где проверяется
    происхождение ссылки и лимит.
    """
    if not uploads_available():
        raise HTTPException(
            status_code=503,
            detail="Загрузка медиа временно недоступна — хранилище не настроено",
        )
    # Лимит проверяем до тяжёлой работы: модерация кадров и заливка в R2
    # стоят денег, а видео сверх лимита в анкету всё равно не встанет.
    result = await session.execute(select(Profile).where(Profile.user_id == user.id))
    profile = result.scalar_one_or_none()
    if profile and len(as_list(profile.videos)) >= settings.MAX_PROFILE_VIDEOS:
        raise HTTPException(
            status_code=400,
            detail=f"Максимум {settings.MAX_PROFILE_VIDEOS} видео в анкете",
        )

    data, ext = await прочитать_видео(file)

    # Кадры нужны только модерации — обложек у видео анкеты нет
    _кадры, ответ_бана = await модерировать_кадры(
        session, user, covers, "profile_video", f"profile video by {user.id}"
    )
    if ответ_бана is not None:
        return ответ_бана

    # Префикс нарочно не photos/: PATCH принимает в поле videos только
    # ссылки из profile-videos/{user_id}/ — фото и видео не перепутать
    object_key = f"profile-videos/{user.id}/{uuid.uuid4()}.{ext}"

    url = await upload_photo_to_r2(object_key, data, file.content_type or "video/mp4")
    if not url:
        raise HTTPException(status_code=500, detail="Upload failed")

    return {"url": url, "key": object_key}


@router.post("/voice")
async def upload_voice(
    file: UploadFile = File(...),
    duration: str = Form(..., description="Секунды записи, 1–60"),
    user: User = Depends(get_current_user),
):
    """Голосовое сообщение для лички — файл в R2 под папкой отправителя.

    AI-модерации нет: транскрибировать аудио нечем, а слушать вручную — не
    масштаб. Защита та же, что у текста в целом: жалоба и блок. Зато файл
    привязан к отправителю префиксом `chat-media/{user_id}/`: доставка
    (services/chat_delivery) принимает в сообщение только его — чужую запись
    переслать как свою нельзя.

    Возвращает `{"url", "key", "duration"}`; в сообщение ссылку кладёт клиент
    полем `media`.
    """
    if not uploads_available():
        raise HTTPException(
            status_code=503,
            detail="Загрузка медиа временно недоступна — хранилище не настроено",
        )
    секунд = разобрать_длительность(duration)

    тип = чистый_тип(file.content_type)
    ext = ALLOWED_AUDIO.get(тип)
    if not ext:
        raise HTTPException(status_code=400, detail="Формат аудио не поддерживается")

    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Пустая запись")
    if len(data) > MAX_VOICE_BYTES:
        raise HTTPException(status_code=400, detail="Запись слишком большая")
    if not looks_like_audio(data):
        raise HTTPException(status_code=400, detail="Файл не похож на аудио")

    object_key = f"chat-media/{user.id}/voice-{uuid.uuid4()}.{ext}"
    url = await upload_photo_to_r2(object_key, data, тип)
    if not url:
        raise HTTPException(status_code=500, detail="Upload failed")
    return {"url": url, "key": object_key, "duration": секунд}


@router.post("/video-note")
async def upload_video_note(
    file: UploadFile = File(...),
    covers: list[UploadFile] = File(
        ..., description="Кадры с разных моментов записи — их и модерируем"
    ),
    duration: str = Form(..., description="Секунды записи, 1–60"),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Видеокружок для лички: файл в R2 + AI-модерация по кадрам.

    Контракт тот же, что у видео анкеты и роликов ленты: сервер видео не
    декодирует, кадры снимает клиент прямо во время записи. Форму кружка
    сервер не хранит здесь — она едет в самом сообщении (поле media.shape) и
    к файлу отношения не имеет: одно и то же видео можно показать любой.
    """
    if not uploads_available():
        raise HTTPException(
            status_code=503,
            detail="Загрузка медиа временно недоступна — хранилище не настроено",
        )
    секунд = разобрать_длительность(duration)

    тип = чистый_тип(file.content_type)
    ext = ALLOWED_VIDEO.get(тип)
    if not ext:
        raise HTTPException(status_code=400, detail="Поддерживаются MP4, MOV и WebM")

    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Пустая запись")
    if len(data) > MAX_NOTE_BYTES:
        raise HTTPException(status_code=400, detail="Запись слишком большая")
    if not looks_like_video(data):
        raise HTTPException(status_code=400, detail="Файл не похож на видео")

    кадры, ответ_бана = await модерировать_кадры(
        session, user, covers, "video_note", f"video note by {user.id}"
    )
    if ответ_бана is not None:
        return ответ_бана

    stem = f"note-{uuid.uuid4()}"
    # Постер — первый промодерированный кадр рядом с видео: собеседник видит
    # лицо в фигуре сразу, а не пустой контур до нажатия (iOS без постера
    # первый кадр не рисует). Не залился — не беда, кружок работает и без него.
    poster_url = None
    if кадры:
        poster_bytes, poster_type, poster_ext = кадры[0]
        poster_url = await upload_photo_to_r2(
            f"chat-media/{user.id}/{stem}.{poster_ext}", poster_bytes, poster_type
        )

    object_key = f"chat-media/{user.id}/{stem}.{ext}"
    url = await upload_photo_to_r2(object_key, data, тип)
    if not url:
        raise HTTPException(status_code=500, detail="Upload failed")
    return {"url": url, "key": object_key, "duration": секунд, "poster": poster_url}


@router.delete("/photo")
async def delete_photo(
    data: dict,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Удалить фото из R2.

    Тот же эндпоинт удаляет и видео анкеты: ключ `profile-videos/{user_id}/…`
    проходит проверку владения ниже, а опорного снимка верификации среди
    видео не бывает.
    """
    key = data.get("key", "")
    if not key:
        raise HTTPException(status_code=400, detail="No key provided")

    # Verify user owns this photo (key contains user.id)
    if f"/{user.id}/" not in key:
        raise HTTPException(status_code=403, detail="Cannot delete photos you don't own")

    # Галочка верификации привязана к конкретному фото: удалил тот снимок,
    # с которым совпало лицо на живой проверке, — совпадение больше нечем
    # подтвердить, галочка снимается. Пройти проверку заново можно всегда.
    result = await session.execute(select(Profile).where(Profile.user_id == user.id))
    profile = result.scalar_one_or_none()
    if profile and profile.verified_photo and profile.verified_photo.endswith(f"/{key}"):
        profile.verified_photo = ""
        user.is_verified = False
        await session.flush()

    await delete_photo_from_r2(key)
    return {"success": True}
