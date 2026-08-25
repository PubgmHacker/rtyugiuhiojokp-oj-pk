"""Общие фикстуры тестов.

Тесты не требуют поднятого PostgreSQL и Redis: приложение переживает их
отсутствие (см. lifespan в main.py), а smoke-проверки касаются схем,
роутов и настроек.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

API_ROOT = Path(__file__).resolve().parent.parent
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))


def _закрытие_циклов_с_доносом() -> None:
    """Назвать задачу, вешающую закрытие event loop, вместо немого зависания.

    CI дважды вис на выходе из TestClient: портальный поток anyio стоит в
    `Runner.close() → _cancel_all_tasks → gather`, то есть какая-то задача
    пережила отмену и ждёт события, которое никогда не придёт. pytest-timeout
    дампит только ПОТОКИ — в дампе виден спящий select, но не имя задачи,
    поэтому виновник до сих пор не назван.

    Подменяем `asyncio.runners._cancel_all_tasks` (его зовёт и anyio — Runner
    у него стандартный): вместо безлимитного gather ждём отменённые задачи с
    потолком, а не уложившихся печатаем поимённо со стеками в sys.__stderr__ —
    мимо перехвата pytest, чтобы строки дошли до лога CI даже при жёстком
    снятии прогона. После доноса бросаем RuntimeError: тест падает сразу и
    громко, а не висит 180 секунд до таймаута.

    Потолок 20 с — заведомо больше любого штатного cleanup'а (потолки в
    aclose — 5–6 с), так что зелёным прогонам подмена не видна: все задачи
    умирают за миллисекунды, и ветка доноса не исполняется.
    """
    import asyncio.runners as _runners
    import asyncio.tasks as _tasks

    def _cancel_all_tasks(loop):  # сигнатура оригинала из asyncio/runners.py
        to_cancel = _tasks.all_tasks(loop)
        if not to_cancel:
            return
        for task in to_cancel:
            task.cancel()

        done, pending = loop.run_until_complete(
            _tasks.wait(to_cancel, timeout=20.0)
        )
        if pending:
            печать = sys.__stderr__ or sys.stderr
            print(
                f"\n=== {len(pending)} задач(а) пережили отмену при закрытии "
                f"цикла — вечные, закрытие висело бы бесконечно ===",
                file=печать,
            )
            for task in pending:
                print(f"\n--- {task!r} ---", file=печать)
                try:
                    task.print_stack(file=печать)
                except Exception as ошибка:  # noqa: BLE001 — донос не должен падать
                    print(f"(стек недоступен: {ошибка!r})", file=печать)
            печать.flush()
            raise RuntimeError(
                "закрытие event loop зависло: "
                + "; ".join(repr(t) for t in pending)
            )

        # Хвост оригинала: показать исключения задач, погибших не от отмены
        for task in done:
            if task.cancelled():
                continue
            if task.exception() is not None:
                loop.call_exception_handler({
                    "message": "unhandled exception during test loop shutdown",
                    "exception": task.exception(),
                    "task": task,
                })

    _runners._cancel_all_tasks = _cancel_all_tasks


_закрытие_циклов_с_доносом()

# Настройки читаются на импорте модулей, поэтому задаём окружение раньше
os.environ.setdefault("DEBUG", "true")
os.environ.setdefault("JWT_SECRET", "test_secret_not_for_production")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5433/test")


@pytest.fixture(scope="session")
def app():
    from main import app as fastapi_app

    return fastapi_app


@pytest.fixture(autouse=True)
def _без_общего_лимитера(monkeypatch):
    """Счётчики частоты — на каждый тест свои.

    Лимиты живут в Redis (middleware/rate_limit.py), и если на машине поднят
    docker compose, счётчики переживают прогон: у `/api/reels` лимит 20 в час,
    поэтому тесты публикации ролика зеленели на чистой базе и падали с 429
    после нескольких прогонов подряд. Тест не должен зависеть от того, гонял
    ли его кто-то полчаса назад.

    Подменяем хранилище на словарь в памяти, живущий ровно один тест. Сам
    лимитер при этом проверяется по-настоящему: логика окна и подсчёта его,
    подменено только хранилище.
    """
    счётчики: dict[str, int] = {}

    class _RedisВПамяти:
        async def incr(self, key: str) -> int:
            счётчики[key] = счётчики.get(key, 0) + 1
            return счётчики[key]

        async def expire(self, *_a, **_kw) -> None:
            """Окно и так не переживает тест — чистить нечего."""

    async def _get_redis():
        return _RedisВПамяти()

    import middleware.rate_limit as rl

    monkeypatch.setattr(rl, "get_redis", _get_redis)


@pytest.fixture(scope="session")
def openapi(app):
    return app.openapi()


@pytest.fixture
def settings():
    from config import get_settings

    return get_settings()
