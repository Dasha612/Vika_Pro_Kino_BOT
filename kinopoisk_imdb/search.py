import aiohttp
import os
import asyncio
from dotenv import load_dotenv
import logging
from sqlalchemy.ext.asyncio import AsyncSession

from database.orm_query import add_movie, get_movies_by_interaction, get_movie_from_db


load_dotenv()


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


API_KEY_OMDB = os.getenv('OMDB_API_KEY')
API_KEY_KINOPOISK = os.getenv('KINOPOISK_API_KEY')


async def get_imdb_id(movie_title: str):
    url = f'http://www.omdbapi.com/?t={movie_title}&apikey={API_KEY_OMDB}'
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                data = await response.json()

                if data['Response'] == 'True':
                    return data['imdbID']
                else:
                    return None
    except Exception as e:
        print(f"Error fetching IMDb ID for {movie_title}: {e}")
        return None


async def get_movie_info(imdb_id: str) -> dict:
    """Получает детальную информацию о фильме из OMDB API"""
    url = f'http://www.omdbapi.com/?i={imdb_id}&apikey={API_KEY_OMDB}'
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                data = await response.json()
                if data['Response'] == 'True':
                    return {
                        'name': data.get('Title', ''),
                        'description': data.get('Plot', ''),
                        'rating': float(data.get('imdbRating', 0)),
                        'poster': data.get('Poster', ''),
                        'year': int(data.get('Year', 0)),
                        'genre': data.get('Genre', ''),
                        'duration': int(data.get('Runtime', '0').replace(' min', '')),
                        'country': data.get('Country', '')
                    }
                return None
    except Exception as e:
        logger.error(f"Ошибка при получении информации о фильме {imdb_id}: {e}")
        return None


async def find_in_ombd(movie_list: list, user_id: int, session: AsyncSession):
    logger.info(f"Полученный список фильмов: {movie_list}")

    if not movie_list:
        logger.warning("Получен пустой список фильмов")
        return {}
    
    movie_imdb_ids = {}
    tasks = []

    # Получаем список уже рекомендованных фильмов для пользователя
    recommended_movies = await get_movies_by_interaction(user_id=user_id, session=session)
    logger.debug(f"Уже рекомендованные фильмы: {recommended_movies}")

    # Формируем задачи для асинхронных запросов
    for movie in movie_list:
        tasks.append(get_imdb_id(movie))

    # Выполняем все задачи одновременно
    imdb_ids = await asyncio.gather(*tasks)

    # Сохраняем результаты
    for i, movie in enumerate(movie_list):
        imdb_id = imdb_ids[i]
        if not imdb_id:
            continue
            
        is_in_db = await get_movie_from_db(imdb_id, session)
        if not is_in_db:
            # Получаем детальную информацию о фильме
            movie_info = await get_movie_info(imdb_id)
            if movie_info:
                try:
                    await add_movie(
                        movie_id=imdb_id,
                        movie_name=movie_info['name'],
                        movie_description=movie_info['description'],
                        movie_rating=movie_info['rating'],
                        movie_poster=movie_info['poster'],
                        movie_year=movie_info['year'],
                        movie_genre=movie_info['genre'],
                        movie_duration=movie_info['duration'],
                        session=session
                    )
                    logger.info(f"Фильм {movie} успешно добавлен в базу данных")
                except Exception as e:
                    logger.error(f"Ошибка при добавлении фильма {movie}: {e}")
                    continue

        if imdb_id in recommended_movies:
            continue
            
        movie_imdb_ids[movie] = imdb_id
    
    logger.info(f"Полученный список с imdb id: {movie_imdb_ids}")
    return movie_imdb_ids




async def fetch_movie_data(url, movie_title, session):
    try:
        async with session.get(url) as response:
            if response.status == 200:
                data = await response.json()
                return data
            else:
                logger.error(f"Ошибка запроса для {movie_title}: {response.status}")
                return None
    except Exception as e:
        logger.error(f"Ошибка при получении данных для {movie_title}: {e}")
        return None


async def find_in_kinopoisk_by_imdb(movie_imdb_ids):
    movies_data = {}
    async with aiohttp.ClientSession() as session:
        tasks = [
            fetch_movie_data(
                f'https://api.kinopoisk.dev/v1.4/movie?externalId.imdb={imdb_id}&token={API_KEY_KINOPOISK}',
                movie,
                session
            )
            for movie, imdb_id in movie_imdb_ids.items() if imdb_id != 'Not Found'
        ]
        movie_data = await asyncio.gather(*tasks)

    for data, (movie, imdb_id) in zip(movie_data, movie_imdb_ids.items()):
        movies_data[movie] = {'imdb_id': imdb_id, 'data': data or 'Not Found'}
    logger.info(f"Movies data from Kinopoisk: {movies_data}")
    return movies_data



async def get_movies(movies_list, user_id, session: AsyncSession):
    movie_imdb_ids = await find_in_ombd(movies_list, user_id, session)
    movies_data = await find_in_kinopoisk_by_imdb(movie_imdb_ids)
    return movies_data



async def extract_movie_data(movies_data):
    logger.info(f"Полученные данные для извлечения в extract_movie_data: {movies_data}")
    movie_info_list = []  # Список для хранения данных о фильмах
    for movie, data in movies_data.items():
        docs = data['data'].get('docs', []) if data['data'] != 'Not Found' else []

        if docs:  # Проверяем, есть ли данные в docs
            movie_info = docs[0]
            title_russian = movie_info.get('name', 'N/A')
            year = movie_info.get('year', 'Unknown')
            poster_url = movie_info.get('poster', {}).get('url', 'No image available')
            description = (
                    movie_info.get('shortDescription') or
                    movie_info.get('description') or
                    'Описание недоступно'
            ).strip()

            rating = movie_info.get('rating', {}).get('kp', 'No rating available')
            genres = ', '.join([genre.get('name', 'Unknown') for genre in movie_info.get('genres', [])])
            duration = movie_info.get('movieLength', 'N/A')
            duration_text = f"{duration} min" if isinstance(duration, int) else duration

            movie_info_list.append({
                'movie_id': data['imdb_id'],
                'title': title_russian,
                'year': year,
                'poster': poster_url,
                'description': description,
                'rating': rating,
                'genres': genres,
                'duration': duration_text,
            })
        else:
            # Если данные отсутствуют
            movie_info_list.append({
                'movie_id': data['imdb_id'],
                'title': movie,
                'year': 'Not Found',
                'poster': 'No image available',
                'description': 'Not Found',
                'rating': 'Not Found',
                'genres': 'Not Found',
                'duration': 'Not Found',
            })

    logger.info(f"Результат Extracted movie data: {movie_info_list}")
    return movie_info_list


async def check_movie():
    pass

#FOR FAVOURITES
async def find_by_imdb(movie_imdb_ids):
    logger.info(f"Полученные фильмы в функцию: {movie_imdb_ids}")

    movies_data = {}

    tasks = []
    for imdb_id in movie_imdb_ids:
        if imdb_id != 'Not Found':
            url = f'https://api.kinopoisk.dev/v1.4/movie?externalId.imdb={imdb_id}&token={API_KEY_KINOPOISK}'
            tasks.append(fetch_data(url))

    movie_data = await asyncio.gather(*tasks)
    for data, imdb_id in zip(movie_data, movie_imdb_ids):
        if data:
            movies_data[imdb_id] = {'imdb_id': imdb_id, 'data': data}
        else:
            movies_data[imdb_id] = {'imdb_id': imdb_id, 'data': 'Not Found'}
    logger.info(f"Найденные фильмы по id: {movies_data}")

    return movies_data


async def fetch_data(url):
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                if response.status == 200:
                    data = await response.json()

                    return data
                else:
                    logger.warning(f"Failed to fetch data for URL: {url}, Status: {response.status}")
                    return None
    except Exception as e:
        logger.error(f"Error fetching data: {e}")
        return None

