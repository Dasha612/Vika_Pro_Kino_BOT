from aiogram import Router, Bot, types
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession
from aiogram import F
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
import logging
from handlers.callback_data import Menu_Callback

from database.orm_query import add_movies_by_interaction, get_movies_by_interaction, check_recommendations_status
from handlers.anketa import Anketa
from kbds.inline import get_callback_btns
from chat_gpt.ai import get_movie_recommendation_by_preferences
from kinopoisk_imdb.search import get_movies, extract_movie_data
from kbds.pagination import create_movie_carousel_keyboard
recommendations_router = Router()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class Reccomendations(StatesGroup):
    waiting_for_action = State()  # Состояние, когда пользователь выбирает действие
    processing = State()          # Состояние, когда выполняется какое-либо действие





@recommendations_router.callback_query(F.data == 'recommendations')
async def send_recommendations(callback: CallbackQuery, session: AsyncSession, bot: Bot, state: FSMContext):
    user_id = callback.from_user.id
    logger.info(f"Запрос рекомендаций от пользователя {user_id}")

    recommendations_status = await check_recommendations_status(user_id, session)
    if not recommendations_status:
        await callback.message.answer(
            "Прежде чем порекомендовать тебе фильм, мне нужно узнать о тебе больше информации...",
            reply_markup=get_callback_btns(btns={"Давай": "set_profile"})
        )
        return

    # Получаем список фильмов
    chat_gpt_response = await get_movie_recommendation_by_preferences(user_id, session)
    movies_data = await get_movies(chat_gpt_response, user_id, session)
    movies = await extract_movie_data(movies_data)
    
    if not movies:
        await callback.message.answer("К сожалению, не удалось найти рекомендации.")
        return

    # Отправляем первый фильм
    message = await send_movie_card(callback.message, movies[0], 0)
    
    # Сохраняем список фильмов, текущий индекс и ID сообщения в состояние
    await state.set_state(Reccomendations.waiting_for_action)
    await state.update_data(
        movies=movies, 
        current_index=0,
        message_id=message.message_id,
        chat_id=message.chat.id
    )
    
    await callback.answer()

async def send_movie_card(message: types.Message, movie: dict, index: int, edit: bool = False):
    """Функция для отправки/редактирования карточки фильма"""
    title = movie['title']
    google_search_url = f"https://www.google.com/search?q=смотреть+фильм+{title.replace(' ', '+')}"
    poster_url = movie.get('poster', 'No image available')
    if not poster_url or poster_url == 'No image available':
        poster_url = None
    
    rating = round(float(movie['rating']), 1) if movie['rating'] != 'Not Found' else 'Not Found'
    
    movie_text = (
        f"<b>Название:</b> {title}\n"
        f"<b>Год:</b> {movie['year']}\n"
        f"<b>Рейтинг:</b> {rating}\n"
        f"<b>Длительность:</b> {movie['duration']}\n"
        f"<b>Жанры:</b> {movie['genres']}\n\n"
        f"<b>Описание:</b> {movie['description']}\n"
        f'<a href="{google_search_url}">🎬 Смотреть</a>'
    )

    if edit:
        try:
            return await message.edit_media(
                types.InputMediaPhoto(
                    media=poster_url,
                    caption=movie_text,
                    parse_mode="HTML"
                ),
                reply_markup=create_movie_carousel_keyboard(index)
            )
        except Exception as e:
            logger.error(f"Ошибка при редактировании сообщения: {e}")
            # Если не удалось отредактировать, отправляем новое сообщение
            return await message.answer_photo(
                photo=poster_url,
                caption=movie_text,
                reply_markup=create_movie_carousel_keyboard(index)
            )
    else:
        return await message.answer_photo(
            photo=poster_url,
            caption=movie_text,
            reply_markup=create_movie_carousel_keyboard(index)
        )

@recommendations_router.callback_query(Menu_Callback.filter())
async def handle_movie_action(callback: CallbackQuery, callback_data: Menu_Callback, state: FSMContext, session: AsyncSession, bot: Bot):
    action = callback_data.menu_name
    current_index = callback_data.index
    user_id = callback.from_user.id
    
    # Получаем текущие данные из состояния
    data = await state.get_data()
    movies = data.get("movies", [])

    if not movies:
        await callback.answer("Ошибка: данные не найдены")
        return

    current_movie = movies[current_index]

    # Обработка действий
    if action == "stop_recommendations":
        remaining_movies = movies[current_index:]
        for movie in remaining_movies:
            await add_movies_by_interaction(user_id, movie['movie_id'], 'unwatched', session)
        await state.clear()
        await callback.message.edit_text(
            "Рекомендации остановлены. Возвращайтесь, когда захотите!",
            reply_markup=get_callback_btns(btns={
                "Мой профиль": "my_profile",
                "Избранное": "favorites",
                "Рекомендации": "recommendations"
            })
        )
        
    elif action in ["like", "next", "watched"]:
        interaction_type = {
            "like": "liked",
            "next": "skipped",
            "watched": "watched"
        }.get(action)
        
        await add_movies_by_interaction(user_id, current_movie['movie_id'], interaction_type, session)

        if current_index + 1 < len(movies):
            next_index = current_index + 1
            await state.update_data(current_index=next_index)
            
            try:
                # Используем существующее сообщение из callback
                await send_movie_card(callback.message, movies[next_index], next_index, edit=True)
            except Exception as e:
                logger.error(f"Ошибка при отправке следующего фильма: {e}")
        else:
            await state.clear()
            await callback.message.edit_text(
                "Это были все рекомендации на сегодня! Возвращайтесь позже за новыми фильмами.",
                reply_markup=get_callback_btns(btns={
                    "Мой профиль": "my_profile",
                    "Избранное": "favorites",
                    "Рекомендации": "recommendations"
                })
            )

    await callback.answer()



