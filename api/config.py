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

    # ── App Store IAP (покупка подписки в iOS) ──────────────────
    # Идентификаторы продуктов и сроки живут в services/plans.py — там же,
    # где цены и уровни. Пока bundle id не задан вместе с корневым
    # сертификатом Apple, покупка в приложении не предлагается.
    APPSTORE_BUNDLE_ID: str = "com.souldawn.dating"
    # Числовой Apple ID приложения из App Store Connect — библиотека Apple
    # требует его для проверки в Production
    APPSTORE_APP_APPLE_ID: int = 0
    # Сборки из Xcode, TestFlight и App Review работают в песочнице
    APPSTORE_USE_SANDBOX: bool = False

    # ── Голосовая рулетка (WebRTC) ──────────────────────────────
    # Без TURN звонок не соберётся у части людей: симметричный NAT мобильных
    # операторов одним STUN не пробивается. Пока не задан — часть звонков не
    # соединится, но раздел работает.
    TURN_URL: str = ""
    TURN_USERNAME: str = ""
    TURN_PASSWORD: str = ""

    # ── APNs (пуши в iOS-приложение) ────────────────────────────
    # Ключ .p8 из Apple Developer Portal — целиком, включая заголовок
    # BEGIN PRIVATE KEY. В .env переводы строк пишутся как \n.
    # Пока не задан, пуши просто не отправляются: приложение работает,
    # уведомления приходят только внутри Telegram.
    APNS_KEY_P8: str = ""
    APNS_KEY_ID: str = ""
    APNS_TEAM_ID: str = ""
    APNS_BUNDLE_ID: str = "com.souldawn.dating"
    # Сборки из Xcode и TestFlight регистрируются в песочнице APNs,
    # прод-хост для них возвращает BadDeviceToken
    APNS_USE_SANDBOX: bool = False

    # ── Referral program ─────────────────────────────────────────
    REFERRAL_MIN_INVITES: int = 3     # друзей для активации буста
    REFERRAL_BOOST_PERCENT: int = 12  # +% к скору анкеты в выдаче (10–15)

    # ── Profile limits ───────────────────────────────────────────
    MAX_PHOTOS: int = 6
    MAX_BIO_LENGTH: int = 500
    MAX_INTERESTS: int = 10
    MIN_AGE: int = 18
    MAX_AGE: int = 99
    DECK_SIZE: int = 10  # анкет за один запрос

    # ── CORS ─────────────────────────────────────────────────────
    # Домены фронтенда через запятую. Звёздочка допустима только при
    # DEBUG: в проде список обязателен, иначе остаётся открытая дыра.
    # localhost и 127.0.0.1 — разные origin'ы для браузера, поэтому в
    # дефолте нужны оба: dev-сервер доступен по обоим адресам.
    CORS_ORIGINS: str = (
        "http://localhost:5173,http://127.0.0.1:5173,"
        "http://localhost:4173,http://127.0.0.1:4173"
    )

    @property
    def cors_origin_list(self) -> list[str]:
        origins = [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]
        if not self.DEBUG:
            origins = [o for o in origins if o != "*"]
        return origins or ["http://localhost:5173"]

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
