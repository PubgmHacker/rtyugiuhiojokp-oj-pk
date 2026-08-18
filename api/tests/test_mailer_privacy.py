"""Адрес получателя не должен попадать в логи почты.

Строка `logger.error(f"Не удалось отправить письмо: {e}")` выглядит безобидно,
пока не посмотреть, что лежит в `e`. Исключения `smtplib` несут адрес внутри
себя: `SMTPRecipientsRefused` печатает словарь `{адрес: (код, ответ)}`,
`SMTPSenderRefused` — отправителя, а текст ответа сервера почти всегда повторяет
адрес в угловых скобках. То есть каждая неудачная отправка писала в лог чужую
почту — и не как отдельное поле, которое можно вырезать, а внутри свободного
текста.

Для дейтинга это не абстрактная утечка. Адрес в логе — это утверждение «этот
человек здесь зарегистрирован», а логи живут в Sentry, в агрегаторах, в
скриншотах из поддержки и в архивах, которые никто не чистит.

Что должно остаться: тип ошибки и ответ сервера целиком (без «550 mailbox
unavailable» причину не найти) плюс хеш адреса — тот же `хеш_почты`, которым
называет адрес восстановление, чтобы строки логов сходились между собой.
"""

from __future__ import annotations

import logging
import smtplib

import pytest

from services import mailer
from services.email_recovery import _код_ключ, хеш_почты

АДРЕС = "Ivan.Petrov+dating@Mail.RU"
ЧИСТЫЙ = "ivan.petrov+dating@mail.ru"
КОД = "428913"


@pytest.fixture
def почта_настроена(monkeypatch):
    """Считаем SMTP настроенным, не трогая общие настройки.

    Патчим `настроен`, а не поля `settings`: экземпляр настроек один на весь
    процесс (`lru_cache`), и правка поля протекла бы в соседние тесты.
    """
    monkeypatch.setattr(mailer, "настроен", lambda: True)


def _падает(ошибка: BaseException):
    def _отправить(адрес, тема, текст):
        raise ошибка

    return _отправить


async def test_адрес_не_попадает_в_лог_при_отказе_сервера(
    почта_настроена, monkeypatch, caplog
):
    """Отказ по получателю: адрес лежит и в ключе словаря, и в тексте ответа."""
    ошибка = smtplib.SMTPRecipientsRefused(
        {ЧИСТЫЙ: (550, b"5.1.1 <ivan.petrov+dating@mail.ru>: user unknown")}
    )
    monkeypatch.setattr(mailer, "_отправить", _падает(ошибка))

    with caplog.at_level(logging.ERROR, logger=mailer.logger.name):
        assert await mailer.отправить_код(АДРЕС, КОД) is False

    строка = caplog.text
    assert ЧИСТЫЙ not in строка.lower(), (
        f"адрес получателя утёк в лог: {строка!r}. Исключения smtplib несут его "
        "внутри текста — в лог можно писать только хеш"
    )
    assert "@mail.ru" not in строка.lower(), f"остаток адреса в логе: {строка!r}"


async def test_диагностика_из_ответа_сервера_сохраняется(
    почта_настроена, monkeypatch, caplog
):
    """Вычищать адрес — не значит вычищать причину: иначе лог бесполезен."""
    ошибка = smtplib.SMTPRecipientsRefused(
        {ЧИСТЫЙ: (550, b"5.1.1 <ivan.petrov+dating@mail.ru>: mailbox unavailable")}
    )
    monkeypatch.setattr(mailer, "_отправить", _падает(ошибка))

    with caplog.at_level(logging.ERROR, logger=mailer.logger.name):
        await mailer.отправить_код(АДРЕС, КОД)

    строка = caplog.text
    assert "SMTPRecipientsRefused" in строка, (
        "в логе нет типа ошибки: по одному «не удалось отправить» нельзя "
        f"отличить отказ сервера от неверного пароля. Строка: {строка!r}"
    )
    assert "550" in строка and "mailbox unavailable" in строка, (
        f"ответ сервера потерян, причину отказа не найти: {строка!r}"
    )


async def test_хеш_в_логе_совпадает_с_ключами_восстановления(
    почта_настроена, monkeypatch, caplog
):
    """Хеш нужен не сам по себе, а чтобы сойтись с остальными строками про эту почту."""
    monkeypatch.setattr(mailer, "_отправить", _падает(smtplib.SMTPServerDisconnected()))

    with caplog.at_level(logging.ERROR, logger=mailer.logger.name):
        await mailer.отправить_код(АДРЕС, КОД)

    хеш = хеш_почты(АДРЕС)
    assert хеш in caplog.text, (
        f"в логе нет хеша адреса ({хеш}): по такой строке нельзя понять, кому "
        f"не ушло письмо, и она не сходится ни с чем. Строка: {caplog.text!r}"
    )
    assert _код_ключ(АДРЕС).endswith(хеш), (
        "хеш в логе и ключ Redis у восстановления считаются по-разному — значит "
        "логи не сойдутся; формула обязана быть одна (хеш_почты)"
    )


async def test_регистр_адреса_не_меняет_хеш(почта_настроена, monkeypatch, caplog):
    """`Ivan@Mail.RU` и `ivan@mail.ru` — один человек, и в логе один хеш."""
    monkeypatch.setattr(mailer, "_отправить", _падает(smtplib.SMTPServerDisconnected()))

    with caplog.at_level(logging.ERROR, logger=mailer.logger.name):
        await mailer.отправить_код(АДРЕС, КОД)
        await mailer.отправить_код(ЧИСТЫЙ, КОД)

    хеши = {
        слово
        for строка in caplog.messages
        for слово in строка.replace("(", " ").replace(")", " ").split()
        if len(слово) == 32 and all(c in "0123456789abcdef" for c in слово)
    }
    assert len(хеши) == 1, (
        f"один адрес в разном регистре дал разные хеши {хеши}: строки логов про "
        "одного человека перестанут сходиться. Нужна нормализация перед хешем"
    )


async def test_чужие_адреса_из_ответа_сервера_тоже_скрыты(
    почта_настроена, monkeypatch, caplog
):
    """Сервер повторяет и отправителя, и адрес релея — скрывать надо все."""
    ошибка = smtplib.SMTPSenderRefused(
        553,
        b"5.7.1 <noreply@simp.app>: not owned by user, relay via smtp@provider.net",
        "noreply@simp.app",
    )
    monkeypatch.setattr(mailer, "_отправить", _падает(ошибка))

    with caplog.at_level(logging.ERROR, logger=mailer.logger.name):
        await mailer.отправить_код(АДРЕС, КОД)

    строка = caplog.text.lower()
    for чужой in ("noreply@simp.app", "smtp@provider.net"):
        assert чужой not in строка, (
            f"{чужой} остался в логе: вычищать надо каждый адрес в тексте, а не "
            f"только адрес получателя. Строка: {caplog.text!r}"
        )


@pytest.mark.parametrize(
    "текст",
    [
        "отказ для ivan@mail.ru",
        "отказ для ivan@mail.ru.",
        "адреса: ivan@mail.ru, petr@mail.ru;",
        "RCPT TO:<ivan@mail.ru> rejected",
        "{'ivan@mail.ru': (550, b'no such user')}",
        "локально: ivan@localhost",
        "['ivan@mail.ru']",
    ],
)
def test_адрес_вычищается_в_любом_обрамлении(текст: str):
    """smtplib печатает адреса в кавычках, скобках, словарях и без точки в домене."""
    очищенный = mailer._без_адресов(текст)
    assert "@" not in очищенный, (
        f"из {текст!r} получилось {очищенный!r} — адрес виден. Обрамление у "
        "smtplib разное, а regexp обязан снимать все варианты"
    )


def test_знаки_препинания_не_уезжают_в_хеш():
    """«ivan@mail.ru.» в конце фразы — адрес без точки, иначе хеш не тот."""
    очищенный = mailer._без_адресов("отказ для ivan@mail.ru.")
    assert очищенный == f"отказ для почта({хеш_почты('ivan@mail.ru')}).", (
        f"получилось {очищенный!r}: точка попала в хеш, и он не совпадёт с "
        "ключами Redis — логи про одного человека разойдутся"
    )


def test_текст_без_адресов_не_трогается():
    """Ошибки без адреса (таймаут, авторизация) должны читаться как есть."""
    текст = "535 5.7.8 Authentication credentials invalid"
    assert mailer._без_адресов(текст) == текст


async def test_код_не_пишется_в_лог_без_debug(monkeypatch, caplog):
    """Ветка «SMTP не настроен» в проде обязана молчать про код и адрес.

    Код в логе — это готовый вход в чужой аккаунт: почтой восстанавливают доступ.
    В DEBUG это осознанная поблажка для разработки, вне DEBUG — дыра.
    """
    monkeypatch.setattr(mailer, "настроен", lambda: False)
    monkeypatch.setattr(mailer.settings, "DEBUG", False)

    with caplog.at_level(logging.DEBUG, logger=mailer.logger.name):
        assert await mailer.отправить_код(АДРЕС, КОД) is False

    строка = caplog.text
    assert КОД not in строка, (
        f"код подтверждения в логе при DEBUG=false: {строка!r}. По такому логу "
        "восстанавливают чужой аккаунт"
    )
    assert ЧИСТЫЙ not in строка.lower(), f"адрес в логе при DEBUG=false: {строка!r}"
    assert "SMTP не настроен" in строка, (
        "сам факт «письмо не ушло, потому что SMTP не настроен» логировать надо: "
        "иначе человек ждёт письмо, а причина молчит"
    )
