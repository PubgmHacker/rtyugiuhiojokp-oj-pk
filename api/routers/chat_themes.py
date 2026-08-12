"""Ручки темы чата. Право доступа — участие в паре, ничего сверх.

Проверку участия берём из matches: своя копия условия разъехалась бы с
основной при первом же изменении правил (так уже было с возрастом,
который считали в двух местах).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from database.connection import get_session
from middleware.auth import get_current_user
from models.models import User
from models.schemas import (
    ChatThemeOut, ChatThemePreset, ChatThemePresets, ChatThemeSet,
)
from routers.matches import _get_own_match
from services import chat_themes
from services.plans import tier_allows
from services.premium import current_tier

router = APIRouter(prefix="/chat-themes", tags=["chat-themes"])


def _out(match_id: str, theme) -> ChatThemeOut:
    if theme is None:
        return ChatThemeOut(match_id=match_id)
    return ChatThemeOut(
        match_id=match_id,
        bubble_mine_color=theme.bubble_mine_color,
        bubble_theirs_color=theme.bubble_theirs_color,
        background_color=theme.background_color,
        pattern_key=theme.pattern_key,
    )


@router.get("/presets", response_model=ChatThemePresets)
async def list_presets(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Каталог тем с пометкой, что закрыто на текущем уровне."""
    tier = await current_tier(session, user.id)
    return ChatThemePresets(
        presets=[ChatThemePreset(**p) for p in chat_themes.каталог(tier)],
        tier=tier,
        custom_allowed=tier_allows(tier, "chat_theme_custom"),
    )


@router.get("/{match_id}", response_model=ChatThemeOut)
async def get_theme(
    match_id: str,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Тема пары. Незаданная отдаётся пустой, а не 404: «нет темы» —
    нормальное состояние чата, а не ошибка."""
    await _get_own_match(session, match_id, user.id)
    return _out(match_id, await chat_themes.получить(session, match_id))


@router.put("/{match_id}", response_model=ChatThemeOut)
async def set_theme(
    match_id: str,
    data: ChatThemeSet,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Поставить тему на пару — обоим сразу.

    Согласия второго не спрашиваем: тема обратима одним нажатием, а
    диалог «партнёр предлагает тему» на такой мелочи — лишний шаг,
    который люди закрывают не читая.
    """
    await _get_own_match(session, match_id, user.id)
    tier = await current_tier(session, user.id)

    свои = any((
        data.bubble_mine_color, data.bubble_theirs_color,
        data.background_color, data.pattern_key,
    ))
    if data.preset and свои:
        raise HTTPException(
            status_code=422, detail="Либо пресет, либо свои цвета — не оба сразу"
        )

    try:
        if data.preset:
            theme = await chat_themes.применить_пресет(
                session, match_id, data.preset, tier
            )
        elif свои:
            theme = await chat_themes.применить_свои(
                session, match_id, tier,
                bubble_mine=data.bubble_mine_color,
                bubble_theirs=data.bubble_theirs_color,
                background=data.background_color,
                pattern=data.pattern_key,
            )
        else:
            raise HTTPException(status_code=422, detail="Нечего применять")
    except chat_themes.ТемаОтклонена as exc:
        # 403 для «нужен уровень выше», 400 для битого значения: клиенту
        # надо различать «покажи экран подписки» и «поправь ввод».
        код = 403 if "доступн" in str(exc) else 400
        raise HTTPException(status_code=код, detail=str(exc)) from exc

    await session.commit()
    return _out(match_id, theme)


@router.delete("/{match_id}", response_model=ChatThemeOut)
async def reset_theme(
    match_id: str,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Вернуть базовое оформление."""
    await _get_own_match(session, match_id, user.id)
    await chat_themes.сбросить(session, match_id)
    await session.commit()
    return ChatThemeOut(match_id=match_id)
