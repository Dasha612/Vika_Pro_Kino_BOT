import aiohttp
import os
import asyncio
from dotenv import load_dotenv
import logging
from sqlalchemy.ext.asyncio import AsyncSession

from database.orm_query import add_movie, get_movies_by_interaction, get_movie_from_db,  get_movies_from_db_by_imdb_list


load_dotenv()


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


API_KEY_OMDB = os.getenv('OMDB_API_KEY')
API_KEY_KINOPOISK = os.getenv('KINOPOISK_API_KEY')

imdb_cache = {}

sem = asyncio.Semaphore(5)  

async def safe_get_imdb_id(title: str) -> str | None:
    if title in imdb_cache:
        return imdb_cache[title]

    async with sem:  # ограничим одновременные запросы
        imdb_id = await get_imdb_id(title)
        imdb_cache[title] = imdb_id
        return imdb_id


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


async def find_in_imbd(movie_list: list, user_id: int, session: AsyncSession):
    if not movie_list:
        logger.warning("Получен пустой список фильмов")
        return {}

    movie_imdb_ids = {}

    # Получаем список уже рекомендованных фильмов
    recommended_movies = await get_movies_by_interaction(
        user_id=user_id, session=session,
        interaction_types=['liked', 'disliked', 'skipped']
    )
    recommended_imdb_ids = {movie.imdb for movie in recommended_movies}

    # Формируем задачи
    tasks = [safe_get_imdb_id(movie) for movie in movie_list]
    imdb_ids = await asyncio.gather(*tasks)

    # Обрабатываем результаты
    for movie, imdb_id in zip(movie_list, imdb_ids):
        if imdb_id and imdb_id not in recommended_imdb_ids:
            movie_imdb_ids[movie] = imdb_id

    return movie_imdb_ids



async def fetch_movie_data(url, movie_title, session, retries=2):
    for attempt in range(retries + 1):
        try:
            async with session.get(url) as response:
                if response.status == 200:
                    return await response.json()
                logger.error(f"[{attempt+1}] Ошибка запроса для {movie_title}: {response.status}")
        except asyncio.TimeoutError:
            logger.warning(f"[{attempt+1}] Таймаут для {movie_title}")
        except Exception as e:
            logger.error(f"[{attempt+1}] Ошибка при получении {movie_title}: {e}")
        await asyncio.sleep(1)  # Короткая пауза
    return None


semaphore = asyncio.Semaphore(5)
async def limited_fetch(url, movie_title, session):
    async with semaphore:
        return await fetch_movie_data(url, movie_title, session)

timeout = aiohttp.ClientTimeout(total=5)
async def find_in_kinopoisk_by_imdb(movie_imdb_ids, session: AsyncSession):
    movies_data = {}
    movies_to_fetch = {}

    valid_imdb_ids = [imdb for imdb in movie_imdb_ids.values() if imdb != 'Not Found']
    movies_from_db = await get_movies_from_db_by_imdb_list(valid_imdb_ids, session)

    for movie, imdb_id in movie_imdb_ids.items():
        if imdb_id == 'Not Found':
            continue

        movie_from_db = movies_from_db.get(imdb_id)
        if movie_from_db:
            movies_data[movie] = {
                'imdb_id': imdb_id,
                'data': {
                    'docs': [{
                        'name': movie_from_db.movie_name,
                        'shortDescription': movie_from_db.movie_description,
                        'rating': {'kp': movie_from_db.movie_rating},
                        'poster': {'url': movie_from_db.movie_poster},
                        'year': movie_from_db.movie_year,
                        'genres': [{'name': genre} for genre in movie_from_db.movie_genre.split(', ')],
                        'movieLength': movie_from_db.movie_duration,
                        'type': movie_from_db.movie_type  # если ты хранишь тип в БД
                    }]
                }
            }
        else:
            movies_to_fetch[movie] = imdb_id

    if movies_to_fetch:
        async with aiohttp.ClientSession(timeout=timeout) as session_http:
            tasks = [
                limited_fetch(
                    f'https://api.kinopoisk.dev/v1.4/movie?externalId.imdb={imdb_id}&token={API_KEY_KINOPOISK}',
                    movie,
                    session_http
                )
                for movie, imdb_id in movies_to_fetch.items()
            ]
            movie_data = await asyncio.gather(*tasks)

            for data, (movie, imdb_id) in zip(movie_data, movies_to_fetch.items()):
                if (
                    not data or
                    'docs' not in data or
                    not data['docs'] or
                    not data['docs'][0].get('name') or
                    not data['docs'][0].get('poster', {}).get('url') or
                    not data['docs'][0].get('rating', {}).get('kp') or
                    not (
                        data['docs'][0].get('shortDescription') or
                        data['docs'][0].get('description')
                    )
                ):
                    logger.warning(f"Пропущен фильм {movie} — недостаточно данных.")
                    continue

                movie_info = data['docs'][0]

                # 💡 Новый блок: определяем длительность
                movie_length = movie_info.get('movieLength')
                series_length = movie_info.get('seriesLength')
                duration = None

                if movie_length:
                    duration = f"{movie_length} min"
                elif series_length:
                    duration = f"{series_length} min"
                else:
                    duration = "0 min"

                # 💡 Новый блок: определяем тип (фильм или сериал)
                movie_type = movie_info.get('type') or "movie"  # 'movie', 'tv-series', 'animated-series' и т.д.

                movies_data[movie] = {'imdb_id': imdb_id, 'data': data}

                try:
                    await add_movie(
                        movie_id=imdb_id,
                        movie_name=movie_info.get('name', ''),
                        movie_description=movie_info.get('shortDescription', '') or movie_info.get('description', ''),
                        movie_rating=movie_info.get('rating', {}).get('kp', 0.0),
                        movie_poster=movie_info.get('poster', {}).get('url', ''),
                        movie_year=movie_info.get('year', 0),
                        movie_genre=', '.join([genre['name'] for genre in movie_info.get('genres', [])]),
                        movie_duration=duration,  # передаём уже строку с мин.
                        movie_type=movie_type,    # 👈 передаём тип контента
                        session=session
                    )
                    logger.info(f"Фильм {movie} успешно добавлен в базу данных")
                except Exception as e:
                    logger.error(f"Ошибка при добавлении фильма {movie} в базу данных: {e}")
                    await session.rollback()

    return movies_data

async def get_movies(movies_list, user_id, session: AsyncSession):
    movie_imdb_ids = await find_in_imbd(movies_list, user_id, session)
    movies_data = await find_in_kinopoisk_by_imdb(movie_imdb_ids, session)
    return movies_data



async def extract_movie_data(movies_data):
    movie_info_list = []  # Список для хранения данных о фильмах

    for movie, data in movies_data.items():
        docs = data['data'].get('docs', []) if data['data'] != 'Not Found' else []

        if docs:
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

            # 💡 Определяем длительность
            movie_length = movie_info.get('movieLength')
            series_length = movie_info.get('seriesLength')
            if movie_length:
                duration = f"{movie_length} min"
            elif series_length:
                duration = f"{series_length} min"
            else:
                duration = 'N/A'

            # 💡 Определяем тип (movie, tv-series и т.д.)
            movie_type = movie_info.get('type', 'unknown')

            movie_info_list.append({
                'movie_id': data['imdb_id'],
                'type': movie_type,
                'title': title_russian,
                'year': year,
                'poster': poster_url,
                'description': description,
                'rating': rating,
                'genres': genres,
                'duration': duration,
            })
        else:
            # Если данных по фильму нет
            movie_info_list.append({
                'movie_id': data['imdb_id'],
                'type': 'unknown',
                'title': movie,
                'year': 'Not Found',
                'poster': 'No image available',
                'description': 'Not Found',
                'rating': 'Not Found',
                'genres': 'Not Found',
                'duration': 'Not Found',
            })

    return movie_info_list


