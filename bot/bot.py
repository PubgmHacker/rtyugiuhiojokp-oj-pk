from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.filters import Command, StateFilter
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.storage.redis import RedisStorage
from aiogram.client.default import DefaultBotProperties
from aiogram.types import BotCommand, ErrorEvent
from aiohttp import web

from config import BOT_TOKEN, BOT_USERNAME, ADMIN_IDS, WEBHOOK_PORT, BANNERS, REDIS_URL
from database import init_db, get_or_create_user, record_referral, get_user_by_id
from handlers import registration, dating, matches, premium, referral, account
from keyboards import main_kb
from middlewares.registration import RegistrationMiddleware
from middlewares.throttle import ThrottleMiddleware
from services.redis_subscriber import close_redis, supervise_redis_subscriber
import texts as T
from texts import welcome

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def cmd_start(message, state):
    """Обработчик /start — приветствие и главное меню (+ deep-link аргументы)."""
    await state.clear()

    db_user = await get_or_create_user(
        message.from_user.id,
        message.from_user.username or "",
        message.from_user.first_name or "",
    )

    # Deep-links: t.me/<bot>?start=premium | ?start=ref_<user_id>
    parts = (message.text or "").split(maxsplit=1)
    arg = parts[1].strip() if len(parts) > 1 else ""

    if arg == "premium":
        from handlers.premium import PREMIUM_PITCH, send_premium_offer
        await message.answer(PREMIUM_PITCH)
        await send_premium_offer(message, db_user["id"])
        return

    if arg.startswith("ref_"):
        await _handle_referral(message, db_user, arg[4:])

    await message.answer_photo(
        photo=BANNERS["welcome"],
        caption=welcome(message.from_user.first_name),
        reply_markup=main_kb(),
    )


async def _handle_referral(message, db_user: dict, referrer_id: str):
    """Засчитать приглашение и уведомить пригласившего."""
    from config import REFERRAL_MIN_INVITES, REFERRAL_BOOST_PERCENT

    try:
        result = await record_referral(referrer_id.strip()[:64], db_user["id"])
        if not result["counted"]:
            return

        referrer = await get_user_by_id(referrer_id)
        if not referrer or not referrer.get("telegram_id"):
            return

        total = result["total"]
        if total >= REFERRAL_MIN_INVITES:
            text = (
                f"🎉 Друг присоединился ({total}/{REFERRAL_MIN_INVITES})!\n\n"
                f"🚀 <b>Буст активирован</b> — ваша анкета теперь показывается "
                f"на {REFERRAL_BOOST_PERCENT}% выше в выдаче."
            )
        else:
            text = (
                f"🎉 По вашей ссылке пришёл друг! Прогресс: "
                f"<b>{total}/{REFERRAL_MIN_INVITES}</b> до буста анкеты "
                f"+{REFERRAL_BOOST_PERCENT}%."
            )
        await message.bot.send_message(chat_id=referrer["telegram_id"], text=text)
    except Exception as e:
        logger.warning(f"Referral processing error: {e}")


async def on_error(event: ErrorEvent) -> bool:
    """Глобальный обработчик ошибок.

    Без него исключение в обработчике оставляет человека без ответа —
    выглядит как «бот сломался и молчит».
    """
    logger.exception(f"Необработанная ошибка: {event.exception}")

    update = event.update
    target = None
    if getattr(update, "message", None):
        target = update.message
    elif getattr(update, "callback_query", None):
        cb = update.callback_query
        try:
            await cb.answer()
        except Exception:
            pass
        target = cb.message

    if target is not None:
        try:
            await target.answer(T.ERROR_GENERIC)
        except Exception:
            pass
    return True


async def health_handler(request):
    """HTTP health endpoint for Railway."""
    return web.json_response({
        "status": "ok",
        "service": "souldawn-dating-bot",
        "username": BOT_USERNAME,
    })


async def start_health_server():
    """Запустить aiohttp health сервер."""
    app = web.Application()
    app.router.add_get("/health", health_handler)
    app.router.add_get("/", health_handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", WEBHOOK_PORT)
    await site.start()
    logger.info(f"Health server running on :{WEBHOOK_PORT}")


async def get_fsm_storage():
    """Redis-backed FSM storage для продакшена, MemoryStorage fallback.

    `RedisStorage.from_url` только собирает пул соединений и ничего не
    проверяет — соединение ленивое. Поэтому раньше except не срабатывал
    никогда: при неверном REDIS_URL бот молча выбирал Redis, а падало уже
    внутри хендлеров, на первом же шаге анкеты, и человек застревал в
    бесконечной «что-то пошло не так». Проверяем доступность явным ping.
    """
    try:
        storage = RedisStorage.from_url(REDIS_URL)
        await asyncio.wait_for(storage.redis.ping(), timeout=5)
        logger.info("Using Redis FSM storage")
        return storage
    except Exception as e:
        # MemoryStorage теряет состояние при рестарте, но регистрация
        # работает — это лучше, чем нерабочий бот
        logger.warning(f"Redis unavailable, using MemoryStorage: {e}")
        return MemoryStorage()


async def main():
    """Точка входа."""
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN not set!")
        return

    # Init DB
    await init_db()
    logger.info("Database initialized")

    # Bot setup
    storage = await get_fsm_storage()
    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
    dp = Dispatcher(storage=storage)

    # Middleware
    # Троттлинг стоит первым: отсекает флуд до любой работы с БД
    dp.message.outer_middleware(ThrottleMiddleware())
    dp.callback_query.outer_middleware(ThrottleMiddleware())
    dp.message.outer_middleware(RegistrationMiddleware())
    dp.callback_query.outer_middleware(RegistrationMiddleware())

    # Ошибка в одном обработчике не должна оставлять человека без ответа
    dp.errors.register(on_error)

    # Handlers
    # /start работает из любого состояния FSM, иначе можно застрять
    dp.message.register(cmd_start, StateFilter("*"), Command("start"))
    # account держим до остальных роутеров: его команды (/menu, /cancel,
    # /delete) должны перехватываться раньше шагов анкеты
    dp.include_router(account.router)
    dp.include_router(premium.router)
    dp.include_router(referral.router)
    dp.include_router(registration.router)
    dp.include_router(dating.router)
    dp.include_router(matches.router)

    # Set bot commands
    await bot.set_my_commands(
        [
            BotCommand(command="start", description="Главное меню"),
            BotCommand(command="profile", description="Моя анкета"),
            BotCommand(command="premium", description="Premium-подписка"),
            BotCommand(command="invite", description="Пригласить друзей"),
            BotCommand(command="link", description="Код для входа в приложение"),
            BotCommand(command="pause", description="Скрыть анкету из поиска"),
            BotCommand(command="resume", description="Вернуть анкету в поиск"),
            BotCommand(command="delete", description="Удалить аккаунт"),
            BotCommand(command="help", description="Помощь"),
        ]
    )
    if ADMIN_IDS:
        for admin_id in ADMIN_IDS:
            try:
                await bot.set_my_commands(
                    [{"command": "start", "description": "Меню (админ)"}],
                    scope={"type": "chat", "chat_id": admin_id},
                )
            except Exception:
                pass

    # Start health server
    await start_health_server()

    # Start Redis subscriber (для real-time мэтч-уведомлений).
    # Под присмотром: обрыв подписки Redis'ом раньше означал, что уведомления
    # в Telegram останавливались до перезапуска бота, и молча.
    redis_task = asyncio.create_task(supervise_redis_subscriber(bot))

    # Start polling
    logger.info(f"Souldawn Dating Bot @{BOT_USERNAME} started!")
    try:
        # pre_checkout_query обязателен для платежей Telegram Stars
        await dp.start_polling(
            bot,
            allowed_updates=["message", "callback_query", "pre_checkout_query"],
        )
    finally:
        redis_task.cancel()
        await close_redis()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
