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
from models.models import User, VoiceCall
from models.schemas import VoiceIceServers
from services.ws_manager import manager
from services.voice import (
    ICE_SERVERS,
    WAITING_KEY,
    pop_waiting,
    push_waiting,
    remove_waiting,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/voice", tags=["voice"])

#: Живые сокеты по user_id. В памяти процесса — соединение и так привязано к
#: конкретному инстансу, а искать его на другом незачем: сигналинг идёт через
#: Redis Pub/Sub, как и остальной realtime.
_sockets: dict[str, WebSocket] = {}


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
    user_id, _ = auth

    await websocket.accept()
    _sockets[user_id] = websocket
    call_id: str | None = None
    partner_id: str | None = None
    started_at: datetime | None = None

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

            if action == "find":
                await leave_call()
                partner = await pop_waiting(user_id)

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
                await websocket.send_json(
                    {"type": "matched", "call_id": call_id, "initiator": True}
                )

                partner_ws = _sockets.get(partner)
                if partner_ws:
                    await manager.connect(call_id, partner_ws, partner)
                    await partner_ws.send_json(
                        {"type": "matched", "call_id": call_id, "initiator": False}
                    )
                else:
                    # Сокет собеседника живёт на другом инстансе — он получит
                    # событие через Redis, подписавшись на комнату по call_id
                    await manager.publish(
                        call_id,
                        {
                            "type": "invite",
                            "call_id": call_id,
                            "for_user": partner,
                        },
                        exclude=websocket,
                    )

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
        _sockets.pop(user_id, None)
