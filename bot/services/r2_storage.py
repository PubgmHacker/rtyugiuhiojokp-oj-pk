from __future__ import annotations

import asyncio
import logging
import uuid

from config import (
    R2_ACCOUNT_ID,
    R2_ACCESS_KEY_ID,
    R2_SECRET_ACCESS_KEY,
    R2_BUCKET_NAME,
    R2_PUBLIC_URL,
)

logger = logging.getLogger(__name__)

_s3_client = None


def _get_s3_client():
    global _s3_client
    if _s3_client is None and R2_ACCOUNT_ID:
        try:
            import boto3
            from botocore.config import Config

            _s3_client = boto3.client(
                "s3",
                endpoint_url=f"https://{R2_ACCOUNT_ID}.r2.cloudflarestorage.com",
                aws_access_key_id=R2_ACCESS_KEY_ID,
                aws_secret_access_key=R2_SECRET_ACCESS_KEY,
                config=Config(signature_version="s3v4"),
                region_name="auto",
            )
        except ImportError:
            logger.warning("boto3 not installed — bot photos stay as Telegram file_id")
    return _s3_client


async def upload_photo(user_id: str, data: bytes, content_type: str = "image/jpeg") -> str | None:
    """Загрузить фото пользователя в R2. None — если R2 не настроен/ошибка.

    При None вызывающий код хранит Telegram file_id (бот его рендерит,
    веб покажет плейсхолдер).
    """
    client = _get_s3_client()
    if not client:
        return None

    object_key = f"photos/{user_id}/{uuid.uuid4()}.jpg"
    try:
        # boto3 синхронный — не блокируем event loop бота
        await asyncio.to_thread(
            client.put_object,
            Bucket=R2_BUCKET_NAME,
            Key=object_key,
            Body=data,
            ContentType=content_type,
        )
        return f"{R2_PUBLIC_URL}/{object_key}" if R2_PUBLIC_URL else None
    except Exception as e:
        logger.error(f"R2 upload error: {e}")
        return None


async def upload_video(
    user_id: str, data: bytes, ext: str = "mp4", content_type: str = "video/mp4"
) -> str | None:
    """Загрузить видео анкеты в R2. None — если R2 не настроен/ошибка.

    Префикс profile-videos/ — тот же, что у API (routers/upload.py): PATCH
    принимает в поле videos только ссылки из этой папки, фото и видео не
    перепутать. При None вызывающий код хранит Telegram file_id (бот его
    рендерит, веб такие значения не отдаёт наружу).
    """
    client = _get_s3_client()
    if not client:
        return None

    object_key = f"profile-videos/{user_id}/{uuid.uuid4()}.{ext}"
    try:
        await asyncio.to_thread(
            client.put_object,
            Bucket=R2_BUCKET_NAME,
            Key=object_key,
            Body=data,
            ContentType=content_type,
        )
        return f"{R2_PUBLIC_URL}/{object_key}" if R2_PUBLIC_URL else None
    except Exception as e:
        logger.error(f"R2 video upload error: {e}")
        return None
