"""Платежи бота: тариф привязан к счёту, зачёт и начисление атомарны.

Две дыры, которые здесь прибиваем.

Первая — эскалация тарифа в CryptoBot-оплате. Кнопка «Проверить оплату»
несёт код тарифа в callback_data (`paycheck:{invoice_id}:{code}`), а
callback_data подделывается клиентом свободно. Проверка счёта сверяла только
владельца и статус «оплачен» — не ЧТО куплено. Оплатил plus_1m за 149 ₽,
нажал кнопку с кодом aurora_12m — получил верхний тариф за год по цене
месяца нижнего. Теперь код тарифа зашит в payload счёта при создании и
сверяется при проверке; для счетов, созданных до этого деплоя (живут ≤1 часа),
тариф подтверждается суммой — цены тарифов попарно различны.

Вторая — потеря оплаты при падении процесса. `activate_premium` бота
коммитил маркер платежа в ОТДЕЛЬНОЙ транзакции до начисления: падение в
зазоре оставляло платёж «зачтённым» навсегда без подписки, и каждая повторная
проверка отвечала «уже зачтено». Деньги списаны — подписки нет. Теперь маркер
и начисление в одной транзакции (маркер — в savepoint ради гонки двух
одновременных проверок), как в api/services/premium.py.

Третий блок — рублёвая оплата (карта и СБП через платёжного провайдера).
Здесь два способа ошибиться молча. Telegram принимает рубли в копейках, а
Stars — штуками: пропущенная сотня не падает и не логируется, просто Ultra на
год уходит за 7 рублей. И журнал платежей идемпотентен по паре
(provider, external_id) — записав рублёвый платёж как "stars", мы кладём его в
одно пространство имён с Stars, а возврат Stars снял бы подписку, оплаченную
картой.

Поведение проверяется интерпретатором бота через subprocess — тем же приёмом,
что test_bot_infra.py: бот живёт в отдельном venv, и код API импортировать
его не может. Там, где venv бота не поднят (CI), поведенческие тесты
пропускаются, а инварианты держат структурные проверки по ast и исходнику —
они выполняются всегда.
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


# ── Поведение check_invoice_paid: подмена кода тарифа не проходит ──

ПРОВЕРКА_СЧЁТА = """
import asyncio, json, sys
sys.path.insert(0, ".")
from services import cryptobot

# Счета «в CryptoBot»: новый формат payload (с кодом тарифа), переходный
# (без кода) и неоплаченный. Суммы — реальные цены линейки при курсе 100 ₽/USDT.
СЧЕТА = {
    "1": {"status": "paid", "payload": "premium:u1:plus_1m", "asset": "USDT", "amount": "1.49"},
    "2": {"status": "paid", "payload": "premium:u1", "asset": "USDT", "amount": "1.49"},
    "3": {"status": "active", "payload": "premium:u1:plus_1m", "asset": "USDT", "amount": "1.49"},
    "4": {"status": "paid", "payload": "premium:u1", "asset": "TON", "amount": "1.49"},
}

async def фейковый_call(method, payload=None):
    assert method == "getInvoices", method
    счёт = СЧЕТА.get(str(payload["invoice_ids"]))
    return {"items": [счёт] if счёт else []}

cryptobot._call = фейковый_call

async def главное():
    из = {}
    # Честный путь: оплачен plus_1m, предъявлен plus_1m
    из["свой_тариф"] = await cryptobot.check_invoice_paid(
        1, "u1", plan_code="plus_1m", expected_amount="1.49")
    # Атака: оплачен plus_1m (149 р), предъявлен aurora_12m (4990 р)
    из["подмена_тарифа"] = await cryptobot.check_invoice_paid(
        1, "u1", plan_code="aurora_12m", expected_amount="49.90")
    # Атака: чужой оплаченный счёт
    из["чужой_счёт"] = await cryptobot.check_invoice_paid(
        1, "u2", plan_code="plus_1m", expected_amount="1.49")
    # Переходный счёт без кода: сумма совпала — зачёт
    из["старый_формат_сумма_ок"] = await cryptobot.check_invoice_paid(
        2, "u1", plan_code="plus_1m", expected_amount="1.49")
    # Переходный счёт: сумма дешёвого не сходится с ценой дорогого — отказ
    из["старый_формат_подмена"] = await cryptobot.check_invoice_paid(
        2, "u1", plan_code="aurora_12m", expected_amount="49.90")
    # Неоплаченный и чужая валюта
    из["неоплаченный"] = await cryptobot.check_invoice_paid(
        3, "u1", plan_code="plus_1m", expected_amount="1.49")
    из["чужая_валюта"] = await cryptobot.check_invoice_paid(
        4, "u1", plan_code="plus_1m", expected_amount="1.49")
    print(json.dumps(из))

asyncio.run(главное())
"""


def test_подмена_кода_тарифа_не_активирует_дорогой():
    из = _в_боте(ПРОВЕРКА_СЧЁТА)
    assert из["свой_тариф"] is True
    assert из["подмена_тарифа"] is False, "оплатив дешёвый тариф, нельзя предъявить код дорогого"
    assert из["чужой_счёт"] is False
    assert из["старый_формат_сумма_ок"] is True, "счета, созданные до деплоя, должны зачитываться"
    assert из["старый_формат_подмена"] is False
    assert из["неоплаченный"] is False
    assert из["чужая_валюта"] is False


# ── Структурные инварианты: выполняются и в CI, где venv бота нет ──

def _функция(дерево: ast.Module, имя: str) -> ast.AsyncFunctionDef:
    for узел in ast.walk(дерево):
        if isinstance(узел, ast.AsyncFunctionDef) and узел.name == имя:
            return узел
    raise AssertionError(f"функция {имя} не найдена")


def _вызовы_в(узел: ast.AST, метод: str) -> list[ast.AsyncWith]:
    """AsyncWith-блоки вида `async with session.<метод>()`."""
    найдено = []
    for н in ast.walk(узел):
        if not isinstance(н, ast.AsyncWith):
            continue
        for item in н.items:
            выр = item.context_expr
            if (
                isinstance(выр, ast.Call)
                and isinstance(выр.func, ast.Attribute)
                and выр.func.attr == метод
            ):
                найдено.append(н)
    return найдено


def test_маркер_платежа_и_начисление_в_одной_транзакции():
    """activate_premium бота: ровно один session.begin(), маркер — в savepoint.

    Две транзакции здесь — это не стиль, а окно потери денег: падение
    процесса между «платёж зачтён» и «подписка продлена» оставляет человека
    без купленного навсегда. Тест держит структуру, потому что поведенческая
    проверка требует настоящего Postgres.
    """
    дерево = ast.parse((БОТ / "database" / "connection.py").read_text())
    fn = _функция(дерево, "activate_premium")

    транзакции = _вызовы_в(fn, "begin")
    assert len(транзакции) == 1, (
        "маркер платежа и начисление обязаны жить в ОДНОЙ транзакции: "
        f"нашёл {len(транзакции)} вызовов session.begin()"
    )

    савпоинты = _вызовы_в(fn, "begin_nested")
    assert len(савпоинты) == 1, "гонку двух проверок держит ровно один savepoint"

    # savepoint — внутри транзакции, а маркер платежа — внутри savepoint
    assert савпоинты[0] in list(ast.walk(транзакции[0])), (
        "savepoint должен открываться внутри общей транзакции"
    )
    внутри_савпоинта = [
        н for н in ast.walk(савпоинты[0])
        if isinstance(н, ast.Call)
        and isinstance(н.func, ast.Name)
        and н.func.id == "ProcessedPayment"
    ]
    assert внутри_савпоинта, "маркер ProcessedPayment обязан вставляться внутри savepoint"


def test_код_тарифа_зашит_в_счёт_и_сверяется():
    """Тариф CryptoBot-счёта живёт в payload, а не только в callback_data.

    Проверка по исходнику: поведенческий тест выше пропускается без venv
    бота, а этот инвариант должен держаться и в CI. Уйдёт привязка кода из
    payload — уйдёт и защита от эскалации тарифа.
    """
    сервис = (БОТ / "services" / "cryptobot.py").read_text()
    assert 'f"premium:{user_id}:{plan_code}"' in сервис, (
        "create_premium_invoice обязан зашивать код тарифа в payload счёта"
    )
    assert 'payload == f"premium:{expected_user_id}:{plan_code}"' in сервис, (
        "check_invoice_paid обязан сверять код тарифа из payload"
    )

    хендлер = (БОТ / "handlers" / "premium.py").read_text()
    assert "plan_code=code" in хендлер, (
        "хендлеры обязаны передавать код тарифа и при создании счёта, "
        "и при проверке оплаты"
    )
    assert "expected_amount=usdt_for(plan)" in хендлер, (
        "проверка оплаты обязана получать ожидаемую сумму — ею подтверждаются "
        "счета переходного формата без кода в payload"
    )


def test_цены_тарифов_попарно_различны():
    """Суммы USDT однозначно определяют тариф — на этом стоит зачёт счетов
    переходного формата. Совпади две цены — подтверждение суммой перестало бы
    различать тарифы, и тест обязан упасть раньше, чем это уедет в прод."""
    import re

    исходник = (БОТ / "services" / "plans.py").read_text()
    цены = [
        int(м.group(2))
        for м in re.finditer(r'Plan\("([a-z0-9_]+)",[^)]*?,\s*(\d+)\)', исходник)
    ]
    assert len(цены) >= 9, "линейка тарифов не распарсилась — проверь регулярку"
    assert len(цены) == len(set(цены)), "цены тарифов обязаны быть попарно различны"


# ── Рубли: карта и СБП через платёжного провайдера ─────────────────

РУБЛЁВЫЙ_СЧЁТ = """
import asyncio, json, os, sys
sys.path.insert(0, ".")
os.environ["PAYMENT_PROVIDER_TOKEN"] = "1744374395:TEST:fake"
import handlers.premium as p
from services.plans import PLANS_BY_CODE
from aiogram.exceptions import TelegramAPIError


class Сообщение:
    def __init__(с, падать=False):
        с.счёт, с.текст, с.падать = None, None, падать

    async def answer_invoice(с, **kw):
        if с.падать:
            raise TelegramAPIError(method=None, message="PAYMENT_PROVIDER_INVALID")
        с.счёт = kw

    async def answer(с, text, **kw):
        с.текст = text


class Кнопка:
    def __init__(с, data, падать=False):
        с.data, с.message, с.алерт = data, Сообщение(падать), None

    async def answer(с, text=None, show_alert=False):
        с.алерт = text


async def главное():
    из = {"счета": {}}

    # Каждый тариф линейки: сумма счёта обязана быть рублёвой ценой в копейках
    for код, plan in PLANS_BY_CODE.items():
        к = Кнопка(f"pay:sbp:{код}")
        await p.pay_sbp(к)
        счёт = к.message.счёт
        из["счета"][код] = {
            "currency": счёт["currency"],
            "amount": счёт["prices"][0].amount,
            "рубли": plan.price_rub,
            "payload": счёт["payload"],
            "токен": bool(счёт["provider_token"]),
        }

    # Кнопки в интерфейсе нет, но callback_data подделывается свободно
    к = Кнопка("pay:sbp:нет_такого_тарифа")
    await p.pay_sbp(к)
    из["чужой_тариф"] = {"алерт": к.алерт, "счёт": к.message.счёт}

    # Провайдер отвязан или токен просрочен: человеку нужен второй способ,
    # а не текст ошибки Telegram
    к = Кнопка("pay:sbp:plus_1m", падать=True)
    await p.pay_sbp(к)
    из["отказ_провайдера"] = {"текст": к.message.текст, "счёт": к.message.счёт}

    из["кнопка_есть"] = [
        b.callback_data for row in p.payment_methods_kb("plus_1m").inline_keyboard
        for b in row
    ]
    print(json.dumps(из, ensure_ascii=False))

asyncio.run(главное())
"""

БЕЗ_ТОКЕНА = """
import asyncio, json, os, sys
sys.path.insert(0, ".")
os.environ["PAYMENT_PROVIDER_TOKEN"] = ""
import handlers.premium as p


class Сообщение:
    def __init__(с):
        с.счёт, с.текст = None, None

    async def answer_invoice(с, **kw):
        с.счёт = kw

    async def answer(с, text, **kw):
        с.текст = text


class Кнопка:
    def __init__(с, data):
        с.data, с.message, с.алерт = data, Сообщение(), None

    async def answer(с, text=None, show_alert=False):
        с.алерт = text


async def главное():
    к = Кнопка("pay:sbp:plus_1m")
    await p.pay_sbp(к)
    print(json.dumps({
        "включён": p.SBP_ENABLED,
        "кнопки": [
            b.callback_data
            for row in p.payment_methods_kb("plus_1m").inline_keyboard
            for b in row
        ],
        "алерт": к.алерт,
        "счёт": к.message.счёт,
    }, ensure_ascii=False))

asyncio.run(главное())
"""


def test_рублёвый_счёт_уходит_в_копейках():
    """Telegram принимает рубли в копейках, Stars — штуками.

    Пропущенная сотня здесь не падает и не логируется: счёт создаётся, оплата
    проходит, подписка выдаётся — просто Ultra на год уходит за 7 рублей.
    Проверяем каждый тариф линейки, а не один: множитель легко потерять в
    новой строке прайса.
    """
    из = _в_боте(РУБЛЁВЫЙ_СЧЁТ)

    assert из["счета"], "линейка тарифов пуста — счёт не с чего строить"
    for код, счёт in из["счета"].items():
        assert счёт["currency"] == "RUB", код
        assert счёт["amount"] == счёт["рубли"] * 100, (
            f"{код}: в счёте {счёт['amount']} копеек при цене {счёт['рубли']} ₽ — "
            "рубли уходят в Telegram в копейках"
        )
        # Тот же payload, что у Stars: зачёт оплаты разбирает его в одном месте
        assert счёт["payload"] == f"plan:{код}", код
        assert счёт["токен"], f"{код}: счёт без токена провайдера Telegram отвергнет"

    assert из["чужой_тариф"]["счёт"] is None, (
        "подделанный код тарифа не должен превращаться в счёт"
    )
    assert из["чужой_тариф"]["алерт"], "на неизвестный тариф нужен ответ, иначе «часики»"

    assert из["отказ_провайдера"]["счёт"] is None
    assert "Stars" in (из["отказ_провайдера"]["текст"] or ""), (
        "отказ провайдера обязан предлагать другой способ оплаты, "
        "а не оставлять человека на экране с ошибкой"
    )
    assert "pay:sbp:plus_1m" in из["кнопка_есть"], (
        "с токеном способ обязан появляться в списке оплаты"
    )


def test_способ_скрыт_без_токена_провайдера():
    """Без токена нет ни кнопки, ни счёта — как у CryptoBot.

    Раньше здесь стоял отдельный выключатель SBP_ENABLED, и поднятый флаг
    рисовал кнопку, которая отвечала «скоро появится». Человек, дошедший до
    выбора способа оплаты, уходил с мыслью, что оплата сломана: это хуже, чем
    отсутствие кнопки. Гейт теперь один — наличие токена.
    """
    из = _в_боте(БЕЗ_ТОКЕНА)

    assert из["включён"] is False
    assert not [c for c in из["кнопки"] if c and c.startswith("pay:sbp")], (
        "без токена кнопки рублёвой оплаты быть не должно"
    )
    # callback_data подделывается: хендлер обязан отказать сам, иначе Telegram
    # вернёт «PAYMENT_PROVIDER_INVALID» и человек увидит «часики»
    assert из["счёт"] is None
    assert из["алерт"], "на подделанный колбэк нужен внятный ответ"


def test_провайдер_платежа_определяется_валютой():
    """Рублёвый платёж нельзя записывать в журнал как "stars".

    Ключ идемпотентности — пара (provider, external_id): в одном пространстве
    имён charge_id Stars и провайдера могут совпасть, и второй платёж
    отклонится как «уже зачтённый». Хуже другое: возврат Stars ищет платёж по
    provider="stars" и снял бы подписку, оплаченную картой.

    Проверка структурная — поведенческая требовала бы Postgres: `provider`
    обязан вычисляться, а не быть строкой в коде.
    """
    дерево = ast.parse((БОТ / "handlers" / "premium.py").read_text())
    fn = _функция(дерево, "on_successful_payment")

    начисления = [
        н for н in ast.walk(fn)
        if isinstance(н, ast.Call)
        and isinstance(н.func, ast.Name)
        and н.func.id == "_grant_premium"
    ]
    assert начисления, "_grant_premium в обработчике оплаты не найден"
    for вызов in начисления:
        провайдер = next(
            (kw.value for kw in вызов.keywords if kw.arg == "provider"), None
        )
        assert провайдер is not None, "provider обязан передаваться явно"
        assert not isinstance(провайдер, ast.Constant), (
            "provider зашит строкой: рублёвая оплата запишется как Stars"
        )

    # Различаем именно по валюте: XTR — Stars, остальное — платёжный провайдер
    исходник = ast.dump(fn)
    assert "'XTR'" in исходник or '"XTR"' in исходник, (
        "валюта Stars (XTR) обязана участвовать в выборе провайдера"
    )
    assert any(
        isinstance(н, ast.Attribute) and н.attr == "currency" for н in ast.walk(fn)
    ), "выбор провайдера обязан читать валюту платежа"


def test_рублёвый_счёт_не_путается_со_stars():
    """Два счёта в одном файле: рублёвый обязан нести провайдера и копейки,
    Stars — валюту XTR и штуки.

    Инвариант структурный, потому что оба вызова уходят в Telegram, а не в наш
    код: перепутанные аргументы проявятся только на живом платеже.
    """
    дерево = ast.parse((БОТ / "handlers" / "premium.py").read_text())

    рублёвый = _функция(дерево, "pay_sbp")
    аргументы = {
        kw.arg: kw.value
        for н in ast.walk(рублёвый)
        if isinstance(н, ast.Call)
        for kw in н.keywords
    }
    assert isinstance(аргументы.get("currency"), ast.Constant)
    assert аргументы["currency"].value == "RUB", "рублёвый счёт обязан быть в RUB"
    assert "provider_token" in аргументы, (
        "без provider_token Telegram не примет счёт в реальной валюте"
    )
    множители = [
        н.right.value for н in ast.walk(рублёвый)
        if isinstance(н, ast.BinOp)
        and isinstance(н.op, ast.Mult)
        and isinstance(н.right, ast.Constant)
    ]
    assert 100 in множители, "цена в рублях обязана уходить в копейках (× 100)"

    звёзды = _функция(дерево, "pay_stars")
    валюта = next(
        kw.value
        for н in ast.walk(звёзды)
        if isinstance(н, ast.Call)
        for kw in н.keywords
        if kw.arg == "currency"
    )
    assert валюта.value == "XTR", "счёт Stars обязан остаться в XTR"
    assert not any(
        kw.arg == "provider_token"
        for н in ast.walk(звёзды)
        if isinstance(н, ast.Call)
        for kw in н.keywords
    ), "Stars оплачиваются без платёжного провайдера — токен здесь лишний"

