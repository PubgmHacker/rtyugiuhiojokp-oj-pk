from __future__ import annotations

import asyncio
import json
import logging
import uuid
from typing import Awaitable, Callable, Optional

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
        # Одно pubsub-подключение и одна задача-читатель на весь процесс.
        # Раньше здесь был словарь задач: по подключению к Redis и по asyncio-
        # задаче на КАЖДУЮ комнату. 5 000 открытых чатов = 5 000 соединений
        # из одного процесса (деплой идёт с `--workers 1`) — упирались бы в
        # maxclients задолго до того, как кончится CPU.
        self._pubsub = None
        self._reader: Optional[asyncio.Task] = None
        # Подписка/отписка меняют состояние одного общего pubsub, а connect
        # и disconnect могут прийти одновременно из разных сокетов
        self._pubsub_lock = asyncio.Lock()
        # Каналы вне комнат: личные приглашения голосовой рулетки. Раньше на
        # каждый её сокет открывался свой pubsub (routers/voice.py) — та же
        # ошибка, что была с комнатами, только на другом канале. Читатель
        # здесь уже есть, так что подписки едут на нём же.
        #
        # Список обработчиков, а не один: канал личный, но вкладок у человека
        # может быть две, и на одном инстансе они делят подписку. Один
        # обработчик на канал означал бы, что вторая вкладка отбирает
        # приглашения у первой, а её закрытие снимает подписку у живой.
        self._handlers: dict[str, list[Callable[[dict], Awaitable[None]]]] = {}

    @staticmethod
    def _channel(match_id: str) -> str:
        return f"dating:match:{match_id}"

    async def subscribe_channel(
        self, channel: str, handler: Callable[[dict], Awaitable[None]]
    ) -> None:
        """Подписаться на произвольный канал на общем подключении.

        `handler` получает уже разобранный JSON. Своё эхо и служебные поля
        читатель отсеивает сам — как и для комнат.
        """
        async with self._pubsub_lock:
            подписчики = self._handlers.setdefault(channel, [])
            подписчики.append(handler)
            if len(подписчики) > 1:
                return  # канал уже в подписке, второй SUBSCRIBE ни к чему
            try:
                if self._pubsub is None:
                    r = await get_redis()
                    self._pubsub = r.pubsub()
                await self._pubsub.subscribe(channel)
                if self._reader is None or self._reader.done():
                    self._reader = asyncio.create_task(self._read_forever())
            except Exception as e:
                # Подписка останется в `_handlers` и вернётся при реконнекте
                logger.error(f"Redis subscribe failed ({channel}): {e}")

    async def unsubscribe_channel(
        self, channel: str, handler: Callable[[dict], Awaitable[None]]
    ) -> None:
        """Снять СВОЙ обработчик. Подписка держится, пока есть остальные."""
        async with self._pubsub_lock:
            подписчики = self._handlers.get(channel) or []
            if handler in подписчики:
                подписчики.remove(handler)
            if подписчики:
                return
            self._handlers.pop(channel, None)
            if self._pubsub is None:
                return
            try:
                await self._pubsub.unsubscribe(channel)
            except Exception as e:
                logger.error(f"Redis unsubscribe failed ({channel}): {e}")

    async def connect(self, match_id: str, ws: WebSocket, user_id: str) -> None:
        room = self.rooms.setdefault(match_id, {})
        первый_в_комнате = len(room) == 0
        room[ws] = user_id
        if первый_в_комнате:
            await self._subscribe(match_id)
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
            # Отписка асинхронная, а disconnect синхронный: его зовут из
            # `broadcast` при мёртвом сокете и из `finally` роутеров. Раньше
            # здесь отменялась задача-читатель комнаты — а `broadcast` зовётся
            # ИЗ этой же задачи, и слушатель отменял сам себя на середине
            # итерации, если последний сокет умирал во время рассылки.
            asyncio.create_task(self._unsubscribe(match_id))

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

    async def _subscribe(self, match_id: str) -> None:
        """Добавить канал комнаты в общее pubsub-подключение."""
        async with self._pubsub_lock:
            try:
                if self._pubsub is None:
                    r = await get_redis()
                    self._pubsub = r.pubsub()
                await self._pubsub.subscribe(self._channel(match_id))
                # Читатель поднимается лениво, после первой подписки: пустой
                # pubsub нечего читать, а `get_message` на нём падал бы
                if self._reader is None or self._reader.done():
                    self._reader = asyncio.create_task(self._read_forever())
            except Exception as e:
                # Комната продолжает работать локально: собеседники на этом
                # же процессе видят друг друга без Redis. Реконнект поднимет
                # подписку заново по списку живых комнат.
                logger.error(f"Redis subscribe failed ({match_id}): {e}")

    async def _unsubscribe(self, match_id: str) -> None:
        """Убрать канал опустевшей комнаты. Подключение остаётся общим."""
        async with self._pubsub_lock:
            # Пока отписка ждала лока, в комнату могли успеть войти снова
            if match_id in self.rooms or self._pubsub is None:
                return
            try:
                await self._pubsub.unsubscribe(self._channel(match_id))
            except Exception as e:
                logger.error(f"Redis unsubscribe failed ({match_id}): {e}")

    async def _read_forever(self) -> None:
        """Один читатель на процесс: разбирает сообщения всех комнат.

        Комната определяется по имени канала, а не по замыканию — поэтому
        подключение одно на процесс, а не одно на чат.

        `listen()` тут не подходит: его цикл живёт, пока `subscribed`, и
        выходит, когда последняя комната отписалась. Читателю же надо
        переживать пустые промежутки — иначе на каждой волне «все ушли,
        кто-то вернулся» задача перезапускалась бы. Поэтому `get_message`
        с таймаутом: он возвращает None и на пустой подписке.
        """
        пауза = 1.0
        while True:
            try:
                if self._pubsub is None:
                    return
                message = await self._pubsub.get_message(
                    ignore_subscribe_messages=True, timeout=1.0,
                )
                пауза = 1.0
                if message is None or message.get("type") != "message":
                    continue

                канал = message.get("channel") or ""
                if isinstance(канал, bytes):
                    канал = канал.decode()

                обработчики = list(self._handlers.get(канал) or ())
                match_id = канал.rsplit(":", 1)[-1]
                if not обработчики and match_id not in self.rooms:
                    continue  # комната закрылась, пока сообщение шло

                try:
                    data = json.loads(message["data"])
                except (json.JSONDecodeError, TypeError):
                    continue
                # Своё эхо пропускаем: локально уже разослано
                if data.get("origin") == INSTANCE_ID:
                    continue
                data.pop("origin", None)
                if обработчики:
                    for обработчик in обработчики:
                        try:
                            await обработчик(data)
                        except Exception as e:
                            # Падение одного слушателя не должно уносить
                            # читателя: на нём висят все комнаты процесса
                            logger.error(f"Channel handler failed ({канал}): {e}")
                    continue
                await self.broadcast(match_id, data)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                # Redis упал: соединение и подписки на нём мертвы. Пересобираем
                # pubsub с нуля и подписываемся на все живые комнаты — иначе
                # после реконнекта чат работал бы только внутри одного инстанса.
                logger.error(f"Redis room reader error: {e}")
                await asyncio.sleep(пауза)
                пауза = min(пауза * 2, 30.0)
                await self._resubscribe_all()

    async def _resubscribe_all(self) -> None:
        """Пересобрать pubsub после разрыва и вернуть подписки живых комнат."""
        async with self._pubsub_lock:
            старый, self._pubsub = self._pubsub, None
            if старый is not None:
                try:
                    await старый.aclose()
                except BaseException:  # включая CancelledError во время cleanup
                    pass
            каналы = [self._channel(m) for m in self.rooms] + list(self._handlers)
            if not каналы:
                return
            try:
                r = await get_redis()
                self._pubsub = r.pubsub()
                await self._pubsub.subscribe(*каналы)
            except Exception as e:
                logger.error(f"Redis resubscribe failed ({len(каналы)} channels): {e}")
                self._pubsub = None

    async def aclose(self) -> None:
        """Остановить читателя и закрыть pubsub — для shutdown приложения."""
        if self._reader is not None:
            self._reader.cancel()
            try:
                await self._reader
            except BaseException:
                # Ожидаемо прилетит CancelledError — мы её сами и вызвали.
                # Остальное тоже глотаем: процесс уже останавливается, и
                # падение здесь оборвало бы закрытие Redis ниже по lifespan.
                pass
            self._reader = None
        if self._pubsub is not None:
            try:
                await self._pubsub.aclose()
            except BaseException:
                pass
            self._pubsub = None


manager = RoomManager()
