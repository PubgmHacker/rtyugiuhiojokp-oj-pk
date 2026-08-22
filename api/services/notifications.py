"""Запись в центр уведомлений.

Пишется всегда в сессии события, никакого best-effort: уведомление об
итоге жалобы без самой жалобы — или жалоба, чей итог молча потерялся, —
хуже, чем ничего. Откат события откатывает и его уведомление, ровно как
запись журнала модерации.

Что сюда попадает, а что нет — решает один вопрос: есть ли у события свой
экран с бейджем. Мэтчи, лайки и сообщения в ленту не пишутся (их считает
routers/badges.py), см. докстринг модели Notification.

Тексты живут на клиенте (web/src/pages/Notifications.tsx): API не знает
ни языка интерфейса, ни разметки — сюда идут только код вида и детали.
"""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from models.models import Notification

#: Виды, которые умеет показывать клиент. Новый вид добавляется здесь и в
#: текстах клиента; опечатка в вызове роняет тест, а не молча копит строки,
#: которые никто никогда не увидит.
ВИДЫ = ("report_outcome", "verification_approved")


async def записать_уведомление(
    session: AsyncSession,
    user_id: str,
    kind: str,
    payload: dict | None = None,
) -> Notification:
    """Положить событие в ленту получателя. Флашит, но не коммитит —
    транзакцией владеет вызывающий."""
    if kind not in ВИДЫ:
        raise ValueError(f"Неизвестный вид уведомления: {kind!r}")
    уведомление = Notification(user_id=user_id, kind=kind, payload=payload or {})
    session.add(уведомление)
    await session.flush()
    return уведомление
