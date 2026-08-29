import logging
from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Update
from redis.asyncio import Redis

from middlewares.db import extract_user_id

logger = logging.getLogger(__name__)

# Обычное действие: показ карточки — это запрос к БД, а «Свой запрос» ещё и
# model.encode. Полсекунды между нажатиями человек не замечает, а зажатую
# кнопку это гасит.
DEFAULT_RATE_MS = 500

# Переключение галочек в анкете — дешёвая операция, и по замыслу его жмут
# быстро, несколько подряд. Полсекунды здесь ощущались бы как залипание,
# поэтому окно короче: оно ловит только автоповтор, а не живые тапы.
FAST_RATE_MS = 150
FAST_PREFIXES = ("select:", "done:")


class ThrottlingMiddleware(BaseMiddleware):
    """Не больше одного действия в окно на пользователя.

    Работает на SET NX PX: атомарная операция на стороне Redis, поэтому
    два апдейта, пришедшие одновременно, не смогут оба получить разрешение.
    """

    def __init__(self, redis: Redis, rate_ms: int = DEFAULT_RATE_MS):
        self.redis = redis
        self.rate_ms = rate_ms
        super().__init__()

    def _window_for(self, event: Update) -> int:
        if event.callback_query and (event.callback_query.data or "").startswith(FAST_PREFIXES):
            return FAST_RATE_MS
        return self.rate_ms

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        if not isinstance(event, Update):
            return await handler(event, data)

        # Команды пропускаем всегда: /reset — аварийный выход из залипшего
        # состояния, и он не должен упираться в тот же лимит, что и всё остальное.
        if event.message and (event.message.text or "").startswith("/"):
            return await handler(event, data)

        user_id = extract_user_id(event)
        if user_id is None:
            return await handler(event, data)

        try:
            allowed = await self.redis.set(
                f"throttle:{user_id}", 1, px=self._window_for(event), nx=True
            )
        except Exception as e:
            # Redis лежит — это не повод не пускать пользователей в бота.
            logger.warning("[Throttle] Redis недоступен, пропускаю без лимита: %s", e)
            return await handler(event, data)

        if allowed:
            return await handler(event, data)

        logger.debug("[Throttle] user_id=%s — слишком часто, апдейт отброшен", user_id)
        if event.callback_query:
            # Без ответа на callback у юзера навсегда повиснет спиннер на кнопке.
            try:
                await event.callback_query.answer("Не так быстро :)")
            except Exception:
                pass
        return None
