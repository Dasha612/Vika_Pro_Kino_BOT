import asyncio
import logging

from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.storage.redis import RedisStorage
from aiogram.types import ErrorEvent

from config import cfg, setup_logging
from middlewares.db import DataBaseSession, CheckUserSubscription
from middlewares.throttling import ThrottlingMiddleware
from handlers.anketa import anketa_router
from handlers.recommendations import recommendations_router
from handlers.favourites import favourites_router
from database.engine import engine, session_maker, redis_client
from database.migrate import run_migrations
from database.embedding import get_model

logger = logging.getLogger(__name__)

bot = Bot(
    token=cfg.bot_token,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML),
)

storage = RedisStorage.from_url(cfg.redis_url)
dp = Dispatcher(storage=storage)

dp.include_router(anketa_router)
dp.include_router(recommendations_router)
dp.include_router(favourites_router)


@dp.errors()
async def on_error(event: ErrorEvent) -> bool:
    """Последний рубеж: без него исключение уходит в лог, а пользователь видит тишину."""
    logger.exception("Необработанная ошибка на апдейте: %s", event.update)

    upd = event.update
    target = upd.message or (upd.callback_query.message if upd.callback_query else None)
    if target:
        try:
            await target.answer("Что-то пошло не так. Наберите /reset, чтобы продолжить.")
        except Exception:
            pass
    return True


async def health_handler(request: web.Request) -> web.Response:
    return web.json_response({"status": "ok"})


async def start_health_server():
    app = web.Application()
    app.router.add_get("/health", health_handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", 8080)
    await site.start()
    logger.info("Health-check сервер запущен на :8080/health")


async def on_startup(bot: Bot):
    logger.info("=== Запуск бота ===")
    # Схема теперь приводится миграциями, а не create_all: только так изменения
    # вроде uq_user_movie доезжают до уже существующей базы.
    await run_migrations()
    logger.info("БД инициализирована, загружаю модель эмбеддингов...")
    await asyncio.to_thread(get_model)
    await start_health_server()
    bot_info = await bot.get_me()
    logger.info("Бот @%s (id=%s) полностью готов к работе", bot_info.username, bot_info.id)


async def on_shutdown(bot: Bot):
    logger.info("=== Бот останавливается ===")
    await storage.close()
    # Redis теперь держит ещё и ключи throttling, а engine — пул на 10 соединений:
    # без явного закрытия Postgres увидит оборванные сессии, а asyncio на выходе
    # напишет 'Unclosed connection'.
    await redis_client.aclose()
    await engine.dispose()


async def main():
    setup_logging()

    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)

    # Порядок = порядок выполнения. Throttling первым: отброшенный апдейт не должен
    # успеть ни открыть сессию к БД, ни сходить в Telegram за проверкой подписки.
    dp.update.middleware(ThrottlingMiddleware(redis=redis_client))
    dp.update.middleware(DataBaseSession(session_pool=session_maker))
    dp.update.middleware(CheckUserSubscription(bot=bot))

    await bot.delete_webhook(drop_pending_updates=True)

    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
