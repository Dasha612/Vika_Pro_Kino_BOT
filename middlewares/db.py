from aiogram import BaseMiddleware, Bot
from aiogram.types import TelegramObject, Message, CallbackQuery, Update
from sqlalchemy.ext.asyncio import async_sessionmaker
from typing import Any, Awaitable, Callable, Dict
import os
from kbds.inline import get_callback_btns, subscribe_button
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)    



class DataBaseSesssion(BaseMiddleware):
    def __init__(self, session_pool: async_sessionmaker):
        self.session_pool = session_pool

    async def __call__(
            self, 
            handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]], 
            event: TelegramObject, 
            data: Dict[str, Any],
    ) -> Any:
        async with self.session_pool() as session:
            data['session'] = session
            return await handler(event, data)


class CheckUserSubscription(BaseMiddleware):
    def __init__(self, bot: Bot):
        self.bot = bot
        super().__init__()

    async def __call__(
            self, 
            handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]], 
            event: Update, 
            data: Dict[str, Any],
    ) -> Any:
        # Определяем тип события и получаем user_id
        if event.message:
            user_id = event.message.from_user.id
            reply_method = event.message.answer
        elif event.callback_query:
            user_id = event.callback_query.from_user.id
            reply_method = event.callback_query.message.answer
        else:
            # Если это другой тип события, пропускаем проверку
            return await handler(event, data)

        try:
            chat_id = '-100' + os.getenv("TEST_CHAT_ID")
            member = await self.bot.get_chat_member(chat_id=chat_id, user_id=user_id)
            logger.info(f"Проверка подписки для пользователя {user_id}: {member.status}")
            if member.status in ['left', 'kicked', 'banned']:
                await reply_method(
                    'Для использования бота необходимо подписаться на канал Вика про кино',
                    reply_markup=subscribe_button
                )
                return  # Прерываем выполнение хэндлера
            

            # Если пользователь подписан, продолжаем выполнение
            return await handler(event, data)
            
        except Exception as e:
            print(f"Ошибка при проверке подписки: {e}")
            return await handler(event, data)
