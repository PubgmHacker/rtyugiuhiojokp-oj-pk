from __future__ import annotations

import asyncio
import json
import logging
from typing import Optional

from fastapi import WebSocket

from services.realtime import get_redis

logger = logging.getLogger(__name__)


class RoomManager:
    """Комнаты WebSocket по match_id + мост из Redis (сообщения из Telegram-бота).

    Работает в рамках одного процесса API (для MVP этого достаточно);
    события от бота приходят через Redis-канал dating:match:{id}.
    """

    def __init__(self) -> None:
        self.rooms: dict[str, dict[WebSocket, str]] = {}
        self._listeners: dict[str, asyncio.Task] = {}

    async def connect(self, match_id: str, ws: WebSocket, user_id: str) -> None:
        room = self.rooms.setdefault(match_id, {})
        room[ws] = user_id
        if match_id not in self._listeners:
            self._listeners[match_id] = asyncio.create_task(self._listen_redis(match_id))

    def disconnect(self, match_id: str, ws: WebSocket) -> None:
        room = self.rooms.get(match_id)
        if not room:
            return
        room.pop(ws, None)
        if not room:
            self.rooms.pop(match_id, None)
            task = self._listeners.pop(match_id, None)
            if task:
                task.cancel()

    def is_user_connected(self, match_id: str, user_id: str) -> bool:
        return user_id in (self.rooms.get(match_id) or {}).values()

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
        """Форвардим в комнату события, опубликованные ботом (origin=bot).

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
                    # ws-события уже разосланы локально — берём только внешние
                    if data.get("origin") == "bot":
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
