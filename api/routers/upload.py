from __future__ import annotations

import uuid
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.ext.asyncio import AsyncSession

from database.connection import get_session
from middleware.auth import get_current_user
from models.models import User
from services.r2_storage import upload_photo_to_r2, delete_photo_from_r2
from services.ai_moderation import moderate_image

router = APIRouter(prefix="/upload", tags=["upload"])


@router.post("/photo")
async def upload_photo(
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Загрузить фото профиля в R2 с AI-модерацией."""
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="Only images are allowed")

    contents = await file.read()
    if len(contents) > 10 * 1024 * 1024:  # 10 MB
        raise HTTPException(status_code=400, detail="Image too large (max 10MB)")

    # AI Moderation
    mod_result = await moderate_image(contents)
    if mod_result["blocked"]:
        raise HTTPException(status_code=422, detail="Image violates content policy")

    file_ext = file.content_type.split("/")[-1]  # jpeg, png, webp
    object_key = f"photos/{user.id}/{uuid.uuid4()}.{file_ext}"

    url = await upload_photo_to_r2(object_key, contents, file.content_type)
    if not url:
        raise HTTPException(status_code=500, detail="Upload failed")

    return {"url": url, "key": object_key}


@router.delete("/photo")
async def delete_photo(
    data: dict,
    user: User = Depends(get_current_user),
):
    """Удалить фото из R2."""
    key = data.get("key", "")
    if not key:
        raise HTTPException(status_code=400, detail="No key provided")

    # Verify user owns this photo (key contains user.id)
    if f"/{user.id}/" not in key:
        raise HTTPException(status_code=403, detail="Cannot delete photos you don't own")

    await delete_photo_from_r2(key)
    return {"success": True}
