"""Исполнение рассылки, созданной в админке.

Задачу ставит API (POST /api/admin/broadcast): пишет строку в
dating_broadcasts и публикует событие в dating:bot:events. Здесь — вторая
половина: выбрать получателей, разослать с оглядкой на лимиты Telegram и
вести счётчики в той же строке, чтобы админка видела прогресс.

Рассылка идёт отдельной asyncio-задачей, НЕ в цикле подписчика: на десяти
тысячах получателей отправка занимает минуты, и всё это время мэтчи, лайки
и баны должны ходить как обычно.
"""
from __future__ import annotations

import asyncio
import html
import logging
from datetime import datetime, timezone

from aiogram.exceptions import TelegramRetryAfter
from sqlalchemy import select

from database.connection import _session_cls
from database.models import Broadcast, User

logger = logging.getLogger(__name__)

#: ~20 сообщений в секунду — с запасом ниже лимита Telegram (30/с),
#: чтобы обычные уведомления бота не упирались в тот же лимит.
ПАУЗА_МЕЖДУ_ОТПРАВКАМИ = 0.05
#: Как часто счётчики уезжают в БД. Каждую отправку — лишний UPDATE
#: на сообщение; реже — прогресс в админке застывает.
ШАГ_ОТЧЁТА = 25


async def run_broadcast(bot, broadcast_id: str) -> None:
    """Разослать одну рассылку от начала до конца.

    Повторное событие с тем же id безвредно: статус уже не queued — выход.
    Любое падение целиком (БД пропала, бот остановлен) оставляет статус
    error, а не вечный running.
    """
    try:
        задача = await _взять_в_работу(broadcast_id)
        if задача is None:
            return
        текст, чаты = задача

        # Telegram у бота по умолчанию parse_mode=HTML — сырые < > & из
        # админки ломали бы отправку. Экранируем: текст уходит как написан,
        # без разметки. Длину с учётом экранирования проверил API.
        экранированный = html.escape(текст, quote=False)

        sent = failed = 0
        for номер, chat_id in enumerate(чаты, start=1):
            if await _отправить(bot, chat_id, экранированный):
                sent += 1
            else:
                failed += 1
            if номер % ШАГ_ОТЧЁТА == 0:
                await _записать_прогресс(broadcast_id, sent, failed)
            await asyncio.sleep(ПАУЗА_МЕЖДУ_ОТПРАВКАМИ)

        await _записать_прогресс(broadcast_id, sent, failed, статус="done")
        logger.info(
            f"Рассылка {broadcast_id} завершена: {sent} доставлено, {failed} нет"
        )
    except asyncio.CancelledError:
        # Бот останавливается: недосланная рассылка — error, перезапуск
        # с середины не строим (дубли хуже недосыла)
        await _записать_прогресс(broadcast_id, статус="error")
        raise
    except Exception as e:
        logger.error(f"Рассылка {broadcast_id} упала: {e}")
        await _записать_прогресс(broadcast_id, статус="error")


async def _взять_в_работу(broadcast_id: str) -> tuple[str, list[int]] | None:
    """Перевести queued → running и вернуть (текст, получатели)."""
    cls = _session_cls()
    async with cls() as session:
        рассылка = await session.get(Broadcast, broadcast_id)
        if рассылка is None:
            logger.error(f"Рассылка {broadcast_id} не найдена — событие без строки")
            return None
        if рассылка.status != "queued":
            logger.info(
                f"Рассылка {broadcast_id} уже {рассылка.status} — дубль события"
            )
            return None

        if рассылка.segment == "test":
            # Только создателю: посмотреть сообщение глазами получателя
            условие = User.id == рассылка.created_by
        else:
            условие = User.is_banned == False  # noqa: E712

        result = await session.execute(
            select(User.telegram_id).where(
                User.telegram_id.is_not(None), условие
            )
        )
        чаты = [chat_id for (chat_id,) in result.all()]

        рассылка.status = "running"
        рассылка.total = len(чаты)
        рассылка.started_at = datetime.now(timezone.utc)
        await session.commit()
        return рассылка.text, чаты


async def _отправить(bot, chat_id: int, текст: str) -> bool:
    """Одно сообщение одному человеку. Flood-лимит пережидаем один раз;
    остальное (бот заблокирован, чат умер) — честный failed."""
    try:
        await bot.send_message(chat_id=chat_id, text=текст)
        return True
    except TelegramRetryAfter as e:
        await asyncio.sleep(e.retry_after + 1)
        try:
            await bot.send_message(chat_id=chat_id, text=текст)
            return True
        except Exception as повторно:
            logger.warning(f"Рассылка в чат {chat_id} не ушла после паузы: {повторно}")
            return False
    except Exception as e:
        logger.debug(f"Рассылка в чат {chat_id} не ушла: {e}")
        return False


async def _записать_прогресс(
    broadcast_id: str,
    sent: int | None = None,
    failed: int | None = None,
    статус: str | None = None,
) -> None:
    """Обновить счётчики/статус. Сбой записи не роняет рассылку: людям
    сообщения важнее, чем админке прогресс-бар."""
    try:
        cls = _session_cls()
        async with cls() as session:
            рассылка = await session.get(Broadcast, broadcast_id)
            if рассылка is None:
                return
            if sent is not None:
                рассылка.sent = sent
            if failed is not None:
                рассылка.failed = failed
            if статус is not None:
                # error не затирает done: отмена после финала — не авария
                if рассылка.status in ("queued", "running"):
                    рассылка.status = статус
                    рассылка.finished_at = datetime.now(timezone.utc)
            await session.commit()
    except Exception as e:
        logger.warning(f"Прогресс рассылки {broadcast_id} не записан: {e}")
