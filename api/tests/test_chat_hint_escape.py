"""Подсказка первого сообщения в боте строится из чужого профиля.

Интересы, имя и био — пользовательский ввод, а `chat_hint` отправляет
сообщение с parse_mode=HTML: без экранирования собеседник протаскивал в
«официальную» подсказку бота свою разметку (жирный, ссылку на скам), а
кривой тег (`<b` без закрытия) ронял отправку целиком — Telegram отвечает
400 на невалидный HTML (аудит, блок «Доверие»).

Хендлер живёт в bot/handlers/matches.py и работает на venv бота — тест
запускает сценарий subprocess-ом, как test_unban_purchase.py: заглушка
sys.modules["database"] ставится до импорта хендлера, фейковая сессия
aiogram записывает исходящие SendMessage.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

БОТ = Path(__file__).resolve().parents[2] / "bot"


def _в_боте(скрипт: str) -> dict:
    python = БОТ / ".venv" / "bin" / "python"
    if not python.exists():
        pytest.skip("рядом нет venv бота — сценарий проверяется в его окружении")
    п = subprocess.run(
        [str(python), "-c", скрипт],
        cwd=БОТ, capture_output=True, text=True, timeout=120,
    )
    assert п.returncode == 0, f"скрипт бота упал:\n{п.stdout}\n{п.stderr}"
    return json.loads(п.stdout.strip().splitlines()[-1])


_СЦЕНАРИЙ = """
import asyncio, json, sys, types
from datetime import datetime, timezone

вызовы = []

# database подменяется ДО импорта хендлера: get_match_partner/get_profile
# отдают профиль с HTML в интересах, имени и био — как если бы человек
# вписал разметку в анкету (мини-апп и бот пропускают её как обычный текст)
db = types.ModuleType("database")

ПАРТНЁР = {}

async def get_or_create_user(tid, username="", name=""):
    return {"id": "u1", "is_banned": False}

async def get_profile(uid):
    return {"id": "p-me", "interests": МОИ_ИНТЕРЕСЫ}

async def get_match_partner(match_id, user_id, spend=False):
    return dict(ПАРТНЁР)

async def get_user_matches(uid):
    return []

for имя in ("get_or_create_user", "get_profile", "get_match_partner",
            "get_user_matches"):
    setattr(db, имя, locals()[имя])
sys.modules["database"] = db

from aiogram import Bot
from aiogram.client.session.base import BaseSession
from aiogram.types import CallbackQuery, Chat, Message, User


class Сессия(BaseSession):
    async def close(self):
        pass

    async def stream_content(self, *a, **kw):
        yield b""

    async def make_request(self, bot, method, timeout=None):
        имя = type(method).__name__
        if имя == "SendMessage":
            вызовы.append(("send", method.text))
            return Message.model_construct(
                message_id=2, date=datetime.now(timezone.utc), chat=_чат
            )
        вызовы.append((имя, None))
        return True


бот = Bot(token="42:TEST", session=Сессия())
_чат = Chat.model_construct(id=42, type="private")
_кто = User.model_construct(id=42, is_bot=False, first_name="Т")


def колбэк(данные):
    сообщение = Message.model_construct(
        message_id=1, date=datetime.now(timezone.utc), chat=_чат, from_user=_кто,
    ).as_(бот)
    return CallbackQuery.model_construct(
        id="1", from_user=_кто, chat_instance="c", data=данные,
        message=сообщение,
    ).as_(бот)


from handlers.matches import chat_hint


async def main():
    # 1. Общий интерес и имя партнёра несут теги
    ПАРТНЁР.clear()
    ПАРТНЁР.update({
        "user_id": "u2",
        "display_name": 'Зл<a href="https://scam.example">ая</a>',
        "interests": ["<i>кино</i>", "дайвинг"],
        "bio": "",
    })
    await chat_hint(колбэк("chat:hint:m1"))

    # 2. Общих интересов нет — ветка цитаты био
    ПАРТНЁР.update({
        "display_name": "Аня",
        "interests": ["шахматы"],
        "bio": "Люблю <script>alert(1)</script> и рыбалку",
    })
    await chat_hint(колбэк("chat:hint:m1"))

    print(json.dumps({"вызовы": вызовы}, ensure_ascii=False))


asyncio.run(main())
"""


def test_подсказка_экранирует_интересы_имя_и_био():
    итог = _в_боте(_СЦЕНАРИЙ.replace("МОИ_ИНТЕРЕСЫ", '["<i>кино</i>", "плавание"]'))
    подсказки = [текст for вид, текст in итог["вызовы"] if вид == "send"]
    assert len(подсказки) == 2, "оба сценария должны дойти до отправки подсказки"

    по_интересу, по_био = подсказки

    # Чужой тег ушёл текстом, а не разметкой; собственный <b> подсказки жив
    assert "&lt;i&gt;кино&lt;/i&gt;" in по_интересу
    assert "<i>кино</i>" not in по_интересу
    assert "<b>&lt;i&gt;кино&lt;/i&gt;</b>" in по_интересу
    # Ссылка из имени не стала кликабельной
    assert "&lt;a href=" in по_интересу
    assert '<a href="https://scam.example">' not in по_интересу

    # Цитата био: script-тег обезврежен, остальной текст цел
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in по_био
    assert "<script>" not in по_био
    assert "и рыбалку" in по_био
