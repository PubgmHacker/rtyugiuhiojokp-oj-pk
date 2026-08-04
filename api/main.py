from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, WebSocketDisconnect, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from config import get_settings
from routers import auth, profiles, likes, matches, chat, upload, report, admin, blocks

settings = get_settings()
logging.basicConfig(level=logging.DEBUG if settings.DEBUG else logging.INFO)
logger = logging.getLogger(__name__)


_MIGRATIONS = [
    # create_all не меняет существующие таблицы — минимальные идемпотентные ALTER'ы
    "ALTER TABLE dating_users ALTER COLUMN telegram_id TYPE BIGINT",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_like_pair ON dating_likes (liker_id, liked_id)",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_match_pair ON dating_matches (user1_id, user2_id)",
]


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup + shutdown hooks."""
    logger.info("SOULDAWN DATING API starting up...")

    if not settings.DEBUG and settings.JWT_SECRET == "change_this_in_production":
        raise RuntimeError(
            "JWT_SECRET is still the default value — set a random secret before running in production"
        )

    # Test DB connection + auto-create tables
    try:
        from sqlalchemy import text as sa_text
        from database.connection import engine
        from models.models import Base
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
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

    yield

    logger.info("SOULDAWN DATING API shutting down...")
    from services.realtime import _redis
    if _redis:
        await _redis.close()


app = FastAPI(
    title="Souldawn Dating API",
    description="API для сервиса знакомств с AI-мэтчами на базе GLM-5.2",
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/docs" if settings.DEBUG else None,
    redoc_url="/redoc" if settings.DEBUG else None,
)

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
app.include_router(admin.router, prefix="/api")


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

    try:
        from services.realtime import get_redis

        r = await get_redis()
        await r.ping()
        checks["redis"] = "ok"
    except Exception as e:
        logger.warning(f"Health: Redis недоступен: {e}")
        checks["redis"] = "degraded"

    # Без Redis чат теряет real-time, но сервис остаётся работоспособным;
    # без базы — нет
    healthy = checks["database"] == "ok"
    if not healthy:
        response.status_code = 503

    return {
        "status": "ok" if healthy else "unhealthy",
        "service": "souldawn-dating-api",
        "checks": checks,
    }


@app.get("/")
async def root():
    return {"service": "Souldawn Dating API", "version": "0.1.0"}
