"""Инфраструктура бота: соединения с Redis и живучесть подписки.

Бот живёт в отдельном venv и код API импортировать не может, поэтому проверки
здесь запускаются его собственным интерпретатором через subprocess — тем же
приёмом, что и витрина в `test_feature_gates.py`. Настоящий Redis не нужен:
`redis.asyncio.from_url` подменяется счётчиком, а нас интересует ровно то,
сколько раз бот заводит клиента и что делает при обрыве подписки.

Почему это тест, а не однократная правка: `redis.from_url` в теле функции
выглядит безобидно и возвращается в код при первой же правке файла. Цена —
утечка TCP-соединения на каждое сообщение в чате и упор в `maxclients`, после
которого перестают ходить вообще все события.
"""

from __future__ import annotations

import ast
import json
import subprocess
from pathlib import Path

import pytest

БОТ = Path(__file__).resolve().parents[2] / "bot"


def _в_боте(скрипт: str) -> dict:
    """Выполнить скрипт интерпретатором бота и забрать JSON из последней строки."""
    python = БОТ / ".venv" / "bin" / "python"
    if not python.exists():
        pytest.skip("venv бота не поднят в этом окружении")

    результат = subprocess.run(
        [str(python), "-c", скрипт], cwd=БОТ, capture_output=True, text=True, timeout=120,
    )
    assert результат.returncode == 0, результат.stderr[-1500:]
    return json.loads(результат.stdout.strip().splitlines()[-1])


#: Подмена redis.asyncio до импорта модуля бота: считаем создания клиентов и
#: закрытия, настоящая сеть не нужна.
ЗАГЛУШКА = """
import sys, types, asyncio, json

создано = []
закрыто = []

class ФейковыйКлиент:
    def __init__(self, номер): self.номер = номер
    async def publish(self, канал, данные): return 1
    async def aclose(self): закрыто.append(self.номер)
    def pubsub(self): return ФейковыйPubSub()

class ФейковыйPubSub:
    async def subscribe(self, *к): pass
    async def unsubscribe(self, *к): pass
    async def aclose(self): pass
    def listen(self):
        async def пусто():
            if False:
                yield None
        return пусто()

def from_url(url, **kw):
    клиент = ФейковыйКлиент(len(создано))
    создано.append(клиент)
    return клиент

модуль = types.ModuleType("redis.asyncio")
модуль.from_url = from_url
модуль.Redis = ФейковыйКлиент
корень = types.ModuleType("redis")
корень.asyncio = модуль
sys.modules["redis"] = корень
sys.modules["redis.asyncio"] = модуль

sys.path.insert(0, ".")
"""


def test_бот_держит_один_клиент_redis_на_процесс():
    """Публикации переиспользуют клиента, а не заводят новый каждый раз.

    `redis.from_url` создаёт клиент вместе с НОВЫМ пулом соединений. Публикация
    происходит на каждое сообщение в чате, и клиента никто не закрывал: бот
    оставлял по соединению на сообщение, пока Redis не отказывал всем сразу.
    """
    ответ = _в_боте(ЗАГЛУШКА_ПУБЛИКАЦИЙ)
    assert ответ["создано"] == 1, (
        f"бот завёл {ответ['создано']} клиентов Redis на 3 публикации — "
        "клиент должен быть один на процесс, как в api/services/realtime.py"
    )
    assert ответ["закрыто_после_close"] == 1, "close_redis() не закрывает клиента"


ЗАГЛУШКА_ПУБЛИКАЦИЙ = ЗАГЛУШКА + """
import services.redis_subscriber as rs

async def main():
    await rs.publish_match_event("m1", "u1", "u2")
    await rs.publish_message_event("m1", "u1", "привет")
    await rs.publish_message_event("m1", "u1", "и ещё раз")
    было = len(создано)
    await rs.close_redis()
    print(json.dumps({"создано": было, "закрыто_после_close": len(закрыто)}))

asyncio.run(main())
"""


def test_подписка_переподключается_после_обрыва():
    """Обрыв подписки не оставляет бота без уведомлений навсегда.

    У Redis pubsub нет ни персистентности, ни backpressure: при переполнении
    исходящего буфера Redis сам обрывает подписчика. Раньше задача после этого
    тихо завершалась — мэтчи, сообщения и лайки перестали бы доходить до людей
    до перезапуска процесса, и в логах не было бы ничего.
    """
    ответ = _в_боте(ЗАГЛУШКА + """
import asyncio, json
import services.redis_subscriber as rs

попытки = []

async def падающая_подписка(bot):
    попытки.append(1)
    raise ConnectionError("Redis закрыл соединение")

rs.start_redis_subscriber = падающая_подписка

async def main():
    задача = asyncio.create_task(rs.supervise_redis_subscriber(None, первая_пауза=0.01))
    await asyncio.sleep(0.2)
    жива = not задача.done()
    задача.cancel()
    try:
        await задача
    except asyncio.CancelledError:
        pass
    print(json.dumps({"попыток": len(попытки), "жива": жива}))

asyncio.run(main())
""")
    assert ответ["попыток"] > 1, (
        f"подписка не переподключилась: попыток {ответ['попыток']} — "
        "упавшая задача оставляет бота без всех уведомлений"
    )
    assert ответ["жива"], "надзиратель сам умер вместе с подпиской"


def test_подписка_не_закрывает_общий_клиент_при_выходе():
    """Выход из подписки не рвёт публикации остальным.

    Клиент теперь общий, и `await r.aclose()` в `finally` подписки закрыл бы
    его всем сразу: подписка при перезапуске поднялась бы, а публикации из
    хендлеров пошли бы в закрытый пул.
    """
    ответ = _в_боте(ЗАГЛУШКА + """
import asyncio, json
import services.redis_subscriber as rs

async def main():
    # Подписка сразу завершится: listen() у заглушки пустой
    await rs.start_redis_subscriber(None)
    # Публикация после выхода из подписки должна пройти на том же клиенте
    await rs.publish_match_event("m1", "u1", "u2")
    print(json.dumps({"создано": len(создано), "закрыто": len(закрыто)}))

asyncio.run(main())
""")
    assert ответ["закрыто"] == 0, (
        "подписка закрыла общий клиент — публикации из хендлеров пойдут в "
        "закрытый пул соединений"
    )
    assert ответ["создано"] == 1


def test_точка_входа_запускает_подписку_под_надзором():
    """`bot.py` заводит именно надзиратель, а не голую подписку.

    Надзиратель может существовать и быть недостижимым: достаточно одной правки
    в `main()`, и подписка снова умирает после первого обрыва — молча, потому
    что вся разница видна только под нагрузкой. Импортировать `bot.py` тут
    нечем (aiogram живёт в другом venv), поэтому читаем вызовы через AST.
    """
    дерево = ast.parse((БОТ / "bot.py").read_text(encoding="utf-8"))

    имена = set()
    for узел in ast.walk(дерево):
        if isinstance(узел, ast.Call) and isinstance(узел.func, ast.Name):
            имена.add(узел.func.id)

    assert "supervise_redis_subscriber" in имена, (
        "bot.py не запускает supervise_redis_subscriber — обрыв подписки "
        "Redis'ом снова остановит ВСЕ уведомления в Telegram до перезапуска"
    )
    assert "start_redis_subscriber" not in имена, (
        "bot.py зовёт start_redis_subscriber напрямую, минуя надзиратель"
    )
    assert "close_redis" in имена, (
        "bot.py не закрывает общий клиент Redis при остановке"
    )
