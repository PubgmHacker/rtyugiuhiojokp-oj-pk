"""Событийная аналитика: девять событий от /start до покупки.

Аналитики не было вообще — ни одного трекинга: ни воронку, ни окупаемость
канала посмотреть было нечем. Внешние трекеры дейтингу противопоказаны
(передача данных третьим лицам — отдельный пункт согласия), поэтому события
пишутся в свой Postgres, а отчёты — обычный SQL.

Девять событий (единственный список, продублирован в docstring модели):

    bot_start           первый /start; props.source — метка канала из
                        deep-link (t.me/<bot>?start=<метка>), first-touch:
                        повторный /start с другой меткой источник не крадёт
    profile_created     анкета в боте дошла до конца
    app_open            вход в мини-апп; одна строка на день (сетка D1/D7)
    first_swipe         первый свайп в деке
    first_match         первый мэтч (пишется каждому из пары)
    first_message       первое отправленное сообщение
    paywall_view        открыл витрину тарифов; одна строка на день
    purchase_started    создан счёт (Stars/CryptoBot); каждая попытка
    purchase_completed  начисление подписки; props.provider различает
                        деньги (stars/cryptobot/appstore) от promo и gift

Воронка «CPI → анкета → первый свайп → D1 → покупка» по когорте недели:

    WITH когорта AS (
        SELECT user_id, props->>'source' AS source, created_at
        FROM dating_analytics_events
        WHERE event = 'bot_start'
          AND created_at >= date_trunc('week', now())
    )
    SELECT
        k.source,
        count(*)                                            AS старт,
        count(*) FILTER (WHERE p.user_id IS NOT NULL)       AS анкета,
        count(*) FILTER (WHERE s.user_id IS NOT NULL)       AS свайп,
        count(*) FILTER (WHERE d1.user_id IS NOT NULL)      AS d1,
        count(*) FILTER (WHERE b.user_id IS NOT NULL)       AS покупка
    FROM когорта k
    LEFT JOIN dating_analytics_events p
        ON p.user_id = k.user_id AND p.event = 'profile_created'
    LEFT JOIN dating_analytics_events s
        ON s.user_id = k.user_id AND s.event = 'first_swipe'
    LEFT JOIN LATERAL (
        SELECT user_id FROM dating_analytics_events
        WHERE user_id = k.user_id AND event = 'app_open'
          AND created_at::date = k.created_at::date + 1
        LIMIT 1
    ) d1 ON true
    LEFT JOIN LATERAL (
        SELECT user_id FROM dating_analytics_events
        WHERE user_id = k.user_id AND event = 'purchase_completed'
          AND props->>'provider' NOT IN ('promo', 'gift')
        LIMIT 1
    ) b ON true
    GROUP BY k.source ORDER BY старт DESC;

Retention D1/D7 без когорт — по дневной сетке app_open:

    SELECT a.created_at::date AS день,
           count(DISTINCT a.user_id)                        AS были,
           count(DISTINCT r1.user_id)                       AS вернулись_d1,
           count(DISTINCT r7.user_id)                       AS вернулись_d7
    FROM dating_analytics_events a
    LEFT JOIN dating_analytics_events r1
        ON r1.user_id = a.user_id AND r1.event = 'app_open'
       AND r1.created_at::date = a.created_at::date + 1
    LEFT JOIN dating_analytics_events r7
        ON r7.user_id = a.user_id AND r7.event = 'app_open'
       AND r7.created_at::date = a.created_at::date + 7
    WHERE a.event = 'app_open'
    GROUP BY 1 ORDER BY 1 DESC;

Запись не смеет ломать продукт: любая ошибка — строка в логе, бизнес-запрос
проходит. Повтор вехи гасится уникальным dedup_key через вложенную
транзакцию — тот же приём, что в activate_premium: при гонке второй INSERT
падает на уникальном ключе внутри savepoint, внешняя транзакция цела.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from models.models import AnalyticsEvent

logger = logging.getLogger(__name__)

EVENT_BOT_START = "bot_start"
EVENT_PROFILE_CREATED = "profile_created"
EVENT_APP_OPEN = "app_open"
EVENT_FIRST_SWIPE = "first_swipe"
EVENT_FIRST_MATCH = "first_match"
EVENT_FIRST_MESSAGE = "first_message"
EVENT_PAYWALL_VIEW = "paywall_view"
EVENT_PURCHASE_STARTED = "purchase_started"
EVENT_PURCHASE_COMPLETED = "purchase_completed"

#: Полный словарь воронки — по нему тесты следят, что список не разъехался
#: с docstring и точками записи
СОБЫТИЯ = (
    EVENT_BOT_START,
    EVENT_PROFILE_CREATED,
    EVENT_APP_OPEN,
    EVENT_FIRST_SWIPE,
    EVENT_FIRST_MATCH,
    EVENT_FIRST_MESSAGE,
    EVENT_PAYWALL_VIEW,
    EVENT_PURCHASE_STARTED,
    EVENT_PURCHASE_COMPLETED,
)


async def track(
    session: AsyncSession,
    user_id: str,
    event: str,
    props: dict | None = None,
    *,
    once: bool = False,
    daily: bool = False,
) -> None:
    """Записать событие в той же транзакции, что и бизнес-действие.

    `once` — веха: одна строка на человека за всю жизнь (первый свайп).
    `daily` — одна строка на календарный день UTC (app_open — из них
    складывается сетка D1/D7, и таблица не пухнет от каждого пинга).
    Повторы молча гасятся уникальным dedup_key.

    Событие коммитится вместе с действием, которое его породило: отдельного
    коммита здесь нет, откат бизнес-транзакции откатывает и событие —
    несостоявшаяся покупка не оставляет следа purchase_completed.
    """
    dedup: str | None = None
    if once:
        dedup = f"{user_id}:{event}"
    elif daily:
        день = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        dedup = f"{user_id}:{event}:{день}"

    try:
        if dedup is not None:
            # Дешёвая предпроверка по уникальному индексу. app_open висит на
            # горячих эндпоинтах (auth, /me): без неё каждый повторный вызов
            # шёл бы через INSERT → duplicate key, а Postgres пишет каждый
            # такой конфликт ошибкой в свой лог. Гонку двух первых вызовов
            # предпроверка не закрывает — её ловит savepoint ниже.
            существует = await session.execute(
                select(AnalyticsEvent.id).where(AnalyticsEvent.dedup_key == dedup)
            )
            if существует.scalar_one_or_none() is not None:
                return

        # Savepoint, не транзакция: при повторе вехи откатывается только
        # INSERT события, а бизнес-изменения запроса остаются целы
        async with session.begin_nested():
            session.add(AnalyticsEvent(
                user_id=user_id,
                event=event,
                props=props or {},
                dedup_key=dedup,
            ))
    except IntegrityError:
        pass  # веха уже записана — повтор не событие
    except Exception as e:
        # Аналитика не смеет ломать продукт: свайп важнее строки в отчёте
        logger.warning(f"Событие {event} не записано (user={user_id}): {e}")
