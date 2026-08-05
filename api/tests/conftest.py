"""Общие фикстуры тестов.

Тесты не требуют поднятого PostgreSQL и Redis: приложение переживает их
отсутствие (см. lifespan в main.py), а smoke-проверки касаются схем,
роутов и настроек.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

API_ROOT = Path(__file__).resolve().parent.parent
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

# Настройки читаются на импорте модулей, поэтому задаём окружение раньше
os.environ.setdefault("DEBUG", "true")
os.environ.setdefault("JWT_SECRET", "test_secret_not_for_production")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5433/test")


@pytest.fixture(scope="session")
def app():
    from main import app as fastapi_app

    return fastapi_app


@pytest.fixture(autouse=True)
def _без_общего_лимитера(monkeypatch):
    """Счётчики частоты — на каждый тест свои.

    Лимиты живут в Redis (middleware/rate_limit.py), и если на машине поднят
    docker compose, счётчики переживают прогон: у `/api/reels` лимит 20 в час,
    поэтому тесты публикации ролика зеленели на чистой базе и падали с 429
    после нескольких прогонов подряд. Тест не должен зависеть от того, гонял
    ли его кто-то полчаса назад.

    Подменяем хранилище на словарь в памяти, живущий ровно один тест. Сам
    лимитер при этом проверяется по-настоящему: логика окна и подсчёта его,
    подменено только хранилище.
    """
    счётчики: dict[str, int] = {}

    class _RedisВПамяти:
        async def incr(self, key: str) -> int:
            счётчики[key] = счётчики.get(key, 0) + 1
            return счётчики[key]

        async def expire(self, *_a, **_kw) -> None:
            """Окно и так не переживает тест — чистить нечего."""

    async def _get_redis():
        return _RedisВПамяти()

    import middleware.rate_limit as rl

    monkeypatch.setattr(rl, "get_redis", _get_redis)


@pytest.fixture(scope="session")
def openapi(app):
    return app.openapi()


@pytest.fixture
def settings():
    from config import get_settings

    return get_settings()
