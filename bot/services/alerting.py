from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# Зачем боту свой алертинг. У API он есть (api/services/alerting.py), у бота
# не было: `on_error` писал стектрейс в logger и отвечал человеку «что-то
# пошло не так». Логи Railway эфемерны и никто не смотрит их в реальном
# времени, поэтому падение в обработчике никого не будило — о нём узнавали
# из жалоб. При этом бот — единственный вход для тех, кто не открывает
# мини-апп: его молчащая ошибка стоит дороже, чем 500 в API.
#
# Модуль намеренно повторяет контракт api/services/alerting.py (init /
# capture_exception / capture_message): два процесса, одна дисциплина, и
# читающему не надо держать в голове две разные схемы. Общий пакет заводить
# не стали — бот и API деплоятся раздельно и не делят зависимости.
#
# Без SENTRY_DSN — полный no-op: ни импорта sentry_sdk, ни сетевых вызовов.
_enabled = False


def init(dsn: str) -> None:
    """Включить отправку ошибок в Sentry, если задан DSN.

    Вызывать один раз при старте процесса. Без dsn — no-op.
    Отсутствие пакета sentry-sdk не роняет бота: зависимость осознанно
    необязательная (см. bot/requirements.txt).
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

    # traces_sample_rate=0.0 — нужны ошибки, не профилирование: трейсы
    # долгого polling'а забили бы квоту событий, ничего не сказав по делу.
    # server_name отличает события бота от событий API в одном проекте
    # Sentry: без него две пачки стектрейсов сливаются в одну и непонятно,
    # какой процесс падает.
    sentry_sdk.init(dsn=dsn, traces_sample_rate=0.0, server_name="simp-dating-bot")
    _enabled = True
    logger.info("Sentry алертинг включён (бот)")


def capture_exception(exc: BaseException, **context) -> None:
    """Отправить исключение в Sentry, если алертинг включён.

    ``context`` попадает в событие тегами: по ним в Sentry ищется
    конкретный апдейт и человек, у которого сломалось, — без этого
    группа «Необработанная ошибка» неразличима внутри себя.

    Без SENTRY_DSN — no-op: вызывающий код не должен ветвиться на то,
    включён ли алертинг.
    """
    if not _enabled:
        return
    try:
        import sentry_sdk

        if context:
            with sentry_sdk.new_scope() as scope:
                for ключ, значение in context.items():
                    if значение is not None:
                        scope.set_tag(ключ, str(значение))
                sentry_sdk.capture_exception(exc)
        else:
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
