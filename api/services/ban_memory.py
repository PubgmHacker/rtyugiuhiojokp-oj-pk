"""Память о банах, которая переживает удаление аккаунта.

Удаление каскадом стирает баны и жалобы вместе с пользователем. Для App Store
это правильно — удалять надо по-настоящему (5.1.1(v)). Но забаненный этим
пользовался: удалял себя, регистрировался тем же Telegram-аккаунтом и приходил
чистым.

Поэтому храним отдельно и только необходимое: `telegram_id` и причину. Ни
имени, ни фото, ни переписки — их удаление остаётся полным.
"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from models.models import BannedIdentity

logger = logging.getLogger(__name__)


async def remember_ban(
    session: AsyncSession, telegram_id: int | None, reason: str = ""
) -> None:
    """Запомнить забаненный Telegram-аккаунт.

    Вызывается при каждом бане. UPSERT, потому что повторный бан того же
    человека — обычное дело, и падать на уникальном ключе тут незачем.

    Пользователи без telegram_id (вход по коду в dev-режиме) не запоминаются:
    привязки к внешнему аккаунту у них нет, и блокировать нечего.
    """
    if not telegram_id:
        return

    try:
        await session.execute(
            pg_insert(BannedIdentity)
            .values(telegram_id=telegram_id, reason=reason[:500])
            .on_conflict_do_nothing(constraint="uq_banned_telegram")
        )
    except Exception as e:
        # Бан уже применён к самому пользователю — сбой записи в список не
        # должен отменять его
        logger.error(f"Не удалось запомнить бан telegram_id={telegram_id}: {e}")


async def is_banned_identity(session: AsyncSession, telegram_id: int | None) -> bool:
    """Проверить, не забанен ли этот Telegram-аккаунт ранее."""
    if not telegram_id:
        return False

    result = await session.execute(
        select(BannedIdentity.id).where(BannedIdentity.telegram_id == telegram_id)
    )
    return result.scalar_one_or_none() is not None


async def forgive(session: AsyncSession, telegram_id: int | None) -> None:
    """Убрать из списка — при разбане.

    Без этого разбан работал бы только до первого удаления аккаунта: сам
    пользователь разбанен, а его Telegram-аккаунт остался в списке.
    """
    if not telegram_id:
        return

    from sqlalchemy import delete

    await session.execute(
        delete(BannedIdentity).where(BannedIdentity.telegram_id == telegram_id)
    )
