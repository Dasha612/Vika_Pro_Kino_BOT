from aiogram import BaseMiddleware, Bot
from aiogram.types import TelegramObject, Message, CallbackQuery
from sqlalchemy.ext.asyncio import async_sessionmaker
from typing import Any, Awaitable, Callable, Dict
import os

from kbds import get_callback_btns




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
            event: Message | CallbackQuery, 
            data: Dict[str, Any],
    ) -> Any:
        # Получаем user_id в зависимости от типа события
        if isinstance(event, Message):
            user_id = event.from_user.id
            reply_method = event.answer
        else:  # CallbackQuery
            user_id = event.from_user.id
            reply_method = event.message.answer

        try:
            chat_id = '-100' + os.getenv("TEST_CHAT_ID")
            member = await self.bot.get_chat_member(chat_id=chat_id, user_id=user_id)
            
            if member.status in ['left', 'kicked', 'banned']:
                await reply_method(
                    'Для использования бота необходимо подписаться на канал Вика про кино',
                    reply_markup=get_callback_btns(
                        btns={
                            "Подписаться": "subscribe",
                            "Проверить подписку": "check_subscription"
                        }
                    )
                )
                return  # Прерываем выполнение хэндлера
            
            # Если пользователь подписан, продолжаем выполнение
            return await handler(event, data)
            
        except Exception as e:
            print(f"Ошибка при проверке подписки: {e}")
            # В случае ошибки пропускаем проверку
            return await handler(event, data)
