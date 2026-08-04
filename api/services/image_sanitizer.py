"""Санитайзер загружаемых изображений.

Две задачи, которые нельзя решать по отдельности:

1. **EXIF.** Снимок с телефона несёт GPS-координаты места съёмки, а для
   дейтинга это домашний адрес пользователя. Файлы в R2 раздаются публично,
   поэтому метаданные обязаны быть срезаны до загрузки, а не при показе.
2. **Реальный формат.** Заголовок `Content-Type` присылает клиент, и ему
   нельзя верить: под видом `image/png` приходит SVG со скриптом и получает
   публичный URL — это stored XSS. Формат определяется по содержимому.

Перекодирование решает и то, и другое: у нового файла нет ни метаданных
исходника, ни возможности оказаться не изображением — Pillow просто не
откроет то, что изображением не является.
"""

from __future__ import annotations

import io
import logging

from PIL import Image, ImageOps

logger = logging.getLogger(__name__)

# SVG сюда намеренно не входит: это XML, который браузер исполняет.
ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP", "HEIF", "HEIC", "GIF"}

# Больше незачем: дека показывает фото в размер экрана телефона,
# а мегапиксели с современных камер только замедляют загрузку карточки.
MAX_DIMENSION = 2048

JPEG_QUALITY = 88


class ImageRejected(Exception):
    """Файл не является изображением допустимого формата."""


def sanitize_image(data: bytes) -> tuple[bytes, str, str]:
    """Проверить и перекодировать изображение.

    Возвращает `(байты, content_type, расширение)`.
    Поднимает `ImageRejected`, если это не изображение или формат запрещён.
    """
    try:
        with Image.open(io.BytesIO(data)) as probe:
            fmt = (probe.format or "").upper()
            if fmt not in ALLOWED_FORMATS:
                raise ImageRejected(f"Формат {fmt or 'неизвестный'} не поддерживается")

            # Кадр анимации/многостраничного файла не нужен — берём первый
            probe.seek(0)

            # exif_transpose учитывает тег ориентации до того, как EXIF
            # будет отброшен: иначе портретные снимки с iPhone лягут на бок
            image = ImageOps.exif_transpose(probe)

            has_alpha = image.mode in ("RGBA", "LA", "PA") or (
                image.mode == "P" and "transparency" in image.info
            )
            image = image.convert("RGBA" if has_alpha else "RGB")

            image.thumbnail((MAX_DIMENSION, MAX_DIMENSION), Image.LANCZOS)

            buf = io.BytesIO()
            if has_alpha:
                # PNG сохраняет прозрачность; EXIF в него не переносится
                image.save(buf, format="PNG", optimize=True)
                return buf.getvalue(), "image/png", "png"

            image.save(buf, format="JPEG", quality=JPEG_QUALITY, optimize=True)
            return buf.getvalue(), "image/jpeg", "jpg"
    except ImageRejected:
        raise
    except Exception as exc:  # noqa: BLE001 — Pillow бросает разное
        # Сюда попадает и SVG, и переименованный ZIP, и битый файл
        logger.info(f"Загрузка отклонена: не удалось разобрать изображение ({exc})")
        raise ImageRejected("Файл не является изображением") from exc
