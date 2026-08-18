"""Smoke-тесты: приложение собирается, ключевые контракты на месте.

Эти тесты защищают от регрессий, которые уже случались в проекте:
пропавший роут, сломанная схема, wildcard в CORS на продакшене.
"""

from __future__ import annotations

import pytest


# ── Приложение и роуты ──────────────────────────────────────────

def test_app_imports(app):
    assert app.title


@pytest.mark.parametrize(
    "path,method",
    [
        ("/health", "get"),
        ("/api/auth/telegram", "post"),
        ("/api/profiles/me", "get"),
        ("/api/profiles/me", "patch"),
        # Удаление аккаунта — требование App Store 5.1.1(v)
        ("/api/profiles/me", "delete"),
        ("/api/profiles/deck", "get"),
        ("/api/likes", "post"),
        ("/api/matches", "get"),
        ("/api/report", "post"),
        ("/api/upload/photo", "post"),
    ],
)
def test_route_exists(openapi, path, method):
    assert path in openapi["paths"], f"нет роута {path}"
    assert method in openapi["paths"][path], f"{path} не поддерживает {method.upper()}"


def test_account_deletion_available(openapi):
    """Без этого Apple отклоняет приложение — проверяем отдельно и явно."""
    assert "delete" in openapi["paths"]["/api/profiles/me"]


# ── Настройки ───────────────────────────────────────────────────

def test_cors_rejects_wildcard_in_production():
    from config import Settings

    prod = Settings(DEBUG=False, CORS_ORIGINS="*,https://simp.app")
    assert "*" not in prod.cors_origin_list
    assert "https://simp.app" in prod.cors_origin_list


def test_cors_never_empty():
    from config import Settings

    assert Settings(DEBUG=False, CORS_ORIGINS="").cors_origin_list


def test_docs_hidden_when_not_debug():
    """Открытая /docs на проде — лишняя поверхность атаки."""
    import importlib
    import config as config_module

    config_module.get_settings.cache_clear()
    try:
        import os

        os.environ["DEBUG"] = "false"
        os.environ["JWT_SECRET"] = "test_secret_not_for_production"
        main = importlib.reload(importlib.import_module("main"))
        assert main.app.docs_url is None
        assert main.app.redoc_url is None
    finally:
        os.environ["DEBUG"] = "true"
        config_module.get_settings.cache_clear()
        importlib.reload(importlib.import_module("main"))


def test_admin_id_parsing():
    from config import Settings

    assert Settings(ADMIN_IDS="1, 22 ,notanumber,333").admin_id_list == [1, 22, 333]


def test_age_limits_match_product_policy():
    from config import get_settings

    # Политика продукта — 16+ (см. Login, онбординг, бот). App Store рейтинг
    # 18+ живёт отдельно в APPSTORE.md и сюда не подмешивается.
    assert get_settings().MIN_AGE == 16


# ── Схемы ───────────────────────────────────────────────────────

def test_profile_update_rejects_underage():
    from models.schemas import ProfileUpdate

    ok = ProfileUpdate(age_min=18, age_max=40)
    assert ok.age_min == 18


def test_deck_profile_schema_shape():
    from models.schemas import DeckProfile

    fields = DeckProfile.model_fields
    for required in ("id", "display_name", "photos"):
        assert required in fields, f"в DeckProfile нет поля {required}"


# ── Утилиты ─────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "raw,expected",
    [
        ('["a","b"]', ["a", "b"]),
        (["a"], ["a"]),
        (None, []),
        ("", []),
        ("не json", []),
    ],
)
def test_as_list_handles_all_shapes(raw, expected):
    """photos/interests приходят и списком, и JSON-строкой из старых записей."""
    from utils import as_list

    assert as_list(raw) == expected
