from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.storage.redis import RedisStorage
from aiogram.client.default import DefaultBotProperties
from aiohttp import web

from config import BOT_TOKEN, BOT_USERNAME, ADMIN_IDS, WEBHOOK_PORT, BANNERS, REDIS_URL
from database import init_db, get_or_create_user
from handlers import registration, dating, matches, premium
from keyboards import main_kb
from middlewares.registration import RegistrationMiddleware
from services.redis_subscriber import start_redis_subscriber
from texts import welcome

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def cmd_start(message, state):
    """Обработчик /start — главное меню (+ deep-link аргументы)."""
    await state.clear()

    db_user = await get_or_create_user(
        message.from_user.id,
        message.from_user.username or "",
        message.from_user.first_name or "",
    )

    # Deep-link: t.me/<bot>?start=premium (кнопка Premium из веба)
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) > 1 and parts[1].strip() == "premium":
        from handlers.premium import PREMIUM_PITCH, send_premium_offer
        await message.answer(PREMIUM_PITCH)
        await send_premium_offer(message, db_user["id"])
        return

    await message.answer_photo(
        photo=BANNERS["welcome"],
        caption=welcome(message.from_user.first_name),
        reply_markup=main_kb(),
    )


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


def get_fsm_storage():
    """Redis-backed FSM storage для продакшена, MemoryStorage fallback."""
    try:
        storage = RedisStorage.from_url(REDIS_URL)
        logger.info("Using Redis FSM storage")
        return storage
    except Exception as e:
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
    storage = get_fsm_storage()
    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
    dp = Dispatcher(storage=storage)

    # Middleware
    dp.message.outer_middleware(RegistrationMiddleware())
    dp.callback_query.outer_middleware(RegistrationMiddleware())

    # Handlers
    dp.message.register(
        cmd_start,
        lambda m: bool(m.text) and (m.text.startswith("/start") or m.text == "/help"),
    )
    dp.include_router(premium.router)
    dp.include_router(registration.router)
    dp.include_router(dating.router)
    dp.include_router(matches.router)

    # Set bot commands
    await bot.set_my_commands([
        {"command": "start", "description": "Главное меню"},
        {"command": "premium", "description": "⭐ Premium-подписка"},
        {"command": "help", "description": "Помощь"},
    ])
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

    # Start Redis subscriber (для real-time мэтч-уведомлений)
    redis_task = asyncio.create_task(start_redis_subscriber(bot))

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
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
