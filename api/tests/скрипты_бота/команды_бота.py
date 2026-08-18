"""Команды бота: заявленные в Telegram, зарегистрированные и описанные в /help.

Меню «/» в поле ввода собирается ровно из `set_my_commands`. Незаявленная
команда существует только для тех, кому её назвали словами: `/menu` не было в
списке, и единственный способ открыть главное меню оставался недоступным —
притом что `/help` обещал меню по `/start`, который открывал выбор языка.
Заявленная без обработчика команда так же плоха: человек её видит, нажимает и
не получает ничего.

Три места обязаны совпадать: список в `bot.КОМАНДЫ`, настоящие обработчики в
`Dispatcher` и текст `/help`. Здесь они сверяются по факту: команды вычитываются
из фильтров собранного продакшеновым `собрать_dispatcher()` диспетчера, а не из
исходника — фильтр можно навесить не на тот роутер, и текст файла останется
похожим на правильный.

Ниже — ещё и поведение `/start` у вернувшегося человека: язык спрашивается один
раз, повторный `/start` с готовой анкетой обязан отдавать меню, а не гнать через
онбординг заново. Прогон настоящий: `Dispatcher.feed_update` с подменённой
базой и сессией бота без сети.

Запускается интерпретатором бота из `tests/test_query_scale.py`.
Ответ — JSON на последней строке stdout.
"""

import asyncio
import json
import sys
from datetime import datetime, timezone

sys.path.insert(0, ".")

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.base import BaseSession
from aiogram.filters import Command
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Chat, Message, Update, User

import bot as модуль_бота
import middlewares.registration as мидлварь_регистрации
import texts as T

ТОКЕН = "123456:TESTTOKENTESTTOKENTESTTOKENTESTTOKEN"
Я = 777

#: Анкета «человек уже здесь был»: имя и фото — то же условие готовности, что в
#: `account.cmd_menu`, иначе /start и /menu разошлись бы в понимании готовности.
ГОТОВАЯ_АНКЕТА = {"display_name": "Боря", "photos": ["ФОТО-1"], "age": 27}

#: Диспетчер собирается ровно один раз: роутеры — модульные синглтоны, и aiogram
#: запрещает подключать один роутер к двум диспетчерам («Router is already
#: attached»). В проде сборка тоже одна, так что ограничение не мешает.
DP = None


class ФейковаяСессия(BaseSession):
    """Сессия бота без Telegram: запоминает вызовы, отвечает минимумом."""

    def __init__(self) -> None:
        super().__init__()
        self.вызовы: list[dict] = []

    async def close(self) -> None:
        return None

    async def make_request(self, bot, method, timeout=None):
        имя = type(method).__name__
        текст = getattr(method, "text", None) or getattr(method, "caption", None) or ""
        разметка = getattr(method, "reply_markup", None)
        кнопки: list[str] = []
        строки = getattr(разметка, "inline_keyboard", None) or []
        for строка in строки:
            кнопки.extend(к.text for к in строка)
        self.вызовы.append({"метод": имя, "текст": текст, "кнопки": кнопки})
        if имя == "SendMessage":
            return Message(
                message_id=len(self.вызовы),
                date=datetime.now(timezone.utc),
                chat=Chat(id=Я, type="private"),
                text=текст,
            )
        return True

    async def stream_content(self, *args, **kwargs):
        yield b""


def команды_роутера(роутер) -> dict[str, list[str]]:
    """Команды, на которые роутер и его дети реально отвечают."""
    найдено: dict[str, list[str]] = {}
    for обработчик in роутер.message.handlers:
        for фильтр in обработчик.filters or ():
            проверка = getattr(фильтр, "callback", фильтр)
            if not isinstance(проверка, Command):
                continue
            for команда in проверка.commands:
                if isinstance(команда, str):
                    найдено.setdefault(команда, []).append(обработчик.callback.__name__)
    for ребёнок in роутер.sub_routers:
        for команда, кто in команды_роутера(ребёнок).items():
            найдено.setdefault(команда, []).extend(кто)
    return найдено


def подменить_бд(профиль):
    """Оба входа в базу — на время прогона: живой Postgres тут не нужен.

    Мидлварь регистрации подменяется тоже: она вызывает базу на каждом апдейте и
    на машине с поднятым compose завела бы настоящего пользователя 777.
    """

    async def _юзер(*_a, **_kw):
        return {"id": "U-1", "telegram_id": Я}

    async def _профиль(*_a, **_kw):
        return профиль

    модуль_бота.get_or_create_user = _юзер
    модуль_бота.get_profile = _профиль
    мидлварь_регистрации.get_or_create_user = _юзер


def диспетчер():
    """Продакшеновая сборка, один экземпляр на прогон."""
    global DP
    if DP is None:
        DP = модуль_бота.собрать_dispatcher(MemoryStorage())
    return DP


async def прогнать_старт(профиль, кто: int = Я) -> list[dict]:
    """Один `/start` через настоящий Dispatcher. Возвращает отправленное.

    `кто` — разный telegram_id на каждый прогон: антифлуд (`ThrottleMiddleware`)
    держит счётчики в памяти процесса и второй `/start` того же человека в тот
    же миг молча гасит. С одним id второй прогон возвращал пустоту, и это
    выглядело бы как «бот не ответил без анкеты».

    Отдаём все вызовы Bot API, а не только SendMessage: ответ одной картинкой
    (`answer_photo`) — тоже ответ, и тест обязан его увидеть, иначе «ничего не
    пришло» и «пришла карточка» для него одно и то же.
    """
    подменить_бд(профиль)
    сессия = ФейковаяСессия()
    бот = Bot(
        token=ТОКЕН,
        session=сессия,
        default=DefaultBotProperties(parse_mode="HTML"),
    )
    dp = диспетчер()
    обновление = Update(
        update_id=кто,
        message=Message(
            message_id=1,
            date=datetime.now(timezone.utc),
            chat=Chat(id=кто, type="private"),
            from_user=User(id=кто, is_bot=False, first_name="Боря"),
            text="/start",
        ),
    )
    await dp.feed_update(бот, обновление)
    await бот.session.close()
    return сессия.вызовы


def main() -> None:
    ответ = {
        "заявленные": [
            {"команда": к.command, "описание": к.description} for к in модуль_бота.КОМАНДЫ
        ],
        "обработчики": команды_роутера(диспетчер()),
        "help": T.HELP,
        "старт_с_анкетой": asyncio.run(прогнать_старт(ГОТОВАЯ_АНКЕТА, Я)),
        "старт_без_анкеты": asyncio.run(прогнать_старт(None, Я + 1)),
        "сетка_языков": T.onboarding_choose_language(),
    }
    print(json.dumps(ответ, ensure_ascii=False, default=str))


main()
