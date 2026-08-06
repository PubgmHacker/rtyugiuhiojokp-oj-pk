"""Отправка писем: коды подтверждения и восстановления.

SMTP настраивается переменными окружения. Без них письма не уходят, и это
видно: функция возвращает False, роутер отвечает честной ошибкой, а в
DEBUG код дополнительно пишется в лог, чтобы разработку не блокировала
почта. Молча «делать вид, что отправили» нельзя: человек будет ждать письмо,
которого нет, и решит, что сломан он, а не сервис.

Отправка блокирующая (`smtplib`), поэтому уходит в отдельный поток: в этом
приложении один event loop, и синхронный вызов в нём вешает всех сразу — на
этом уже обжигались с синхронным клиентом AI-модерации.
"""

from __future__ import annotations

import asyncio
import logging
import smtplib
from email.message import EmailMessage

from config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


def настроен() -> bool:
    return bool(settings.SMTP_HOST and settings.SMTP_FROM)


def _отправить(адрес: str, тема: str, текст: str) -> None:
    письмо = EmailMessage()
    письмо["From"] = settings.SMTP_FROM
    письмо["To"] = адрес
    письмо["Subject"] = тема
    письмо.set_content(текст)

    if settings.SMTP_PORT == 465:
        сервер = smtplib.SMTP_SSL(settings.SMTP_HOST, settings.SMTP_PORT, timeout=10)
    else:
        сервер = smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=10)

    with сервер:
        if settings.SMTP_PORT != 465:
            сервер.starttls()
        if settings.SMTP_USER:
            сервер.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
        сервер.send_message(письмо)


async def отправить_код(адрес: str, код: str) -> bool:
    """Отправить код. `False` — письмо не ушло, и это надо показать человеку."""
    if not настроен():
        if settings.DEBUG:
            # Разработка не должна упираться в почтовый сервер
            logger.warning(f"SMTP не настроен. Код для {адрес}: {код}")
            return True
        logger.error("SMTP не настроен — код подтверждения не отправлен")
        return False

    текст = (
        f"Ваш код: {код}\n\n"
        "Он нужен, чтобы подтвердить почту в Souldawn. Код действует 15 минут.\n"
        "Если вы этого не запрашивали, просто не вводите его — с аккаунтом "
        "ничего не произойдёт."
    )

    try:
        # smtplib блокирующий: в общем event loop он подвесил бы всех сразу
        await asyncio.to_thread(_отправить, адрес, "Код подтверждения Souldawn", текст)
        return True
    except Exception as e:
        logger.error(f"Не удалось отправить письмо: {e}")
        return False
