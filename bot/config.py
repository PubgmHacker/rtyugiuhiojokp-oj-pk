from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlsplit


def _load_dotenv() -> None:
    """Читает корневой .env, не перетирая уже заданные переменные."""
    candidates = (
        Path(__file__).resolve().parent.parent / ".env",
        Path.cwd() / ".env",
        Path.cwd().parent / ".env",
    )
    seen: set[Path] = set()
    for path in candidates:
        try:
            path = path.resolve()
        except OSError:
            continue
        if path in seen or not path.is_file():
            continue
        seen.add(path)
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        for raw in text.splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
                value = value[1:-1]
            if key and key not in os.environ:
                os.environ[key] = value


_load_dotenv()


# ── Telegram Bot ────────────────────────────────────────────────
BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
BOT_USERNAME: str = os.getenv("BOT_USERNAME", "")

# ── Режим разработки ────────────────────────────────────────────
# Тот же смысл, что DEBUG в api/config.py, и та же переменная окружения.
# Локальный стенд обязан работать без внешних ключей, поэтому в DEBUG сбой
# AI-модерации фото пропускает снимок. В проде наоборот: фото без проверки
# в анкету не попадает (fail-closed, см. services/moderation.py).
DEBUG: bool = os.getenv("DEBUG", "").lower() in ("1", "true", "yes")

# ── Возрастные границы ──────────────────────────────────────────
# Те же числа, что MIN_AGE/MAX_AGE в api/config.py: пул анкет общий для
# бота и приложения, порог обязан совпадать. Намеренно не из env — это
# обещание оферты, а не настройка стенда. Синхронность всех копий числа
# (код, тексты, документы) проверяет api/tests/test_age_floor.py.
MIN_AGE: int = 18
MAX_AGE: int = 99

# ── Admin ──────────────────────────────────────────────────────
ADMIN_IDS: list[int] = []
raw = os.getenv("ADMIN_IDS", "")
if raw:
    ADMIN_IDS = [int(x.strip()) for x in raw.split(",") if x.strip().isdigit()]

# ── Database ───────────────────────────────────────────────────
DATABASE_URL: str = os.getenv("DATABASE_URL", "postgresql+asyncpg://simp:simp_dating_dev@localhost:5433/simp_dating")

# ── Redis ────────────────────────────────────────────────────────
REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6380/0")

# ── API ─────────────────────────────────────────────────────────
SITE_URL: str = os.getenv("SITE_URL", "http://localhost:5173").rstrip("/")  # Mini App / веб

#: Канонический домен документов: он же в `<link rel="canonical">` каждой страницы
#: лендинга, в его sitemap и в APPSTORE.md (Privacy Policy URL, Terms of Use). Тот
#: же дефолт зашит в вебе (`web/src/lib/legal.ts`): ссылка на политику обязана
#: вести в одно место из бота, мини-аппа и нативного приложения.
LEGAL_ORIGIN: str = "https://simp.app"

# Юридические страницы. Пусто — берём URL мини-аппа: он отдаёт свои копии
# privacy.html / terms.html из web/public (синхронизируются с landing/).
LANDING_URL: str = os.getenv("LANDING_URL", "").rstrip("/")


def mini_app_url(path: str = "") -> str:
    """URL мини-аппа для web_app-кнопок и Menu Button."""
    if not path:
        return SITE_URL
    return f"{SITE_URL}{path if path.startswith('/') else '/' + path}"


def webapp_https() -> bool:
    """Telegram принимает web_app и Menu Button только по HTTPS."""
    return SITE_URL.startswith("https://")


def mini_app_openable() -> bool:
    """Мини-апп откроется у получателя сообщения, а не только у нас.

    Нужна для кнопок-ссылок: по HTTP web_app невозможен, но обычная url-кнопка
    открывает тот же адрес во внешнем браузере — для стенда на голом IP это
    рабочий путь. Петля так не работает ни у кого, кроме машины, где поднят
    vite: в чужом Telegram `http://localhost:5173` ведёт в сам телефон.

    Для web_app правило про петлю намеренно не применяется (см. `legal_url` и
    `скрипты_бота/адреса_документов.py`): такую кнопку по HTTPS открывает тот
    же человек, который поднял сервер, и localhost там настоящий адрес.
    """
    return SITE_URL.startswith(("http://", "https://")) and not _петля(SITE_URL)


def _петля(url: str) -> bool:
    """Адрес ведёт на устройство получателя, а не на сервер."""
    host = urlsplit(url).hostname or ""
    return host in {"localhost", "127.0.0.1", "0.0.0.0", "::1"} or host.endswith(".localhost")


def legal_url(page: str) -> str:
    """Политика / оферта — ссылкой, которая откроется у получателя.

    Ссылка уходит в чужой Telegram, и петля в ней — гарантированно мёртвый
    адрес: `http://localhost:5173/privacy.html` на телефоне человека ведёт в
    него самого, где ничего не слушает. Поэтому в цепочке дефолтов петля
    пропускается и остаётся канонический домен: пока не поднят DNS, ссылка
    ведёт в никуда одинаково для всех, а не выглядит рабочей у того, кто
    запустил бота на своей машине.

    Явно заданный LANDING_URL уважается как есть — это осознанная настройка,
    в том числе для локального просмотра из десктопного Telegram.

    Хвостовой слэш срезан один раз, при чтении переменных выше: второй rstrip
    здесь маскировал бы потерю первого, и `https://simp.app//privacy.html`
    (404 на статик-хостингах) уехал бы в прод незамеченным.
    """
    name = page if page.endswith(".html") else f"{page}.html"
    if LANDING_URL.startswith(("http://", "https://")):
        return f"{LANDING_URL}/{name}"
    if SITE_URL.startswith(("http://", "https://")) and not _петля(SITE_URL):
        return f"{SITE_URL}/{name}"
    return f"{LEGAL_ORIGIN}/{name}"

# ── Premium / Payments (значения задаются в .env) ──────────────
# Цены и сроки живут в services/plans.py — там же, где уровни. Здесь только
# курсы пересчёта рублёвой цены в единицы платёжных систем: Stars и USDT
# ходят по своему курсу, а линейка должна оставаться одной для всех способов.
RUB_PER_STAR: float = float(os.getenv("RUB_PER_STAR", "1.9"))
RUB_PER_USDT: float = float(os.getenv("RUB_PER_USDT", "95"))
# Досрочная разблокировка забаненного аккаунта. Оплата — только Stars: они
# доступны каждому без настройки, а забаненному нельзя предлагать способ,
# который может оказаться выключенным.
UNBAN_PRICE_RUB: int = int(os.getenv("UNBAN_PRICE_RUB", "349"))
# CryptoBot (@CryptoBot, Crypto Pay API) — если токен пуст, способ скрыт
CRYPTOBOT_TOKEN: str = os.getenv("CRYPTOBOT_TOKEN", "")
# Рублёвая оплата (карта и СБП) — токен платёжного провайдера из BotFather:
# /mybots → Payments → ЮKassa (или другой), он же выдаёт СБП внутри своей
# формы. Telegram сам держит счёт и присылает successful_payment, поэтому
# отдельного вебхука и HTTP-клиента здесь не нужно.
PAYMENT_PROVIDER_TOKEN: str = os.getenv("PAYMENT_PROVIDER_TOKEN", "")
# Способ скрыт, пока нет токена — ровно как у CryptoBot. Отдельного
# выключателя нет сознательно: раньше здесь стоял SBP_ENABLED, и поднятый
# флаг рисовал кнопку, которая отвечала «скоро появится». Флаг, включающий
# заглушку, хуже отсутствующей кнопки: человек уходит с экрана оплаты,
# решив, что оплата сломана.
SBP_ENABLED: bool = bool(PAYMENT_PROVIDER_TOKEN)

# ── Referral program ─────────────────────────────────────────────
REFERRAL_MIN_INVITES: int = int(os.getenv("REFERRAL_MIN_INVITES", "3"))
REFERRAL_BOOST_PERCENT: int = int(os.getenv("REFERRAL_BOOST_PERCENT", "12"))

# ── Отложенные пуши онбординга (services/nudges.py) ──────────────
# Рассылки про субкультуру и почту не уходят в онбординге — они ставятся в
# очередь и уезжают после паузы: согласие и конец анкеты двигают отсчёт.
# 45 минут — человек успел либо заполнить анкету, либо отвлечься; сутки для
# почты — просьба «сохрани доступ» звучит уместно, когда анкета уже пожила.
NUDGE_STYLE_DELAY_MIN: int = int(os.getenv("NUDGE_STYLE_DELAY_MIN", "45"))
NUDGE_EMAIL_DELAY_HOURS: int = int(os.getenv("NUDGE_EMAIL_DELAY_HOURS", "24"))
# Пуш старше недели не отправляем, а строку удаляем: человек, молчащий семь
# дней, от догоняющей рекламы не вернётся — это уже спам по мёртвой базе.
NUDGE_MAX_AGE_DAYS: int = int(os.getenv("NUDGE_MAX_AGE_DAYS", "7"))

# ── Cloudflare R2 (перезаливка фото из Telegram, чтобы видел веб) ─
R2_ACCOUNT_ID: str = os.getenv("R2_ACCOUNT_ID", "")
R2_ACCESS_KEY_ID: str = os.getenv("R2_ACCESS_KEY_ID", "")
R2_SECRET_ACCESS_KEY: str = os.getenv("R2_SECRET_ACCESS_KEY", "")
R2_BUCKET_NAME: str = os.getenv("R2_BUCKET_NAME", "simp-dating")
R2_PUBLIC_URL: str = os.getenv("R2_PUBLIC_URL", "")

# ── AI-модерация (Zhipu GLM) ─────────────────────────────────────
# Без ключа модерация в боте работает по словарному фильтру
ZHIPU_API_KEY: str = os.getenv("ZHIPU_API_KEY", "")
# Пусто — SDK идёт на материковый open.bigmodel.cn. Ключ с Z.ai
# (международная площадка Zhipu, регистрация по почте) работает только
# через https://api.z.ai/api/paas/v4 — адрес задаётся этой переменной.
ZHIPU_BASE_URL: str = os.getenv("ZHIPU_BASE_URL", "")
# Имена моделей на площадках расходятся: материк — glm-4-flash /
# glm-4v-flash, на Z.ai бесплатные — glm-4.5-flash / glm-4.6v-flash.
# Дефолты материковые, чтобы существующие ключи работали без правок.
ZHIPU_TEXT_MODEL: str = os.getenv("ZHIPU_TEXT_MODEL", "glm-4-flash")
ZHIPU_VISION_MODEL: str = os.getenv("ZHIPU_VISION_MODEL", "glm-4v-flash")

# ── Антифлуд ─────────────────────────────────────────────────────
# Минимальный интервал между действиями одного пользователя, секунды
THROTTLE_MESSAGE: float = float(os.getenv("THROTTLE_MESSAGE", "0.7"))
THROTTLE_CALLBACK: float = float(os.getenv("THROTTLE_CALLBACK", "0.4"))

# ── Алертинг (Sentry) ────────────────────────────────────────────
# Та же переменная, что у API: один проект Sentry на оба процесса, события
# бота помечены server_name (см. services/alerting.py). Пусто — no-op, но на
# старте о этом предупреждаем: логи Railway эфемерны, и без DSN упавший
# обработчик виден только жалобой пользователя.
SENTRY_DSN: str = os.getenv("SENTRY_DSN", "")

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
