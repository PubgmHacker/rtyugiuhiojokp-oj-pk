from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.filters import Command, StateFilter
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.storage.redis import RedisStorage
from aiogram.client.default import DefaultBotProperties
from aiogram.types import BotCommand, ErrorEvent, MenuButtonWebApp, WebAppInfo
from aiohttp import web

from config import BOT_TOKEN, BOT_USERNAME, ADMIN_IDS, WEBHOOK_PORT, REDIS_URL, SENTRY_DSN, SITE_URL, webapp_https, mini_app_url
from database import init_db, get_or_create_user, get_profile, record_referral, get_user_by_id
from handlers import registration, dating, matches, premium, referral, account, onboarding, unban
from handlers.onboarding import send_language_picker
from keyboards import main_kb
from middlewares.ban_gate import BanGateMiddleware
from middlewares.registration import RegistrationMiddleware
from middlewares.throttle import ThrottleMiddleware
from services.redis_subscriber import close_redis, supervise_redis_subscriber
import texts as T

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

#: Список команд в интерфейсе Telegram — единственная витрина, по которой человек
#: узнаёт, что бот умеет: меню «/» в поле ввода собирается ровно из него.
#: Незаявленная команда существует только для тех, кому её назвали словами, а
#: заявленная без обработчика молча ничего не делает. Список сверяется с
#: настоящим `Dispatcher` и с текстом `/help` (api/tests/test_bot_commands.py):
#: разъехаться этим трём местам нельзя незаметно.
КОМАНДЫ: list[BotCommand] = [
    BotCommand(command="start", description="Запустить бота"),
    BotCommand(command="menu", description="Главное меню"),
    BotCommand(command="profile", description="Моя анкета"),
    BotCommand(command="premium", description="Premium-подписка"),
    BotCommand(command="invite", description="Пригласить друзей"),
    BotCommand(command="link", description="Код для входа в приложение"),
    BotCommand(command="pause", description="Скрыть анкету из поиска"),
    BotCommand(command="resume", description="Вернуть анкету в поиск"),
    BotCommand(command="cancel", description="Отменить текущее действие"),
    BotCommand(command="delete", description="Удалить аккаунт"),
    BotCommand(command="help", description="Помощь"),
]


async def cmd_start(message, state):
    """Обработчик /start — язык, политика, рассылки (как у Mimolet).

    Тому, кто уже прошёл онбординг и заполнил анкету, /start отдаёт меню, а не
    спрашивает язык заново. Иначе самая частая команда в Telegram превращалась в
    повторный опрос: язык → политика → «Начать», четыре сообщения ради того, что
    человек хотел сделать одним нажатием. У Mimolet выбор языка тоже разовый.
    """
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

    await _ensure_dating_menu(message.bot, chat_id=message.chat.id)

    # Анкета готова — человек здесь не впервые. Сбой чтения профиля не должен
    # стоить ему входа: онбординг проходится и повторно, а пустой ответ на
    # /start не оставляет вообще ничего.
    try:
        profile = await get_profile(db_user["id"])
    except Exception as e:
        logger.warning("не прочитали профиль для /start: %s", e)
        profile = None
    if profile and profile.get("display_name") and profile.get("photos"):
        await message.answer(T.menu_text(is_ready=True), reply_markup=main_kb())
        return

    await send_language_picker(message, state)


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


async def _ensure_dating_menu(bot: Bot, chat_id: int | None = None) -> None:
    """Кнопка меню Telegram «Dating» — открывает Mini App, как у Mimolet.

    Без HTTPS Bot API отклоняет MenuButtonWebApp: локальный http://localhost
    кнопку не поставит, и это не молчаливый успех.
    """
    if not webapp_https():
        logger.warning(
            "SITE_URL=%s is not HTTPS — Dating menu button skipped", SITE_URL
        )
        return
    try:
        await bot.set_chat_menu_button(
            chat_id=chat_id,
            menu_button=MenuButtonWebApp(
                text="Dating",
                web_app=WebAppInfo(url=mini_app_url()),
            ),
        )
    except Exception as e:
        logger.warning("Failed to set Dating menu button: %s", e)


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

    # В Sentry уходит то же исключение, что в лог. Логи Railway эфемерны и
    # никто не смотрит их в реальном времени, а упавший обработчик — это
    # человек, который получил «что-то пошло не так» вместо ответа. Теги
    # (кто, какой апдейт, какая кнопка) отличают такие события друг от
    # друга: без них всё сваливается в одну неразличимую группу.
    # Без SENTRY_DSN — no-op (см. services/alerting.py).
    from services.alerting import capture_exception

    нажатие = getattr(update, "callback_query", None)
    capture_exception(
        event.exception,
        update_id=getattr(update, "update_id", None),
        telegram_id=getattr(getattr(target, "from_user", None), "id", None),
        callback_data=getattr(нажатие, "data", None),
    )

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
        "service": "simp-dating-bot",
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


def собрать_dispatcher(storage) -> Dispatcher:
    """Готовый `Dispatcher`: мидлвари, обработчик ошибок, роутеры по порядку.

    Отдельной функцией, чтобы тесты собирали ровно то, что работает в проде.
    Копия этой сборки в тестах разъехалась бы с продакшеном молча, а порядок
    здесь существенный: `account` перехватывает /menu, /cancel и /delete раньше
    шагов анкеты, а заглушка устаревших тапов живёт в первом роутере.
    """
    dp = Dispatcher(storage=storage)

    # Троттлинг стоит первым: отсекает флуд до любой работы с БД
    dp.message.outer_middleware(ThrottleMiddleware())
    dp.callback_query.outer_middleware(ThrottleMiddleware())
    dp.message.outer_middleware(RegistrationMiddleware())
    dp.callback_query.outer_middleware(RegistrationMiddleware())
    # Бан-гейт — сразу после регистрации: она кладёт db_user в data, по нему
    # гейт и решает. pre_checkout_query не оборачиваем — оплата разблокировки
    # должна подтверждаться (см. middlewares/ban_gate.py)
    dp.message.outer_middleware(BanGateMiddleware())
    dp.callback_query.outer_middleware(BanGateMiddleware())

    # Ошибка в одном обработчике не должна оставлять человека без ответа
    dp.errors.register(on_error)

    # /start работает из любого состояния FSM, иначе можно застрять
    dp.message.register(cmd_start, StateFilter("*"), Command("start"))
    # account держим до остальных роутеров: его команды (/menu, /cancel,
    # /delete) должны перехватываться раньше шагов анкеты
    dp.include_router(onboarding.router)
    dp.include_router(account.router)
    dp.include_router(premium.router)
    dp.include_router(unban.router)
    dp.include_router(referral.router)
    dp.include_router(registration.router)
    dp.include_router(dating.router)
    dp.include_router(matches.router)
    return dp


async def main():
    """Точка входа."""
    # Алертинг — первым делом, до любой работы: падение на инициализации БД
    # или на set_my_commands тоже должно доходить до Sentry, а не только в
    # эфемерный лог. Без SENTRY_DSN — no-op (см. services/alerting.py).
    from services.alerting import init as init_alerting

    init_alerting(SENTRY_DSN)
    if not SENTRY_DSN:
        logger.warning("SENTRY_DSN пуст: об ошибках бота никто не узнает первым")

    if not BOT_TOKEN:
        logger.error("BOT_TOKEN not set!")
        return

    # Init DB
    await init_db()
    logger.info("Database initialized")

    # Bot setup
    storage = await get_fsm_storage()
    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
    dp = собрать_dispatcher(storage)

    # Set bot commands
    await bot.set_my_commands(КОМАНДЫ)
    await _ensure_dating_menu(bot)
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
    logger.info(f"Simp Dating Bot @{BOT_USERNAME} started!")
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
