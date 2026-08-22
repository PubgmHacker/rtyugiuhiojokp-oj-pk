"""Жалоба обязана возвращаться ответом — иначе модерация выглядит выключенной.

Дыра, которую здесь закрываем: человек нажимал «Пожаловаться», получал
«Модераторы разберутся» и больше не узнавал ничего. Ни что анкету скрыли из
поиска, ни что нарушителя забанили, ни что модератор нарушения не нашёл. Со
стороны это неотличимо от кнопки, которая никуда не ведёт, — а эскалация в
routers/report.py стоит ровно на жалобах тех, кто реально пересекался с
нарушителем: перестанут жаловаться, перестанет работать и автоматика.

Второй вопрос — дозировка. Порог считается по числу разных жалобщиков, и
наивное «уведомить всех, если счёт ≥ 5» рассылало бы «аккаунт заблокирован»
предыдущим пятерым на каждую следующую жалобу, а заодно повторяло бы
бан-уведомление самой цели. Уведомление уходит на ПЕРЕХОДЕ через порог.

Третий — автобан по жалобам собирался в report.py руками (флаг, память банов,
отзыв токенов) и не имел защиты роли: пять сговорившихся аккаунтов
блокировали админа. Теперь бан идёт через общий ban_user_for_violation.

Четвёртый — каналов доставки два. Событие в Redis подхватывает бот, но у
человека, вошедшего через Apple ID, Telegram может не быть вовсе: подписчик
молча выходит на пустом telegram_id, и для него итог существует только пушем.
Каналы независимы — упавший Redis не отменяет пуш и наоборот.

База и Redis для этих тестов не нужны: сессия, Redis и APNs подменены
заглушками, проверяется решение эскалации и состав отправленного.
"""

from __future__ import annotations

import ast
import inspect
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

БОТ = Path(__file__).resolve().parents[2] / "bot"


# ── Заглушки сессии и Redis ───────────────────────────────────────

class _Результат:
    """Ответ session.execute: и скаляр, и список — по месту вызова."""

    def __init__(self, значение=None, список=None):
        self._значение = значение
        self._список = список or []

    def scalar_one_or_none(self):
        return self._значение

    def scalar(self):
        return self._значение

    def scalars(self):
        return SimpleNamespace(all=lambda: list(self._список))

    def all(self):
        return list(self._список)


class _Сессия:
    """Сессия с очередью ответов на execute в порядке вызовов.

    Порядок запросов — часть проверяемого поведения: если в create_report
    появится лишний select, тест упадёт на пустой очереди, а не тихо позеленеет
    на сдвинутых ответах.
    """

    def __init__(self, *ответы: _Результат):
        self.ответы = list(ответы)
        self.добавлено: list = []

    async def execute(self, _запрос):
        assert self.ответы, "запросов больше, чем заготовленных ответов"
        return self.ответы.pop(0)

    def add(self, объект):
        self.добавлено.append(объект)

    async def flush(self):
        pass


@pytest.fixture
def события(monkeypatch):
    """Перехватить всё, что уходит в Redis, и обезвредить побочные эффекты бана."""
    import services.ai_moderation as ai_moderation
    import services.enforcement as enforcement
    import services.push as push
    import services.realtime as rt

    опубликовано: list[tuple[str, dict]] = []

    class _Redis:
        async def publish(self, канал, тело):
            опубликовано.append((канал, json.loads(тело)))

    async def _редис():
        return _Redis()

    async def _тихо(*a, **kw):
        return True

    async def _без_пуша(*a, **kw):
        return 0

    async def _без_журнала(*a, **kw):
        return None

    async def _первый_бан(user_id):
        return 0

    monkeypatch.setattr(rt, "get_redis", _редис)
    monkeypatch.setattr(enforcement, "remember_ban", _тихо)
    monkeypatch.setattr(enforcement, "revoke_all_for_user", _тихо)
    # Лестницу сроков прибиваем к первой ступени, а журнал глушим: иначе на
    # машине с поднятым docker compose каждый прогон писал бы «цели» реальный
    # ban_applied, и со второго раза тест получал бы уже вечный бан вместо
    # первой ступени. Тест не должен зависеть от истории прошлых прогонов.
    monkeypatch.setattr(ai_moderation, "log_moderation", _без_журнала)
    monkeypatch.setattr(enforcement, "prior_ban_count", _первый_бан)
    # Пуш глушим всегда, а не полагаемся на то, что в окружении теста нет
    # ключей APNs: иначе набор тестов зависел бы от наличия .p8 в env и на
    # машине с настроенными пушами полез бы в БД за токенами устройств
    monkeypatch.setattr(push, "send_to_user", _без_пуша)
    return опубликовано


@pytest.fixture
def пуши(события, monkeypatch):
    """Перехватить пуши APNs — второй канал доставки итога.

    Зависит от `события` намеренно: та фикстура ставит пушам заглушку, и
    перехват обязан встать поверх неё, а не наоборот, в каком бы порядке тест
    ни просил обе.
    """
    import services.push as push

    отправлено: list[dict] = []

    async def _отправить(user_id, title, body, data=None, collapse_id=None):
        отправлено.append(
            {
                "user_id": user_id,
                "title": title,
                "body": body,
                "data": data or {},
                "collapse_id": collapse_id,
            }
        )
        return 1

    monkeypatch.setattr(push, "send_to_user", _отправить)
    return отправлено


def _цель(**kw):
    основа = dict(
        id="цель", role="user", telegram_id=555, apple_id=None, is_banned=False
    )
    основа.update(kw)
    return SimpleNamespace(**основа)


def _жалоба(reported_id="цель"):
    from models.schemas import ReportRequest

    return ReportRequest(reported_id=reported_id, reason="harassment", description="")


def _итоги(опубликовано: list[tuple[str, dict]]) -> list[dict]:
    return [
        тело for канал, тело in опубликовано
        if канал == "dating:bot:events" and тело.get("type") == "report_outcome"
    ]


# ── Рассылка итога ────────────────────────────────────────────────

async def test_итог_уходит_каждому_жалобщику_по_одному_разу(события):
    """Дубли склеиваются: на одну цель жалуются и из деки, и из переписки."""
    from services.report_notify import notify_report_outcome

    await notify_report_outcome(["a", "b", "a", "", "c"], "banned")

    assert [т["user_id"] for т in _итоги(события)] == ["a", "b", "c"]
    assert all(т["outcome"] == "banned" for т in _итоги(события))
    assert all(канал == "dating:bot:events" for канал, _ in события)


async def test_неизвестный_итог_не_публикуется(события, пуши):
    """Код, которого нет в ИТОГИ, — ошибка вызывающего, а не сообщение людям."""
    from services.report_notify import notify_report_outcome

    await notify_report_outcome(["a"], "что_то_новое")
    await notify_report_outcome([], "banned")
    await notify_report_outcome(["", None], "banned")

    assert события == []
    assert пуши == [], "проверка кода обязана стоять до отправки, а не после"


async def test_падение_redis_не_ломает_жалобу(события, monkeypatch):
    """Модерация уже применена: недоставленное уведомление не должно её ронять."""
    import services.realtime as rt
    from services.report_notify import notify_report_outcome

    async def _взорвать():
        raise RuntimeError("redis лежит")

    monkeypatch.setattr(rt, "get_redis", _взорвать)
    await notify_report_outcome(["a"], "hidden")  # исключение не улетает наружу


# ── Второй канал: пуш в приложение ────────────────────────────────

async def test_жалобщик_без_телеграма_получает_пуш(пуши):
    """Вход по Apple ID не требует Telegram — событие бота до человека не дойдёт.

    Подписчик бота молча выходит на пустом telegram_id
    (bot/services/redis_subscriber.py), так что для такого жалобщика
    единственный канал — пуш, и слать его обязан API.
    """
    from services.report_notify import notify_report_outcome

    await notify_report_outcome(["a", "b", "a"], "hidden")

    assert [п["user_id"] for п in пуши] == ["a", "b"], (
        "дубли склеиваются и здесь: два пуша об одном итоге — это спам"
    )
    assert all(п["data"] == {"kind": "report_outcome", "outcome": "hidden"} for п in пуши)


async def test_пуш_не_сворачивается_и_не_несёт_разметки(пуши):
    """Пуш — одна строка текста, а не HTML бота, и без collapse_id.

    Разметка в пуше видна как теги: у APNs нет HTML. А общий collapse_id
    заменял бы предыдущий итог следующим — из трёх решений по трём разным
    людям человек увидел бы одно.
    """
    from services.report_notify import ПУШИ, notify_report_outcome

    await notify_report_outcome(["a"], "banned")

    (пуш,) = пуши
    assert пуш["collapse_id"] is None
    assert пуш["title"] and пуш["body"]
    assert "<" not in пуш["title"] + пуш["body"]
    assert "\n" not in пуш["body"], "перенос строки в пуше обрежется системой"
    assert (пуш["title"], пуш["body"]) == ПУШИ["banned"]


async def test_упавший_пуш_не_отменяет_телеграм(события, monkeypatch):
    """Каналы независимы: APNs не должен уносить с собой сообщение бота."""
    import services.push as push
    from services.report_notify import notify_report_outcome

    async def _взорвать(*a, **kw):
        raise RuntimeError("APNs отвечает 500")

    monkeypatch.setattr(push, "send_to_user", _взорвать)
    await notify_report_outcome(["ж1", "ж2"], "banned")

    assert [т["user_id"] for т in _итоги(события)] == ["ж1", "ж2"]


async def test_упавший_редис_не_отменяет_пуш(пуши, monkeypatch):
    """И обратно: лежащий Redis не должен лишать пуша тех, кому он единственный."""
    import services.realtime as rt
    from services.report_notify import notify_report_outcome

    async def _взорвать():
        raise RuntimeError("redis лежит")

    monkeypatch.setattr(rt, "get_redis", _взорвать)
    await notify_report_outcome(["ж1", "ж2"], "hidden")

    assert [п["user_id"] for п in пуши] == ["ж1", "ж2"], (
        "один try/except на оба канала — и падение первого отменяет второй"
    )


async def test_пуши_уходят_разом_а_не_по_очереди(события, monkeypatch):
    """Пять жалобщиков подряд держали бы ручку жалобы почти минуту.

    Разговор с APNs — до 10 секунд на устройство (httpx timeout в
    services/push.py), а получателей на пороге бана пять. Проверяем без
    таймингов: каждый вызов ждёт, пока войдут остальные, и последний открывает
    барьер. Последовательный цикл на этом встанет и упадёт по таймауту.
    """
    import asyncio

    import services.push as push
    from services.report_notify import notify_report_outcome

    кому = [f"ж{i}" for i in range(1, 6)]
    вошли: list[str] = []
    барьер = asyncio.Event()

    async def _отправить(user_id, title, body, data=None, collapse_id=None):
        вошли.append(user_id)
        if len(вошли) == len(кому):
            барьер.set()
        await барьер.wait()
        return 1

    monkeypatch.setattr(push, "send_to_user", _отправить)

    try:
        await asyncio.wait_for(notify_report_outcome(кому, "banned"), timeout=5)
    except asyncio.TimeoutError:
        pytest.fail(
            f"пуши отправляются по очереди (вошло {len(вошли)} из {len(кому)}): "
            "ручка жалобы будет ждать APNs по каждому жалобщику отдельно"
        )

    assert вошли == кому


# ── Эскалация: пороги и уведомления ───────────────────────────────

async def test_третья_жалоба_прячет_анкету_и_отвечает_жалобщикам(события):
    from routers import report

    анкета = SimpleNamespace(user_id="цель", is_incognito=False)
    сессия = _Сессия(
        _Результат(значение=_цель()),                       # цель существует
        _Результат(значение=None),                          # дубля жалобы нет
        _Результат(список=["ж1", "ж2", "ж3"]),              # трое разных
        _Результат(значение=анкета),                        # анкета цели
    )

    await report.create_report(_жалоба(), user=SimpleNamespace(id="ж3"), session=сессия)

    assert анкета.is_incognito is True, "третья жалоба обязана убирать анкету из выдачи"
    assert [т["user_id"] for т in _итоги(события)] == ["ж1", "ж2", "ж3"]
    assert {т["outcome"] for т in _итоги(события)} == {"hidden"}


async def test_четвёртая_жалоба_не_повторяет_ответ(события):
    """Порог пройден раньше: анкета уже скрыта, а рассылать «скрыли» второй
    раз — превращать модерацию в спам."""
    from routers import report

    анкета = SimpleNamespace(user_id="цель", is_incognito=True)
    сессия = _Сессия(
        _Результат(значение=_цель()),
        _Результат(значение=None),
        _Результат(список=["ж1", "ж2", "ж3", "ж4"]),
        _Результат(значение=анкета),
    )

    await report.create_report(_жалоба(), user=SimpleNamespace(id="ж4"), session=сессия)

    assert анкета.is_incognito is True
    assert _итоги(события) == []


async def test_пятая_жалоба_банит_и_говорит_обеим_сторонам(события):
    from routers import report

    цель = _цель()
    сессия = _Сессия(
        _Результат(значение=цель),
        _Результат(значение=None),
        _Результат(список=["ж1", "ж2", "ж3", "ж4", "ж5"]),
    )

    await report.create_report(_жалоба(), user=SimpleNamespace(id="ж5"), session=сессия)

    assert цель.is_banned is True
    # Цель узнаёт о бане (бот шлёт экран блокировки с кнопкой разблокировки),
    # мини-апп — своим каналом
    каналы = {канал for канал, _ in события}
    assert "dating:user:цель" in каналы
    (бан,) = [
        тело for канал, тело in события
        if канал == "dating:bot:events" and тело.get("type") == "banned"
    ]
    assert бан["user_id"] == "цель"
    assert бан["reason"] == "автобан по жалобам"
    # Первая ступень лестницы «reports» — 7 дней: срок обязан уйти в событии,
    # бот показывает его в сообщении о бане
    from datetime import datetime, timedelta, timezone

    срок = datetime.fromisoformat(бан["banned_until"])
    assert timedelta(days=6) < срок - datetime.now(timezone.utc) <= timedelta(days=7)
    assert цель.banned_until is not None
    # Все пятеро получают итог
    assert [т["user_id"] for т in _итоги(события)] == ["ж1", "ж2", "ж3", "ж4", "ж5"]
    assert {т["outcome"] for т in _итоги(события)} == {"banned"}


async def test_шестая_жалоба_не_банит_повторно(события):
    """Иначе каждая следующая жалоба присылала бы забаненному новый экран
    блокировки, а предыдущим жалобщикам — второе «аккаунт заблокирован»."""
    from routers import report

    цель = _цель(is_banned=True)
    сессия = _Сессия(
        _Результат(значение=цель),
        _Результат(значение=None),
        _Результат(список=[f"ж{i}" for i in range(1, 7)]),
    )

    await report.create_report(_жалоба(), user=SimpleNamespace(id="ж6"), session=сессия)

    assert события == []


async def test_автобан_по_жалобам_не_сносит_админа(события):
    """Пять сговорившихся аккаунтов не должны блокировать команду.

    Раньше report.py выставлял флаг руками, без проверки роли, — в отличие от
    ban_user_for_violation, где эта защита есть. Обещать жалобщикам бан,
    которого не случилось, тоже нельзя.
    """
    from routers import report

    цель = _цель(role="admin")
    сессия = _Сессия(
        _Результат(значение=цель),
        _Результат(значение=None),
        _Результат(список=[f"ж{i}" for i in range(1, 6)]),
    )

    await report.create_report(_жалоба(), user=SimpleNamespace(id="ж5"), session=сессия)

    assert цель.is_banned is False, "автоматика не должна банить админа по жалобам"
    assert _итоги(события) == [], "бана не было — сообщать о бане нечего"


# ── Решение модератора ────────────────────────────────────────────

def _админ():
    return SimpleNamespace(id="админ", role="admin")


async def test_отказ_модератора_доходит_до_жалобщика(события):
    from routers import admin
    from routers.admin import ReportAction

    жалоба = SimpleNamespace(
        id="r1", reporter_id="ж1", reported_id="цель", status="pending"
    )
    сессия = _Сессия(
        _Результат(значение=жалоба),
        _Результат(значение=_цель()),  # цель — в аудит: над кем вынесли вердикт
        _Результат(),                  # имена-снапшоты для записи аудита
    )

    await admin.report_action(
        ReportAction(report_id="r1", action="dismiss"),
        user=_админ(),
        session=сессия,
    )

    assert жалоба.status == "dismissed"
    assert _итоги(события) == [
        {"type": "report_outcome", "user_id": "ж1", "outcome": "dismissed"}
    ], "отказ тоже итог: без ответа жалобщик считает, что жалоба потерялась"


async def test_бан_модератором_доходит_до_жалобщика(события):
    from routers import admin
    from routers.admin import ReportAction

    жалоба = SimpleNamespace(
        id="r1", reporter_id="ж1", reported_id="цель", status="pending"
    )
    цель = _цель()
    сессия = _Сессия(
        _Результат(значение=жалоба),
        _Результат(значение=цель),
        _Результат(),  # имена-снапшоты для записи аудита
    )

    await admin.report_action(
        ReportAction(report_id="r1", action="ban_reported"),
        user=_админ(),
        session=сессия,
    )

    assert цель.is_banned is True
    assert жалоба.status == "resolved"
    assert _итоги(события) == [
        {"type": "report_outcome", "user_id": "ж1", "outcome": "banned"}
    ]


async def test_непрошедший_бан_не_обещает_бана(события):
    """Жалоба на владельца: ban_user_for_violation вернёт False, и жалобщику
    честнее «меры приняты», чем «аккаунт заблокирован»."""
    from routers import admin
    from routers.admin import ReportAction

    жалоба = SimpleNamespace(
        id="r1", reporter_id="ж1", reported_id="цель", status="pending"
    )
    сессия = _Сессия(
        _Результат(значение=жалоба),
        _Результат(значение=_цель(role="owner")),
        _Результат(),  # имена-снапшоты для записи аудита
    )

    await admin.report_action(
        ReportAction(report_id="r1", action="ban_reported"),
        user=_админ(),
        session=сессия,
    )

    assert [т["outcome"] for т in _итоги(события)] == ["resolved"]


# ── Контракт API ↔ бот ────────────────────────────────────────────

def test_каждый_код_итога_имеет_текст_в_боте():
    """Коды задаёт API, тексты живут в боте — рассинхрон даёт пустое сообщение.

    Проверяем по ast, а не импортом: bot/texts.py тянет config бота и в venv
    API не поднимается. Тест обязан работать и в CI.
    """
    from services.report_notify import ИТОГИ

    дерево = ast.parse((БОТ / "texts.py").read_text())
    словарь = None
    for узел in ast.walk(дерево):
        if (
            isinstance(узел, ast.Assign)
            and any(
                isinstance(ц, ast.Name) and ц.id == "REPORT_OUTCOMES"
                for ц in узел.targets
            )
            and isinstance(узел.value, ast.Dict)
        ):
            словарь = узел.value
    assert словарь is not None, "REPORT_OUTCOMES в bot/texts.py не найден"

    коды = {к.value for к in словарь.keys if isinstance(к, ast.Constant)}
    assert set(ИТОГИ) <= коды, (
        f"итоги без текста в боте: {sorted(set(ИТОГИ) - коды)} — человек получит "
        "общий ответ вместо конкретного"
    )
    assert all(len(з.value) > 40 for з in словарь.values if isinstance(з, ast.Constant)), (
        "итог из двух слов не объясняет, что произошло"
    )


def test_каждый_код_итога_имеет_текст_пуша():
    """Пропущенный код — KeyError на живой ручке жалобы.

    Тексты пуша живут рядом с кодами (в API), а не в боте: до владельца iPhone
    без Telegram сообщение бота не доходит вовсе, и переиспользовать его текст
    нельзя — там HTML и несколько абзацев.
    """
    from services.report_notify import ИТОГИ, ПУШИ

    assert set(ПУШИ) == set(ИТОГИ), (
        f"итоги без текста пуша: {sorted(set(ИТОГИ) - set(ПУШИ))}; "
        f"лишние коды: {sorted(set(ПУШИ) - set(ИТОГИ))}"
    )
    for код, (заголовок, строка) in ПУШИ.items():
        assert len(заголовок) <= 40, f"{код}: заголовок пуша обрежется на экране"
        assert 20 < len(строка) <= 180, f"{код}: строка пуша либо пустая, либо не влезет"
        assert "<" not in заголовок + строка, f"{код}: APNs не разбирает HTML"


def test_бот_разбирает_событие_итога():
    """Публикация без обработчика на стороне бота — тишина без единой ошибки."""
    подписчик = (БОТ / "services" / "redis_subscriber.py").read_text()

    assert '"report_outcome"' in подписчик, (
        "подписчик бота не разбирает событие report_outcome — итог не дойдёт"
    )
    assert "_notify_reporter_about_outcome" in подписчик
    assert "T.report_outcome(outcome)" in подписчик, (
        "текст итога обязан браться из texts.py, иначе незнакомый код уйдёт "
        "пустым сообщением и send_message упадёт"
    )
    # Канал тот же, что у бана: заводить второй подписчик не нужно
    assert 'pubsub.subscribe("dating:bot:matches", "dating:bot:events")' in подписчик


def test_итог_рассылается_из_обоих_путей_модерации():
    """Автоматика и админка — два входа в один и тот же исход жалобы."""
    from routers import admin, report

    for функция in (report.create_report, admin.report_action):
        assert "notify_report_outcome" in inspect.getsource(функция), (
            f"{функция.__name__} закрывает жалобу, не отвечая жалобщику"
        )
