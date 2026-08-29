import logging
from aiogram import BaseMiddleware, Bot
from aiogram.types import TelegramObject, Update
from sqlalchemy.ext.asyncio import async_sessionmaker
from typing import Any, Awaitable, Callable, Dict

from config import cfg
from database.orm_query import add_user
from kbds.inline import subscribe_button

logger = logging.getLogger(__name__)


def extract_user_id(event: TelegramObject) -> int | None:
    if isinstance(event, Update):
        if event.message:
            return event.message.from_user.id
        if event.callback_query:
            return event.callback_query.from_user.id
    return None


class DataBaseSession(BaseMiddleware):
    def __init__(self, session_pool: async_sessionmaker):
        self.session_pool = session_pool

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        async with self.session_pool() as session:
            data["session"] = session

            # Регистрируем на любом входе, а не только на /start: иначе клик по кнопке
            # в старом сообщении падал бы по внешнему ключу на users_anketa / users_interaction.
            user_id = extract_user_id(event)
            if user_id is not None:
                await add_user(user_id, session)

            try:
                return await handler(event, data)
            except Exception as e:
                logger.error("Ошибка при обработке update: %s", e, exc_info=True)
                raise


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
        if event.message:
            user_id = event.message.from_user.id
            reply_method = event.message.answer
            logger.debug("[Middleware] Входящее сообщение от user_id=%s: %s", user_id, event.message.text)
        elif event.callback_query:
            user_id = event.callback_query.from_user.id
            reply_method = event.callback_query.message.answer
            logger.debug("[Middleware] Callback от user_id=%s: %s", user_id, event.callback_query.data)
        else:
            return await handler(event, data)

        if not cfg.chat_id:
            return await handler(event, data)

        try:
            member = await self.bot.get_chat_member(
                chat_id=cfg.full_chat_id, user_id=user_id
            )
            if member.status in ("left", "kicked", "banned"):
                await reply_method(
                    'Для использования бота необходимо подписаться на канал "Вика про кино"',
                    reply_markup=subscribe_button,
                )
                return
        except Exception as e:
            logger.warning("Ошибка при проверке подписки user_id=%s: %s", user_id, e)

        return await handler(event, data)
