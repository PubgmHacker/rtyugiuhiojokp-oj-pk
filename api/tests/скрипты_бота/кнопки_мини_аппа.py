"""Кнопки в мини-апп на настоящих клавиатурах бота, при разном SITE_URL.

Telegram отклоняет `web_app` не по HTTPS — и отклоняет СООБЩЕНИЕ ЦЕЛИКОМ
(`Bad Request: BUTTON_TYPE_INVALID`), а не одну кнопку. Одна такая кнопка в
главном меню означала, что меню не приходит вовсе: ни текста, ни остальных
кнопок. Происходило это ровно на HTTP-конфигурации, то есть на той самой, где
`start_app_kb` осознанно уводит человека в анкету бота, рассчитывая, что меню
придёт следом.

Проверяется поведение, а не форма кода: `webapp_https()` можно вызвать не там,
проверить не то или потерять при следующей правке — исходник останется
«правильным». Здесь настоящий `keyboards.py` с перечитанным `config.py`, и
утверждается тип кнопки, которая уедет в Bot API.

Последний случай — настоящий `handlers.dating._show_next_profile` с пустой
декой: текст и клавиатура собираются в разных модулях, и рассинхрон между
«откройте приложение» в тексте и отсутствующей кнопкой рядом виден только
здесь.

Запускается интерпретатором бота из `tests/test_query_scale.py`.
Ответ — JSON на последней строке stdout.
"""

import asyncio
import importlib
import json
import os
import sys

sys.path.insert(0, ".")

import config as конфиг  # noqa: E402
import keyboards  # noqa: E402

КЛЮЧИ = ("SITE_URL", "LANDING_URL")

СЛУЧАИ: dict[str, str] = {
    # Дефолт из .env.example и то, с чем бот уезжает, если про SITE_URL забыли
    "петля": "http://localhost:5173",
    "петля_по_ip": "http://127.0.0.1:5173",
    # Стенд на голом IP: web_app невозможен, но ссылка в браузере работает
    "http_домен": "http://staging.simp.app",
    "http_ip": "http://203.0.113.10:5173",
    # Прод
    "https_домен": "https://simp.app",
    "туннель": "https://ab12cd.ngrok-free.app",
}


def перечитать(site_url: str):
    """Конфигурация с заданным SITE_URL — константы читаются при импорте.

    `_load_dotenv` не перетирает заданные ключи, поэтому корневой .env
    разработчика не подмешается: иначе результат зависел бы от чужой машины.
    """
    for ключ in КЛЮЧИ:
        os.environ[ключ] = site_url if ключ == "SITE_URL" else ""
    return importlib.reload(конфиг)


def разобрать(разметка) -> list[dict]:
    """Тип каждой кнопки клавиатуры — то, чем она станет в Bot API."""
    кнопки = []
    for строка in разметка.inline_keyboard:
        for кнопка in строка:
            if кнопка.web_app:
                вид, адрес = "web_app", кнопка.web_app.url
            elif кнопка.url:
                вид, адрес = "url", кнопка.url
            else:
                вид, адрес = "callback", кнопка.callback_data
            кнопки.append({"текст": кнопка.text, "вид": вид, "адрес": адрес})
    return кнопки


КЛАВИАТУРЫ = {
    "start_app_kb": lambda: keyboards.start_app_kb("ru"),
    "main_kb": keyboards.main_kb,
    "no_more_profiles_kb": keyboards.no_more_profiles_kb,
    "profile_kb": keyboards.profile_kb,
    # Клавиатуры без мини-аппа: если в них внезапно появится web_app по HTTP,
    # сообщение об исчерпанном лимите тоже перестанет доходить
    "limit_reached_kb": lambda: keyboards.limit_reached_kb("menu"),
    "like_locked_kb": keyboards.like_locked_kb,
    "matches_list_kb": lambda: keyboards.matches_list_kb([]),
}


async def дека_кончилась() -> dict:
    """Текст и клавиатура «анкеты закончились» — из настоящего хендлера."""
    import handlers.dating as dating

    async def пустая_дека(user_id, limit=5):
        return []

    dating.get_deck_profiles = пустая_дека

    class ФейковоеСообщение:
        def __init__(self):
            self.отправлено = []

        async def answer_photo(self, photo, caption, reply_markup):
            self.отправлено.append((caption, reply_markup))

    class ФейковоеСостояние:
        async def update_data(self, **kw):
            pass

        async def set_state(self, s):
            pass

        async def clear(self):
            pass

    сообщение = ФейковоеСообщение()
    await dating._show_next_profile(сообщение, 1, "uid", ФейковоеСостояние())
    подпись, разметка = сообщение.отправлено[0]
    return {"текст": подпись, "кнопки": разобрать(разметка)}


def main() -> None:
    ответ: dict = {"клавиатуры": {}, "дека": {}}

    for имя_случая, site_url in СЛУЧАИ.items():
        перечитать(site_url)
        ответ["клавиатуры"][имя_случая] = {
            имя: разобрать(собрать()) for имя, собрать in КЛАВИАТУРЫ.items()
        }

    for имя_случая in ("петля", "http_домен", "https_домен"):
        перечитать(СЛУЧАИ[имя_случая])
        ответ["дека"][имя_случая] = asyncio.run(дека_кончилась())

    print(json.dumps(ответ, ensure_ascii=False, default=str))


main()
