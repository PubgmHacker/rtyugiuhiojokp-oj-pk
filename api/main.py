from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from config import get_settings
from middleware.auth import BANNED_CODE, AccountBannedError
from middleware.rate_limit import RateLimitMiddleware
from routers import (
    auth, profiles, likes, matches, chat, upload, report, admin, blocks, iap, reels,
    leaderboard, photo_ratings, rooms, cases, daily, voice, sections, tarot, habits,
    chat_themes, stories, badges,
)

settings = get_settings()
logging.basicConfig(level=logging.DEBUG if settings.DEBUG else logging.INFO)
logger = logging.getLogger(__name__)


_MIGRATIONS = [
    # Страховка для баз, заведённых до Alembic: идемпотентные ALTER'ы, которые
    # create_all не делает. Основной путь изменения схемы — миграции ниже.
    "ALTER TABLE dating_users ALTER COLUMN telegram_id TYPE BIGINT",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_like_pair ON dating_likes (liker_id, liked_id)",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_match_pair ON dating_matches (user1_id, user2_id)",
]


def _конфиг_alembic():
    """Конфиг alembic с адресом базы из настроек, а не из alembic.ini."""
    from alembic.config import Config

    здесь = Path(__file__).resolve().parent
    cfg = Config(str(здесь / "alembic.ini"))
    cfg.set_main_option("script_location", str(здесь / "migrations"))
    cfg.set_main_option("sqlalchemy.url", settings.DATABASE_URL)
    return cfg


def _применить_миграции() -> None:
    """Накатить миграции Alembic до последней ревизии.

    Без этого 24 файла в migrations/versions лежали мёртвым грузом:
    `create_all` создаёт недостающие таблицы, но НЕ добавляет колонки в уже
    существующие. На пустой базе всё работало, а на боевой новая колонка
    (например, apple_id или email) просто не появлялась, и запросы к ней
    падали в рантайме.

    Блокирующий вызов, поэтому запускается до старта обслуживания запросов.
    Ошибку не глотаем: работать на разъехавшейся схеме хуже, чем не
    подняться, — второе видно сразу, а первое всплывает у пользователей.
    """
    from alembic import command

    command.upgrade(_конфиг_alembic(), "head")


def _отметить_схему_свежей() -> None:
    """Пометить пустую базу как «уже на последней ревизии».

    На чистой базе схему ставит `create_all` по моделям — она по
    определению совпадает с последней ревизией. Прогонять после этого
    всю цепочку нельзя: первая же миграция с `create_table` упала бы на
    только что созданной таблице, а транзакционный DDL Postgres откатил
    бы вместе с ней всю пачку. Поэтому ставим штамп: догонять нечего,
    а следующие миграции найдут точку отсчёта.
    """
    from alembic import command

    command.stamp(_конфиг_alembic(), "head")


async def _уборка_историй(интервал: int = 3600) -> None:
    """Снимать истёкшие истории раз в час, вечно.

    Час, а не сутки: суточный проход копил бы за раз всё опубликованное
    и удалял пачкой в тысячи файлов, а истории — единственный контент со
    сроком, и «исчезло вовремя» здесь часть обещания.

    Каждый проход в своём try: упавший запрос к БД или к R2 не должен
    убивать цикл — иначе одна ночная недоступность хранилища оставляет
    истёкшие истории видимыми до следующего перезапуска процесса.

    Первая пауза идёт до первого прохода: на старте база может быть ещё
    не готова, а уборка — не то, ради чего стоит задерживать запуск.
    """
    from database.connection import async_session_factory
    from services.stories import удалить_истёкшие

    while True:
        try:
            await asyncio.sleep(интервал)
            async with async_session_factory() as session:
                снято = await удалить_истёкшие(session)
                await session.commit()
            if снято:
                logger.info(f"stories janitor: снято {снято}")
        except asyncio.CancelledError:
            # Остановка процесса — выходим молча, не логируя как сбой
            raise
        except Exception as e:
            logger.warning(f"stories janitor failed: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup + shutdown hooks."""
    logger.info("SIMP DATING API starting up...")

    # Без SENTRY_DSN — no-op, поведение не меняется (см. services/alerting.py)
    from services.alerting import init as init_alerting
    init_alerting(settings.SENTRY_DSN)

    if not settings.DEBUG and settings.JWT_SECRET == "change_this_in_production":
        raise RuntimeError(
            "JWT_SECRET is still the default value — set a random secret before running in production"
        )

    # Test DB connection + auto-create tables
    try:
        from sqlalchemy import inspect as sa_inspect
        from sqlalchemy import text as sa_text
        from database.connection import engine
        from models.models import Base

        async with engine.begin() as conn:
            под_alembic = await conn.run_sync(
                lambda c: sa_inspect(c).has_table("alembic_version")
            )

        if под_alembic:
            # База уже версионирована: СНАЧАЛА миграции, потом create_all как
            # страховка для таблиц, которым миграции не завели. Обратный
            # порядок ломал деплой: create_all поднимал новую таблицу по
            # модели, следующая же миграция падала на ней DuplicateTableError,
            # и транзакционный DDL откатывал ВСЮ пачку — включая ревизии,
            # которые добавляли колонки. Схема оставалась старой, а запрос к
            # новой колонке падал у пользователей.
            await asyncio.to_thread(_применить_миграции)
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
        else:
            # Чистая база: схему ставит create_all по моделям и сразу
            # штампуем последнюю ревизию — цепочку догонять нечего.
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            await asyncio.to_thread(_отметить_схему_свежей)

        for stmt in _MIGRATIONS:
            try:
                async with engine.begin() as conn:
                    await conn.execute(sa_text(stmt))
            except Exception as e:
                logger.debug(f"Migration skipped ({stmt[:40]}…): {e}")
        logger.info("PostgreSQL connected, tables ensured")
    except Exception as e:
        logger.warning(f"PostgreSQL not available: {e}")

    # Test Redis connection
    try:
        from services.realtime import get_redis
        r = await get_redis()
        await r.ping()
        logger.info("Redis connected successfully")
    except Exception as e:
        logger.warning(f"Redis not available: {e}")

    # Уборщик историй. Держим ссылку: задача без ссылки может быть собрана
    # сборщиком мусора на середине паузы, и уборка тихо перестанет идти.
    janitor = asyncio.create_task(_уборка_историй(), name="stories-janitor")

    yield

    logger.info("SIMP DATING API shutting down...")

    # Гасим уборщика первым: он берёт сессию из того же пула и лезет в R2,
    # а закрывать пул под работающим запросом — способ получить ошибку
    # в логе на каждой остановке.
    janitor.cancel()
    try:
        await janitor
    except asyncio.CancelledError:
        pass

    from services.push import close as close_push
    from services.realtime import _redis

    # Читатель комнат живёт на том же соединении с Redis. Гасим его ДО
    # закрытия соединения: иначе задача проснётся на мёртвом сокете и
    # уйдёт в цикл переподключения уже во время остановки процесса.
    from services.ws_manager import manager as room_manager
    await room_manager.aclose()

    if _redis:
        await _redis.close()
    await close_push()


app = FastAPI(
    title="Simp Dating API",
    description="API для сервиса знакомств с AI-мэтчами на базе GLM-5.2",
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/docs" if settings.DEBUG else None,
    redoc_url="/redoc" if settings.DEBUG else None,
)

# Лимит частоты запросов на чувствительных путях (жалобы, вход, загрузка).
# Ставится до CORS, чтобы отброшенный запрос не тратил работу приложения.
app.add_middleware(RateLimitMiddleware)

# CORS: авторизация через Bearer-заголовок, куки не используем —
# credentials выключены. Список origin'ов приходит из CORS_ORIGINS,
# в проде звёздочка отбрасывается (см. Settings.cors_origin_list).
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers
app.include_router(auth.router, prefix="/api")
app.include_router(profiles.router, prefix="/api")
app.include_router(likes.router, prefix="/api")
app.include_router(matches.router, prefix="/api")
app.include_router(chat.router)
app.include_router(upload.router, prefix="/api")
app.include_router(report.router, prefix="/api")
app.include_router(blocks.router, prefix="/api")
app.include_router(iap.router, prefix="/api")
app.include_router(reels.router, prefix="/api")
app.include_router(leaderboard.router, prefix="/api")
app.include_router(photo_ratings.router, prefix="/api")
app.include_router(rooms.router, prefix="/api")
app.include_router(cases.router, prefix="/api")
app.include_router(daily.router, prefix="/api")
app.include_router(tarot.router, prefix="/api")
app.include_router(voice.router, prefix="/api")
app.include_router(sections.router, prefix="/api")
app.include_router(habits.router, prefix="/api")
app.include_router(chat_themes.router, prefix="/api")
app.include_router(stories.router, prefix="/api")
app.include_router(badges.router, prefix="/api")
app.include_router(admin.router, prefix="/api")


@app.exception_handler(AccountBannedError)
async def account_banned_handler(request: Request, exc: AccountBannedError):
    """Бан — единственный 403, под который у клиента есть отдельный экран.

    Код кладём рядом с ``detail``, а не внутрь него: ``detail`` остаётся
    строкой, и ни один клиент, который просто её показывает, не ломается.
    Обработчик подобранного класса имеет приоритет над обработчиком
    ``HTTPException`` — Starlette ищет по MRO исключения.
    """
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail, "code": BANNED_CODE},
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    """Логируем стектрейс, наружу отдаём нейтральный текст.

    Без этого FastAPI возвращает пустой 500, а в DEBUG-режиме способен
    показать внутренности приложения.
    """
    logger.exception(f"Необработанная ошибка на {request.method} {request.url.path}: {exc}")
    return JSONResponse(
        status_code=500,
        content={"detail": "Внутренняя ошибка сервера. Попробуйте позже."},
    )


@app.get("/health")
async def health(response: Response):
    """Health-check, который реально проверяет зависимости.

    Railway и балансировщику нужен честный ответ: сервис без БД
    работать не может, поэтому такое состояние отдаём как 503.
    """
    from services.alerting import capture_message

    checks: dict[str, str] = {}

    try:
        from sqlalchemy import text as sa_text
        from database.connection import engine

        async with engine.connect() as conn:
            await conn.execute(sa_text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as e:
        logger.warning(f"Health: база недоступна: {e}")
        checks["database"] = "fail"
        capture_message(f"Health: база недоступна: {e}")

    try:
        from services.realtime import get_redis

        r = await get_redis()
        await r.ping()
        checks["redis"] = "ok"
    except Exception as e:
        logger.warning(f"Health: Redis недоступен: {e}")
        checks["redis"] = "degraded"
        capture_message(f"Health: Redis недоступен: {e}")

    # Без Redis чат теряет real-time, но сервис остаётся работоспособным;
    # без базы — нет
    healthy = checks["database"] == "ok"
    if not healthy:
        response.status_code = 503

    # Модерация фото без AI-ключа пропускает ВСЁ (у текста хотя бы есть
    # словарный фильтр). Сервис при этом работает, поэтому не 503 — но
    # состояние должно быть видно в мониторинге, а не только в логах
    # Алертинг сюда не вешаем: "disabled" — статичное состояние конфигурации
    # (нет ключа), а не сбой, и слать его в Sentry на каждый опрос /health
    # означало бы спам. Настоящий сбой (AI недоступен во время запроса)
    # алертится из services/ai_moderation.py, где он и происходит.
    try:
        from services.ai_moderation import image_moderation_available

        checks["photo_moderation"] = (
            "ok" if image_moderation_available() else "disabled"
        )
    except Exception:
        checks["photo_moderation"] = "unknown"

    # Без TURN голосовая рулетка не соберёт звонок у части людей: симметричный
    # NAT мобильных операторов одним STUN не пробивается. Код готов и ждёт
    # только учётных данных, поэтому состояние видно здесь — иначе «у меня не
    # звонит» приходит жалобами, а не мониторингом
    try:
        from services.voice import turn_configured

        checks["turn"] = "ok" if turn_configured() else "disabled"
    except Exception:
        checks["turn"] = "unknown"

    return {
        "status": "ok" if healthy else "unhealthy",
        "service": "simp-dating-api",
        "checks": checks,
    }


@app.get("/")
async def root():
    return {"service": "Simp Dating API", "version": "0.1.0"}
