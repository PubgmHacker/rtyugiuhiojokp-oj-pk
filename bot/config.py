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
API_BASE_URL: str = os.getenv("API_BASE_URL", "http://localhost:8000")
SITE_URL: str = os.getenv("SITE_URL", "http://localhost:5173")  # Web frontend

# ── Misc ─────────────────────────────────────────────────────────
# Railway отдаёт PORT для web-сервисов; для бота используем WEBHOOK_PORT
WEBHOOK_PORT: int = int(os.getenv("PORT", os.getenv("WEBHOOK_PORT", "8081")))

# ── Banners ─────────────────────────────────────────────────────
BANNERS: dict[str, str] = {
    "welcome": "https://placehold.co/600x400/0a0a1a/c97b3d.png?text=SOULDAWN+DATING",
    "match": "https://placehold.co/600x400/1a0a2e/ff6b9d.png?text=It%E2%80%99s+a+Match!",
    "profile": "https://placehold.co/600x400/0a1a2e/6bb3ff.png?text=Your+Profile",
    "like": "https://placehold.co/600x200/0a2e1a/6bff9d.png?text=%E2%9D%A4%EF%B8%8F",
    "dislike": "https://placehold.co/600x200/2e0a0a/ff6b6b.png?text=%F0%9F%91%8E",
    "menu": "https://placehold.co/600x300/0a0a1a/c97b3d.png?text=Souldawn+Dating",
    "deck": "https://placehold.co/600x800/1a1a2e/e0e0e0.png?text=Profile+Photo",
}


def is_admin(telegram_id: int) -> bool:
    return telegram_id in ADMIN_IDS
