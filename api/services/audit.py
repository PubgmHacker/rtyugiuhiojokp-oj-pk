"""Запись в журнал действий админов (models.AdminAuditLog).

Одна функция на все ручки админки: собирает снапшоты имён и кладёт запись
в ТУ ЖЕ сессию, что и само действие. Никаких своих commit — атомарность
с действием обеспечивает транзакция запроса: откат отменяет и запись.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.models import AdminAuditLog, Profile, User


async def write_audit(
    session: AsyncSession,
    admin: User,
    action: str,
    *,
    target: User | None = None,
    details: dict | None = None,
) -> None:
    """Добавить запись журнала в текущую транзакцию.

    Имена берутся снапшотами прямо сейчас: журнал должен остаться
    читабельным и после удаления аккаунтов (в модели нет FK — каскад
    историю не тронет, но и имён взять будет больше неоткуда).
    """
    ids = [admin.id] + ([target.id] if target is not None else [])
    result = await session.execute(
        select(Profile.user_id, Profile.display_name).where(Profile.user_id.in_(ids))
    )
    имена = {user_id: display_name or "" for user_id, display_name in result.all()}

    session.add(AdminAuditLog(
        admin_id=admin.id,
        admin_name=имена.get(admin.id, ""),
        action=action,
        target_user_id=target.id if target is not None else "",
        target_name=имена.get(target.id, "") if target is not None else "",
        details=details or {},
    ))
    await session.flush()
