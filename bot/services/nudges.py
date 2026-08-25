"""Отложенные завлекающие пуши онбординга: субкультура и почта.

Раньше обе рассылки уходили прямо в онбординге, сразу после согласия с
политикой: человек ещё не сделал в боте ничего, а уже получил три сообщения
подряд — и читал это как спам. Теперь согласие и конец анкеты только СТАВЯТ
пуш (`запланировать_пуши_онбординга`, upsert по telegram_id+stage), а цикл
`supervise_nudges` отправляет его после паузы, когда сообщение работает как
возврат в бота, а не как шум поверх живого диалога.

Очередь лежит в БД (`dating_onboarding_nudges`), а не в памяти: пуш на
45 минут и на сутки обязан переживать рестарт бота и деплой. Отправленные,
просроченные и потерявшие смысл строки удаляются — таблица держит только
несосланное.

Пуш теряет смысл тихо, и перед отправкой это проверяется заново:
- почта уже привязана — просить «сохрани доступ» не о чем;
- аккаунт забанен или удалён — рекламе там делать нечего;
- анкета уже заполнена — «нажми Начать» звучит нелепо, уходит текст без CTA.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timedelta, timezone

from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from config import NUDGE_EMAIL_DELAY_HOURS, NUDGE_MAX_AGE_DAYS, NUDGE_STYLE_DELAY_MIN
from keyboards import start_app_kb
import texts as T

# Слой БД здесь НЕ импортируется на уровне модуля — только внутри функций,
# в момент вызова, и обязательно модулем (`db._session_cls()`), а не именами.
# Обе странности — контракты тестов:
#   • сценарии с настоящей БД в памяти подменяют фабрику сессий на модуле
#     `database.connection` (см. суточные_лимиты.py) — имя, связанное при
#     импорте, продолжало бы держать боевой Postgres;
#   • сценарии БЕЗ БД подменяют весь `database` плоским фейк-модулем до
#     импорта хендлеров (см. test_identity_enforcement.py), а хендлеры
#     импортируют этот файл — модульный `import database.connection` ронял
#     бы их на «'database' is not a package».

logger = logging.getLogger(__name__)

#: Как часто цикл смотрит в очередь. Минута — на порядок мельче самой ранней
#: задержки (45 минут), поэтому точность отправки от интервала не страдает.
ИНТЕРВАЛ_ПРОВЕРКИ = 60.0

#: Сколько строк берётся за один тик. Ограничение — защита от залпа после
#: долгого простоя бота: накопившаяся очередь уходит порциями, а не одним
#: всплеском в лимиты Telegram.
ПОРЦИЯ = 50

#: ~20 сообщений в секунду — та же оглядка на лимиты, что в broadcast.py:
#: обычные уведомления бота не должны упираться в общий лимит из-за рекламы.
ПАУЗА_МЕЖДУ_ОТПРАВКАМИ = 0.05


async def запланировать_пуши_онбординга(telegram_id: int, locale: str) -> None:
    """Поставить оба пуша или передвинуть их отсчёт заново.

    Зовётся дважды: согласие с политикой ставит пуши, конец анкеты двигает
    их вперёд — иначе «укажи субкультуру» приходило бы через 45 минут после
    согласия, посреди заполнения той самой анкеты. Upsert по (telegram_id,
    stage): у человека не бывает двух одинаковых пушей в очереди.

    Ошибка здесь не имеет права ронять вызвавший шаг: недоступная база на
    согласии — это потерянная реклама, а не потерянный онбординг. Поэтому
    все исключения гасятся логом.
    """
    now = datetime.now(timezone.utc)
    план = (
        ("style", now + timedelta(minutes=NUDGE_STYLE_DELAY_MIN)),
        ("email", now + timedelta(hours=NUDGE_EMAIL_DELAY_HOURS)),
    )
    try:
        # Внутри try намеренно: в сценариях с фейковым `database` сам импорт
        # и падает — а падать этому шагу нельзя, см. док-строку
        import database.connection as db
        from database.models import OnboardingNudge

        cls = db._session_cls()
        async with cls() as session:
            for stage, due_at in план:
                строка = (
                    await session.execute(
                        select(OnboardingNudge).where(
                            OnboardingNudge.telegram_id == telegram_id,
                            OnboardingNudge.stage == stage,
                        )
                    )
                ).scalar_one_or_none()
                if строка is None:
                    session.add(
                        OnboardingNudge(
                            telegram_id=telegram_id,
                            stage=stage,
                            locale=locale,
                            due_at=due_at,
                        )
                    )
                else:
                    строка.due_at = due_at
                    строка.locale = locale
            await session.commit()
    except IntegrityError:
        # Двойной тап по согласию наперегонки: вторая вставка упёрлась в
        # uq_onboarding_nudge. Строка уже есть — цель достигнута, а повторный
        # сдвиг due_at на доли секунды ничего не меняет.
        logger.debug("пуши для %s уже поставлены параллельным тапом", telegram_id)
    except Exception as e:
        logger.warning("не поставили пуши онбординга для %s: %s", telegram_id, e)


async def _созревшие(now: datetime) -> list:
    """Строки, чей срок пришёл — старшие первыми, не больше порции."""
    import database.connection as db
    from database.models import OnboardingNudge

    cls = db._session_cls()
    async with cls() as session:
        return list(
            (
                await session.execute(
                    select(OnboardingNudge)
                    .where(OnboardingNudge.due_at <= now)
                    .order_by(OnboardingNudge.due_at)
                    .limit(ПОРЦИЯ)
                )
            ).scalars()
        )


async def _удалить(nudge_id: str) -> None:
    import database.connection as db
    from database.models import OnboardingNudge

    cls = db._session_cls()
    async with cls() as session:
        await session.execute(delete(OnboardingNudge).where(OnboardingNudge.id == nudge_id))
        await session.commit()


async def _адресат(telegram_id: int) -> tuple[dict | None, dict | None]:
    """Свежие пользователь и анкета: пуш проверяется по базе, не по строке.

    За 45 минут и тем более за сутки человек успевает привязать почту,
    заполнить анкету или попасть в бан — и решение «что слать» обязано
    опираться на состояние на момент отправки.
    """
    import database.connection as db
    from database.models import Profile, User

    cls = db._session_cls()
    async with cls() as session:
        user = (
            await session.execute(select(User).where(User.telegram_id == telegram_id))
        ).scalar_one_or_none()
        if user is None:
            return None, None
        profile = (
            await session.execute(select(Profile).where(Profile.user_id == user.id))
        ).scalar_one_or_none()
        пользователь = {
            "id": user.id,
            "locale": user.locale,
            "email": user.email,
            "is_banned": user.is_banned,
        }
        анкета = None
        if profile is not None:
            анкета = {
                "display_name": profile.display_name,
                "photos": profile.photos or [],
            }
        return пользователь, анкета


async def отправить_созревшие(bot) -> int:
    """Один проход по очереди: отправить готовое, вычистить мёртвое.

    Возвращает число отправленных сообщений — цифру пишет лог тика, по ней
    в Railway видно, что очередь живёт.
    """
    import database.connection as db

    now = datetime.now(timezone.utc)
    отправлено = 0
    for строка in await _созревшие(now):
        created_at = строка.created_at
        # SQLite отдаёт naive-даты — выравниваем, как _возраст_из_даты
        if created_at is not None and created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        if created_at is not None and now - created_at > timedelta(days=NUDGE_MAX_AGE_DAYS):
            # Человек молчит больше недели: догоняющая реклама его не вернёт,
            # это уже спам по мёртвой базе. Строку — вон.
            await _удалить(строка.id)
            continue

        пользователь, анкета = await _адресат(строка.telegram_id)
        if пользователь is None or пользователь["is_banned"]:
            await _удалить(строка.id)
            continue

        locale = пользователь["locale"] or строка.locale or "ru"
        анкета_готова = bool(анкета and анкета["display_name"] and анкета["photos"])

        if строка.stage == "email":
            if пользователь["email"]:
                # Почта уже привязана — просьба «сохрани доступ» опоздала
                await _удалить(строка.id)
                continue
            текст, клавиатура = T.onboarding_broadcast_email(locale), None
        else:
            # Готовой анкете «нажми Начать» не предлагаем — только сам совет
            текст = T.onboarding_broadcast_style(locale, with_cta=not анкета_готова)
            клавиатура = None if анкета_готова else start_app_kb(locale)

        try:
            await bot.send_message(
                chat_id=строка.telegram_id, text=текст, reply_markup=клавиатура
            )
        except TelegramRetryAfter as e:
            # Упёрлись в лимит Telegram: строки не трогаем, тик прерываем —
            # очередь дошлёт остаток со следующего захода
            logger.warning("лимит Telegram на пушах, пауза %sс", e.retry_after)
            await asyncio.sleep(float(e.retry_after))
            break
        except (TelegramForbiddenError, TelegramBadRequest) as e:
            # Бот заблокирован или чат исчез — этому адресату не доставить
            logger.info("пуш %s для %s не доставить: %s", строка.stage, строка.telegram_id, e)
            await _удалить(строка.id)
            continue
        except Exception as e:
            # Сеть мигнула: строку оставляем, следующий тик повторит,
            # а безнадёжную через неделю удалит проверка возраста
            logger.warning("пуш %s для %s отложен: %s", строка.stage, строка.telegram_id, e)
            continue

        await _удалить(строка.id)
        отправлено += 1
        # Веха воронки: по ней видно, догоняет ли реклама кого-то живого
        try:
            await db.track_event(
                пользователь["id"], "nudge_sent", {"stage": строка.stage}
            )
        except Exception as e:
            logger.debug("nudge_sent не записан: %s", e)
        await asyncio.sleep(ПАУЗА_МЕЖДУ_ОТПРАВКАМИ)
    return отправлено


async def supervise_nudges(bot, интервал: float = ИНТЕРВАЛ_ПРОВЕРКИ) -> None:
    """Держать очередь живой: тикать вечно, падения гасить логом.

    Тот же принцип, что supervise_redis_subscriber: фоновая задача без
    присмотра умирает молча, и пуши перестают уходить насовсем — без единой
    строчки в логе. `CancelledError` пропускаем: это штатная остановка бота.
    """
    while True:
        начало = time.monotonic()
        try:
            отправлено = await отправить_созревшие(bot)
            if отправлено:
                logger.info("отправлено пушей онбординга: %d", отправлено)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error("тик очереди пушей упал: %s", e)
        прошло = time.monotonic() - начало
        await asyncio.sleep(max(1.0, интервал - прошло))
