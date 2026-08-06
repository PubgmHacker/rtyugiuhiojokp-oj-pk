"""Тесты алертинга (services/alerting.py).

Требование: без SENTRY_DSN поведение не меняется ни на йоту (полный no-op),
а при сбое внешней зависимости деградация видна — не тишина.
"""

from __future__ import annotations

import logging

import pytest


def test_без_dsn_init_не_включает_алертинг():
    """Пустой DSN (дефолт) — init должен остаться no-op."""
    from services import alerting

    alerting._enabled = False
    alerting.init("")
    assert alerting._enabled is False


def test_без_dsn_capture_exception_не_падает_и_не_шлёт_ничего(monkeypatch):
    """capture_exception без включённого алертинга — no-op, не пытается
    даже импортировать sentry_sdk."""
    from services import alerting

    alerting._enabled = False
    вызовов = {"было": False}

    import builtins
    настоящий_import = builtins.__import__

    def _считающий_import(name, *args, **kwargs):
        if name == "sentry_sdk":
            вызовов["было"] = True
        return настоящий_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _считающий_import)

    alerting.capture_exception(RuntimeError("тест"))

    assert вызовов["было"] is False


def test_с_dsn_но_без_установленного_пакета_init_не_роняет_приложение(caplog, monkeypatch):
    """Пакет sentry-sdk может быть не установлен — это осознанно необязательная
    зависимость. init с DSN должен предупредить, а не бросить исключение.

    Отсутствие пакета изображаем подменой импорта: прежняя версия полагалась на
    то, что в окружении его нет, и сломалась, как только он появился, — то есть
    проверяла окружение, а не поведение кода.
    """
    import builtins

    from services import alerting

    настоящий_импорт = builtins.__import__

    def без_sentry(имя, *a, **kw):
        if имя == "sentry_sdk":
            raise ImportError("нет пакета")
        return настоящий_импорт(имя, *a, **kw)

    monkeypatch.setattr(builtins, "__import__", без_sentry)

    alerting._enabled = False
    with caplog.at_level(logging.WARNING):
        alerting.init("https://fake@example.test/1")

    assert alerting._enabled is False, "алертинг включился без пакета"
    assert any("sentry-sdk" in з.message for з in caplog.records), (
        "об отсутствии пакета не предупредили"
    )


async def test_сбой_ai_модерации_вызывает_capture_exception(monkeypatch):
    """Сбой внешней зависимости (AI-модерация текста) должен быть виден в
    алертинге, а не проглочен молча."""
    from services import ai_moderation, alerting

    class _ПадающийКлиент:
        class chat:
            class completions:
                @staticmethod
                def create(**kwargs):
                    raise RuntimeError("AI недоступен")

    monkeypatch.setattr(ai_moderation, "_get_zhipu_client", lambda: _ПадающийКлиент())

    вызовов = {"exc": None}

    def _fake_capture_exception(exc):
        вызовов["exc"] = exc

    monkeypatch.setattr(alerting, "capture_exception", _fake_capture_exception)

    результат = await ai_moderation.moderate_text("привет, как дела")

    assert результат["safe"] is True  # fail-open: не блокируем пользователя
    assert вызовов["exc"] is not None
    assert isinstance(вызовов["exc"], RuntimeError)


def test_алертинг_реально_отправляет_с_настоящим_sdk():
    """Прежние тесты проверяли только no-op без DSN — то есть путь, на котором
    ничего не происходит. Сам факт «с DSN события уходят» не проверялся ни
    разу, и ошибка в обёртке осталась бы незамеченной до боевого инцидента.

    Транспорт подменяем: настоящих запросов наружу из теста быть не должно.
    """
    sentry_sdk = pytest.importorskip(
        "sentry_sdk", reason="sentry-sdk не установлен в этом окружении"
    )

    import services.alerting as al

    ушло = []

    class Транспорт(sentry_sdk.transport.Transport):
        def capture_envelope(self, envelope):
            ушло.append(envelope)

        def flush(self, *a, **k):
            pass

        def kill(self):
            pass

    прежнее = al._enabled
    try:
        sentry_sdk.init(
            dsn="https://ключ@example.invalid/1",
            transport=Транспорт(),
            traces_sample_rate=0.0,
        )
        al._enabled = True

        al.capture_message("проверка сообщения")
        al.capture_exception(RuntimeError("проверка исключения"))
        sentry_sdk.flush()
    finally:
        al._enabled = прежнее

    assert len(ушло) == 2, (
        f"обёртка не отправила события в Sentry (ушло {len(ушло)} из 2)"
    )


async def test_зависший_вызов_ai_не_держит_поток_вечно(monkeypatch):
    """Без таймаута зависший запрос к Zhipu держит поток из пула `to_thread`
    неограниченно долго. Воркер один, пул общий — несколько таких запросов
    упираются в него, и вместе с модерацией встают загрузки фото.

    В боте таймаут был с самого начала, в API его забыли. Проверяем, что
    зависание теперь заканчивается отказом, а не ожиданием.
    """
    import asyncio

    from services import ai_moderation

    monkeypatch.setattr(ai_moderation, "_AI_TIMEOUT", 0.2)

    class ЗависшийКлиент:
        class chat:
            class completions:
                @staticmethod
                def create(*_a, **_kw):
                    import time

                    time.sleep(5)  # дольше таймаута
                    raise AssertionError("не должно дойти")

    monkeypatch.setattr(ai_moderation, "_get_zhipu_client", lambda: ЗависшийКлиент())

    начало = asyncio.get_event_loop().time()
    итог = await ai_moderation.moderate_text("любой текст")
    прошло = asyncio.get_event_loop().time() - начало

    assert прошло < 3, f"вызов не оборвался по таймауту, прошло {прошло:.1f}с"
    # Fail-open по содержимому осознан: рубить переписку из-за недоступного
    # AI хуже, чем пропустить сообщение. Но ждать вечно нельзя.
    assert итог["blocked"] is False
