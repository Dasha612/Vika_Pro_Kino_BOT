from aiogram import Router, Bot, types
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession
from aiogram import F
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
import logging
from handlers.callback_data import Menu_Callback
import os

from database.orm_query import add_movies_by_interaction, get_movies_by_interaction, check_recommendations_status, delete_movies_by_interaction
from kbds.inline import get_callback_btns, subscribe_button, rate_buttons
from chat_gpt.ai import get_movie_recommendation_by_preferences
from kinopoisk_imdb.search import get_movies, extract_movie_data
from kbds.pagination import create_movie_carousel_keyboard
from handlers.movie_utils import send_movie_card
recommendations_router = Router()


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class Recomendations(StatesGroup):
    waiting_for_action = State()  # Состояние, когда пользователь выбирает действие
    processing = State()          # Состояние, когда выполняется какое-либо действие





@recommendations_router.callback_query(F.data == 'recommendations')
async def send_recommendations(callback: CallbackQuery, session: AsyncSession, bot: Bot, state: FSMContext):
    current_state = await state.get_state()
    logger.info(f"STATE: {current_state}\n")

    user_id = callback.from_user.id
    logger.info(f"Запрос рекомендаций от пользователя {user_id}")

    recommendations_status = await check_recommendations_status(user_id, session)
    if not recommendations_status:
        await callback.message.answer(
            "Прежде чем порекомендовать тебе фильм, мне нужно узнать о тебе больше информации. Давай заполним анкету?",
            reply_markup=get_callback_btns(btns={"Давай": "set_profile"})
        )
        return
    
    unwatched_movies  = await get_movies_by_interaction(user_id, session,['unwatched'])

    if unwatched_movies:
        # Если есть непросмотренные фильмы, показываем их
        logger.info("_" * 100)
        logger.info(f"Отправка непросмотренных фильмов пользователю {user_id}, {unwatched_movies}")
        logger.info("_" * 100)
  
        
        # Отправляем первый непросмотренный фильм
        message = await send_movie_card(callback.message, unwatched_movies[0], 0, custom_keyboard=create_movie_carousel_keyboard)
        
        # Сохраняем список фильмов, текущий индекс и ID сообщения в состояние
        await state.set_state(Recomendations.waiting_for_action)
        await state.update_data(
            movies=unwatched_movies, 
            current_index=0,
            message_id=message.message_id,
            chat_id=message.chat.id
        )
        await delete_movies_by_interaction(user_id, session, ['unwatched'])

    else:
    # Получаем список фильмов
        max_retries = 3
        retries = 0
        movies = []

        while not movies and retries < max_retries:
            chat_gpt_response = await get_movie_recommendation_by_preferences(user_id, session)
            movies_data = await get_movies(chat_gpt_response, user_id, session)
            movies = await extract_movie_data(movies_data)

            logger.info("_" * 100)
            logger.info(f"Отправка фильмов пользователю из функции extract_movie_data: {movies}")
            logger.info("_" * 100)

            retries += 1
        if retries >= max_retries: callback.message.answer('Кажется, произошла ошибка или прогер хочет денег :(\nПопробуйте нажать кнопку "Стоп" и возобновить рекомендации или обратитесь в поддержку - @Ddasmii')


        # Отправляем первый фильм
        message = await send_movie_card(callback.message, movies[0], 0, custom_keyboard=create_movie_carousel_keyboard)

        # Сохраняем список фильмов, текущий индекс и ID сообщения в состояние
        await state.set_state(Recomendations.waiting_for_action)
        await state.update_data(
            movies=movies,
            current_index=0,
            message_id=message.message_id,
            chat_id=message.chat.id
        )

    
    await callback.answer()


@recommendations_router.callback_query(Menu_Callback.filter())
async def handle_movie_action(callback: CallbackQuery, callback_data: Menu_Callback, state: FSMContext, session: AsyncSession, bot: Bot):
    action = callback_data.menu_name
    user_id = callback.from_user.id
    current_state = await state.get_state()

    if current_state == Recomendations.processing.state:
        await callback.answer("Пожалуйста, подождите, пока завершится текущее действие.")
        return
    
    await state.set_state(Recomendations.processing.state)
    data = await state.get_data()
    movies = data.get("movies", [])
    current_index = data.get("current_index", 0)
    
    if current_index >= len(movies) or current_index < 0:
        await callback.message.answer("Возникла ошибка с выбором фильма. Попробуйте снова.")
        await callback.answer()
        await state.set_state(Recomendations.waiting_for_action.state)  # Сбрасываем в начальное состояние
        return
    

    movie = movies[current_index]

    logger.info("_" * 100)
    logger.info(f"Текущий фильм: {movie}")
    logger.info("_" * 100)

    last_action = data.get("last_action", "")
    logger.info(f"Last action before checking: {last_action}, current action: {action}")

    if last_action == "watched":
        await state.set_state(Recomendations.waiting_for_action.state)
        await callback.answer()
        return
    

    if action == "stop_recommendations":
        remaining_movies = movies[current_index:]
        for movie in remaining_movies:
            await add_movies_by_interaction(user_id, movie['movie_id'], 'unwatched', session)
        await state.clear()  # Очищаем состояние, если остановили рекомендации
        await bot.delete_message(chat_id=callback.message.chat.id, message_id=callback.message.message_id)
        await callback.message.answer(
            "Рекомендации остановлены. Возвращайтесь, когда захотите!",
            reply_markup=get_callback_btns(btns={
                "Мой профиль": "my_profile",
                "Избранное": "favorites",
                "Рекомендации": "recommendations"
            })
        )
        await callback.answer()
        return
    
    
    elif action in ["like", "next"]:
        interaction_type = {
            "like": "liked",
            "next": "skipped"
        }.get(action)

        # Сохраняем действия пользователя
        await add_movies_by_interaction(user_id, movie['movie_id'], interaction_type, session)

    if action == "watched":
        await state.set_state(Recomendations.waiting_for_action.state)
        await state.update_data(last_action="watched")
        await callback.message.edit_caption(caption='Пожалуйста, оцените фильм', reply_markup=rate_buttons )
        await callback.answer()
        return
    
    current_index += 1
    retries = 0

    while current_index >= len(movies) and retries < 3:
        await callback.answer("Подождите немного, подгружаем новые рекомендации...")
        chat_gpt_response = await get_movie_recommendation_by_preferences(user_id, session)
        movies_data = await get_movies(chat_gpt_response, user_id, session)
        movies = await extract_movie_data(movies_data)

        logger.info("_" * 100)
        logger.info(f"Отправка фильмов пользователю из функции extract_movie_data: {movies}")
        logger.info("_" * 100)
        if movies:

            message = await send_movie_card(callback.message, movies[0], 0, custom_keyboard=create_movie_carousel_keyboard)

            await state.set_state(Recomendations.waiting_for_action)
            await state.update_data(
                movies=movies,
                current_index=0,
                message_id=message.message_id,
                chat_id=message.chat.id
            )
        else: retries += 1
        

    await state.update_data(current_index=current_index)
    if current_index < len(movies):
        await send_movie_card(callback.message, movies[current_index], current_index, edit=True, custom_keyboard=create_movie_carousel_keyboard)
    await state.set_state(Recomendations.waiting_for_action)
    await callback.answer()


    


    


@recommendations_router.callback_query(lambda c: c.data in ['1', '2', '3', '4', '5'])
async def handle_rating(callback: types.CallbackQuery, state: FSMContext, session: AsyncSession,  bot: Bot):
    user_rating = int(callback.data)  # callback.data содержит оценку (1-5)
    data = await state.get_data()
    current_index = data.get("current_index", 0)
    movies = data.get("movies", [])
    movie = movies[current_index]

    logger.info("_" * 100)
    logger.info(f"MOVIE: {movie}")
    logger.info("_" * 100)


    user_id = callback.from_user.id

    if user_rating >= 4:
        await add_movies_by_interaction(user_id, movie['movie_id'], 'watched', session)

    else: await add_movies_by_interaction(user_id, movie['movie_id'], 'disliked', session)
    
    await state.update_data(last_action="")
    if current_index + 1 < len(movies):
        next_index = current_index + 1
        await state.update_data(current_index=next_index)

        try:
            await send_movie_card(callback.message, movies[next_index], next_index, edit=True, custom_keyboard=create_movie_carousel_keyboard)
        except Exception as e:
            logger.error(f"Ошибка при отправке следующего фильма: {e}")
    else:


        logger.info("Фильмы закончились, запрашиваем новые рекомендации.")
        retries = 0
        while retries < 3:
            await callback.answer("Подождите немного, подгружаем новые рекомендации...")
            chat_gpt_response = await get_movie_recommendation_by_preferences(user_id, session)
            movies_data = await get_movies(chat_gpt_response, user_id, session)
            movies = await extract_movie_data(movies_data)

            logger.info("_" * 100)
            logger.info(f"Отправка фильмов пользователю из функции extract_movie_data: {movies}")
            logger.info("_" * 100)
            if movies:

                message = await send_movie_card(callback.message, movies[0], 0, custom_keyboard=create_movie_carousel_keyboard)

                await state.set_state(Recomendations.waiting_for_action)
                await state.update_data(
                    movies=movies,
                    current_index=0,
                    message_id=message.message_id,
                    chat_id=message.chat.id
                )
            else: retries += 1
        
        
    
    await callback.answer()



