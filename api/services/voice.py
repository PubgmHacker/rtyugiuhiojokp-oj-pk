"""Очередь ожидания и параметры соединения для голосовой рулетки.

Очередь в Redis: инстансов API несколько, и человек, попавший на другой,
ждал бы вечно. Список, а не множество, потому что нужен порядок — кто раньше
нажал, тот раньше соединяется.
"""

from __future__ import annotations

import logging

from config import get_settings
from services.realtime import get_redis

logger = logging.getLogger(__name__)
settings = get_settings()

#: Ключ очереди ожидающих.
WAITING_KEY = "dating:voice:waiting"
#: Сколько ждёт запись в очереди. Закрытая вкладка не должна оставлять
#: «призрака», на которого будут соединять живых людей.
WAITING_TTL = 120


def _ice_servers() -> list[dict]:
    """STUN всегда, TURN — если настроен.

    Без TURN звонок не соберётся у части людей: симметричный NAT у мобильных
    операторов не пробивается одним STUN. Поэтому TURN не «улучшение», а
    условие работы в мобильных сетях — но и без него часть звонков пройдёт,
    поэтому не падаем.
    """
    servers: list[dict] = [{"urls": ["stun:stun.l.google.com:19302"]}]

    if settings.TURN_URL and settings.TURN_USERNAME and settings.TURN_PASSWORD:
        servers.append(
            {
                "urls": [settings.TURN_URL],
                "username": settings.TURN_USERNAME,
                "credential": settings.TURN_PASSWORD,
            }
        )
    else:
        logger.info("TURN не настроен — часть звонков не соединится в мобильных сетях")

    return servers


ICE_SERVERS = _ice_servers()


async def push_waiting(user_id: str) -> None:
    """Встать в очередь. Повторный вызов не создаёт дубля."""
    r = await get_redis()
    await r.lrem(WAITING_KEY, 0, user_id)
    await r.rpush(WAITING_KEY, user_id)
    await r.expire(WAITING_KEY, WAITING_TTL)


async def pop_waiting(exclude_user_id: str, blocked: set[str] | None = None) -> str | None:
    """Взять из очереди первого подходящего.

    Своего же идентификатора в очереди быть не должно, но проверяем: два
    открытых окна одного человека иначе соединили бы его с самим собой.

    Заблокированные пропускаются и возвращаются в очередь: человек заблокировал
    обидчика именно чтобы больше его не встречать, и голосом — тем более. Но
    выкидывать его из очереди нельзя, он ждёт разговора с кем-то другим.
    """
    r = await get_redis()
    skipped: list[str] = []
    try:
        for _ in range(20):
            candidate = await r.lpop(WAITING_KEY)
            if candidate is None:
                return None
            if isinstance(candidate, bytes):
                candidate = candidate.decode()
            if candidate == exclude_user_id:
                continue
            if blocked and candidate in blocked:
                skipped.append(candidate)
                continue
            return candidate
        return None
    finally:
        # Возвращаем пропущенных в начало: они ждали дольше остальных
        if skipped:
            await r.lpush(WAITING_KEY, *reversed(skipped))
            await r.expire(WAITING_KEY, WAITING_TTL)


async def remove_waiting(user_id: str) -> None:
    """Убрать из очереди — при отмене или обрыве сокета."""
    r = await get_redis()
    await r.lrem(WAITING_KEY, 0, user_id)


def personal_channel(user_id: str) -> str:
    """Личный канал приглашений.

    Нужен потому, что второй участник может сидеть на другом инстансе API: там
    нет ни его сокета, ни комнаты звонка, и опубликовать событие «в комнату»
    некуда — на неё никто не подписан. Поэтому ждущий подписывается на канал по
    своему id заранее, ещё вставая в очередь.
    """
    return f"dating:voice:invite:{user_id}"


async def invite(user_id: str, call_id: str, partner_id: str) -> None:
    """Позвать человека в звонок по его личному каналу.

    `partner_id` передаём сразу: без него собеседник анонимен, и пожаловаться
    на него нельзя — а голос незнакомца без кнопки жалобы это то, чего в
    дейтинге быть не должно.
    """
    import json

    r = await get_redis()
    await r.publish(
        personal_channel(user_id),
        json.dumps({
            "type": "matched",
            "call_id": call_id,
            "initiator": False,
            "partner_id": partner_id,
        }),
    )
