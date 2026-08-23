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
    # Конструктор повторяет оба пути создания клиента в боте: подписной
    # redis.from_url(...) и командный redis.Redis(connection_pool=пул)
    def __init__(self, *a, **kw):
        self.номер = len(создано)
        создано.append(self)
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
    return ФейковыйКлиент()

class ФейковыйБлокирующийПул:
    @classmethod
    def from_url(cls, url, **kw):
        return cls()

модуль = types.ModuleType("redis.asyncio")
модуль.from_url = from_url
модуль.Redis = ФейковыйКлиент
модуль.BlockingConnectionPool = ФейковыйБлокирующийПул
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


def test_подписка_живёт_на_своём_клиенте_и_убирает_за_собой():
    """Подписка и публикации — на РАЗНЫХ клиентах, выход закрывает только свой.

    Разделение принципиально: командному клиенту нужен socket_timeout (иначе
    blackhole вешает publish вместе с хендлером), а подписному он противопоказан
    (для listen() тихий канал неотличим от мёртвого сокета — таймаут рвал бы
    подписку на каждой паузе). При выходе подписка обязана закрыть свой клиент —
    её перезапускает supervise_redis_subscriber, и незакрытый пул тёк бы на
    каждом переподключении, — но не общий: публикации из хендлеров после
    перезапуска идут в него же.
    """
    ответ = _в_боте(ЗАГЛУШКА + """
import asyncio, json
import services.redis_subscriber as rs

async def main():
    # Подписка сразу завершится: listen() у заглушки пустой
    await rs.start_redis_subscriber(None)
    # Публикация после выхода из подписки должна пройти на живом общем клиенте
    await rs.publish_match_event("m1", "u1", "u2")
    print(json.dumps({"создано": len(создано), "закрыто": закрыто}))

asyncio.run(main())
""")
    assert ответ["создано"] == 2, (
        f"клиентов создано {ответ['создано']}, а не 2 — подписка и публикации "
        "должны жить на разных клиентах: подписному нельзя socket_timeout, "
        "командному он обязателен"
    )
    assert ответ["закрыто"] == [0], (
        f"закрыты клиенты {ответ['закрыто']} — при выходе подписка закрывает "
        "ровно свой клиент (№0): иначе либо утечка пула на каждом "
        "переподключении, либо публикации хендлеров в закрытый общий пул"
    )


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


#: Подмена sentry_sdk до импорта алертинга: настоящая сеть и настоящий проект
#: Sentry не нужны, нас интересует ровно то, что модуль отдаёт наружу.
ФЕЙК_SENTRY = """
import sys, types, json

события = []
теги = {}

class _Область:
    def set_tag(self, k, v): теги[k] = v
    def __enter__(self): return self
    def __exit__(self, *a): return False

фейк = types.ModuleType("sentry_sdk")
фейк.init = lambda **kw: события.append(("init", kw))
фейк.new_scope = lambda: _Область()
фейк.capture_exception = lambda exc: события.append(("exc", type(exc).__name__))
фейк.capture_message = lambda msg, level="error": события.append(("msg", level, msg))
sys.modules["sentry_sdk"] = фейк

import services.alerting as A
"""


def test_алертинг_бота_молчит_без_dsn():
    """Без SENTRY_DSN — ни одного обращения к sentry_sdk.

    Это не косметика: `capture_exception` зовётся из `on_error`, то есть на
    каждой упавшей кнопке. Если no-op сломается, локальная разработка и любое
    окружение без DSN начнут ловить исключения внутри обработчика ошибок —
    единственного места, которое обязано работать всегда.
    """
    ответ = _в_боте(ФЕЙК_SENTRY + """
A.init("")
A.capture_exception(ValueError("падение"), update_id=7)
A.capture_message("деградация")
print(json.dumps({"события": события}))
""")
    assert ответ["события"] == [], (
        f"без DSN алертинг всё равно дёргает sentry_sdk: {ответ['события']}"
    )


def test_алертинг_бота_отправляет_с_тегами():
    """С DSN исключение уходит вместе с тегами апдейта.

    Теги — вся разница между «в проекте 4000 событий „Необработанная ошибка“»
    и «вот этот апдейт этого человека на этой кнопке». А `server_name` отличает
    поток бота от потока API: DSN один на два процесса, и без метки стектрейсы
    сливаются в одну кучу.
    """
    ответ = _в_боте(ФЕЙК_SENTRY + """
A.init("https://ключ@example.invalid/1")
A.capture_exception(ValueError("падение"), update_id=7, telegram_id=42, callback_data=None)
A.capture_message("подписка лежит")
print(json.dumps({"события": события, "теги": теги}))
""")
    вид = [e[0] for e in ответ["события"]]
    assert вид == ["init", "exc", "msg"], f"неожиданный поток событий: {вид}"

    инит = ответ["события"][0][1]
    assert инит.get("server_name") == "simp-dating-bot", (
        "события бота не помечены server_name — в одном проекте Sentry их "
        "не отличить от событий API"
    )
    assert инит.get("traces_sample_rate") == 0.0, (
        "включена трассировка: трейсы долгого polling'а забьют квоту событий"
    )
    assert ответ["теги"] == {"update_id": "7", "telegram_id": "42"}, (
        f"теги потерялись или проехал None: {ответ['теги']}"
    )


def test_точка_входа_включает_алертинг():
    """`bot.py` инициализирует алертинг и сообщает об ошибке в Sentry.

    Модуль может существовать и не вызываться: до этой правки бот целиком
    полагался на `logger.exception`, а логи Railway живут до следующего
    деплоя и никого не будят. Импортировать `bot.py` нечем (aiogram в другом
    venv) — читаем вызовы через AST, как и надзиратель подписки выше.
    """
    дерево = ast.parse((БОТ / "bot.py").read_text(encoding="utf-8"))

    имена = set()
    for узел in ast.walk(дерево):
        if isinstance(узел, ast.Call) and isinstance(узел.func, ast.Name):
            имена.add(узел.func.id)

    assert "init_alerting" in имена, (
        "bot.py не зовёт init_alerting — падения обработчиков останутся "
        "только в эфемерном логе Railway"
    )
    assert "capture_exception" in имена, (
        "on_error не отправляет исключение в Sentry: об упавшей кнопке "
        "узнаем от пользователя, а не от алерта"
    )
