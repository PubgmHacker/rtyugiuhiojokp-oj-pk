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


@pytest.fixture(scope="session")
def openapi(app):
    return app.openapi()


@pytest.fixture
def settings():
    from config import get_settings

    return get_settings()
