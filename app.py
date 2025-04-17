import asyncio
import os
from aiogram import Bot, Dispatcher, types
from dotenv import find_dotenv, load_dotenv
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
load_dotenv(find_dotenv())

from middlewares.db import DataBaseSesssion, CheckUserSubscription
from handlers.anketa import anketa_router
from handlers.recommendations import recommendations_router
from database.engine import create_db, drop_db, session_maker
from handlers.favourites import favourites_router




ALLOWED_UPDATES = ['message', 'edited_message', 'callback_query']

bot  = Bot(token=os.getenv('TOKEN'), default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()






dp.include_router(anketa_router)
dp.include_router(recommendations_router)
dp.include_router(favourites_router)

async def on_startup(bot: Bot, dispatcher: Dispatcher):
    run_param = False
    if run_param:
        await drop_db()
    await create_db()

async def on_shutdown(bot: Bot, dispatcher: Dispatcher):
    print('Бот лег...')


async def main():
    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)

    dp.update.middleware(DataBaseSesssion(session_pool=session_maker))
    dp.update.middleware(CheckUserSubscription(bot=bot))

    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())

asyncio.run(main())
