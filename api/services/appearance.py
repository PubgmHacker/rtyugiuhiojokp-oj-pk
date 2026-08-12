"""Схемы оформления приложения — вкус, который переезжает с человеком.

Палитры живут на клиенте: это презентация, и сервер не должен знать
шестнадцатеричные цвета. Здесь только имена схем и право на них —
чтобы выбор не терялся при смене устройства и чтобы платные схемы не
включались правкой localStorage.
"""
from __future__ import annotations

from services.plans import tier_allows

#: Все схемы. Порядок = порядок в списке выбора.
THEME_KEYS: tuple[str, ...] = (
    "dawn", "midnight", "graphite", "light", "sepia", "nebula", "goldleaf",
)

#: Схема по умолчанию — базовые токены дизайн-системы.
DEFAULT_THEME = "dawn"

#: Платные. Ровно две: оформление продаётся плохо, если бесплатных мало,
#: и человек решает, что приложение выкрашено в подписку.
PREMIUM_THEMES: frozenset[str] = frozenset({"nebula", "goldleaf"})


def нормализовать(key: str | None) -> str:
    """Незнакомая схема — базовая. Так старый клиент, приславший
    выпиленную схему, получает рабочий экран, а не 422."""
    if not key:
        return DEFAULT_THEME
    return key if key in THEME_KEYS else DEFAULT_THEME


def доступна(key: str, tier: str) -> bool:
    if key not in THEME_KEYS:
        return False
    if key in PREMIUM_THEMES:
        return tier_allows(tier, "appearance_premium")
    return True
