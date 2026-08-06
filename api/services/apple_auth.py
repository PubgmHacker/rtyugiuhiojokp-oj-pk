"""Проверка identity-токена Sign in with Apple.

Apple отдаёт клиенту подписанный JWT, и войти по нему можно только после
серверной проверки. Доверять содержимому токена без проверки подписи нельзя:
тело JWT — это обычный base64, любой может подставить чужой `sub` и войти под
чужим аккаунтом. Поэтому здесь проверяется всё:

* подпись — ключом Apple из `https://appleid.apple.com/auth/keys` (RS256);
* `iss` — ровно `https://appleid.apple.com`;
* `aud` — наш bundle id, иначе подойдёт токен, выданный чужому приложению;
* `exp` — просроченный токен не принимаем (это делает сама библиотека).

Ключи Apple меняются, поэтому их набор кэшируется на время и перечитывается,
если встретился неизвестный `kid`, — но не чаще, чем раз в минуту, чтобы
подделанный `kid` не превратился в способ дёргать Apple бесконечно.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Optional

import httpx
from jose import jwt
from jose.exceptions import JWTError

from config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

APPLE_ISSUER = "https://appleid.apple.com"
_KEYS_URL = "https://appleid.apple.com/auth/keys"
#: Сколько держим набор ключей, не спрашивая Apple заново.
_KEYS_TTL = 3600
#: Не чаще одного внепланового похода за ключами в минуту.
_REFRESH_COOLDOWN = 60

_keys: list[dict[str, Any]] = []
_keys_at: float = 0.0
_last_refresh: float = 0.0


class AppleAuthError(Exception):
    """Токен не прошёл проверку. Наружу уходит как 401, без подробностей."""


def is_configured() -> bool:
    """Готов ли вход через Apple.

    Bundle id есть в настройках всегда (у него есть дефолт), поэтому проверка
    формальная: она нужна, чтобы клиент не показывал кнопку, если поле пустое.
    """
    return bool(settings.APPSTORE_BUNDLE_ID)


async def _fetch_keys() -> list[dict[str, Any]]:
    async with httpx.AsyncClient(timeout=5.0) as client:
        response = await client.get(_KEYS_URL)
        response.raise_for_status()
        return response.json().get("keys", [])


async def _get_key(kid: str) -> Optional[dict[str, Any]]:
    """Ключ Apple по `kid`, с обновлением кэша при промахе."""
    global _keys, _keys_at, _last_refresh

    now = time.time()
    if not _keys or now - _keys_at > _KEYS_TTL:
        _keys = await _fetch_keys()
        _keys_at = now
        _last_refresh = now

    for key in _keys:
        if key.get("kid") == kid:
            return key

    # Неизвестный kid: Apple могла выкатить новый ключ. Перечитываем, но
    # редко — иначе подделанный kid станет способом дёргать Apple с нашего
    # сервера сколько угодно раз
    if now - _last_refresh > _REFRESH_COOLDOWN:
        _keys = await _fetch_keys()
        _keys_at = now
        _last_refresh = now
        for key in _keys:
            if key.get("kid") == kid:
                return key

    return None


async def verify_identity_token(identity_token: str) -> dict[str, Any]:
    """Проверить токен и вернуть его содержимое.

    Бросает `AppleAuthError`, если токен подделан, просрочен, выдан другому
    приложению или подписан неизвестным ключом.
    """
    if not identity_token:
        raise AppleAuthError("пустой токен")

    try:
        header = jwt.get_unverified_header(identity_token)
    except JWTError as exc:
        raise AppleAuthError("не разобрать заголовок токена") from exc

    kid = header.get("kid")
    if not kid:
        raise AppleAuthError("в токене нет kid")

    try:
        key = await _get_key(kid)
    except Exception as exc:
        # Сеть до Apple недоступна — это наша проблема, а не человека,
        # но пускать без проверки нельзя ни в каком случае
        logger.error(f"Не удалось получить ключи Apple: {exc}")
        raise AppleAuthError("проверка недоступна") from exc

    if not key:
        raise AppleAuthError("неизвестный ключ подписи")

    try:
        payload = jwt.decode(
            identity_token,
            key,
            algorithms=["RS256"],
            audience=settings.APPSTORE_BUNDLE_ID,
            issuer=APPLE_ISSUER,
        )
    except JWTError as exc:
        raise AppleAuthError("токен не прошёл проверку") from exc

    if not payload.get("sub"):
        raise AppleAuthError("в токене нет идентификатора пользователя")

    return payload
