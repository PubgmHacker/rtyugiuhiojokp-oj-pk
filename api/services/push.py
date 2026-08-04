"""Отправка пуш-уведомлений в APNs.

Провайдерский токен — JWT, подписанный ES256 по ключу `.p8` из Apple
Developer Portal. Apple разрешает переиспользовать его до часа, поэтому
кешируем: подпись на каждое уведомление — лишняя работа на горячем пути.

Отправка всегда best-effort. Мэтч и сообщение уже сохранены в БД, и падение
APNs не должно рвать основной поток — потерянное уведомление переживаемо,
потерянное сообщение нет.
"""

from __future__ import annotations

import logging
import time
from typing import Optional

import httpx
from jose import jwt
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from config import get_settings
from models.models import DeviceToken

settings = get_settings()
logger = logging.getLogger(__name__)

# Apple разрешает жизнь токена до часа; берём с запасом на расхождение часов
_TOKEN_TTL = 3000

_PROD_HOST = "https://api.push.apple.com"
_SANDBOX_HOST = "https://api.sandbox.push.apple.com"

_cached_token: Optional[str] = None
_cached_at: float = 0.0
_client: Optional[httpx.AsyncClient] = None


def is_configured() -> bool:
    """Заданы ли ключи APNs. Без них пуши просто не отправляются."""
    return bool(
        settings.APNS_KEY_P8
        and settings.APNS_KEY_ID
        and settings.APNS_TEAM_ID
        and settings.APNS_BUNDLE_ID
    )


def _provider_token() -> str:
    global _cached_token, _cached_at

    now = time.time()
    if _cached_token and now - _cached_at < _TOKEN_TTL:
        return _cached_token

    # В env перевод строки приходит как \n — иначе ключ не разберётся
    key = settings.APNS_KEY_P8.replace("\\n", "\n")
    _cached_token = jwt.encode(
        {"iss": settings.APNS_TEAM_ID, "iat": int(now)},
        key,
        algorithm="ES256",
        headers={"kid": settings.APNS_KEY_ID},
    )
    _cached_at = now
    return _cached_token


async def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        # APNs требует HTTP/2 и вознаграждает переиспользование соединения
        _client = httpx.AsyncClient(http2=True, timeout=10.0)
    return _client


async def close() -> None:
    """Закрыть соединение с APNs — вызывается при остановке приложения."""
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


async def register_device(session: AsyncSession, user_id: str, token: str, platform: str) -> None:
    """Запомнить токен устройства.

    Тот же токен мог принадлежать другому аккаунту (на телефоне сменили
    пользователя) — тогда перепривязываем, иначе пуши уходили бы прежнему
    владельцу устройства.
    """
    result = await session.execute(select(DeviceToken).where(DeviceToken.token == token))
    existing = result.scalar_one_or_none()

    if existing:
        existing.user_id = user_id
        existing.platform = platform
    else:
        session.add(DeviceToken(user_id=user_id, token=token, platform=platform))


async def _send_one(token: str, payload: dict, collapse_id: Optional[str]) -> Optional[int]:
    """Отправить одному устройству. Возвращает HTTP-статус или None при сбое."""
    client = await _get_client()
    host = _SANDBOX_HOST if settings.APNS_USE_SANDBOX else _PROD_HOST
    headers = {
        "authorization": f"bearer {_provider_token()}",
        "apns-topic": settings.APNS_BUNDLE_ID,
        "apns-push-type": "alert",
        "apns-priority": "10",
    }
    if collapse_id:
        # Десять сообщений из одного чата должны схлопнуться в одно
        headers["apns-collapse-id"] = collapse_id[:64]

    try:
        response = await client.post(
            f"{host}/3/device/{token}", json=payload, headers=headers,
        )
        return response.status_code
    except Exception as e:
        logger.error(f"APNs send failed: {e}")
        return None


async def send_to_user(
    session: AsyncSession,
    user_id: str,
    title: str,
    body: str,
    data: Optional[dict] = None,
    collapse_id: Optional[str] = None,
) -> int:
    """Отправить уведомление на все устройства пользователя.

    Возвращает число доставленных. Токены, которые Apple объявила мёртвыми,
    удаляются: иначе таблица копит мусор и каждый пуш тратится впустую.
    """
    if not is_configured():
        return 0

    result = await session.execute(
        select(DeviceToken).where(DeviceToken.user_id == user_id)
    )
    devices = list(result.scalars().all())
    if not devices:
        return 0

    payload = {
        "aps": {
            "alert": {"title": title, "body": body},
            "sound": "default",
            "badge": 1,
        },
        **(data or {}),
    }

    delivered = 0
    dead: list[str] = []
    for device in devices:
        status = await _send_one(device.token, payload, collapse_id)
        if status == 200:
            delivered += 1
        elif status in (400, 410):
            # 410 Unregistered, 400 BadDeviceToken — приложение удалено
            dead.append(device.token)

    if dead:
        await session.execute(delete(DeviceToken).where(DeviceToken.token.in_(dead)))

    return delivered


async def notify_new_match(session: AsyncSession, user_id: str, partner_name: str, match_id: str) -> None:
    """Пуш о новом мэтче — best-effort, мэтч уже сохранён."""
    try:
        await send_to_user(
            session,
            user_id,
            title="Взаимная симпатия",
            body=f"{partner_name} тоже вас лайкнул. Напишите первым.".strip()
            if partner_name
            else "У вас новый мэтч. Напишите первым.",
            data={"match_id": match_id, "kind": "match"},
            collapse_id=f"match-{match_id}",
        )
    except Exception as e:
        logger.error(f"Match push failed (user={user_id}): {e}")


async def notify_new_message(
    session: AsyncSession,
    user_id: str,
    sender_name: str,
    text: str,
    match_id: str,
) -> None:
    """Пуш о новом сообщении — best-effort, сообщение уже сохранено."""
    try:
        await send_to_user(
            session,
            user_id,
            title=sender_name or "Новое сообщение",
            body=text[:150] if text else "Прислал фото",
            data={"match_id": match_id, "kind": "message"},
            collapse_id=f"chat-{match_id}",
        )
    except Exception as e:
        logger.error(f"Message push failed (user={user_id}): {e}")
