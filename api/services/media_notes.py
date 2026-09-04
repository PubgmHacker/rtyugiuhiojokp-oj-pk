"""Голосовые сообщения и видеокружки: что принимаем и как проверяем файл.

Идея взята у мессенджеров — голосовое и кружок в личке. Наше поверх этого:
кружок не обязан быть кругом (VIDEO_NOTE_SHAPES), а волна голосового едет
вместе с сообщением и рисуется без декодирования аудио на приёмнике.

Файл проверяем по заголовку И сигнатуре, как видео: Content-Type клиент
подставляет любой. У MediaRecorder заголовок приходит с параметрами
(`audio/webm;codecs=opus`) — их срезает `чистый_тип`.
"""

from __future__ import annotations

from fastapi import HTTPException

#: Формы видеокружка. Первая — по умолчанию и для клиентов, которые форм не
#: знают. Список зашит, а не свободная строка: форма — CSS-маска на клиенте,
#: и неизвестный код рисовал бы пустоту вместо видео.
VIDEO_NOTE_SHAPES: tuple[str, ...] = (
    "circle", "squircle", "heart", "star", "hexagon", "tree", "flower",
)

#: Длительность как в Telegram: минуту слушают, две — уже нет.
MAX_MEDIA_SECONDS = 60

#: Минута opus ~ 0.5 МБ; трёх хватает любому кодеку, а файлообменником чат
#: не становится.
MAX_VOICE_BYTES = 3 * 1024 * 1024
#: Кружок 60 с в 480p — 6–10 МБ; 20 — с запасом на Safari (H.264 без
#: битрейт-подсказки).
MAX_NOTE_BYTES = 20 * 1024 * 1024

ALLOWED_AUDIO: dict[str, str] = {
    "audio/webm": "webm",
    "audio/ogg": "ogg",
    "audio/mp4": "m4a",
    "audio/x-m4a": "m4a",
    "audio/aac": "aac",
    "audio/mpeg": "mp3",
    "audio/wav": "wav",
    "audio/x-wav": "wav",
}


def чистый_тип(content_type: str | None) -> str:
    """`audio/webm;codecs=opus` → `audio/webm`."""
    return (content_type or "").split(";", 1)[0].strip().lower()


def looks_like_audio(data: bytes) -> bool:
    """Сигнатура контейнера: WebM/Matroska, Ogg, ISO BMFF, MP3, WAV, ADTS."""
    if len(data) < 12:
        return False
    if data[:4] == b"\x1a\x45\xdf\xa3" or data[:4] == b"OggS":
        return True
    if data[4:8] == b"ftyp":
        return True
    if data[:3] == b"ID3":
        return True
    if data[:4] == b"RIFF" and data[8:12] == b"WAVE":
        return True
    # Синхрослово MPEG-аудио (MP3) и ADTS (AAC): 0xFFF? с установленными
    # старшими битами второго байта
    return data[0] == 0xFF and (data[1] & 0xE0) == 0xE0


def разобрать_длительность(raw: str | int | None) -> int:
    """Секунды из формы: целое от 1 до MAX_MEDIA_SECONDS, иначе 400.

    Клиент режет запись сам; сервер сверяет, чтобы в чат не уехало
    «голосовое на 0 секунд» или подписанное часовым таймером.
    """
    try:
        секунд = int(float(str(raw).strip()))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Длительность не число")
    if секунд < 1 or секунд > MAX_MEDIA_SECONDS:
        raise HTTPException(
            status_code=400,
            detail=f"Длительность от 1 до {MAX_MEDIA_SECONDS} секунд",
        )
    return секунд
