from __future__ import annotations

import asyncio
import logging
from typing import Optional

import boto3
from botocore.config import Config

from config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)

_s3_client = None


def _get_s3_client():
    global _s3_client
    if _s3_client is None and settings.R2_ACCOUNT_ID:
        _s3_client = boto3.client(
            "s3",
            endpoint_url=f"https://{settings.R2_ACCOUNT_ID}.r2.cloudflarestorage.com",
            aws_access_key_id=settings.R2_ACCESS_KEY_ID,
            aws_secret_access_key=settings.R2_SECRET_ACCESS_KEY,
            config=Config(signature_version="s3v4"),
            region_name="auto",
        )
    return _s3_client


def uploads_available() -> bool:
    """Загрузка медиа возможна: настроен R2 (или DEBUG с заглушкой).

    Ранний сторож роутеров загрузки: в проде без ключей R2 исход предрешён —
    честнее ответить 503 сразу, чем сжечь платный вызов модерации и упасть
    на самой заливке. В DEBUG upload_photo_to_r2 живёт без ключей (заглушка),
    поэтому DEBUG проходит всегда.
    """
    if settings.DEBUG:
        return True
    return bool(
        settings.R2_ACCOUNT_ID
        and settings.R2_ACCESS_KEY_ID
        and settings.R2_SECRET_ACCESS_KEY
        and settings.R2_PUBLIC_URL
    )


async def upload_photo_to_r2(object_key: str, data: bytes, content_type: str) -> Optional[str]:
    """Загрузить фото в Cloudflare R2. Возвращает публичный URL.

    Без настроенного R2 загрузка ПАДАЕТ (None → 5xx в роутерах), а не
    подменяется заглушкой: молчаливый placehold.co в проде записывал бы в
    профиль чужую картинку, а настоящий снимок пользователя просто исчезал.
    Заглушка остаётся только в DEBUG — локальная разработка без ключей.
    """
    client = _get_s3_client()
    if not client:
        if settings.DEBUG:
            logger.warning("R2 not configured — returning placeholder URL (DEBUG)")
            return "https://placehold.co/600x800/1a1a2e/e0e0e0?text=Photo"
        logger.error("R2 is not configured — refusing upload (fail-closed)")
        return None

    try:
        # boto3 синхронный — не блокируем event loop
        await asyncio.to_thread(
            client.put_object,
            Bucket=settings.R2_BUCKET_NAME,
            Key=object_key,
            Body=data,
            ContentType=content_type,
        )
        public_url = f"{settings.R2_PUBLIC_URL}/{object_key}"
        return public_url
    except Exception as e:
        logger.error(f"R2 upload error: {e}")
        return None


async def delete_photo_from_r2(object_key: str):
    """Удалить фото из R2."""
    client = _get_s3_client()
    if not client:
        return

    try:
        await asyncio.to_thread(
            client.delete_object, Bucket=settings.R2_BUCKET_NAME, Key=object_key,
        )
    except Exception as e:
        logger.error(f"R2 delete error: {e}")
