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


#: Типы уведомлений Apple, после которых доступ надо закрыть немедленно.
#: REFUND — деньги вернули, REVOKE — покупку отозвали (например, Family
#: Sharing), а CONSUMPTION_REQUEST приходит при споре и сам доступа не меняет.
ОТЗЫВАЮЩИЕ = {"REFUND", "REVOKE"}


def разобрать_уведомление(signed_payload: str) -> dict:
    """Проверить уведомление App Store и вытащить из него суть.

    Раньше отзыв ловился только в момент, когда клиент сам предъявлял чек
    (`revocationDate` в `verify_transaction`). До этого момента вернувший
    деньги продолжал пользоваться подпиской — а мог и вовсе больше не
    открывать приложение с проверкой.

    Подпись проверяем тем же верификатором, что и чеки: уведомление приходит
    на открытый эндпоинт, и без проверки подписи любой мог бы прислать
    поддельный REFUND и погасить подписку любому.

    Возвращает `{"тип", "подтип", "отзыв", "original_transaction_id",
    "transaction_id"}` — оба идентификатора, потому что у продления они разные.
    """
    if not is_configured():
        raise ReceiptInvalid("Проверка чеков App Store не настроена")

    from appstoreserverlibrary.signed_data_verifier import VerificationException

    try:
        payload = _load_verifier().verify_and_decode_notification(signed_payload)
    except VerificationException as e:
        raise ReceiptInvalid(f"Подпись уведомления не подтверждена: {e}") from e
    except Exception as e:
        logger.error(f"App Store notification verification failed: {e}")
        raise ReceiptInvalid("Не удалось проверить уведомление") from e

    тип = str(getattr(payload, "notificationType", "") or "")
    подтип = str(getattr(payload, "subtype", "") or "")

    original_id = None
    transaction_id = None
    данные = getattr(payload, "data", None)
    подписанная = getattr(данные, "signedTransactionInfo", None) if данные else None
    if подписанная:
        try:
            сделка = _load_verifier().verify_and_decode_signed_transaction(подписанная)
            original_id = str(сделка.originalTransactionId)
            # У продления transactionId свой, и в журнале платежей лежит
            # именно он — ищем потом по обоим
            transaction_id = str(сделка.transactionId)
        except Exception as e:
            # Тип уведомления уже известен и полезен сам по себе, но без
            # original_transaction_id мы не поймём, чью подписку гасить
            logger.warning(f"Уведомление без разбираемой транзакции: {e}")

    return {
        "тип": тип,
        "подтип": подтип,
        "отзыв": тип in ОТЗЫВАЮЩИЕ,
        "original_transaction_id": original_id,
        "transaction_id": transaction_id,
    }
