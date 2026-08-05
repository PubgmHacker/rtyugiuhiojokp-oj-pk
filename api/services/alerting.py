from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# Sentry — необязательная зависимость. Без SENTRY_DSN (дефолт — пустая
# строка) модуль работает как no-op: ни импорта пакета, ни сетевых вызовов
# не происходит. Пакет может быть даже не установлен — приложение это
# переживает, просто алертинг не работает.
_enabled = False


def init(dsn: str) -> None:
    """Включить отправку ошибок в Sentry, если задан DSN.

    Вызывать один раз при старте приложения. Без dsn — no-op.
    Отсутствие пакета sentry-sdk не роняет приложение: это осознанно
    необязательная зависимость (см. requirements.txt).
    """
    global _enabled
    if not dsn:
        return

    try:
        import sentry_sdk
    except ImportError:
        logger.warning(
            "SENTRY_DSN задан, но пакет sentry-sdk не установлен — "
            "алертинг не будет работать. Добавьте sentry-sdk в requirements.txt."
        )
        return

    sentry_sdk.init(dsn=dsn, traces_sample_rate=0.0)
    _enabled = True
    logger.info("Sentry алертинг включён")


def capture_exception(exc: BaseException) -> None:
    """Отправить исключение в Sentry, если алертинг включён.

    Без SENTRY_DSN — no-op: вызывающий код не должен знать и не должен
    ветвиться на то, включён ли алертинг.
    """
    if not _enabled:
        return
    try:
        import sentry_sdk

        sentry_sdk.capture_exception(exc)
    except Exception as e:  # алертинг не должен уронить основной сценарий
        logger.error(f"Не удалось отправить исключение в Sentry: {e}")


def capture_message(message: str, level: str = "error") -> None:
    """Отправить сообщение в Sentry (для деградации без исключения), если включён."""
    if not _enabled:
        return
    try:
        import sentry_sdk

        sentry_sdk.capture_message(message, level=level)
    except Exception as e:
        logger.error(f"Не удалось отправить сообщение в Sentry: {e}")
