"""Автоматические уведомления вовлечения: сгорающая серия и дайджест дня-2.

До этого файла вся инициатива исходила от людей: push.py шлёт только мэтч и
сообщение, рассылки запускает админ руками. Две механики, ради которых
строились стрики и карта дня, молчали в самый важный момент: серия сгорала
без предупреждения (а терять 40 дней огонька из-за забытого вечера — повод
удалить приложение, не повод вернуться), и человек второго дня не имел ни
одной причины открыть приложение снова — хотя день 2 решает удержание.

Два уведомления, оба автоматические и оба ровно один раз:

- «серия догорает» — паре, где вчера писали, а сегодня ещё нет, ближе к
  вечеру. Одно сообщение — и серия живёт; молчание — сгорает в полночь UTC.
- дайджест дня-2 — человеку через сутки после регистрации: его карта дня
  и приглашение в ленту. Один раз за жизнь аккаунта, не сериал.

Каналы те же, что у итога жалобы (report_notify.py): событие боту в
dating:bot:events (тексты живут у бота) плюс APNs-пуш тем, кто вошёл через
Apple ID и Telegram не имеет. Оба канала best-effort — но дедуп строгий:
ключ в Redis ставится ДО отправки (SET NX), и если Redis лежит, проход
пропускается целиком. Недоставленное уведомление переживаемо, а вот
одинаковый пуш каждые полчаса — самый быстрый способ научить человека
отключить уведомления насовсем.

Часы окон — UTC: стрики живут на UTC-сутках (streaks._today_utc), значит
и «вечер перед сгоранием» определяется по UTC. Для основной аудитории
(МСК, UTC+3) окно 16–21 UTC — это 19:00–00:00, вечер и есть.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from models.models import ChatStreak, Match, Profile, User

logger = logging.getLogger(__name__)

#: Окно предупреждения о серии, часы UTC [от, до). До полуночи остаётся
#: 3–8 часов: раньше — предупреждать не о чем (день только начался),
#: позже — человек уже спит и всё равно не успеет.
ОКНО_СТРИКА = (16, 21)
#: Окно дайджеста, часы UTC [от, до): дневные часы аудитории, чтобы пуш
#: не будил среди ночи того, кто зарегистрировался в полночь.
ОКНО_ДАЙДЖЕСТА = (8, 16)

#: Сколько живёт дедуп-ключ. У стрика — двое суток: ключ датирован днём,
#: и дольше защищать нечего. У дайджеста — неделя: окно кандидата 24–48
#: часов от регистрации, после недели он кандидатом не станет никогда.
_TTL_СТРИКА = 2 * 24 * 3600
_TTL_ДАЙДЖЕСТА = 7 * 24 * 3600


def _в_окне(now: datetime, окно: tuple[int, int]) -> bool:
    return окно[0] <= now.hour < окно[1]


async def сгорающие_стрики(
    session: AsyncSession, now: datetime,
) -> list[dict]:
    """Пары, чья серия сгорит в ближайшую полночь UTC.

    Это ровно «вчера писали, сегодня ещё нет»: last_counted_for лежит во
    вчерашних сутках. Позавчерашние серии уже мертвы (их сожжёт первый же
    просмотр), сегодняшние — вне опасности. Сравниваем диапазоном, а не
    равенством: колонка в Postgres aware, в SQLite naive, и точечное
    равенство datetime — гонка форматов, которую диапазон не замечает.

    Пары с забаненной стороной пропускаются: подталкивать человека писать
    тому, кто ему ответить не может, — жестоко и бессмысленно.
    """
    сегодня = now.astimezone(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    вчера = сегодня - timedelta(days=1)

    u1, u2 = aliased(User), aliased(User)
    result = await session.execute(
        select(
            Match.id,
            Match.user1_id,
            Match.user2_id,
            ChatStreak.streak_days,
        )
        .join(Match, Match.id == ChatStreak.match_id)
        .join(u1, u1.id == Match.user1_id)
        .join(u2, u2.id == Match.user2_id)
        .where(
            ChatStreak.streak_days > 0,
            ChatStreak.last_counted_for >= вчера,
            ChatStreak.last_counted_for < сегодня,
            Match.is_active == True,  # noqa: E712
            u1.is_banned == False,  # noqa: E712
            u2.is_banned == False,  # noqa: E712
        )
    )
    пары = [
        {
            "match_id": match_id,
            "user_ids": [user1_id, user2_id],
            "days": streak_days,
        }
        for match_id, user1_id, user2_id, streak_days in result.all()
    ]
    if not пары:
        return пары

    # Имена сторон — для текста «серия с {имя} догорает». Одним запросом
    # на все пары: пуш не повод для N+1
    все_ид = {uid for пара in пары for uid in пара["user_ids"]}
    имена = dict(
        (
            await session.execute(
                select(Profile.user_id, Profile.display_name).where(
                    Profile.user_id.in_(все_ид)
                )
            )
        ).all()
    )
    for пара in пары:
        пара["names"] = [имена.get(uid) or "Ваш мэтч" for uid in пара["user_ids"]]
    return пары


async def кандидаты_дайджеста(
    session: AsyncSession, now: datetime,
) -> list[str]:
    """Кто получает дайджест дня-2: аккаунту 24–48 часов, анкета заведена,
    бана нет. Без анкеты дайджест зовёт в пустоту — сначала онбординг."""
    от = now - timedelta(hours=48)
    до = now - timedelta(hours=24)
    result = await session.execute(
        select(User.id)
        .join(Profile, Profile.user_id == User.id)
        .where(
            User.created_at > от,
            User.created_at <= до,
            User.is_banned == False,  # noqa: E712
        )
    )
    return [uid for (uid,) in result.all()]


async def _занять(r, ключ: str, ttl: int) -> bool:
    """Дедуп: True — ключ наш, слать; False — уже отправлено или Redis лёг.

    Ключ ставится ДО отправки. Обратный порядок при падении между отправкой
    и записью давал бы дубль на каждом следующем проходе.
    """
    try:
        return bool(await r.set(ключ, "1", nx=True, ex=ttl))
    except Exception as e:
        logger.warning(f"Дедуп вовлечения недоступен ({ключ}): {e}")
        return False


async def предупредить_о_стриках(now: datetime | None = None) -> int:
    """Разослать «серия догорает» всем парам под угрозой. Возвращает число
    пар, получивших предупреждение (для лога и тестов)."""
    from database.connection import async_session_factory
    from services import push
    from services.realtime import get_redis

    now = now or datetime.now(timezone.utc)
    if not _в_окне(now, ОКНО_СТРИКА):
        return 0

    async with async_session_factory() as session:
        пары = await сгорающие_стрики(session, now)
    if not пары:
        return 0

    r = await get_redis()
    день = now.astimezone(timezone.utc).date().isoformat()
    отправлено = 0
    for пара in пары:
        if not await _занять(
            r, f"dating:engage:streak:{пара['match_id']}:{день}", _TTL_СТРИКА
        ):
            continue
        отправлено += 1
        # Каждому — с именем ДРУГОЙ стороны пары
        for uid, имя_партнёра in zip(пара["user_ids"], reversed(пара["names"])):
            try:
                await r.publish(
                    "dating:bot:events",
                    json.dumps({
                        "type": "streak_expiring",
                        "user_id": uid,
                        "partner_name": имя_партнёра,
                        "days": пара["days"],
                    }),
                )
            except Exception as e:
                logger.warning(f"Стрик-событие боту не ушло (user={uid}): {e}")
            try:
                await push.send_to_user(
                    uid,
                    title="Серия догорает 🔥",
                    body=(
                        f"{пара['days']} дн. переписки с {имя_партнёра} сгорят "
                        "сегодня. Одно сообщение — и серия живёт."
                    ),
                    data={"kind": "streak_expiring", "match_id": пара["match_id"]},
                    collapse_id=f"streak-{пара['match_id']}",
                )
            except Exception as e:
                logger.warning(f"Стрик-пуш не ушёл (user={uid}): {e}")

    if отправлено:
        logger.info(f"Предупреждения о сгорающих сериях: {отправлено} пар")
    return отправлено


async def разослать_дайджест_дня2(now: datetime | None = None) -> int:
    """Дайджест второго дня: карта дня + приглашение в ленту, один раз за
    жизнь аккаунта. Возвращает число получателей."""
    from database.connection import async_session_factory
    from services import push
    from services.daily_card import card_for_day
    from services.realtime import get_redis

    now = now or datetime.now(timezone.utc)
    if not _в_окне(now, ОКНО_ДАЙДЖЕСТА):
        return 0

    async with async_session_factory() as session:
        кандидаты = await кандидаты_дайджеста(session, now)
    if not кандидаты:
        return 0

    r = await get_redis()
    отправлено = 0
    for uid in кандидаты:
        if not await _занять(r, f"dating:engage:day2:{uid}", _TTL_ДАЙДЖЕСТА):
            continue
        отправлено += 1
        # Карта дня — та же, что человек увидит в приложении: чистая функция
        # от (кто, когда). Живую фразу от модели не зовём: рассылка обязана
        # быть предсказуемой и бесплатной, справочного совета достаточно
        карта = card_for_day(uid, now.astimezone(timezone.utc).date())
        try:
            await r.publish(
                "dating:bot:events",
                json.dumps({
                    "type": "day2_digest",
                    "user_id": uid,
                    "card_name": карта.name,
                    "card_meaning": карта.meaning,
                    "card_advice": карта.advice,
                }),
            )
        except Exception as e:
            logger.warning(f"Дайджест-событие боту не ушло (user={uid}): {e}")
        try:
            await push.send_to_user(
                uid,
                title="Ваша карта дня ждёт",
                body=f"{карта.name}: {карта.advice}",
                data={"kind": "day2_digest"},
                collapse_id=f"day2-{uid}",
            )
        except Exception as e:
            logger.warning(f"Дайджест-пуш не ушёл (user={uid}): {e}")

    if отправлено:
        logger.info(f"Дайджест дня-2 отправлен: {отправлено} чел.")
    return отправлено


async def цикл_вовлечения(интервал: int = 1800) -> None:
    """Фоновый цикл уведомлений вовлечения — второй жилец рядом с уборщиком
    историй (main.py), устроен по его же правилам: первая пауза до первого
    прохода, каждый проход в своём try, отмена — штатный выход.

    Полчаса, а не час: окна по 5–8 часов, и часовой шаг в худшем случае
    (проход за минуту до окна) съедал бы почти час окна. Дубли отсекает
    не интервал, а дедуп-ключ.
    """
    while True:
        try:
            await asyncio.sleep(интервал)
            await предупредить_о_стриках()
            await разослать_дайджест_дня2()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning(f"Цикл вовлечения: проход упал: {e}")
