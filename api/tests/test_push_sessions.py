"""Пуш не держит соединение с БД, пока отвечает Apple.

Пул API — 10 постоянных соединений плюс 20 сверх (database/connection.py), и
это на весь инстанс: деплой идёт с `--workers 1`. Отправка одного мэтча — два
уведомления, каждое на все устройства человека, и на каждое устройство APNs
отвечает до 10 секунд (`timeout=10.0` в services/push.py).

Раньше сессию в `send_to_user` передавал вызывающий: в `routers/likes.py` это
была сессия ЗАПРОСА, и она вместе с соединением висела открытой весь разговор
с Apple. Тридцати одновременных мэтчей хватало, чтобы выбрать пул — и тогда
падают не пуши, а все остальные ручки API, включая логин.

Здесь закрепляется, что во время разговора с APNs открытых сессий ноль.
"""

from __future__ import annotations

import inspect

import pytest


class РезультатДвойник:
    """Ответ на select: одинаково умеет отдать строки и одно значение."""

    def __init__(self, строки: list[tuple]) -> None:
        self._строки = строки

    def all(self) -> list[tuple]:
        return list(self._строки)

    def scalar_one_or_none(self):
        return self._строки[0][0] if self._строки else None


class СессияДвойник:
    def __init__(self, фабрика: "ФабрикаДвойников") -> None:
        self.фабрика = фабрика

    async def execute(self, запрос):
        if запрос.__class__.__name__ == "Delete":
            self.фабрика.удаления.append(запрос)
            return None
        return РезультатДвойник(self.фабрика.строки)

    async def commit(self) -> None:
        self.фабрика.коммиты += 1


class ФабрикаДвойников:
    """Фабрика сессий, которая помнит, сколько их открыто ПРЯМО СЕЙЧАС.

    Считать «сколько всего создали» недостаточно: баг был именно в том, что
    сессия оставалась открытой на время сетевого вызова. Поэтому проверяем
    мгновенный счётчик в момент обращения к APNs.
    """

    def __init__(self, строки: list[tuple] | None = None) -> None:
        self.строки = строки if строки is not None else []
        self.открыто = 0
        self.всего = 0
        self.удаления: list = []
        self.коммиты = 0

    def __call__(self) -> "ФабрикаДвойников":
        return self

    async def __aenter__(self) -> СессияДвойник:
        self.открыто += 1
        self.всего += 1
        return СессияДвойник(self)

    async def __aexit__(self, *_а) -> bool:
        self.открыто -= 1
        return False


@pytest.fixture
def ключи_apns(monkeypatch):
    """APNs «настроен» — иначе отправка выходит на первой же строке."""
    from services import push

    for имя, значение in (
        ("APNS_KEY_P8", "key"),
        ("APNS_KEY_ID", "ABC123"),
        ("APNS_TEAM_ID", "TEAM123"),
        ("APNS_BUNDLE_ID", "com.simp.dating"),
    ):
        monkeypatch.setattr(push.settings, имя, значение)
    return push


async def test_соединение_не_занято_пока_отвечает_apple(ключи_apns, monkeypatch):
    """Главное следствие правки: на каждом обращении к APNs сессий ноль.

    Устройств берём три — у человека бывает телефон, планшет и старая сборка,
    и раньше сессия держалась через все три round-trip'а подряд.
    """
    push = ключи_apns
    фабрика = ФабрикаДвойников([("токен-1",), ("токен-2",), ("токен-3",)])
    открыто_во_время: list[int] = []

    async def _send(токен, payload, collapse_id):
        открыто_во_время.append(фабрика.открыто)
        return 200

    monkeypatch.setattr(push, "_send_one", _send)
    monkeypatch.setattr(push, "async_session_factory", фабрика)

    доставлено = await push.send_to_user("user-1", "Мэтч", "текст")

    assert доставлено == 3
    assert открыто_во_время == [0, 0, 0], (
        f"сессия была открыта во время разговора с Apple: {открыто_во_время}"
    )


async def test_токены_читаются_одной_короткой_сессией(ключи_apns, monkeypatch):
    """Живые токены — одна сессия на всё чтение, второй незачем открываться."""
    push = ключи_apns
    фабрика = ФабрикаДвойников([("токен-1",), ("токен-2",)])

    async def _send(токен, payload, collapse_id):
        return 200

    monkeypatch.setattr(push, "_send_one", _send)
    monkeypatch.setattr(push, "async_session_factory", фабрика)

    await push.send_to_user("user-1", "Мэтч", "текст")

    assert фабрика.всего == 1, f"сессий открыто {фабрика.всего}, хватало одной"
    assert фабрика.открыто == 0, "сессия не закрыта после отправки"


async def test_мёртвые_токены_чистятся_своей_сессией(ключи_apns, monkeypatch):
    """Уборка мусора — отдельная короткая сессия ПОСЛЕ разговора с Apple.

    410 приходит от Apple, то есть узнать о мёртвом токене раньше отправки
    нельзя. Значит, удаление обязано открыть свою сессию — и снова не держать
    её, пока идут остальные round-trip'ы.
    """
    push = ключи_apns
    фабрика = ФабрикаДвойников([("живой",), ("мёртвый",)])

    async def _send(токен, payload, collapse_id):
        assert фабрика.открыто == 0, "чистка открыла сессию посреди отправки"
        return 200 if токен == "живой" else 410

    monkeypatch.setattr(push, "_send_one", _send)
    monkeypatch.setattr(push, "async_session_factory", фабрика)

    доставлено = await push.send_to_user("user-1", "Мэтч", "текст")

    assert доставлено == 1
    assert len(фабрика.удаления) == 1, "мёртвый токен не удалён"
    assert фабрика.коммиты == 1, "удаление не закоммичено — токен останется"
    assert фабрика.всего == 2, (
        f"ожидались две короткие сессии (чтение и уборка), было {фабрика.всего}"
    )


async def test_без_мёртвых_токенов_вторая_сессия_не_открывается(
    ключи_apns, monkeypatch
):
    """Всё доставлено — уборке нечего делать, соединение зря не берём."""
    push = ключи_apns
    фабрика = ФабрикаДвойников([("живой",)])

    async def _send(токен, payload, collapse_id):
        return 200

    monkeypatch.setattr(push, "_send_one", _send)
    monkeypatch.setattr(push, "async_session_factory", фабрика)

    await push.send_to_user("user-1", "Мэтч", "текст")

    assert фабрика.всего == 1, "открылась лишняя сессия под пустую уборку"
    assert фабрика.удаления == []


async def test_без_устройств_к_apple_не_ходим(ключи_apns, monkeypatch):
    """Токенов нет — сети не касаемся: у большинства нет iOS-приложения."""
    push = ключи_apns
    фабрика = ФабрикаДвойников([])

    async def _send(*_а, **_к):
        raise AssertionError("отправка без токенов")

    monkeypatch.setattr(push, "_send_one", _send)
    monkeypatch.setattr(push, "async_session_factory", фабрика)

    assert await push.send_to_user("user-1", "Мэтч", "текст") == 0
    assert фабрика.всего == 1, "чтение токенов должно быть ровно одно"


async def test_мэтч_отпускает_соединение_до_пуша(monkeypatch):
    """Слой выше: `likes._push_match_notifications` читает имена и закрывается.

    Имена собеседников нужны для текста пуша, но взять их — дело на один
    select. Держать эту сессию до конца отправки значило бы вернуть тот же баг
    этажом выше: `send_to_user` внизу уже честный, а соединение всё равно
    занято.
    """
    from routers import likes

    фабрика = ФабрикаДвойников([("user-1", "Аня"), ("user-2", "Боря")])
    открыто_во_время: list[int] = []
    пуши: list[tuple] = []

    async def _notify(кому, имя, match_id):
        открыто_во_время.append(фабрика.открыто)
        пуши.append((кому, имя, match_id))

    monkeypatch.setattr(likes, "is_configured", lambda: True)
    monkeypatch.setattr(likes, "notify_new_match", _notify)
    monkeypatch.setattr(likes, "async_session_factory", фабрика)

    await likes._push_match_notifications("user-1", "user-2", "match-1")

    assert открыто_во_время == [0, 0], (
        f"сессия мэтча дожила до пуша: {открыто_во_время}"
    )
    # Каждому — имя ДРУГОГО: перепутать здесь значит прислать человеку пуш с
    # его собственным именем
    assert пуши == [
        ("user-1", "Боря", "match-1"),
        ("user-2", "Аня", "match-1"),
    ]


async def test_мэтч_без_ключей_apns_в_бд_не_ходит(monkeypatch):
    """Ключей нет — незачем и имена читать: соединение осталось бы зря взятым."""
    from routers import likes

    async def _нет_сессий(*_а, **_к):
        raise AssertionError("без ключей APNs сессия не нужна")

    async def _нет_пушей(*_а, **_к):
        raise AssertionError("отправка без ключей")

    monkeypatch.setattr(likes, "is_configured", lambda: False)
    monkeypatch.setattr(likes, "notify_new_match", _нет_пушей)
    monkeypatch.setattr(likes, "async_session_factory", _нет_сессий)

    await likes._push_match_notifications("user-1", "user-2", "match-1")


async def test_сообщение_отпускает_соединение_до_пуша(monkeypatch):
    """Тот же слой в чате: имя отправителя прочитано, сессия закрыта.

    Здесь это особенно важно: сообщение приходит из WebSocket, и такие
    соединения живут долго — занятое на разговор с Apple соединение из пула
    держалось бы у каждого активного чата.
    """
    from services import chat_delivery

    фабрика = ФабрикаДвойников([("Аня",)])
    открыто_во_время: list[int] = []
    пуши: list[tuple] = []

    async def _notify(кому, имя, текст, match_id):
        открыто_во_время.append(фабрика.открыто)
        пуши.append((кому, имя, текст, match_id))

    monkeypatch.setattr(chat_delivery, "is_configured", lambda: True)
    monkeypatch.setattr(chat_delivery, "notify_new_message", _notify)
    monkeypatch.setattr(chat_delivery, "async_session_factory", фабрика)

    await chat_delivery._push_notification("match-1", "user-1", "user-2", "привет")

    assert открыто_во_время == [0], f"сессия чата дожила до пуша: {открыто_во_время}"
    assert пуши == [("user-2", "Аня", "привет", "match-1")]


async def test_сбой_чтения_имени_не_роняет_доставку(monkeypatch):
    """БД отказала на чтении имени — сообщение уже сохранено, падать нельзя.

    Пуш best-effort: без имени он не уйдёт, но исключение из фан-аута оборвало
    бы обработчик сокета уже ПОСЛЕ коммита сообщения.
    """
    from services import chat_delivery

    class _Падает:
        async def __aenter__(self):
            raise RuntimeError("пул исчерпан")

        async def __aexit__(self, *_а):
            return False

    async def _нет_пушей(*_а, **_к):
        raise AssertionError("без имени пуш не отправляем")

    monkeypatch.setattr(chat_delivery, "is_configured", lambda: True)
    monkeypatch.setattr(chat_delivery, "notify_new_message", _нет_пушей)
    monkeypatch.setattr(chat_delivery, "async_session_factory", lambda: _Падает())

    await chat_delivery._push_notification("match-1", "user-1", "user-2", "привет")


def test_пуш_не_принимает_чужую_сессию():
    """Страховка от возврата бага: сессию в подписи держит только запись токена.

    Правка легко откатывается «удобным» параметром `session=None` — и первый же
    вызывающий передаст туда сессию запроса. `register_device` — исключение и
    остаётся с сессией осознанно: это запись в транзакции запроса, сети в ней
    нет.
    """
    from services import push

    for функция in (push.send_to_user, push.notify_new_match, push.notify_new_message):
        параметры = inspect.signature(функция).parameters
        assert "session" not in параметры, (
            f"{функция.__name__} снова берёт сессию — соединение из пула будет "
            "занято на весь разговор с APNs"
        )

    assert "session" in inspect.signature(push.register_device).parameters, (
        "register_device пишет в транзакции запроса и сессию принимать должен"
    )
