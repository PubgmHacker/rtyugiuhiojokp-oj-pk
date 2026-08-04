from __future__ import annotations

import os


# ── Telegram Bot ────────────────────────────────────────────────
BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
BOT_USERNAME: str = os.getenv("BOT_USERNAME", "")

# ── Admin ──────────────────────────────────────────────────────
ADMIN_IDS: list[int] = []
raw = os.getenv("ADMIN_IDS", "")
if raw:
    ADMIN_IDS = [int(x.strip()) for x in raw.split(",") if x.strip().isdigit()]

# ── Database ───────────────────────────────────────────────────
DATABASE_URL: str = os.getenv("DATABASE_URL", "postgresql+asyncpg://souldawn:souldawn_dating_dev@localhost:5433/souldawn_dating")

# ── Redis ────────────────────────────────────────────────────────
REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6380/0")

# ── API ─────────────────────────────────────────────────────────
SITE_URL: str = os.getenv("SITE_URL", "http://localhost:5173")  # Web frontend

# ── Premium / Payments (значения задаются в .env) ──────────────
# Цены и сроки живут в services/plans.py — там же, где уровни. Здесь только
# курсы пересчёта рублёвой цены в единицы платёжных систем: Stars и USDT
# ходят по своему курсу, а линейка должна оставаться одной для всех способов.
RUB_PER_STAR: float = float(os.getenv("RUB_PER_STAR", "1.9"))
RUB_PER_USDT: float = float(os.getenv("RUB_PER_USDT", "95"))
# CryptoBot (@CryptoBot, Crypto Pay API) — если токен пуст, способ скрыт
CRYPTOBOT_TOKEN: str = os.getenv("CRYPTOBOT_TOKEN", "")
# СБП — появится после подключения провайдера (заглушка)
SBP_ENABLED: bool = os.getenv("SBP_ENABLED", "").lower() in ("1", "true", "yes")

# ── Referral program ─────────────────────────────────────────────
REFERRAL_MIN_INVITES: int = int(os.getenv("REFERRAL_MIN_INVITES", "3"))
REFERRAL_BOOST_PERCENT: int = int(os.getenv("REFERRAL_BOOST_PERCENT", "12"))

# ── Cloudflare R2 (перезаливка фото из Telegram, чтобы видел веб) ─
R2_ACCOUNT_ID: str = os.getenv("R2_ACCOUNT_ID", "")
R2_ACCESS_KEY_ID: str = os.getenv("R2_ACCESS_KEY_ID", "")
R2_SECRET_ACCESS_KEY: str = os.getenv("R2_SECRET_ACCESS_KEY", "")
R2_BUCKET_NAME: str = os.getenv("R2_BUCKET_NAME", "souldawn-dating")
R2_PUBLIC_URL: str = os.getenv("R2_PUBLIC_URL", "")

# ── AI-модерация (Zhipu GLM) ─────────────────────────────────────
# Без ключа модерация в боте работает по словарному фильтру
ZHIPU_API_KEY: str = os.getenv("ZHIPU_API_KEY", "")

# ── Антифлуд ─────────────────────────────────────────────────────
# Минимальный интервал между действиями одного пользователя, секунды
THROTTLE_MESSAGE: float = float(os.getenv("THROTTLE_MESSAGE", "0.7"))
THROTTLE_CALLBACK: float = float(os.getenv("THROTTLE_CALLBACK", "0.4"))

# ── Misc ─────────────────────────────────────────────────────────
# Railway отдаёт PORT для web-сервисов; для бота используем WEBHOOK_PORT
WEBHOOK_PORT: int = int(os.getenv("PORT", os.getenv("WEBHOOK_PORT", "8081")))

# ── Banners ─────────────────────────────────────────────────────
# Цвета совпадают с дизайн-системой: фон #0a0b0f, акцент #5b66ff
BANNERS: dict[str, str] = {
    "welcome": "https://placehold.co/900x600/0a0b0f/5b66ff.png?text=SOULDAWN",
    "match": "https://placehold.co/900x600/0a0b0f/5b66ff.png?text=%D0%92%D0%B7%D0%B0%D0%B8%D0%BC%D0%BD%D0%BE!",
    "profile": "https://placehold.co/900x600/0a0b0f/5b66ff.png?text=%D0%9C%D0%BE%D1%8F+%D0%B0%D0%BD%D0%BA%D0%B5%D1%82%D0%B0",
    "like": "https://placehold.co/900x300/0a0b0f/34d399.png?text=%E2%9D%A4%EF%B8%8F",
    "dislike": "https://placehold.co/900x300/0a0b0f/8f97a8.png?text=%F0%9F%91%8E",
    "menu": "https://placehold.co/900x450/0a0b0f/5b66ff.png?text=SOULDAWN",
    "deck": "https://placehold.co/900x1200/16181f/8f97a8.png?text=%D0%A4%D0%BE%D1%82%D0%BE",
}

