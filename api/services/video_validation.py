"""Проверка и модерация загружаемого видео.

Один и тот же контракт у ленты роликов (`routers/reels.py`) и у видео в
анкете (`routers/upload.py`): сервер не умеет декодировать видео (ffmpeg в
контейнере нет), поэтому клиент присылает вместе с файлом несколько кадров
из разных моментов, и модерация смотрит на них. Кадры перекодируются тем же
санитайзером, что и фото профиля, — EXIF с координатами срезается, файл,
притворяющийся картинкой, отсекается.

Валидация самого файла — заголовок И сигнатура контейнера: Content-Type
клиент подставляет любой, а переименованный архив не должен пройти как видео.
"""

from __future__ import annotations

from fastapi import HTTPException, UploadFile
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from models.models import User
from services.ai_moderation import log_moderation, moderate_image
from services.enforcement import enforce_text_verdict
from services.image_sanitizer import ImageRejected, sanitize_image

#: Больше — и лента превращается в файлообменник, а R2 в статью расходов.
MAX_VIDEO_BYTES = 50 * 1024 * 1024

#: Меньше — и модерация видит только один подобранный кадр: начало ролика
#: может быть безобидным, а нарушение — дальше по видео.
MIN_COVERS = 3

#: Что принимаем. Проверяем и заголовок, и сигнатуру файла: заголовок клиент
#: подставляет любой.
ALLOWED_VIDEO = {
    "video/mp4": "mp4",
    "video/quicktime": "mov",
    "video/webm": "webm",
}


def looks_like_video(data: bytes) -> bool:
    """Сигнатура контейнера. Переименованный архив не должен пройти как видео.

    MP4 и MOV — ISO BMFF: на 4-м байте лежит 'ftyp'. WebM — Matroska с EBML.
    """
    if len(data) < 12:
        return False
    if data[4:8] == b"ftyp":
        return True
    return data[:4] == b"\x1a\x45\xdf\xa3"


async def прочитать_видео(video: UploadFile) -> tuple[bytes, str]:
    """Прочитать файл и проверить, что это видео допустимого формата.

    Возвращает `(байты, расширение)`; на любой беде — HTTPException 400,
    с которым вызывающий роутер ничего не доделывает.
    """
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
    if not looks_like_video(data):
        raise HTTPException(status_code=400, detail="Файл не похож на видео")

    return data, ext


async def модерировать_кадры(
    session: AsyncSession,
    user: User,
    covers: list[UploadFile],
    журнал_тип: str,
    метка: str,
) -> tuple[list[tuple[bytes, str, str]], JSONResponse | None]:
    """Санитайзер и AI-модерация присланных кадров видео.

    Один заблокированный кадр — всё видео не публикуется, даже если
    остальные кадры чистые: нарушение может быть в любой части ролика.

    Возвращает `(перекодированные кадры, ответ_бана)`. Ответ бана не None,
    когда реклама в кадре добила счёт страйков, — вызывающий обязан вернуть
    его как есть (JSONResponse коммитит сессию, исключение откатило бы бан).
    Остальные отказы — HTTPException 400/422/503.
    """
    if len(covers) < MIN_COVERS:
        raise HTTPException(
            status_code=400,
            detail=f"Нужно как минимум {MIN_COVERS} кадра из разных моментов видео",
        )

    sanitized: list[tuple[bytes, str, str]] = []
    for i, cover in enumerate(covers):
        raw = await cover.read()
        try:
            sanitized.append(sanitize_image(raw))
        except ImageRejected as exc:
            raise HTTPException(status_code=400, detail=f"Кадр {i + 1}: {exc}") from exc

    for i, (cover_bytes, _cover_type, _cover_ext) in enumerate(sanitized):
        verdict = await moderate_image(cover_bytes)
        await log_moderation(user.id, журнал_тип, f"{метка} frame {i + 1}", verdict)
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
                return sanitized, ответ_бана
        if verdict["blocked"]:
            raise HTTPException(status_code=422, detail="Видео нарушает правила")

    return sanitized, None
