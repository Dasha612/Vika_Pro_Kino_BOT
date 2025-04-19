from aiogram import types
from aiogram.utils.keyboard import InlineKeyboardBuilder
from kbds.pagination import create_movie_carousel_keyboard
import logging

logger = logging.getLogger(__name__)

async def send_movie_card(message: types.Message, movie, index: int, edit: bool = False, custom_keyboard=None) -> types.Message:
    """Функция для отправки или редактирования карточки фильма"""

    if isinstance(movie, dict):
        title = movie.get('title')
        google_search_url = f"https://www.google.com/search?q=смотреть+фильм+{title.replace(' ', '+')}"
        poster_url = movie.get('poster', 'No image available')
        rating = round(float(movie.get('rating', 0)), 1) if movie.get('rating') != 'Not Found' else 'Not Found'
        year = movie.get('year', 'Неизвестно')
        duration = movie.get('duration', 'Неизвестно')
        genres = movie.get('genres', 'Неизвестно')
        description = movie.get('description', 'Описание отсутствует')
    else:
        title = movie.movie_name
        google_search_url = f"https://www.google.com/search?q=смотреть+фильм+{title.replace(' ', '+')}"
        poster_url = movie.movie_poster if movie.movie_poster else 'No image available'
        rating = round(float(movie.movie_rating), 1) if movie.movie_rating != 'Not Found' else 'Not Found'
        year = movie.movie_year
        duration = movie.movie_duration
        genres = movie.movie_genre
        description = movie.movie_description

    movie_text = (
        f"<b>Название:</b> {title}\n"
        f"<b>Год:</b> {year}\n"
        f"<b>Рейтинг:</b> {rating}\n"
        f"<b>Длительность:</b> {duration}\n"
        f"<b>Жанры:</b> {genres}\n\n"
        f"<b>Описание:</b> {description}\n"
        f'<a href="{google_search_url}">🎬 Смотреть</a>'
    )

    try:
        if edit:
            msg = await message.edit_media(
                types.InputMediaPhoto(
                    media=poster_url,
                    caption=movie_text,
                    parse_mode="HTML"
                ),
                reply_markup=custom_keyboard(index)
            )
        else:
            msg = await message.answer_photo(
                photo=poster_url,
                caption=movie_text,
                reply_markup=custom_keyboard(index)
            )
    except Exception as e:
        logger.error(f"Ошибка при редактировании сообщения: {e}")
        msg = await message.answer_photo(
            photo=poster_url,
            caption=movie_text,
            reply_markup=custom_keyboard(index)
        )

    return msg  # всегда возвращаем объект сообщения