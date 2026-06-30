from __future__ import annotations

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


async def upload_photo_to_r2(object_key: str, data: bytes, content_type: str) -> Optional[str]:
    """Загрузить фото в Cloudflare R2. Возвращает публичный URL."""
    client = _get_s3_client()
    if not client:
        logger.warning("R2 not configured — returning placeholder URL")
        return f"https://placehold.co/600x800/1a1a2e/e0e0e0?text=Photo"

    try:
        client.put_object(
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
        client.delete_object(Bucket=settings.R2_BUCKET_NAME, Key=object_key)
    except Exception as e:
        logger.error(f"R2 delete error: {e}")


def get_presigned_upload_url(object_key: str, content_type: str = "image/jpeg", expires_in: int = 300) -> Optional[str]:
    """Генерировать presigned URL для прямой загрузки с клиента."""
    client = _get_s3_client()
    if not client:
        return None

    try:
        return client.generate_presigned_url(
            "put_object",
            Params={
                "Bucket": settings.R2_BUCKET_NAME,
                "Key": object_key,
                "ContentType": content_type,
            },
            ExpiresIn=expires_in,
        )
    except Exception as e:
        logger.error(f"Presigned URL error: {e}")
        return None
