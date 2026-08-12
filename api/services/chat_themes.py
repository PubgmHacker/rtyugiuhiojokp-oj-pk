"""Темы чата — общее оформление пары, а не настройка одного устройства.

Тема одна на match и видна обоим: в этом её смысл. Локальная тема в
localStorage — украшение для себя; общая становится маленьким общим
предметом, который у пары появляется на второй неделе переписки, и
терять его при переустановке приложения обидно.

Цвет уезжает в атрибут style на клиенте, поэтому формат проверяем здесь,
на входе: «#rrggbb» и ничего кроме. Узор — только ключ из списка, каждому
на клиенте отвечает готовый рисунок.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.models import ChatThemeSettings
from services.plans import (
    TIER_AURORA, TIER_FREE, TIER_PLUS, TIER_ULTRA, tier_allows, tier_rank,
)

_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")

#: Узоры фона. Произвольную строку не принимаем по той же причине, что и
#: произвольный цвет: она попадёт в разметку.
PATTERNS: frozenset[str] = frozenset(
    {"none", "hearts", "dots", "waves", "stars", "grid"}
)


@dataclass(frozen=True)
class Пресет:
    """Готовая тема. `min_tier = free` — доступна всем."""

    key: str
    name: str
    bubble_mine: str
    bubble_theirs: str
    background: str
    pattern: str
    min_tier: str = TIER_FREE


#: Бесплатных больше половины намеренно: тема — повод вернуться в чат и
#: поменять что-то вдвоём, а не витрина платного. Платные отличаются
#: характером, а не «тем же, но красивее».
PRESETS: tuple[Пресет, ...] = (
    Пресет("dawn", "Рассвет", "#ff2d6f", "#1c1f28", "#0a0b0f", "none"),
    Пресет("night", "Ночь", "#3b4a6b", "#16181f", "#07080c", "stars"),
    Пресет("mint", "Мята", "#1f7a63", "#171c1b", "#080d0c", "dots"),
    Пресет("sand", "Песок", "#8a6a3a", "#1e1b16", "#0d0b08", "waves"),
    Пресет("ink", "Графит", "#4a4f5e", "#191b21", "#090a0d", "grid"),
    Пресет("paper", "Бумага", "#2f6bd8", "#eef0f4", "#f7f8fa", "none"),
    Пресет("violet", "Ирис", "#7b3ff2", "#1b1726", "#0b0812", "dots", TIER_PLUS),
    Пресет("coral", "Коралл", "#ff5c3a", "#241a17", "#0f0907", "hearts", TIER_PLUS),
    Пресет("aurora", "Аврора", "#00c2a8", "#122024", "#060f11", "waves", TIER_ULTRA),
    Пресет("gold", "Золото", "#c8a23c", "#221d12", "#100d06", "stars", TIER_AURORA),
)

PRESETS_BY_KEY: dict[str, Пресет] = {p.key: p for p in PRESETS}

#: Что отдаём, когда пара ничего не выбирала. Совпадает с базовыми токенами
#: интерфейса, поэтому «не выбрано» и «Рассвет» выглядят одинаково и клиенту
#: не нужна отдельная ветка на пустоту.
DEFAULT_KEY = "dawn"


class ТемаОтклонена(ValueError):
    """Цвет, узор или уровень подписки не прошли проверку."""


def _цвет(value: str | None, field: str) -> str | None:
    """Пустая строка — осознанное «убрать», а не ошибка."""
    if not value:
        return None
    if not _HEX.match(value):
        raise ТемаОтклонена(f"{field}: ожидается цвет вида #rrggbb")
    return value.lower()


def _узор(value: str | None) -> str | None:
    if not value:
        return None
    if value not in PATTERNS:
        raise ТемаОтклонена("Неизвестный узор фона")
    return value


def каталог(tier: str) -> list[dict]:
    """Пресеты для клиента. Закрытые отдаём тоже, но помечаем `locked`:
    спрятать платную тему значит спрятать причину её купить."""
    rank = tier_rank(tier)
    return [
        {
            "key": p.key,
            "name": p.name,
            "bubble_mine_color": p.bubble_mine,
            "bubble_theirs_color": p.bubble_theirs,
            "background_color": p.background,
            "pattern_key": p.pattern,
            "min_tier": p.min_tier,
            "locked": tier_rank(p.min_tier) > rank,
        }
        for p in PRESETS
    ]


async def получить(session: AsyncSession, match_id: str) -> ChatThemeSettings | None:
    result = await session.execute(
        select(ChatThemeSettings).where(ChatThemeSettings.match_id == match_id)
    )
    return result.scalar_one_or_none()


async def _строка(session: AsyncSession, match_id: str) -> ChatThemeSettings:
    theme = await получить(session, match_id)
    if theme is None:
        theme = ChatThemeSettings(match_id=match_id)
        session.add(theme)
        await session.flush()
    return theme


async def применить_пресет(
    session: AsyncSession, match_id: str, key: str, tier: str
) -> ChatThemeSettings:
    """Разложить пресет по колонкам.

    Храним значения, а не ключ: пресет когда-нибудь перекрасят или уберут
    из каталога, и пара, выбравшая его год назад, не должна из-за этого
    увидеть чужой чат.
    """
    preset = PRESETS_BY_KEY.get(key)
    if preset is None:
        raise ТемаОтклонена("Такой темы нет")
    if tier_rank(preset.min_tier) > tier_rank(tier):
        raise ТемаОтклонена(f"Тема «{preset.name}» доступна на уровне выше")

    theme = await _строка(session, match_id)
    theme.bubble_mine_color = preset.bubble_mine
    theme.bubble_theirs_color = preset.bubble_theirs
    theme.background_color = preset.background
    theme.pattern_key = preset.pattern
    await session.flush()
    return theme


async def применить_свои(
    session: AsyncSession,
    match_id: str,
    tier: str,
    *,
    bubble_mine: str | None,
    bubble_theirs: str | None,
    background: str | None,
    pattern: str | None,
) -> ChatThemeSettings:
    """Произвольные цвета — платная возможность уровня Plus."""
    if not tier_allows(tier, "chat_theme_custom"):
        raise ТемаОтклонена("Свои цвета доступны с подпиской Plus")

    theme = await _строка(session, match_id)
    theme.bubble_mine_color = _цвет(bubble_mine, "bubble_mine_color")
    theme.bubble_theirs_color = _цвет(bubble_theirs, "bubble_theirs_color")
    theme.background_color = _цвет(background, "background_color")
    theme.pattern_key = _узор(pattern)
    await session.flush()
    return theme


async def сбросить(session: AsyncSession, match_id: str) -> None:
    """Вернуть чат к базовому оформлению. Строку не удаляем — обнуляем:
    удаление гоняло бы вставку туда-обратно на каждом переключении."""
    theme = await получить(session, match_id)
    if theme is None:
        return
    theme.bubble_mine_color = None
    theme.bubble_theirs_color = None
    theme.background_color = None
    theme.pattern_key = None
    await session.flush()
