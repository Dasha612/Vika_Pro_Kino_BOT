from aiogram import Router, Bot, types
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession
from aiogram import F
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
import logging
from handlers.callback_data import Menu_Callback
import os
import asyncio

from database.orm_query import add_movies_by_interaction, get_movies_by_interaction, check_recommendations_status, delete_movies_by_interaction
from kbds.inline import get_callback_btns, subscribe_button, rate_buttons
from chat_gpt.ai import get_movie_recommendation_by_interaction, get_movie_recommendation_by_search
from kinopoisk_imdb.search import get_movies, extract_movie_data
from kbds.pagination import create_movie_carousel_keyboard
from handlers.movie_utils import send_movie_card
recommendations_router = Router()


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class Recomendations(StatesGroup):
    waiting_for_action = State()  # Состояние, когда пользователь выбирает действие
    processing = State()          # Состояние, когда выполняется какое-либо действие
    waiting_for_rating = State()
    waiting_for_query = State()

@recommendations_router.callback_query(F.data == 'choose_option')
async def options(callback: CallbackQuery, session: AsyncSession, bot: Bot, state: FSMContext ):
    await callback.message.edit_text(
        (
            f"<b>Выберите опцию</b>"
        ),
        parse_mode="HTML",
        reply_markup=get_callback_btns(
            btns={
                "Запуск рекомендаций": "recommendations",
                "Свой запрос": "search_movie",
                'Вернуться в меню': 'to_the_main_page'
            }
        )
    )



@recommendations_router.callback_query(F.data == 'search_movie')
async def prompt_search_query(callback: CallbackQuery, state: FSMContext):
    await state.set_state(Recomendations.waiting_for_query)
    await callback.message.edit_text('Введите свой запрос')


# 2. Пользователь вводит запрос (например: "Гарри Поттер")
@recommendations_router.message(Recomendations.waiting_for_query, F.text)
async def process_search_query(message: types.Message, state: FSMContext, session: AsyncSession, bot: Bot):
    user_text = message.text
    user_id = message.from_user.id
    user_message_id = message.message_id
    max_retries = 3
    retries = 0
    if (user_text):
        await bot.send_chat_action(message.chat.id, action="typing")
        await asyncio.sleep(1)

        chat_gpt_response = await get_movie_recommendation_by_search(user_id, user_text, session)

        if chat_gpt_response:
            movies_data = await get_movies(chat_gpt_response, user_id, session)
            movies = await extract_movie_data(movies_data)

            retries += 1
        if retries >= max_retries: 
            await message.answer('Кажется, произошла ошибка или прогер хочет денег :(\nПопробуйте нажать кнопку "Стоп" и возобновить рекомендации или обратитесь в поддержку - @Ddasmii')
            await message.answer()
            return
        await asyncio.sleep(3)
        try:
            await bot.delete_message(message.chat.id, user_message_id)
        except Exception as e:
            logger.warning(f"Не удалось удалить сообщение: {e}")


        # Отправляем первый фильм
        message = await send_movie_card(message, movies[0], 0, custom_keyboard=create_movie_carousel_keyboard)

        # Сохраняем список фильмов, текущий индекс и ID сообщения в состояние
        await state.set_state(Recomendations.waiting_for_action)
        await state.update_data(
            movies=movies,
            current_index=0,
            message_id=message.message_id,
            chat_id=message.chat.id
        )








@recommendations_router.callback_query(F.data == 'recommendations')
async def send_recommendations(callback: CallbackQuery, session: AsyncSession, bot: Bot, state: FSMContext):
    #await bot.delete_message(chat_id=callback.message.chat.id, message_id=callback.message.message_id)

    await bot.send_chat_action(callback.message.chat.id, action="typing")
    await asyncio.sleep(1) 

    current_state = await state.get_state()

    user_id = callback.from_user.id


    recommendations_status = await check_recommendations_status(user_id, session)
    if not recommendations_status:
        await callback.message.edit_text(
            "Прежде чем порекомендовать тебе фильм, мне нужно узнать о тебе больше информации. Давай заполним анкету?",
            reply_markup=get_callback_btns(btns={"Давай": "set_profile"})
        )
        return
    
    unwatched_movies  = await get_movies_by_interaction(user_id, session,['unwatched'])

    if unwatched_movies:

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
        await delete_movies_by_interaction(user_id, session, ['unwatched'], unwatched_movies[0].imdb)
        await callback.answer()
            

    else:
    # Получаем список фильмов
        max_retries = 3
        retries = 0
        movies = []

        while not movies and retries < max_retries:
            chat_gpt_response = await get_movie_recommendation_by_interaction(user_id, session)
            movies_data = await get_movies(chat_gpt_response, user_id, session)
            movies = await extract_movie_data(movies_data)


            retries += 1
        if retries >= max_retries: 
            await callback.message.answer('Кажется, произошла ошибка или прогер хочет денег :(\nПопробуйте нажать кнопку "Стоп" и возобновить рекомендации или обратитесь в поддержку - @Ddasmii')
            await callback.answer()
            return


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
    data = await state.get_data()
    movies = data.get("movies", [])
    current_index = data.get("current_index", 0)
    action = callback_data.menu_name
    user_id = callback.from_user.id
    current_state = await state.get_state()

    if current_state == Recomendations.processing.state:
        await callback.answer("Пожалуйста, подождите, пока завершится текущее действие.")
        return
    
    await state.set_state(Recomendations.processing.state)
    
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


    if last_action == "watched":
        await state.set_state(Recomendations.waiting_for_action.state)
        await callback.answer()
        return
    

    if action == "stop_recommendations":
        remaining_movies = movies[current_index:]
        for movie in remaining_movies:
            movie_id = movie.imdb if hasattr(movie, 'imdb') else movie.get('movie_id')
            await add_movies_by_interaction(user_id, movie_id, 'unwatched', session)

        await state.clear()  # Очищаем состояние, если остановили рекомендации
        await bot.delete_message(chat_id=callback.message.chat.id, message_id=callback.message.message_id)

        start_message_id = data.get("start_message_id")

        if start_message_id:
            try:
                await bot.edit_message_text(
                    chat_id=callback.message.chat.id,
                    message_id=start_message_id,
                    text="Рекомендации остановлены. Возвращайтесь, когда захотите!",
                    reply_markup=get_callback_btns(btns={
                        "Мой профиль": "my_profile",
                        "Избранное": "favourites",
                        "Рекомендации": "choose_option"
                    })
                )
            except Exception as e:
                logger.error(f"Не удалось отредактировать стартовое сообщение: {e}")
                # optionally: отправить новое сообщение, если нужно
                await bot.send_message(
                    chat_id=callback.message.chat.id,
                    text="Рекомендации остановлены. Возвращайтесь, когда захотите!",
                    reply_markup=get_callback_btns(btns={
                        "Мой профиль": "my_profile",
                        "Избранное": "favorites",
                        "Рекомендации": "choose_option"
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
        movie_id = movie.imdb if hasattr(movie, 'imdb') else movie.get('movie_id')
        await add_movies_by_interaction(user_id, movie_id, interaction_type, session)

    if action == "watched":
        await state.set_state(Recomendations.waiting_for_action.state)
        await state.update_data(last_action="watched")
        await callback.message.edit_caption(caption='Пожалуйста, оцените фильм', reply_markup=rate_buttons )
        await callback.answer()
        return
    
    current_index += 1
    await state.update_data(current_index=current_index)

    if current_index < len(movies):
        await send_movie_card(callback.message, movies[current_index], current_index, edit=True, custom_keyboard=create_movie_carousel_keyboard)
        await state.set_state(Recomendations.waiting_for_action)
        await callback.answer()

    else:
        await callback.answer("Подождите немного, подгружаем новые рекомендации...")

        while True:
            chat_gpt_response = await get_movie_recommendation_by_interaction(user_id, session)
            movies_data = await get_movies(chat_gpt_response, user_id, session)
            new_movies = await extract_movie_data(movies_data)
            if new_movies:
                message = await send_movie_card(callback.message, new_movies[0], 0, edit=True, custom_keyboard=create_movie_carousel_keyboard)

                await state.set_state(Recomendations.waiting_for_action)
                await state.update_data(
                    movies=new_movies,
                    current_index=0,
                    message_id=message.message_id,
                    chat_id=message.chat.id
                )
                await callback.answer()
                return
            
            await callback.answer("Не удалось получить рекомендации. Пробуем ещё раз...")
            await callback.answer()



@recommendations_router.callback_query(lambda c: c.data in ['1', '2', '3', '4', '5'])
async def handle_rating(callback: types.CallbackQuery, state: FSMContext, session: AsyncSession,  bot: Bot):
    user_rating = int(callback.data)  
    data = await state.get_data()
    current_index = data.get("current_index", 0)
    movies = data.get("movies", [])
    movie = movies[current_index]
    user_id = callback.from_user.id

    movie_id = movie.imdb if hasattr(movie, 'imdb') else movie.get('movie_id')

    if user_rating >= 4:
        await add_movies_by_interaction(user_id, movie_id, 'watched', session)

    else: await add_movies_by_interaction(user_id, movie_id, 'disliked', session)
    
    await state.update_data(last_action="")
    current_index += 1
    await state.update_data(current_index=current_index)

    if current_index < len(movies):
        await send_movie_card(callback.message, movies[current_index], current_index, edit=True, custom_keyboard=create_movie_carousel_keyboard)
        await state.set_state(Recomendations.waiting_for_action)
        await callback.answer()

    else:
        await callback.answer("Подождите немного, подгружаем новые рекомендации...")

        while True:
            chat_gpt_response = await get_movie_recommendation_by_interaction(user_id, session)
            movies_data = await get_movies(chat_gpt_response, user_id, session)
            new_movies = await extract_movie_data(movies_data)
            
            if new_movies:
                message = await send_movie_card(callback.message, new_movies[0], 0, edit=True, custom_keyboard=create_movie_carousel_keyboard)

                await state.set_state(Recomendations.waiting_for_action)
                await state.update_data(
                    movies=new_movies,
                    current_index=0,
                    message_id=message.message_id,
                    chat_id=message.chat.id
                )
                await callback.answer()
                return
            
            await callback.answer("Не удалось получить рекомендации. Пробуем ещё раз...")
            await callback.answer()

    



