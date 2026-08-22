"""Память о банах, которая переживает удаление аккаунта.

Удаление каскадом стирает баны и жалобы вместе с пользователем. Для App Store
это правильно — удалять надо по-настоящему (5.1.1(v)). Но забаненный этим
пользовался: удалял себя, регистрировался тем же аккаунтом и приходил чистым.

Поэтому храним отдельно и только необходимое — внешнюю привязку входа, причину
и срок. Привязок две: `telegram_id` для бота и Mini App, `apple_id` для
нативного iOS. Каждая хранится своей строкой; ни имени, ни фото, ни переписки —
их удаление остаётся полным.

Срок (`banned_until`) — копия users.banned_until на момент бана: вернувшийся
после удаления аккаунта наследует остаток срока, а не вечность. NULL — вечный
бан; истёкшие строки при проверке не считаются и чистятся лениво.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from models.models import BannedIdentity

logger = logging.getLogger(__name__)


def _dialect_insert(session: AsyncSession):
    """INSERT .. ON CONFLICT нужного диалекта.

    Продакшен — PostgreSQL, тесты — SQLite; конструкция pg-диалекта на SQLite
    не компилируется, и память банов в тестах молча превращалась бы в no-op.
    Оба диалекта дают одинаковый API on_conflict_do_nothing().
    """
    if session.bind is not None and session.bind.dialect.name == "sqlite":
        from sqlalchemy.dialects.sqlite import insert as sqlite_insert
        return sqlite_insert
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    return pg_insert


def _aware(dt: datetime | None) -> datetime | None:
    """SQLite в тестах возвращает naive-даты; в проде колонка tz-aware."""
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


async def remember_ban(
    session: AsyncSession,
    telegram_id: int | None = None,
    apple_id: str | None = None,
    reason: str = "",
    banned_until: datetime | None = None,
) -> None:
    """Запомнить забаненные привязки входа — с текущим сроком.

    Вызывается при каждом бане и записывает все привязки, что есть у человека:
    у пришедшего из App Store это apple_id, у забаненного в боте — telegram_id,
    у входившего обоими способами — обе. Каждая идёт своей строкой, чтобы её
    можно было проверить независимо.

    Повторный бан того же человека ОБНОВЛЯЕТ строку, а не игнорируется:
    лестница удлиняет срок с каждым нарушением, и старая строка с коротким
    (или уже истёкшим) сроком отпускала бы рецидивиста раньше нового срока.
    Поэтому сначала UPDATE, и только для новой привязки — INSERT;
    on_conflict_do_nothing на вставке гасит гонку двух одновременных банов.

    Личности без обеих привязок (гость по коду в dev-режиме) не запоминаются:
    привязки к внешнему аккаунту у них нет, и блокировать нечего.
    """
    reason = reason[:500]
    rows: list[dict] = []
    if telegram_id:
        rows.append({"telegram_id": telegram_id, "apple_id": None})
    if apple_id:
        rows.append({"telegram_id": None, "apple_id": apple_id})
    if not rows:
        return

    insert_stmt = _dialect_insert(session)
    for row in rows:
        try:
            условие = (
                BannedIdentity.telegram_id == row["telegram_id"]
                if row["telegram_id"]
                else BannedIdentity.apple_id == row["apple_id"]
            )
            result = await session.execute(
                update(BannedIdentity)
                .where(условие)
                .values(reason=reason, banned_until=banned_until)
            )
            if result.rowcount == 0:
                await session.execute(
                    insert_stmt(BannedIdentity)
                    .values(reason=reason, banned_until=banned_until, **row)
                    .on_conflict_do_nothing()
                )
        except Exception as e:
            # Бан уже применён к самому пользователю — сбой записи в список не
            # должен отменять его
            logger.error(f"Не удалось запомнить бан {row!r}: {e}")


async def banned_identity_record(
    session: AsyncSession,
    telegram_id: int | None = None,
    apple_id: str | None = None,
) -> BannedIdentity | None:
    """Действующий бан этой привязки входа, если он есть.

    Параметры именованные, потому что перепутать их дорого: строковый apple_id,
    попав в сравнение по BigInteger-колонке telegram_id, не совпадёт никогда
    (обход бана пройдёт), а на asyncpg ещё и уронит запрос. Здесь каждая
    привязка сравнивается со своей колонкой.

    Истёкшие строки не считаются баном и удаляются по пути: отсидевший срок и
    удаливший аккаунт человек должен вернуться чистым, а не ждать, пока кто-то
    вручную почистит список. Из нескольких действующих строк возвращается
    самая строгая — вечная, иначе с самым поздним сроком: наследовать надо
    полный остаток, а не самый короткий.
    """
    conds = []
    if telegram_id:
        conds.append(BannedIdentity.telegram_id == telegram_id)
    if apple_id:
        conds.append(BannedIdentity.apple_id == apple_id)
    if not conds:
        return None

    result = await session.execute(select(BannedIdentity).where(or_(*conds)))
    строки = result.scalars().all()

    now = datetime.now(timezone.utc)
    действующая: BannedIdentity | None = None
    for строка in строки:
        срок = _aware(строка.banned_until)
        if срок is not None and срок <= now:
            await session.delete(строка)
            continue
        if действующая is None:
            действующая = строка
            continue
        текущий = _aware(действующая.banned_until)
        if текущий is not None and (срок is None or срок > текущий):
            действующая = строка
    return действующая


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
