"""Доставка сообщения в личный чат: запись, realtime и уведомления.

Сообщение в личку рождается в трёх местах — из WebSocket (`routers/chat.py`),
из HTTP-отправки (`routers/matches.py`) и из пересыла ролика
(`routers/reels.py`). Пока путь был один, фан-аут жил прямо в обработчике
сокета; второй источник его не повторил, и пересланный ролик молча ложился в
базу: собеседник с открытым чатом ничего не видел, пуш не уходил, бот не
узнавал. Это тот же сорт расхождения, что аудит нашёл в `hide_age` —
правильный код есть, но ровно в одной копии.

Поэтому запись и фан-аут лежат здесь, а роутеры только вызывают. Порядок
важен: сначала коммит, потом рассылка. Событие о несохранённом сообщении хуже,
чем сохранённое сообщение без события, — второе исправит перезагрузка чата.

По той же причине здесь живут и ПРАВИЛА отправки — чужая картинка и «одно
письмо до ответа». Пока они стояли в роутерах, каждый новый путь заводил свою
копию или обходился без них: сокет проверял картинку, HTTP — нет; HTTP
проверял письмо, `POST /matches/direct` — нет. Здесь же они проверяются в ТОЙ
ЖЕ транзакции, что и вставка сообщения, поэтому между проверкой и записью не
может вклиниться параллельный запрос.
"""

from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy import and_, select
from sqlalchemy import text as sa_text

from database.connection import async_session_factory
from models.models import Match, Message, Profile, Reel
from services.direct_messages import (
    DirectDenied,
    can_send_message,
    mark_answered_if_needed,
)
from services.public_profile import наша_картинка
from services.push import is_configured, notify_new_message
from services.realtime import publish_bot_event
from services.streaks import touch_streak_for_message
from services.ws_manager import manager

logger = logging.getLogger(__name__)

#: Чем короткое уведомление подписывает пересланный ролик. В пуше и в Telegram
#: нельзя показать само видео, а «прислал сообщение» без подписи непонятно.
REEL_FALLBACK_TEXT = "прислал видео"

#: Картинка принимается только из нашего хранилища. Пакет собирает клиент, и в
#: обход интерфейса (загрузки фото в чат в нём нет) сюда можно было положить
#: ссылку на что угодно: она показывалась собеседнику как <img>, не увидев ни
#: AI-модерации, ни санитайзера.
DENIED_FOREIGN_IMAGE = DirectDenied(
    "foreign_image", "Картинку можно отправить только загрузкой"
)


class ДоставкаОтклонена(Exception):
    """Сообщение не сохранено: правило чата не пропустило.

    Исключение, а не `None`, потому что `None` у `save_message` уже занят
    другим смыслом («мэтча больше нет»), а звать эти случаи одинаково значило
    бы показать человеку «чат не найден» вместо настоящей причины.
    """

    def __init__(self, отказ: DirectDenied) -> None:
        super().__init__(отказ.detail)
        self.отказ = отказ

    @property
    def code(self) -> str:
        return self.отказ.code

    @property
    def detail(self) -> str:
        return self.отказ.detail


def reel_preview(reel: Reel | None) -> dict | None:
    """Превью ролика для сообщения — единая форма для REST и для WebSocket.

    Скрытый модерацией ролик не отдаём даже в старой переписке: снятое с показа
    видео не должно продолжать ходить по чатам.
    """
    if not reel or reel.is_hidden:
        return None
    return {
        "id": reel.id,
        "video_url": reel.video_url,
        "cover_url": reel.cover_url,
        "caption": reel.caption,
    }


async def save_message(
    match_id: str,
    sender_id: str,
    text: str,
    image_url: Optional[str] = None,
    reel_id: Optional[str] = None,
) -> Optional[dict]:
    """Сохранить сообщение и собрать payload события. None — мэтч уже неактивен.

    Мэтч перепроверяется здесь, а не только у вызывающего: сокет живёт долго и
    пару могли развести, пока он был открыт.

    Здесь же проходят правила отправки, и оба — внутри той же транзакции, что и
    вставка. Раньше «одно письмо до ответа» проверялось в роутере отдельной
    сессией: между проверкой и записью успевал пройти второй запрос, и оба
    письма ложились в базу. Advisory-lock на чат закрывает эту щель тем же
    приёмом, что лайки и кейсы.

    Отказ — исключение `ДоставкаОтклонена`, а не `None`: `None` уже значит
    «мэтча нет», и смешивать их значило бы отвечать человеку «чат не найден»
    там, где он просто исчерпал лимит.
    """
    if not наша_картинка(image_url):
        raise ДоставкаОтклонена(DENIED_FOREIGN_IMAGE)

    async with async_session_factory() as session:
        async with session.begin():
            # Лок на беседу, а не на отправителя: гонка тут между двумя
            # письмами в ОДИН чат, и взят до чтения мэтча — иначе второй
            # запрос успеет прочитать «сообщений ноль» до записи первого
            await session.execute(
                sa_text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 0))"),
                {"k": f"dating:chat:{match_id}"},
            )

            result = await session.execute(
                select(Match).where(and_(Match.id == match_id, Match.is_active == True))  # noqa: E712
            )
            match = result.scalar_one_or_none()
            if not match:
                return None

            denied = await can_send_message(session, match, sender_id)
            if denied:
                raise ДоставкаОтклонена(denied)

            # Флаг «ответили» ставится тут же: он снимает лимит с отправителя,
            # и разъехаться с фактом сообщения не должен ни на одном пути
            await mark_answered_if_needed(match, sender_id)

            # Стрик: +1 день, если это первое сообщение сегодня. Читаем эту
            # ветку до флага answer-статуса: иначе при повторном открытии
            # окна неизвестно, какой из флагов должен победить.
            await touch_streak_for_message(session, match.id)

            message = Message(
                match_id=match_id,
                sender_id=sender_id,
                text=text,
                image_url=image_url,
                reel_id=reel_id,
            )
            session.add(message)
            await session.flush()

            preview = None
            if reel_id:
                result = await session.execute(select(Reel).where(Reel.id == reel_id))
                preview = reel_preview(result.scalar_one_or_none())

            return {
                "type": "message",
                "id": message.id,
                "match_id": match_id,
                "sender_id": sender_id,
                "text": text,
                "image_url": image_url,
                # Форма та же, что у GET /matches/{id}/messages: иначе клиенту
                # пришлось бы рисовать пересланный ролик двумя разными ветками
                "reel": preview,
                "created_at": message.created_at.isoformat() if message.created_at else None,
            }


async def _push_notification(
    match_id: str, sender_id: str, receiver_id: str, text: str,
) -> None:
    """Пуш в iOS — своя сессия, сокет её не держит.

    Сессия закрывается до отправки: держать её открытой всё время, пока
    отвечает APNs (до 10 с на устройство), значило бы занимать соединение из
    пула на разговор с чужим сервером.
    """
    if not is_configured():
        return
    try:
        async with async_session_factory() as session:
            result = await session.execute(
                select(Profile.display_name).where(Profile.user_id == sender_id)
            )
            sender_name = result.scalar_one_or_none() or ""
    except Exception as e:
        logger.error(f"Message push name failed ({match_id}): {e}")
        return

    await notify_new_message(receiver_id, sender_name, text, match_id)


async def fan_out(
    payload: dict,
    match_id: str,
    sender_id: str,
    receiver_id: str,
    notify_text: str,
) -> None:
    """Разослать сохранённое сообщение: WebSocket, Telegram, пуш.

    `publish`, а не `broadcast`: собеседник может сидеть на другом инстансе API,
    туда событие дойдёт только через Redis.

    Telegram и пуш — только если получателя нет в чате ни на одном инстансе:
    иначе человек с открытым приложением получает то же сообщение трижды.
    """
    await manager.publish(match_id, payload)

    if await manager.is_user_online(match_id, receiver_id):
        return

    await publish_bot_event({
        "type": "new_message",
        "match_id": match_id,
        "sender_id": sender_id,
        "receiver_id": receiver_id,
        "text": notify_text[:200],
    })
    await _push_notification(match_id, sender_id, receiver_id, notify_text)
