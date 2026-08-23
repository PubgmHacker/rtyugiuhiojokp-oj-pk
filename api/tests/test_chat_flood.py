"""Антифлуд личного чата и лимит активации промокодов.

Находка аудита: у сообщений лички не было никакого потолка частоты, а у
`/api/promo/activate` — никакого лимита попыток. Комнаты свой антифлуд имели
(`routers/rooms.py::check_flood`, SQL-счётчик), личка — нет: бот слал залпы,
и каждое сообщение до отказа модерации успевало стать платным AI-запросом.
Промокод же перебирался свободно: код короткий и человекочитаемый, выигрыш —
бесплатная подписка.

Закрытие: `services/chat_delivery.py::check_chat_flood` — Redis-счётчик по
минутному окну (SQL как в комнатах не годится: Message — самая большая
таблица и индекса по sender_id у неё нет), вызывается во всех трёх точках
отправки ДО `moderate_text`; промо — строка в `middleware/rate_limit.py`
и членство в `_CRITICAL_PREFIXES` (при сбое Redis путь закрывается, а не
открывается).
"""

from __future__ import annotations

import inspect

import pytest

from middleware.rate_limit import _CRITICAL_PREFIXES, _find_limit
from services import chat_delivery
from services.chat_delivery import (
    CHAT_FLOOD_PER_MINUTE, ДоставкаОтклонена, check_chat_flood,
)


class _FakeRedis:
    """INCR/EXPIRE в память — ровно то, что зовёт check_chat_flood."""

    def __init__(self) -> None:
        self.counts: dict[str, int] = {}
        self.expires: dict[str, int] = {}

    async def incr(self, key: str) -> int:
        self.counts[key] = self.counts.get(key, 0) + 1
        return self.counts[key]

    async def expire(self, key: str, ttl: int) -> None:
        self.expires[key] = ttl


@pytest.fixture()
def redis(monkeypatch) -> _FakeRedis:
    fake = _FakeRedis()

    async def _get_redis() -> _FakeRedis:
        return fake

    monkeypatch.setattr(chat_delivery, "get_redis", _get_redis)
    return fake


async def test_до_лимита_проходит(redis: _FakeRedis):
    """Живая переписка репликами по слову не должна упираться в антифлуд."""
    for _ in range(CHAT_FLOOD_PER_MINUTE):
        await check_chat_flood("user-1")


async def test_сверх_лимита_отклоняется(redis: _FakeRedis):
    for _ in range(CHAT_FLOOD_PER_MINUTE):
        await check_chat_flood("user-1")
    with pytest.raises(ДоставкаОтклонена) as err:
        await check_chat_flood("user-1")
    # Код стабилен — по нему решает клиент; текст должен объяснять, что делать
    assert err.value.code == "flood"
    assert "подожд" in err.value.detail.lower()


async def test_отправители_не_делят_счётчик(redis: _FakeRedis):
    """Флудер не должен закрывать чат соседям: ключ — на отправителя."""
    for _ in range(CHAT_FLOOD_PER_MINUTE + 1):
        try:
            await check_chat_flood("spammer")
        except ДоставкаОтклонена:
            pass
    await check_chat_flood("user-2")  # не бросает


async def test_ключ_живёт_минуту(redis: _FakeRedis):
    """Окно фиксированное: ключ включает номер минуты и истекает сам.

    EXPIRE ставится один раз, на первом INCR — иначе каждый запрос продлевал
    бы окно и флудер, шлющий без пауз, никогда бы из него не выходил.
    """
    await check_chat_flood("user-1")
    await check_chat_flood("user-1")
    (key,) = redis.expires  # ровно один ключ с TTL
    assert redis.expires[key] == 60
    assert key.startswith("dating:chatflood:user-1:")


async def test_сбой_redis_пропускает(monkeypatch):
    """Личка — не перебор кодов: минута без антифлуда лучше чата, лежащего
    вместе с кешем. При сбое Redis сообщение проходит."""

    async def _упал():
        raise ConnectionError("redis down")

    monkeypatch.setattr(chat_delivery, "get_redis", _упал)
    await check_chat_flood("user-1")  # не бросает


def test_все_точки_отправки_зовут_антифлуд_до_модерации():
    """Незакрытая точка отправки обнуляет лимит целиком — читать это как
    «в проекте уже было»: пересыл ролика когда-то обходил комнатный антифлуд
    ровно потому, что проверка жила только в обработчике обычной отправки.

    И до модерации, не после: главный расход при флуде — платные AI-вызовы.
    """
    from routers.chat import websocket_chat
    from routers.matches import post_message
    from routers.reels import forward_reel

    for точка in (websocket_chat, post_message, forward_reel):
        src = inspect.getsource(точка)
        assert "check_chat_flood(" in src, точка.__name__
        assert src.index("check_chat_flood(") < src.index("moderate_text("), (
            f"{точка.__name__}: антифлуд должен стоять до платной модерации"
        )


def test_промо_лимит_в_таблице():
    """10 попыток в час: на опечатки хватает, перебор мёртв."""
    found = _find_limit("/api/promo/activate", "POST")
    assert found is not None
    prefix, limit, window = found
    assert prefix == "/api/promo/activate"
    assert (limit, window) == (10, 3600)


def test_промо_закрывается_при_сбое_redis():
    """Перебор промокода = бесплатная подписка: окно сбоя Redis не должно
    становиться окном перебора — путь в _CRITICAL_PREFIXES, отвечает 503."""
    assert "/api/promo/activate" in _CRITICAL_PREFIXES
