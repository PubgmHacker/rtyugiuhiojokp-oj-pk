from __future__ import annotations

import os
from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Все настройки загружаются из env-переменных."""

    # ── App ──────────────────────────────────────────────────────
    API_HOST: str = "0.0.0.0"
    API_PORT: int = 8000
    # DEBUG включает /docs, гостевой /auth/dev и fail-open проверку initData.
    # По умолчанию ВЫКЛЮЧЕН — включайте явно через .env только локально.
    DEBUG: bool = False

    # ── JWT ─────────────────────────────────────────────────────
    JWT_SECRET: str = "change_this_in_production"
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_EXPIRE_HOURS: int = 72  # 3 дня

    # ── Database ────────────────────────────────────────────────
    DATABASE_URL: str = "postgresql+asyncpg://souldawn:souldawn_dating_dev@localhost:5433/souldawn_dating"

    # ── Redis ────────────────────────────────────────────────────
    REDIS_URL: str = "redis://localhost:6380/0"

    # ── Telegram ─────────────────────────────────────────────────
    BOT_TOKEN: str = ""
    BOT_USERNAME: str = ""
    ADMIN_IDS: str = ""  # comma-separated

    # ── Cloudflare R2 ───────────────────────────────────────────
    R2_ACCOUNT_ID: str = ""
    R2_ACCESS_KEY_ID: str = ""
    R2_SECRET_ACCESS_KEY: str = ""
    R2_BUCKET_NAME: str = "souldawn-dating"
    R2_PUBLIC_URL: str = ""

    # ── Zhipu AI (GLM-5.2) ──────────────────────────────────────
    ZHIPU_API_KEY: str = ""

    # ── Profile limits ───────────────────────────────────────────
    MAX_PHOTOS: int = 6
    MAX_BIO_LENGTH: int = 500
    MAX_INTERESTS: int = 10
    MIN_AGE: int = 18
    MAX_AGE: int = 99
    DECK_SIZE: int = 10  # анкет за один запрос

    @property
    def admin_id_list(self) -> list[int]:
        if not self.ADMIN_IDS:
            return []
        return [int(x.strip()) for x in self.ADMIN_IDS.split(",") if x.strip().isdigit()]

    class Config:
        # Ищем .env и в корне репо (запуск `uvicorn` из api/), и рядом
        env_file = ("../.env", ".env")
        env_file_encoding = "utf-8"
        extra = "ignore"  # в общем .env есть переменные бота/фронтенда


@lru_cache
def get_settings() -> Settings:
    return Settings()
