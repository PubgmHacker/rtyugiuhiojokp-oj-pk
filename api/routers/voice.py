"""Голосовая рулетка: случайный звонок одним тапом.

Голос идёт напрямую между браузерами через WebRTC — сервер только знакомит
собеседников и передаёт сигналы установки соединения. Пропускать звук через
себя значило бы платить за трафик и хранить то, что хранить нельзя.

Очередь ожидания живёт в Redis, а не в памяти процесса: инстансов API может
быть несколько, и человек, попавший на другой, ждал бы вечно.

Каждая пара пишется в журнал. Не для записи разговора — её нет, — а чтобы по
жалобе понимать, кто с кем говорил: без этого жалоба на голос неразбираема.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from sqlalchemy import select

from database.connection import async_session_factory
from middleware.auth import get_current_user
from routers.chat import _ws_auth
from services.token_revocation import is_revoked
from models.models import Block, User, VoiceCall
from models.schemas import VoiceIceServers
from services.ws_manager import manager
from services.voice import (
    ICE_SERVERS,
    invite,
    personal_channel,
    pop_waiting,
    push_waiting,
    remove_waiting,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/voice", tags=["voice"])

@router.get("/ice-servers", response_model=VoiceIceServers)
async def get_ice_servers(user: User = Depends(get_current_user)):
    """Серверы для установки соединения.

    Отдаём с сервера, а не хардкодим в клиенте: TURN-креденшелы меняются, и
    зашитые в бандл потребовали бы пересборки приложения.
    """
    return VoiceIceServers(ice_servers=ICE_SERVERS)


@router.websocket("/ws/roulette")
async def websocket_roulette(websocket: WebSocket):
    """Сигналинг голосовой рулетки.

    Сервер знакомит двоих и передаёт между ними offer/answer/ICE. Сам звук идёт
    напрямую между браузерами: пропускать его через себя значило бы платить за
    трафик и хранить то, чего хранить нельзя.

    Протокол от клиента: `find` — встать в очередь, `signal` — передать данные
    собеседнику, `leave` — выйти. Обратно: `waiting`, `matched`, `signal`,
    `partner_left`.
    """
    auth = await _ws_auth(websocket)
    if not auth:
        return
    user_id, token_payload = auth

    await websocket.accept()
    call_id: str | None = None
    partner_id: str | None = None
    started_at: datetime | None = None

    async def on_invite(событие: dict) -> None:
        """Приглашение из личного канала.

        Тот, кто ждёт в очереди, узнаёт о найденной паре только так: на его
        инстансе комнаты звонка ещё нет, и подписаться на неё заранее нельзя —
        call_id придумывает тот, кто нашёл.

        Раньше здесь висел собственный `r.pubsub()` на КАЖДЫЙ открытый сокет
        рулетки — то же, что было с комнатами чата: 10 000 ждущих = 10 000
        подключений к Redis из одного процесса. Теперь подписка едет на общем
        читателе `RoomManager` (services/ws_manager.py).
        """
        nonlocal call_id, partner_id, started_at

        if событие.get("type") != "matched":
            return

        call_id = событие["call_id"]
        partner_id = событие.get("partner_id")
        started_at = datetime.now(timezone.utc)
        await manager.connect(call_id, websocket, user_id)
        await websocket.send_json(событие)

    await manager.subscribe_channel(personal_channel(user_id), on_invite)

    async def leave_call() -> None:
        """Разорвать текущий звонок и сообщить собеседнику."""
        nonlocal call_id, partner_id, started_at
        if not call_id:
            return
        await manager.publish(call_id, {"type": "partner_left", "user_id": user_id})
        manager.disconnect(call_id, websocket)

        # Длительность пишем при разрыве: до него она неизвестна
        if started_at:
            seconds = int((datetime.now(timezone.utc) - started_at).total_seconds())
            async with async_session_factory() as session:
                result = await session.execute(
                    select(VoiceCall).where(VoiceCall.id == call_id)
                )
                call = result.scalar_one_or_none()
                if call and not call.duration_seconds:
                    call.duration_seconds = seconds
                    await session.commit()

        call_id, partner_id, started_at = None, None, None

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                continue

            action = data.get("type")

            # Бан рвёт и уже открытый сокет — так же, как в личном чате
            # (routers/chat.py). Проверки при подключении мало: забанить могли
            # пока человек стоял в очереди или уже говорил, и без этого он
            # продолжал бы заводить новые звонки с незнакомыми людьми
            if await is_revoked(token_payload):
                await leave_call()
                await websocket.close(code=4001, reason="Token revoked")
                break

            if action == "find":
                await leave_call()

                # Заблокированные не должны попадаться в паре — ни в деке, ни
                # тем более голосом. Список читаем на каждый поиск: за время
                # сессии человек мог кого-то заблокировать
                async with async_session_factory() as session:
                    result = await session.execute(
                        select(Block.blocked_id).where(Block.blocker_id == user_id)
                    )
                    blocked = {row[0] for row in result.all()}
                    result = await session.execute(
                        select(Block.blocker_id).where(Block.blocked_id == user_id)
                    )
                    blocked |= {row[0] for row in result.all()}

                partner = await pop_waiting(user_id, blocked)

                if partner is None:
                    # Никого нет — встаём сами и ждём
                    await push_waiting(user_id)
                    await websocket.send_json({"type": "waiting"})
                    continue

                call_id = str(uuid.uuid4())
                partner_id = partner
                started_at = datetime.now(timezone.utc)

                async with async_session_factory() as session:
                    session.add(
                        VoiceCall(id=call_id, caller_id=user_id, callee_id=partner)
                    )
                    await session.commit()

                await manager.connect(call_id, websocket, user_id)

                # Инициатором offer назначаем того, кто нашёл: иначе оба
                # отправят offer и соединение не соберётся
                await websocket.send_json({
                    "type": "matched",
                    "call_id": call_id,
                    "initiator": True,
                    # Кому мы попались — чтобы было на кого жаловаться
                    "partner_id": partner,
                })

                # Приглашение уходит в личный канал партнёра, а не «в комнату»:
                # на другом инстансе комнаты звонка ещё нет и подписчиков у неё
                # тоже — событие ушло бы в пустоту, и пара не собиралась бы.
                # Локальный сокет тоже получит его через этот канал: одна
                # ветка вместо двух, и не бывает случая «работает только
                # когда оба на одном инстансе»
                await invite(partner, call_id, user_id)

            elif action == "signal" and call_id:
                # Тело сигнала не разбираем: это SDP и ICE-кандидаты, они
                # интересны только браузеру на той стороне
                await manager.publish(
                    call_id,
                    {"type": "signal", "from": user_id, "payload": data.get("payload")},
                    exclude=websocket,
                )

            elif action == "leave":
                await leave_call()
                await remove_waiting(user_id)
                await websocket.send_json({"type": "left"})

    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.error(f"Ошибка в рулетке ({user_id}): {e}")
    finally:
        # Закрытая вкладка не должна оставлять «призрака» в очереди, на
        # которого будут соединять живых людей
        await remove_waiting(user_id)
        await leave_call()
        # Подписка на личный канал живёт на общем читателе процесса — без
        # снятия она переживёт закрытый сокет, и приглашения будут уходить
        # в обработчик, у которого сокета уже нет
        await manager.unsubscribe_channel(personal_channel(user_id), on_invite)
