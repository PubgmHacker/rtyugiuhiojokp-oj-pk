"""Очередь отложенных пушей онбординга — на настоящей БД в памяти.

Рассылки Mimolet (субкультура, почта) убраны из онбординга: согласие и конец
анкеты только СТАВЯТ строку в `dating_onboarding_nudges`, а отправляет её цикл
из `services/nudges.py` — позже, когда сообщение работает как возврат в бота,
а не как спам поверх живого диалога. Здесь проверяется сама очередь:

  • постановка: согласие ставит два пуша с настроенными отсрочками, повторный
    вызов не плодит дублей, а двигает срок вперёд (upsert);
  • срок: до due_at не уходит ничего, после — уходит и строка удаляется;
  • переоценка перед отправкой: почта привязана / анкета готова / бан /
    аккаунт исчез — пуш гаснет или меняет текст, решает база на момент
    отправки, а не на момент постановки;
  • отказоустойчивость: блокировка бота чистит строку, сетевой сбой оставляет
    её на повтор, лимит Telegram прерывает тик целиком;
  • язык: текст приходит на языке аккаунта, а не на языке строки.

Проверяется поведение, а не форма кода: сервис гоняется на настоящем
SQLAlchemy поверх aiosqlite (подмена `database.connection._session_cls`, как в
`суточные_лимиты.py`), от бота остаётся ровно то, что очередь зовёт —
`send_message`.

Запускается интерпретатором бота из `tests/test_query_scale.py`.
Ответ — JSON на последней строке stdout.
"""

import asyncio
import json
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, ".")

from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter
from aiogram.methods import SendMessage
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import database.connection as c
import services.nudges as nudges
import texts as T
from config import NUDGE_EMAIL_DELAY_HOURS, NUDGE_MAX_AGE_DAYS, NUDGE_STYLE_DELAY_MIN
from database.models import AnalyticsEvent, OnboardingNudge, Profile, User

#: Личка: id чата и id человека совпадают, как в настоящем диалоге с ботом.
Я = 111

#: Метод в конструкторах исключений aiogram обязателен, но очередь его не
#: читает — хватает любого корректного.
_МЕТОД = SendMessage(chat_id=Я, text="x")


class ФейковыйБот:
    """Всё, что очередь зовёт у бота — `send_message`.

    `ошибки` — очередь исключений: каждый вызов снимает первое и поднимает
    его. Так один объект отыгрывает и заблокировавшего бота человека, и
    мигнувшую сеть, и лимит Telegram.
    """

    def __init__(self, ошибки=None):
        self.отправлено: list[dict] = []
        self.ошибки = list(ошибки or [])

    async def send_message(self, chat_id, text, reply_markup=None):
        if self.ошибки:
            raise self.ошибки.pop(0)
        кнопки = []
        if reply_markup is not None:
            кнопки = [кн.text for ряд in reply_markup.inline_keyboard for кн in ряд]
        self.отправлено.append({"chat_id": chat_id, "text": text, "кнопки": кнопки})
        return True


async def свежая_база():
    """Пустая БД в памяти, на которую смотрит `database.connection`.

    Фабрика подменяется на модуле (`c._session_cls`), потому что и очередь, и
    `track_event` берут её оттуда в момент вызова — см. services/nudges.py.
    """
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(User.metadata.create_all)
    session_cls = async_sessionmaker(engine, expire_on_commit=False)
    c._session_cls = lambda: session_cls
    return session_cls


async def строки(session_cls) -> list[OnboardingNudge]:
    async with session_cls() as s:
        return list((await s.execute(select(OnboardingNudge))).scalars())


async def созрело(session_cls, **часов_назад) -> None:
    """Сдвинуть due_at строк в прошлое: stage → сколько часов назад."""
    async with session_cls() as s:
        for stage, часов in часов_назад.items():
            await s.execute(
                update(OnboardingNudge)
                .where(OnboardingNudge.stage == stage)
                .values(due_at=datetime.now(timezone.utc) - timedelta(hours=часов))
            )
        await s.commit()


async def завести(session_cls, **поля) -> None:
    async with session_cls() as s:
        s.add(User(id="U-1", telegram_id=Я, **поля))
        await s.commit()


def _минут_до(due_at: datetime, отсчёт: datetime) -> int:
    # SQLite отдаёт naive-даты из DateTime(timezone=True) — выравниваем
    if due_at.tzinfo is None:
        due_at = due_at.replace(tzinfo=timezone.utc)
    return round((due_at - отсчёт).total_seconds() / 60)


# ── Постановка: отсрочки, upsert, тишина до срока ────────────────

async def случай_постановки() -> dict:
    session_cls = await свежая_база()
    отсчёт = datetime.now(timezone.utc)
    await nudges.запланировать_пуши_онбординга(Я, "ru")
    поставлено = sorted(
        [[п.stage, _минут_до(п.due_at, отсчёт)] for п in await строки(session_cls)],
        key=lambda пара: пара[1],
    )

    # Дубли: конец анкеты зовёт постановку второй раз — строк остаётся две,
    # но отсчёт начинается заново (иначе «укажи субкультуру» пришло бы посреди
    # заполнения анкеты), и язык обновляется на свежевыбранный
    await созрело(session_cls, style=1, email=1)
    await nudges.запланировать_пуши_онбординга(Я, "uz")
    после = await строки(session_cls)
    now = datetime.now(timezone.utc)

    # Пока срок не пришёл, тик обязан молчать: вся починка «спама» держится
    # на том, что между согласием и рекламой есть пауза
    бот = ФейковыйБот()
    тишина = await nudges.отправить_созревшие(бот)

    return {
        "постановка_строк": поставлено,
        "ожидание_минут": [NUDGE_STYLE_DELAY_MIN, NUDGE_EMAIL_DELAY_HOURS * 60],
        "перенос_строк": len(после),
        "перенос_локали": sorted({п.locale for п in после}),
        "перенос_в_будущее": all(_минут_до(п.due_at, now) > 0 for п in после),
        "тишина_отправлено": тишина + len(бот.отправлено),
        "тишина_строк_осталось": len(await строки(session_cls)),
    }


# ── Созревшие уходят и переоцениваются по свежей базе ────────────

async def случай_новичка() -> dict:
    """Анкеты нет: стиль уходит с CTA и кнопкой «Начать», почта — просьбой."""
    session_cls = await свежая_база()
    await завести(session_cls)
    await nudges.запланировать_пуши_онбординга(Я, "ru")
    await созрело(session_cls, style=2, email=1)  # стиль раньше — уйдёт первым

    бот = ФейковыйБот()
    отправлено = await nudges.отправить_созревшие(бот)
    async with session_cls() as s:
        события = [
            (е.props or {}).get("stage")
            for е in (
                await s.execute(
                    select(AnalyticsEvent).where(AnalyticsEvent.event == "nudge_sent")
                )
            ).scalars()
        ]
    return {
        "новичок_отправлено": отправлено,
        "новичок_тексты": [м["text"] for м in бот.отправлено],
        "новичок_ожидание": [
            T.onboarding_broadcast_style("ru", with_cta=True),
            T.onboarding_broadcast_email("ru"),
        ],
        "новичок_кнопки": [м["кнопки"] for м in бот.отправлено],
        "новичок_метка_кнопки": T.onboarding_start_label("ru"),
        "новичок_строк_осталось": len(await строки(session_cls)),
        "новичок_события": sorted(события),
    }


async def случай_готовой_анкеты() -> dict:
    """Имя и фото уже есть: «нажми Начать» звучит нелепо — совет без CTA."""
    session_cls = await свежая_база()
    await завести(session_cls)
    async with session_cls() as s:
        s.add(Profile(user_id="U-1", display_name="Боря", photos=["ФОТО"], gender="male"))
        await s.commit()
    await nudges.запланировать_пуши_онбординга(Я, "ru")
    await созрело(session_cls, style=1)  # почта остаётся в будущем

    бот = ФейковыйБот()
    await nudges.отправить_созревшие(бот)
    return {
        "готовому_тексты": [м["text"] for м in бот.отправлено],
        "готовому_ожидание": [T.onboarding_broadcast_style("ru", with_cta=False)],
        "готовому_кнопки": [м["кнопки"] for м in бот.отправлено],
    }


async def случай_почты() -> dict:
    """Почта привязана за время паузы: просьба «сохрани доступ» опоздала."""
    session_cls = await свежая_база()
    await завести(session_cls, email="borya@example.com")
    await nudges.запланировать_пуши_онбординга(Я, "ru")
    await созрело(session_cls, style=2, email=1)

    бот = ФейковыйБот()
    await nudges.отправить_созревшие(бот)
    return {
        "с_почтой_тексты": [м["text"] for м in бот.отправлено],
        "с_почтой_ожидание": [T.onboarding_broadcast_style("ru", with_cta=True)],
        "с_почтой_строк_осталось": len(await строки(session_cls)),
    }


async def случай_мёртвых_адресатов() -> dict:
    """Бан, исчезнувший аккаунт, недельная тишина — рекламе там делать нечего."""
    # Забаненный: строки чистятся, не отправив ничего
    session_cls = await свежая_база()
    await завести(session_cls, is_banned=True)
    await nudges.запланировать_пуши_онбординга(Я, "ru")
    await созрело(session_cls, style=2, email=1)
    бан_бот = ФейковыйБот()
    await nudges.отправить_созревшие(бан_бот)
    бан_строк = len(await строки(session_cls))

    # Аккаунт удалён между постановкой и сроком
    session_cls = await свежая_база()
    await nudges.запланировать_пуши_онбординга(Я, "ru")
    await созрело(session_cls, style=2, email=1)
    исчез_бот = ФейковыйБот()
    await nudges.отправить_созревшие(исчез_бот)
    исчез_строк = len(await строки(session_cls))

    # Строка старше NUDGE_MAX_AGE_DAYS: человек молчит неделю, догонять — спам
    session_cls = await свежая_база()
    await завести(session_cls)
    await nudges.запланировать_пуши_онбординга(Я, "ru")
    давно = datetime.now(timezone.utc) - timedelta(days=NUDGE_MAX_AGE_DAYS + 1)
    async with session_cls() as s:
        await s.execute(update(OnboardingNudge).values(due_at=давно, created_at=давно))
        await s.commit()
    старый_бот = ФейковыйБот()
    await nudges.отправить_созревшие(старый_бот)
    старых_строк = len(await строки(session_cls))

    return {
        "забаненному_отправлено": len(бан_бот.отправлено),
        "забаненному_строк_осталось": бан_строк,
        "исчезнувшему_отправлено": len(исчез_бот.отправлено),
        "исчезнувшему_строк_осталось": исчез_строк,
        "просроченному_отправлено": len(старый_бот.отправлено),
        "просроченному_строк_осталось": старых_строк,
    }


# ── Сбои отправки: чистка, повтор, лимит ─────────────────────────

async def случай_сбоев() -> dict:
    # Человек заблокировал бота: доставить некому, строка чистится
    session_cls = await свежая_база()
    await завести(session_cls)
    await nudges.запланировать_пуши_онбординга(Я, "ru")
    await созрело(session_cls, style=1)
    блок_бот = ФейковыйБот(
        ошибки=[TelegramForbiddenError(method=_МЕТОД, message="Forbidden: bot was blocked")]
    )
    await nudges.отправить_созревшие(блок_бот)
    осталось_после_блока = sorted(п.stage for п in await строки(session_cls))

    # Сеть мигнула: строка остаётся, следующий тик дошлёт
    session_cls = await свежая_база()
    await завести(session_cls)
    await nudges.запланировать_пуши_онбординга(Я, "ru")
    await созрело(session_cls, style=1)
    сеть_бот = ФейковыйБот(ошибки=[RuntimeError("сеть мигнула")])
    await nudges.отправить_созревшие(сеть_бот)
    осталось_после_сети = sorted(п.stage for п in await строки(session_cls))
    добито = await nudges.отправить_созревшие(сеть_бот)

    # Лимит Telegram: тик прерывается целиком, очередь дошлёт со следующего
    session_cls = await свежая_база()
    await завести(session_cls)
    await nudges.запланировать_пуши_онбординга(Я, "ru")
    await созрело(session_cls, style=2, email=1)
    лимит_бот = ФейковыйБот(
        ошибки=[TelegramRetryAfter(method=_МЕТОД, message="Too Many Requests", retry_after=0)]
    )
    лимит_отправлено = await nudges.отправить_созревшие(лимит_бот)

    return {
        "заблокировавшему_отправлено": len(блок_бот.отправлено),
        "после_блокировки_осталось": осталось_после_блока,
        "сбой_сети_строк_осталось": осталось_после_сети,
        "сбой_сети_добито": добито,
        "лимит_отправлено": лимит_отправлено + len(лимит_бот.отправлено),
        "лимит_строк_осталось": len(await строки(session_cls)),
    }


async def случай_локали() -> dict:
    """Язык аккаунта главнее языка строки: человек мог сменить его за сутки."""
    session_cls = await свежая_база()
    await завести(session_cls, locale="uz")
    await nudges.запланировать_пуши_онбординга(Я, "ru")
    await созрело(session_cls, email=1)  # стиль остаётся в будущем

    бот = ФейковыйБот()
    await nudges.отправить_созревшие(бот)
    return {
        "локаль_тексты": [м["text"] for м in бот.отправлено],
        "локаль_ожидание": [T.onboarding_broadcast_email("uz")],
        "локаль_ожидание_ru": [T.onboarding_broadcast_email("ru")],
    }


def слить(ответ: dict, добавка: dict) -> None:
    for ключ, значение in добавка.items():
        assert ключ not in ответ, f"ключ {ключ!r} пишут два сценария"
        ответ[ключ] = значение


async def main() -> None:
    ответ: dict = {}
    слить(ответ, await случай_постановки())
    слить(ответ, await случай_новичка())
    слить(ответ, await случай_готовой_анкеты())
    слить(ответ, await случай_почты())
    слить(ответ, await случай_мёртвых_адресатов())
    слить(ответ, await случай_сбоев())
    слить(ответ, await случай_локали())
    print(json.dumps(ответ, ensure_ascii=False, default=str))


asyncio.run(main())
