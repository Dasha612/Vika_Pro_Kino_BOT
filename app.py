import asyncio
import os
from aiogram import Bot, Dispatcher, types
from dotenv import find_dotenv, load_dotenv
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
load_dotenv(find_dotenv())

from middlewares.db import DataBaseSesssion, CheckUserSubscription
from handlers.anketa import anketa_router
from database.engine import create_db, drop_db, session_maker



ALLOWED_UPDATES = ['message', 'edited_message', 'callback_query']

bot  = Bot(token=os.getenv('TOKEN'), default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()


dp.include_router(anketa_router)

async def on_startup(bot: Bot, dispatcher: Dispatcher):
    run_param = False
    if run_param:
        await drop_db()
    else:
        await create_db()

async def on_shutdown(bot: Bot, dispatcher: Dispatcher):
    print('Бот лег...')


async def main():
    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)

    dp.update.middleware(DataBaseSesssion(session_pool=session_maker))

    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())

asyncio.run(main())
