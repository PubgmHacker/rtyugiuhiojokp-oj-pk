"""Проверка покупок App Store (StoreKit 2).

Клиент присылает подписанную транзакцию — JWS Compact: `header.payload.signature`,
подпись ES256, цепочка сертификатов в заголовке `x5c`. Проверка подписи —
единственное, что отделяет реальную оплату от подделки, поэтому доверять
клиентскому «я купил» нельзя ни в каком виде.

Проверку делает официальная библиотека Apple (`app-store-server-library`):
она собирает цепочку до Apple Root CA G3 и знает про случаи, когда Apple
подписывает валидные транзакции формально истёкшим промежуточным
сертификатом — ручная реализация на таких транзакциях отклоняла бы честные
покупки.

Корневой сертификат берётся из локального файла, а НЕ из `x5c` присланного
токена: иначе атакующий приложил бы собственный «корень» и подпись сошлась бы.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)

# Скачивается с https://www.apple.com/certificateauthority/AppleRootCA-G3.cer
_ROOT_CERT_PATH = Path(__file__).resolve().parent / "certs" / "AppleRootCA-G3.cer"


class ReceiptInvalid(Exception):
    """Чек не прошёл проверку — покупку зачитывать нельзя."""


@dataclass(frozen=True)
class VerifiedPurchase:
    """Проверенная транзакция — то, на что можно начислять подписку."""

    transaction_id: str
    original_transaction_id: str
    product_id: str
    expires_at: Optional[datetime]
    purchased_at: Optional[datetime]
    app_account_token: Optional[str]
    is_subscription: bool


def is_configured() -> bool:
    """Готова ли проверка чеков. Без этого покупка в iOS не предлагается.

    В Production библиотека Apple отказывается работать без числового
    `app_apple_id`, поэтому без него покупку нельзя даже предлагать: кнопка
    появилась бы, а любая оплата падала бы на проверке.
    """
    if not settings.APPSTORE_BUNDLE_ID or not _ROOT_CERT_PATH.exists():
        return False
    if not settings.APPSTORE_USE_SANDBOX and not settings.APPSTORE_APP_APPLE_ID:
        return False
    return True


def _ms_to_dt(value: Optional[int]) -> Optional[datetime]:
    """Apple отдаёт время в миллисекундах Unix."""
    if not value:
        return None
    return datetime.fromtimestamp(int(value) / 1000, tz=timezone.utc)


def _load_verifier():
    """Верификатор Apple. Импорт внутри функции: без ключей библиотека не нужна."""
    from appstoreserverlibrary.models.Environment import Environment
    from appstoreserverlibrary.signed_data_verifier import SignedDataVerifier

    environment = (
        Environment.SANDBOX if settings.APPSTORE_USE_SANDBOX else Environment.PRODUCTION
    )
    return SignedDataVerifier(
        root_certificates=[_ROOT_CERT_PATH.read_bytes()],
        enable_online_checks=True,
        environment=environment,
        bundle_id=settings.APPSTORE_BUNDLE_ID,
        # В Production библиотека Apple требует числовой идентификатор приложения
        app_apple_id=settings.APPSTORE_APP_APPLE_ID or None,
    )


def verify_transaction(signed_transaction: str, expected_account_token: str) -> VerifiedPurchase:
    """Проверить подписанную транзакцию и убедиться, что она наша и свежая.

    `expected_account_token` — UUID пользователя, который делает запрос. Без
    этой сверки валидный чужой чек можно предъявить с любого аккаунта: подпись
    Apple подтверждает лишь факт покупки, но не того, кто её предъявил.
    """
    if not is_configured():
        raise ReceiptInvalid("Проверка чеков App Store не настроена")

    from appstoreserverlibrary.models.Environment import Environment
    from appstoreserverlibrary.signed_data_verifier import VerificationException

    try:
        payload = _load_verifier().verify_and_decode_signed_transaction(signed_transaction)
    except VerificationException as e:
        # Подпись не сошлась — либо подделка, либо чек другого приложения
        raise ReceiptInvalid(f"Подпись Apple не подтверждена: {e}") from e
    except Exception as e:
        logger.error(f"App Store verification failed: {e}")
        raise ReceiptInvalid("Не удалось проверить чек") from e

    if payload.bundleId != settings.APPSTORE_BUNDLE_ID:
        raise ReceiptInvalid("Чек выдан для другого приложения")

    expected_env = (
        Environment.SANDBOX if settings.APPSTORE_USE_SANDBOX else Environment.PRODUCTION
    )
    if payload.environment != expected_env:
        # Иначе покупка из песочницы давала бы платный доступ в проде
        raise ReceiptInvalid("Покупка из другого окружения App Store")

    # Возврат или чарджбэк: доступ закрывается независимо от срока подписки
    if getattr(payload, "revocationDate", None):
        raise ReceiptInvalid("Покупка отозвана")

    token = str(payload.appAccountToken) if payload.appAccountToken else None
    if not token:
        raise ReceiptInvalid("Покупка не привязана к аккаунту")
    if token.lower() != expected_account_token.lower():
        raise ReceiptInvalid("Покупка принадлежит другому аккаунту")

    expires_at = _ms_to_dt(payload.expiresDate)
    if expires_at and expires_at <= datetime.now(timezone.utc):
        raise ReceiptInvalid("Срок подписки истёк")

    return VerifiedPurchase(
        transaction_id=str(payload.transactionId),
        # У продления transactionId новый, а этот остаётся прежним —
        # только по нему видно, что это та же подписка
        original_transaction_id=str(payload.originalTransactionId),
        product_id=payload.productId,
        expires_at=expires_at,
        purchased_at=_ms_to_dt(payload.purchaseDate),
        app_account_token=token,
        is_subscription=expires_at is not None,
    )
