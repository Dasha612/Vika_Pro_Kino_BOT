from aiogram import types
import logging
import aiohttp

async def debug_image_url(url: str):
    async with aiohttp.ClientSession() as session:
        async with session.head(url) as resp:
            print(f"URL: {url}")
            print(f"Status: {resp.status}")
            print(f"Content-Type: {resp.content_type}")

logger = logging.getLogger(__name__)

    
async def is_url_valid(url: str) -> bool:
    try:
        async with aiohttp.ClientSession() as session:
            async with session.head(url, timeout=3) as response:
                return response.status == 200
    except Exception:
        return False





async def send_movie_card(message: types.Message, movie, index: int, edit: bool = False, custom_keyboard=None) -> types.Message:
    """Функция для отправки или редактирования карточки фильма"""

    if isinstance(movie, dict):
        title = movie.get('title')
        google_search_url = f"https://www.google.com/search?q=смотреть+фильм+{title.replace(' ', '+')}"
        poster_url = movie.get('poster') #or "https://i.imgur.com/RwD6GYr.png"
        omdb_poster = movie.get('omdb_poster') or movie.get('movie_omdb_poster')
        rating = round(float(movie.get('rating', 0)), 1) if movie.get('rating') != 'Not Found' else 'Not Found'
        year = movie.get('year', 'Неизвестно')
        duration = movie.get('duration', 'Неизвестно')
        genres = movie.get('genres', 'Неизвестно')
        description = movie.get('description', 'Описание отсутствует')
        logger.info(f"ИЗ СЛОВАРЯ: poster {poster_url}, ombd poster {omdb_poster}")
    else:
        logger.info(f"Текущий фильм: {movie.movie_name}")
        logger.info("🔍 Полное содержимое movie (ORM): %s", movie.__dict__)
        title = movie.movie_name
        google_search_url = f"https://www.google.com/search?q=смотреть+фильм+{title.replace(' ', '+')}"
        poster_url = movie.movie_poster #or "https://i.imgur.com/RwD6GYr.png"
        omdb_poster = movie.movie_omdb_poster
        rating = round(float(movie.movie_rating), 1) if movie.movie_rating != 'Not Found' else 'Not Found'
        year = movie.movie_year
        duration = movie.movie_duration
        genres = movie.movie_genre
        description = movie.movie_description
        logger.info(f"ИЗ БАЗЫ ДАННЫХ: poster {poster_url}, ombd poster {omdb_poster}")

    # 💡 Проверка постера
    for fallback_url in [poster_url, omdb_poster]:
        
        if fallback_url and await is_url_valid(fallback_url):
            poster_url = fallback_url
            break

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
                    parse_mode="HTML",
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
        logger.error(f"Ошибка при отправке карточки фильма: {e}")
        msg = await message.answer_photo(
            photo="https://i.imgur.com/RwD6GYr.png",
            caption=movie_text,
            reply_markup=custom_keyboard(index)
        )

    return msg