from aiogram import Router, Bot
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession
from aiogram import F
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
import logging

from database.orm_query import get_movies_by_interaction, check_recommendations_status
from handlers.anketa import Anketa
from kbds.inline import get_callback_btns
from chat_gpt.ai import get_movie_recommendation_by_preferences
from kinopoisk_imdb.search import get_movies, extract_movie_data
recommendations_router = Router()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class Reccomendations(StatesGroup):
    send_movies = State()


@recommendations_router.callback_query(F.data  == 'recommendations')
async def recommendations(callback: CallbackQuery, session: AsyncSession, bot: Bot):
    await bot.delete_message(chat_id=callback.message.chat.id, message_id=callback.message.message_id)
    await callback.message.answer('Рекомендации')

    user_id = callback.from_user.id
    unwatched_movies = await get_movies_by_interaction(user_id, session, interaction_type='unwatched')
    recommendations_status = await check_recommendations_status(user_id, session)

    if not recommendations_status:
        await callback.message.answer(
            "Прежде чем порекомендовать тебе фильм, мне нужно узнать о тебе больше информации.\n"
            "Сейчас я задам тебе 7 вопросов, а тебе нужно будет на них ответить. Чем развёрнутее будут "
            "твои ответы, тем лучше я смогу настроить свой рекомендательный алгоритм.\nПриступим?",
            reply_markup= get_callback_btns(btns={
                "Давай" : "set_profile",
            })
        )
        return
    chat_gpt_response = await get_movie_recommendation_by_preferences(user_id, session)
    movies_data = await get_movies(chat_gpt_response, user_id)
    movies = await extract_movie_data(movies_data)
    logger.info(f"Фильмы для отправки: {movies}")
    #НУЖНО ОТПРАВИТЬ ФИЛЬМЫ



    await callback.answer()



