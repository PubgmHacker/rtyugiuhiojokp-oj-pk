from __future__ import annotations

import asyncio
import json
import logging
import uuid
from typing import Optional

from fastapi import WebSocket

from services.realtime import get_redis

logger = logging.getLogger(__name__)

# Идентификатор процесса. Все события чата уходят в Redis, чтобы дойти до
# собеседника на другом инстансе API; своё же эхо процесс отбрасывает по
# этому полю, иначе локальные подключения получили бы каждое сообщение дважды.
INSTANCE_ID = str(uuid.uuid4())

# Присутствие переживает короткие паузы, но истекает, если инстанс упал,
# не успев снять ключ. Клиент шлёт heartbeat раз в 25 с, так что запас двойной.
PRESENCE_TTL = 90


class RoomManager:
    """Комнаты WebSocket по match_id + мост через Redis Pub/Sub.

    Работает на любом числе инстансов API: собеседники одного мэтча могут
    быть подключены к разным процессам, события расходятся через канал
    dating:match:{id}. Оттуда же приходят сообщения от Telegram-бота.
    """

    def __init__(self) -> None:
        self.rooms: dict[str, dict[WebSocket, str]] = {}
        self._listeners: dict[str, asyncio.Task] = {}

    async def connect(self, match_id: str, ws: WebSocket, user_id: str) -> None:
        room = self.rooms.setdefault(match_id, {})
        room[ws] = user_id
        if match_id not in self._listeners:
            self._listeners[match_id] = asyncio.create_task(self._listen_redis(match_id))
        await self._mark_presence(match_id, user_id, online=True)

    def disconnect(self, match_id: str, ws: WebSocket) -> None:
        room = self.rooms.get(match_id)
        if not room:
            return
        user_id = room.pop(ws, None)
        # Тот же пользователь может держать вторую вкладку на этом инстансе
        if user_id and user_id not in room.values():
            asyncio.create_task(self._mark_presence(match_id, user_id, online=False))
        if not room:
            self.rooms.pop(match_id, None)
            task = self._listeners.pop(match_id, None)
            if task:
                task.cancel()

    def is_user_connected(self, match_id: str, user_id: str) -> bool:
        """Подключён ли пользователь к ЭТОМУ процессу."""
        return user_id in (self.rooms.get(match_id) or {}).values()

    async def is_user_online(self, match_id: str, user_id: str) -> bool:
        """Подключён ли пользователь к любому инстансу API.

        Нужно, чтобы не дублировать сообщение в Telegram человеку, который
        читает чат прямо сейчас, но подключён к другому процессу. Ключ живёт
        с TTL: если инстанс упал не сняв присутствие, запись истечёт сама.
        """
        if self.is_user_connected(match_id, user_id):
            return True
        try:
            r = await get_redis()
            return bool(await r.exists(self._presence_key(match_id, user_id)))
        except Exception as e:
            # Redis недоступен — лучше отправить лишнее уведомление,
            # чем потерять сообщение для человека вне чата
            logger.error(f"Presence check failed ({match_id}): {e}")
            return False

    @staticmethod
    def _presence_key(match_id: str, user_id: str) -> str:
        return f"dating:presence:{match_id}:{user_id}"

    async def _mark_presence(self, match_id: str, user_id: str, online: bool) -> None:
        try:
            r = await get_redis()
            key = self._presence_key(match_id, user_id)
            if online:
                await r.set(key, INSTANCE_ID, ex=PRESENCE_TTL)
            else:
                await r.delete(key)
        except Exception as e:
            logger.error(f"Presence update failed ({match_id}): {e}")

    async def refresh_presence(self, match_id: str, user_id: str) -> None:
        """Продлить присутствие — вызывается на активность в сокете."""
        await self._mark_presence(match_id, user_id, online=True)

    async def publish(
        self,
        match_id: str,
        payload: dict,
        exclude: Optional[WebSocket] = None,
    ) -> None:
        """Разослать событие локально и остальным инстансам через Redis.

        `exclude` действует только на локальный сокет-отправитель: у других
        инстансов этого сокета нет, а адресат события — всегда собеседник.
        """
        await self.broadcast(match_id, payload, exclude=exclude)
        try:
            r = await get_redis()
            await r.publish(
                f"dating:match:{match_id}",
                json.dumps({**payload, "origin": INSTANCE_ID}),
            )
        except Exception as e:
            # Локальная доставка уже произошла — падение Redis не должно
            # рвать чат тем, кто сидит на этом же инстансе
            logger.error(f"Redis publish failed ({match_id}): {e}")

    async def broadcast(
        self,
        match_id: str,
        payload: dict,
        exclude: Optional[WebSocket] = None,
    ) -> None:
        room = self.rooms.get(match_id) or {}
        dead: list[WebSocket] = []
        for ws in list(room.keys()):
            if ws is exclude:
                continue
            try:
                await ws.send_json(payload)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(match_id, ws)

    async def _listen_redis(self, match_id: str) -> None:
        """Форвардим в комнату события из Redis — от бота и от других инстансов.

        Переживает падение Redis (реконнект с бэкоффом) и всегда закрывает
        pubsub-подключение при остановке (иначе течёт по соединению на комнату).
        """
        while match_id in self.rooms:
            pubsub = None
            try:
                r = await get_redis()
                pubsub = r.pubsub()
                await pubsub.subscribe(f"dating:match:{match_id}")
                async for message in pubsub.listen():
                    if message["type"] != "message":
                        continue
                    try:
                        data = json.loads(message["data"])
                    except (json.JSONDecodeError, TypeError):
                        continue
                    # Своё эхо пропускаем: локально уже разослано
                    if data.get("origin") == INSTANCE_ID:
                        continue
                    data.pop("origin", None)
                    await self.broadcast(match_id, data)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Redis room listener error ({match_id}): {e}")
                await asyncio.sleep(3)  # реконнект с паузой
            finally:
                if pubsub is not None:
                    try:
                        await pubsub.unsubscribe()
                        await pubsub.aclose()
                    except BaseException:  # включая CancelledError во время cleanup
                        pass


manager = RoomManager()
