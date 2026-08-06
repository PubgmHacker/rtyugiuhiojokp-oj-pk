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
# Свои картинки со своего домена. Раньше баннеры вели на placehold.co: каждый
# пользователь видел чужую картинку, мы зависели от чужой доступности и
# отдавали туда статистику показов — а цвет там остался прежним индиго.
# Рисуются генератором tools/make_banners.py, лежат в web/public/banners.
BANNERS: dict[str, str] = {
    имя: f"{SITE_URL}/banners/{имя}.png"
    for имя in ("welcome", "menu", "match", "profile", "like", "dislike", "deck")
}
