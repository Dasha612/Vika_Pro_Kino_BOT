import asyncio
import logging

from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.storage.redis import RedisStorage

from config import cfg, setup_logging
from middlewares.db import DataBaseSession, CheckUserSubscription
from handlers.anketa import anketa_router
from handlers.recommendations import recommendations_router
from handlers.favourites import favourites_router
from database.engine import create_db, session_maker
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
    await create_db()
    logger.info("БД инициализирована, загружаю модель эмбеддингов...")
    await asyncio.to_thread(get_model)
    await start_health_server()
    bot_info = await bot.get_me()
    logger.info("Бот @%s (id=%s) полностью готов к работе", bot_info.username, bot_info.id)


async def on_shutdown(bot: Bot):
    logger.info("=== Бот останавливается ===")
    await storage.close()


async def main():
    setup_logging()

    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)

    dp.update.middleware(DataBaseSession(session_pool=session_maker))
    dp.update.middleware(CheckUserSubscription(bot=bot))

    await bot.delete_webhook(drop_pending_updates=True)

    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
