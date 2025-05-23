import aiohttp
import os
import asyncio
from dotenv import load_dotenv
import logging
from sqlalchemy.ext.asyncio import AsyncSession

from sqlalchemy import select, update
from database.models import Movies
from database.orm_query import add_movie, get_movies_by_interaction, get_movie_from_db,  get_movies_from_db_by_imdb_list, add_omdb_poster_to_db


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





async def find_in_imbd(movie_list: list, user_id: int, session: AsyncSession):
    if not movie_list:
        logger.warning("Получен пустой список фильмов")
        return {}

    movie_imdb_ids = {}

    # Получаем список уже рекомендованных фильмов
    recommended_movies = await get_movies_by_interaction(
        user_id=user_id, session=session,
        interaction_types=['liked', 'disliked', 'skipped', 'watched']
    )

    recommended_imdb_ids = {movie.imdb for movie in recommended_movies}
    #logger.info(f"ID рекомендованных фильмов: {recommended_imdb_ids}.\n")

    # Формируем задачи
    tasks = [safe_get_imdb_id(movie) for movie in movie_list]
    imdb_ids = await asyncio.gather(*tasks)

    # Обрабатываем результаты
    for movie, imdb_id in zip(movie_list, imdb_ids):
        if imdb_id and imdb_id not in recommended_imdb_ids:
            movie_imdb_ids[movie] = imdb_id

    logger.info(f"финальный список фильмов после сортировки: {movie_imdb_ids}.")

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

    # Проверяем локальную базу
    valid_imdb_ids = [imdb for imdb in movie_imdb_ids.values() if imdb != 'Not Found']
    movies_from_db = await get_movies_from_db_by_imdb_list(valid_imdb_ids, session)

    for movie, imdb_id in movie_imdb_ids.items():
        if imdb_id == 'Not Found':
            continue

        movie_from_db = movies_from_db.get(imdb_id)
        if movie_from_db:
            omdb_poster = movie_from_db.movie_omdb_poster

            movies_data[movie] = {
                'imdb_id': imdb_id,
                'omdb_poster': omdb_poster,
                'data': {
                    'docs': [{
                        'name': movie_from_db.movie_name,
                        'shortDescription': movie_from_db.movie_description,
                        'rating': {'kp': movie_from_db.movie_rating},
                        'poster': {'url': movie_from_db.movie_poster},
                        'year': movie_from_db.movie_year,
                        'genres': [{'name': genre} for genre in movie_from_db.movie_genre.split(', ')],
                        'movieLength': movie_from_db.movie_duration,
                        'type': movie_from_db.movie_type
                    }]
                }
            }
        else:
            movies_to_fetch[movie] = imdb_id

    # Обращаемся к API Кинопоиска
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
            movie_data_list = await asyncio.gather(*tasks)

            for data, (movie, imdb_id) in zip(movie_data_list, movies_to_fetch.items()):
                if not data:
                    logger.warning(f"❌ Нет данных от API для '{movie}' (imdb: {imdb_id})")
                    continue

                docs = data.get("docs")
                if not docs or not isinstance(docs, list) or not docs:
                    logger.warning(f"❌ Пустой или неверный формат 'docs' от API для '{movie}' (imdb: {imdb_id}). Ответ: {data}")
                    continue

                doc = docs[0]
                if not doc.get('name') or not doc.get('poster', {}).get('url') or not doc.get('rating', {}).get('kp') or not (doc.get('shortDescription') or doc.get('description')):
                    logger.warning(f"⚠️ Недостаточно данных для '{movie}' (imdb: {imdb_id}):")
                    logger.warning(f" - name: {doc.get('name')}")
                    logger.warning(f" - poster: {doc.get('poster', {}).get('url')}")
                    logger.warning(f" - rating.kp: {doc.get('rating', {}).get('kp')}")
                    logger.warning(f" - shortDescription: {doc.get('shortDescription')}")
                    logger.warning(f" - description: {doc.get('description')}")
                    continue

                movie_info = doc
                movie_length = movie_info.get('movieLength')
                series_length = movie_info.get('seriesLength')
                duration = f"{movie_length or series_length or 0} min"
                movie_type = movie_info.get('type') or "movie"

                # Сохраняем в результирующий словарь
                movies_data[movie] = {'imdb_id': imdb_id, 'data': data}

                # Сохраняем в базу данных
                try:
                    await add_movie(
                        movie_id=imdb_id,
                        movie_name=movie_info.get('name', ''),
                        movie_description=movie_info.get('shortDescription') or movie_info.get('description', ''),
                        movie_rating=movie_info.get('rating', {}).get('kp', 0.0),
                        movie_poster=movie_info.get('poster', {}).get('url', ''),
                        movie_year=movie_info.get('year', 0),
                        movie_genre=', '.join([genre['name'] for genre in movie_info.get('genres', [])]),
                        movie_duration=duration,
                        movie_type=movie_type,
                        session=session,
                        movie_omdb_poster=""
                    )
                    omdb_poster = await add_omdb_poster_to_db(imdb_id, session)
                    movies_data[movie] = {
                        'imdb_id': imdb_id,
                        'omdb_poster': omdb_poster, 
                        'data': data
                    }


                except Exception as e:
                    logger.error(f"❌ Ошибка при добавлении фильма '{movie}' в БД: {e}")
                    await session.rollback()

    return movies_data

async def get_movies(movies_list, user_id, session: AsyncSession):
    movie_imdb_ids = await find_in_imbd(movies_list, user_id, session)
    movies_data = await find_in_kinopoisk_by_imdb(movie_imdb_ids, session)
    return movies_data



async def extract_movie_data(movies_data):
    movie_info_list = [] 


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

        
            movie_length = movie_info.get('movieLength')
            series_length = movie_info.get('seriesLength')
            if movie_length:
                duration = f"{movie_length} min"
            elif series_length:
                duration = f"{series_length} min"
            else:
                duration = 'N/A'

      
            movie_type = movie_info.get('type', 'unknown')

            movie_info_list.append({
                'movie_id': data['imdb_id'],
                'type': movie_type,
                'title': title_russian,
                'year': year,
                'poster': poster_url,
                'omdb_poster': data.get('omdb_poster', ''),
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