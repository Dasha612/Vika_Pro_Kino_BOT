from aiogram import types
from aiogram.utils.keyboard import InlineKeyboardBuilder
from kbds.pagination import create_movie_carousel_keyboard
import logging

logger = logging.getLogger(__name__)

async def send_movie_card(message: types.Message, movie, index: int, edit: bool = False, custom_keyboard=None):
    """Функция для отправки/редактирования карточки фильма"""
    
    # Если передан объект Movies, используем его атрибуты, если словарь, то используем ключи
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
        title = movie.movie_name  # Для объекта Movies
        google_search_url = f"https://www.google.com/search?q=смотреть+фильм+{title.replace(' ', '+')}"
        poster_url = movie.movie_poster if movie.movie_poster else 'No image available'
        rating = round(float(movie.movie_rating), 1) if movie.movie_rating != 'Not Found' else 'Not Found'
        year = movie.movie_year
        duration = movie.movie_duration
        genres = movie.movie_genre
        description = movie.movie_description

    # Текст карточки фильма
    movie_text = (
        f"<b>Название:</b> {title}\n"
        f"<b>Год:</b> {year}\n"
        f"<b>Рейтинг:</b> {rating}\n"
        f"<b>Длительность:</b> {duration}\n"
        f"<b>Жанры:</b> {genres}\n\n"
        f"<b>Описание:</b> {description}\n"
        f'<a href="{google_search_url}">🎬 Смотреть</a>'
    )

    # Если edit == True, редактируем сообщение, иначе отправляем новое
    if edit:
        try:
            return await message.edit_media(
                types.InputMediaPhoto(
                    media=poster_url,
                    caption=movie_text,
                    parse_mode="HTML"
                ),
                reply_markup=custom_keyboard(index)
            )
        except Exception as e:
            logger.error(f"Ошибка при редактировании сообщения: {e}")
            return await message.answer_photo(
                photo=poster_url,
                caption=movie_text,
                reply_markup=custom_keyboard(index)
            )
    else:
        return await message.answer_photo(
            photo=poster_url,
            caption=movie_text,
            reply_markup=custom_keyboard(index)
        )
