from __future__ import annotations

import asyncio
import json
import logging
import time

import redis.asyncio as redis

from config import REDIS_URL

logger = logging.getLogger(__name__)

#: Живые задачи рассылок. Ссылки обязательны: asyncio держит task слабо,
#: и безымянный create_task мог бы быть собран сборщиком посреди отправки.
_рассылки: set[asyncio.Task] = set()

#: Один клиент на процесс — как в `api/services/realtime.py`. Раньше здесь
#: стоял `redis.from_url` прямо в функции, и каждая публикация заводила НОВЫЙ
#: клиент с новым пулом соединений, который никто не закрывал. Публикация
#: происходит на каждое сообщение в чате (`handlers/matches.py`), так что бот
#: съедал по TCP-соединению на сообщение и упирался в `maxclients` Redis —
#: после чего переставали ходить вообще все события, включая мэтчи.
_redis: redis.Redis | None = None


async def _get_redis() -> redis.Redis:
    global _redis
    if _redis is None:
        # Командный клиент (publish, отзыв токенов): с таймаутами, иначе
        # blackhole до Redis вешает публикацию — а с ней и хендлер сообщения —
        # навсегда. Подписка живёт на СВОЁМ клиенте без socket_timeout (см.
        # start_redis_subscriber): для listen() тихий канал неотличим от
        # мёртвого сокета, и здесь таймаут рвал бы подписку каждые 5 секунд.
        _redis = redis.from_url(
            REDIS_URL,
            decode_responses=True,
            socket_timeout=5.0,
            socket_connect_timeout=2.0,
            retry_on_timeout=True,
            health_check_interval=30,
            max_connections=50,
        )
    return _redis


async def close_redis() -> None:
    """Закрыть общий клиент — зовётся при остановке бота."""
    global _redis
    if _redis is not None:
        await _redis.aclose()
        _redis = None


async def publish_match_event(match_id: str, user1_id: str, user2_id: str):
    """Publish match event for bot Redis subscriber."""
    try:
        r = await _get_redis()
        data = {
            "type": "new_match",
            "match_id": match_id,
            "user1_id": user1_id,
            "user2_id": user2_id,
        }
        await r.publish("dating:bot:matches", json.dumps(data))
    except Exception as e:
        logger.error(f"Redis publish error: {e}")


async def publish_message_event(
    match_id: str,
    sender_id: str,
    text: str,
    message_id: str = "",
    created_at: str | None = None,
):
    """Publish message for real-time sync (web WS слушает канал dating:match:{id})."""
    try:
        r = await _get_redis()
        data = {
            "type": "message",
            "origin": "bot",
            "id": message_id,
            "match_id": match_id,
            "sender_id": sender_id,
            "text": text,
            "image_url": None,
            "created_at": created_at,
        }
        await r.publish(f"dating:match:{match_id}", json.dumps(data))
    except Exception as e:
        logger.error(f"Redis publish error: {e}")


async def revoke_user_tokens(user_id: str) -> None:
    """Отозвать все токены пользователя — та же отметка, что ставит API.

    Ключ и семантика — api/services/token_revocation.py: токены, выданные до
    отметки, мертвы. TTL держим равным жизни токена (72 ч, JWT_ACCESS_EXPIRE_HOURS
    в api/config.py) — дольше держать бессмысленно, токены истекают сами.
    Боту отметка нужна одному сценарию: бан вернулся после возврата Stars
    за разблокировку, и живые сессии мини-аппа надо погасить немедленно.
    """
    import time

    try:
        r = await _get_redis()
        await r.set(
            f"dating:jwt:revoked_before:{user_id}",
            str(int(time.time())),
            ex=72 * 3600,
        )
    except Exception as e:
        logger.error(f"Не удалось отозвать токены user={user_id}: {e}")


async def start_redis_subscriber(bot):
    """Subscribe to Redis channels and forward events to Telegram users."""
    # Отдельный клиент, а не общий _get_redis: у общего стоит socket_timeout,
    # который для вечно ждущего listen() означал бы обрыв на каждой паузе в
    # событиях. Подписке таймаут на чтение не нужен — обрыв TCP и рестарт
    # Redis ловит supervise_redis_subscriber переподключением.
    r = redis.from_url(REDIS_URL, decode_responses=True, socket_connect_timeout=2.0)
    pubsub = r.pubsub()

    await pubsub.subscribe("dating:bot:matches", "dating:bot:events")

    logger.info("Redis subscriber started, listening for matches...")

    try:
        async for message in pubsub.listen():
            if message["type"] != "message":
                continue

            try:
                data = json.loads(message["data"])
                event_type = data.get("type")

                if event_type == "new_match":
                    # Notify both users
                    for uid in [data["user1_id"], data["user2_id"]]:
                        await _notify_user_about_match(bot, uid, data["match_id"])

                elif event_type == "new_message":
                    await _notify_user_about_message(
                        bot, data["receiver_id"], data["sender_id"], data.get("text", ""),
                    )

                elif event_type == "new_like":
                    await _notify_user_about_like(bot, data["receiver_id"], data["liker_id"])

                elif event_type == "banned":
                    await _notify_user_about_ban(
                        bot,
                        data["user_id"],
                        data.get("reason", ""),
                        data.get("banned_until"),
                    )

                elif event_type == "report_outcome":
                    await _notify_reporter_about_outcome(
                        bot, data["user_id"], data.get("outcome", "")
                    )

                elif event_type == "broadcast":
                    # Отдельной задачей, не в этом цикле: рассылка на тысячи
                    # получателей идёт минуты, а мэтчи и баны ждать не должны
                    from services.broadcast import run_broadcast

                    задача = asyncio.create_task(
                        run_broadcast(bot, data["broadcast_id"])
                    )
                    _рассылки.add(задача)
                    задача.add_done_callback(_рассылки.discard)

            except Exception as e:
                logger.error(f"Redis message processing error: {e}")

    except asyncio.CancelledError:
        logger.info("Redis subscriber cancelled")
    finally:
        # Закрываем и pubsub, и клиент: клиент здесь свой (не _get_redis),
        # и без aclose каждое переподключение супервизора теряло бы пул
        # соединений. Ошибки глушим — сокет к этому моменту может быть
        # уже мёртв, а падение в finally скрыло бы настоящую причину выхода.
        for закрыть in (pubsub.unsubscribe, pubsub.aclose, r.aclose):
            try:
                await закрыть()
            except Exception:
                pass


#: Подписка, прожившая столько секунд, считается состоявшейся: паузу и признак
#: «об аварии уже сообщили» сбрасываем. Без сброса пауза росла до минуты
#: навсегда — после суток работы следующий короткий обрыв обходился минутой
#: молчания вместо секунды, а второй сбой за неделю не долетал до Sentry вовсе.
_ЖИВАЯ_ПОДПИСКА = 30.0
#: Порог алерта: 1+2+4+8 секунд неудач подряд. Ниже порога — обычный обрыв,
#: который переподключение забирает незаметно (деплой Redis, разрыв TCP), и
#: слать такое в Sentry значит утопить настоящую аварию в шуме.
_ПОРОГ_АЛЕРТА = 16.0


async def supervise_redis_subscriber(bot, первая_пауза: float = 1.0) -> None:
    """Держать подписку живой, переподключаясь с ростом паузы.

    Без присмотра подписка — единственная точка отказа для ВСЕХ уведомлений в
    Telegram. У Redis pubsub нет ни персистентности, ни backpressure: когда
    исходящий буфер подписчика переполняется, Redis сам обрывает соединение,
    `async for` завершается, задача тихо умирает — и мэтчи, сообщения и лайки
    перестают доходить до людей насовсем, без единой строчки в логе.

    Пауза растёт до минуты, чтобы при лежащем Redis не молотить переподключения
    в пустоту. `CancelledError` пропускаем наружу: это штатная остановка бота.

    Затяжная серия неудач уходит в Sentry один раз за аварию: молчащие
    уведомления — отказ, который сам себя не показывает (интерфейс работает,
    просто ничего не приходит), и узнавать о нём из жалоб слишком поздно.
    """
    пауза = первая_пауза
    сообщено = False
    while True:
        начало = time.monotonic()
        try:
            await start_redis_subscriber(bot)
            # Штатного выхода из подписки нет — значит соединение оборвали
            logger.warning("Redis subscriber exited, reconnecting in %.0fs", пауза)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error("Redis subscriber crashed (%s), reconnecting in %.0fs", e, пауза)

        if time.monotonic() - начало >= _ЖИВАЯ_ПОДПИСКА:
            пауза, сообщено = первая_пауза, False
        elif пауза >= _ПОРОГ_АЛЕРТА and not сообщено:
            from services.alerting import capture_message

            capture_message(
                "Redis subscriber не поднимается более "
                f"{int(пауза)}с: уведомления в Telegram (мэтчи, сообщения, "
                "лайки) не доходят до пользователей"
            )
            сообщено = True

        await asyncio.sleep(пауза)
        пауза = min(пауза * 2, 60.0)


async def _notify_user_about_match(bot, user_id: str, match_id: str):
    """Send match notification to Telegram user."""
    try:
        from database import get_user_by_id, get_match_partner

        user = await get_user_by_id(user_id)
        if not user or not user.get("telegram_id"):
            return

        # Слот НЕ тратим (`spend` по умолчанию False): пуш — не открытие мэтча,
        # и суточная квота не должна утекать от прилетевшего события
        partner = await get_match_partner(match_id, user_id)
        if not partner:
            return

        from keyboards import limit_reached_kb
        from texts import match_locked_notification, match_notification
        from config import BANNERS

        if partner.get("locked"):
            # Суточные открытия исчерпаны: про мэтч говорим, кто это — нет.
            # Иначе пуш выдавал бы даром именно то, что скрывает список
            try:
                await bot.send_message(
                    chat_id=user["telegram_id"],
                    text=match_locked_notification(
                        partner["limit"], partner["reset_at"]
                    ),
                    reply_markup=limit_reached_kb("matches:list"),
                )
            except Exception as e:
                logger.warning(
                    "Failed to send locked match notification to %s: %s",
                    user["telegram_id"], e,
                )
            return

        text = match_notification(partner)

        try:
            await bot.send_photo(
                chat_id=user["telegram_id"],
                photo=BANNERS["match"],
                caption=text,
            )
        except Exception as e:
            logger.warning(f"Failed to send match notification to {user['telegram_id']}: {e}")

    except Exception as e:
        logger.error(f"Match notification error: {e}")


async def _notify_user_about_ban(
    bot, user_id: str, reason: str, banned_until: str | None = None
):
    """Сообщить о блокировке в Telegram — с кнопкой досрочной разблокировки.

    Публикует api/services/enforcement.py (автобан за чужие фото) в канал
    dating:bot:events. Без этого уведомления человек узнавал о бане только
    по «сломавшемуся» приложению: экран блокировки в мини-аппе появляется
    лишь при следующем заходе, а бот молчал вовсе.

    ``banned_until`` — ISO-срок из того же события (None — вечный): экран
    бана показывает, когда доступ вернётся сам, а не только платный выход.
    """
    try:
        from config import UNBAN_PRICE_RUB
        from database import get_user_by_id
        from keyboards import unban_kb
        import texts as T

        user = await get_user_by_id(user_id)
        if not user or not user.get("telegram_id"):
            return

        await bot.send_message(
            chat_id=user["telegram_id"],
            text=T.ban_notice(UNBAN_PRICE_RUB, reason, until_iso=banned_until),
            reply_markup=unban_kb(UNBAN_PRICE_RUB),
        )
    except Exception as e:
        logger.error(f"Ban notification error: {e}")


async def _notify_reporter_about_outcome(bot, user_id: str, outcome: str):
    """Сказать жалобщику, чем закончилась его жалоба.

    Публикует api/services/report_notify.py в канал dating:bot:events — при
    автоматической эскалации (скрытие анкеты, автобан) и при решении
    модератора в админке. До этого обещание «модераторы разберутся» не
    закрывалось ничем: человек не узнавал ни про бан нарушителя, ни про отказ,
    и кнопка «Пожаловаться» выглядела декоративной.

    Текст берём у бота, а не у API: коды итогов не знают ни языка, ни разметки
    Telegram, а незнакомый код даёт общий ответ вместо тишины.
    """
    try:
        from database import get_user_by_id
        import texts as T

        user = await get_user_by_id(user_id)
        if not user or not user.get("telegram_id"):
            return

        await bot.send_message(
            chat_id=user["telegram_id"],
            text=T.report_outcome(outcome),
        )
    except Exception as e:
        # Итог жалобы не доставлен — модерация уже применена, ретраить нечего
        logger.error(f"Report outcome notification error: {e}")


async def _notify_user_about_message(bot, receiver_id: str, sender_id: str, text: str):
    """Уведомить в Telegram о новом сообщении из web-чата."""
    try:
        from database import get_user_by_id, get_profile

        receiver = await get_user_by_id(receiver_id)
        if not receiver or not receiver.get("telegram_id"):
            return

        import html as _html

        sender = await get_profile(sender_id)
        sender_name = _html.escape((sender or {}).get("display_name") or "Ваш мэтч", quote=False)

        preview = (text[:100] + "…") if len(text) > 100 else text
        preview = _html.escape(preview, quote=False)
        await bot.send_message(
            chat_id=receiver["telegram_id"],
            text=f"💬 <b>{sender_name}</b> написал(а) вам:\n\n«{preview}»\n\n"
                 f"Откройте «💕 Мои мэтчи», чтобы ответить.",
        )
    except Exception as e:
        logger.error(f"Message notification error: {e}")


async def _notify_user_about_like(bot, receiver_id: str, liker_id: str):
    """Уведомить в Telegram о новом лайке из web-приложения (Дайвинчик-механика).

    Анкету лайкнувшего показываем только на Plus: «кто вас лайкнул» — платный
    гейт, и в мини-аппе он соблюдается. Этот путь — второй из пары (первый в
    handlers/dating.py), и раньше он тоже отдавал анкету бесплатно.
    """
    try:
        from database import get_user_by_id, get_profile
        from services.plans import видно_кто_лайкнул

        receiver = await get_user_by_id(receiver_id)
        if not receiver or not receiver.get("telegram_id"):
            return

        liker = await get_profile(liker_id)
        if not liker or not liker.get("display_name"):
            return

        if not await видно_кто_лайкнул(receiver_id):
            from keyboards import like_locked_kb
            import texts as T

            await bot.send_message(
                chat_id=receiver["telegram_id"],
                text=T.LIKE_LOCKED,
                reply_markup=like_locked_kb(),
            )
            return

        from handlers.dating import _render_profile_to_chat

        await bot.send_message(
            chat_id=receiver["telegram_id"],
            text="💌 Вы кому-то понравились! Взгляните на анкету:",
        )
        await _render_profile_to_chat(bot, receiver["telegram_id"], liker)
    except Exception as e:
        logger.error(f"Like notification error: {e}")
