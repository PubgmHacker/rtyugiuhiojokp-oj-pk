"""Память о банах, которая переживает удаление аккаунта.

Удаление каскадом стирает баны и жалобы вместе с пользователем. Для App Store
это правильно — удалять надо по-настоящему (5.1.1(v)). Но забаненный этим
пользовался: удалял себя, регистрировался тем же аккаунтом и приходил чистым.

Поэтому храним отдельно и только необходимое — внешнюю привязку входа и причину.
Привязок две: `telegram_id` для бота и Mini App, `apple_id` для нативного iOS.
Каждая хранится своей строкой; ни имени, ни фото, ни переписки — их удаление
остаётся полным.
"""

from __future__ import annotations

import logging

from sqlalchemy import or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from models.models import BannedIdentity

logger = logging.getLogger(__name__)


async def remember_ban(
    session: AsyncSession,
    telegram_id: int | None = None,
    apple_id: str | None = None,
    reason: str = "",
) -> None:
    """Запомнить забаненные привязки входа.

    Вызывается при каждом бане и записывает все привязки, что есть у человека:
    у пришедшего из App Store это apple_id, у забаненного в боте — telegram_id,
    у входившего обоими способами — обе. Каждая идёт своей строкой, чтобы её
    можно было проверить независимо.

    UPSERT без цели по конфликту (`on_conflict_do_nothing`): повторный бан того
    же человека — обычное дело, и падать на уникальном ключе тут незачем.

    Личности без обеих привязок (гость по коду в dev-режиме) не запоминаются:
    привязки к внешнему аккаунту у них нет, и блокировать нечего.
    """
    reason = reason[:500]
    rows: list[dict] = []
    if telegram_id:
        rows.append({"telegram_id": telegram_id, "apple_id": None, "reason": reason})
    if apple_id:
        rows.append({"telegram_id": None, "apple_id": apple_id, "reason": reason})
    if not rows:
        return

    for row in rows:
        try:
            await session.execute(
                pg_insert(BannedIdentity).values(**row).on_conflict_do_nothing()
            )
        except Exception as e:
            # Бан уже применён к самому пользователю — сбой записи в список не
            # должен отменять его
            logger.error(f"Не удалось запомнить бан {row!r}: {e}")


async def is_banned_identity(
    session: AsyncSession,
    telegram_id: int | None = None,
    apple_id: str | None = None,
) -> bool:
    """Проверить, не забанена ли ранее эта привязка входа.

    Параметры именованные, потому что перепутать их дорого: строковый apple_id,
    попав в сравнение по BigInteger-колонке telegram_id, не совпадёт никогда
    (обход бана пройдёт), а на asyncpg ещё и уронит запрос. Здесь каждая
    привязка сравнивается со своей колонкой.
    """
    conds = []
    if telegram_id:
        conds.append(BannedIdentity.telegram_id == telegram_id)
    if apple_id:
        conds.append(BannedIdentity.apple_id == apple_id)
    if not conds:
        return False

    result = await session.execute(select(BannedIdentity.id).where(or_(*conds)))
    return result.scalar_one_or_none() is not None


async def forgive(
    session: AsyncSession,
    telegram_id: int | None = None,
    apple_id: str | None = None,
) -> None:
    """Убрать привязки из списка — при разбане.

    Без этого разбан работал бы только до первого удаления аккаунта: сам
    пользователь разбанен, а его привязки остались в списке. Чистим обе, чтобы
    разбан не зависел от того, каким входом человек вернётся.
    """
    conds = []
    if telegram_id:
        conds.append(BannedIdentity.telegram_id == telegram_id)
    if apple_id:
        conds.append(BannedIdentity.apple_id == apple_id)
    if not conds:
        return

    from sqlalchemy import delete

    await session.execute(delete(BannedIdentity).where(or_(*conds)))
