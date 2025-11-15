from database.models import Users_anketa, Users, Movies, Users_interaction
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime
from sqlalchemy import select, delete
import aiohttp
from sqlalchemy import update
import os
from typing import Sequence
import asyncio


from tmdb_parser import tmdb_search_movie, fetch_movie_safe
API_KEY_OMDB = os.getenv('OMDB_API_KEY')
timeout = aiohttp.ClientTimeout(total=5)

language = "ru-RU"

#функция для добавления ответов пользователя в базу
async def orm_add_user_rec_set(user_id: int, session: AsyncSession, data: dict):
    try:
        def get_answer(key: str) -> str:
            return ", ".join(data.get(f"{key}_selected", []))

        # Подготавливаем данные
        mood = get_answer("question_1")
        genres = get_answer("question_2")
        era = get_answer("question_3")
        themes = get_answer("question_4")
        country = get_answer("question_5")

        query = select(Users_anketa).where(Users_anketa.user_id == user_id)
        existing = await session.scalar(query)

        if existing:
            existing.user_rec_status = True
            existing.mood = mood
            existing.genres = genres
            existing.era = era
            existing.country = country
            existing.themes = themes
        else:
            new_obj = Users_anketa(
                user_id=user_id,
                user_rec_status=True,
                mood=mood,
                genres=genres,
                era=era,
                country=country,
                themes=themes,
            )
            session.add(new_obj)

        await session.commit()

    except Exception as e:
        await session.rollback()
        raise e




#функция для добавления пользователя в базу
async def add_user(user_id: int, session: AsyncSession):
    # Сначала проверяем, существует ли пользователь
    query = select(Users).where(Users.user_id == user_id)
    existing_user = await session.scalar(query)
    
    # Если пользователь не существует, создаем нового
    if not existing_user:
        current_time = datetime.now()
        obj = Users(
            user_id=user_id,
            user_start_date=current_time,
            user_end_date=current_time
        )
        session.add(obj)
        await session.commit()
        return obj
    
    return existing_user  # Возвращаем существующего пользователя, если он уже есть


#функция для проверки статуса рекомендаций
async def check_recommendations_status(user_id: int, session: AsyncSession):
    query = select(Users_anketa.user_rec_status).where(Users_anketa.user_id  == user_id)
    status = await session.scalar(query)
    return status



#функция для добавления фильма в базу по взаимодействию
async def add_movies_by_interaction(user_id: int, movie_id: str, interaction_type: str, session: AsyncSession):
    try:
        # Проверяем существование записи
        query = select(Users_interaction).where(
            Users_interaction.user_id == user_id,
            Users_interaction.tmdb_id == movie_id
        )
        existing = await session.scalar(query)
        
        if existing:
            # Если запись существует, обновляем тип взаимодействия
            existing.interaction_type = interaction_type
        else:
            # Если записи нет, создаем новую
            obj = Users_interaction(
                user_id=user_id,
                tmdb_id=movie_id,
                interaction_type=interaction_type
            )
            session.add(obj)
        
        await session.commit()

        
    except Exception as e:
        await session.rollback()
        raise

#функция для получения фильмов по взаимодействию
async def get_movies_by_interaction(user_id: int, session: AsyncSession, interaction_types: list = None):
    #logger.debug(f"Получение фильмов для пользователя {user_id}, типы взаимодействия: {interaction_types}")
    
    # Начальный запрос
    query = select(Movies).join(Users_interaction).where(Users_interaction.user_id == user_id)
    
    # Если переданы типы взаимодействия, фильтруем по ним
    if interaction_types:
        query = query.where(Users_interaction.interaction_type.in_(interaction_types))
    
    try:
        # Выполняем запрос
        result = await session.scalars(query)
        movies = result.all()
        #logger.debug(f"Найдено {len(movies)} фильмов")
        return movies
    except Exception as e:
        return []
    
async def delete_movies_by_interaction(user_id: int, session: AsyncSession, interaction_types: list = None, movie_id: str = None):
    """Удаляет фильмы из базы данных по типу взаимодействия пользователя (like, dislike, unwatched)"""
    
    try:
        # Начальный запрос на выборку фильмов для пользователя
        query = select(Users_interaction).where(Users_interaction.user_id == user_id)
        
        # Если переданы типы взаимодействия, фильтруем по ним
        if interaction_types:
            query = query.where(Users_interaction.interaction_type.in_(interaction_types))
            
        # Если передан ID фильма, фильтруем по нему
        if movie_id:
            query = query.where(Users_interaction.tmdb_id == movie_id)

        # Выполняем запрос для получения всех записей
        result = await session.execute(query)
        interactions = result.scalars().all()

        # Если записей нет
        if not interactions:
            return

        # Логируем количество найденных записей
   


        # Для каждого взаимодействия удаляем запись
        for interaction in interactions:
            # Удаляем запись из таблицы взаимодействий
            await session.execute(delete(Users_interaction).where(Users_interaction.id == interaction.id))

        # Подтверждаем изменения
        await session.commit()

        #logger.info(f"Удалены {len(interactions)} фильмов для пользователя {user_id}")

    except Exception as e:
        await session.rollback()
        raise


#функция для получения предпочтений пользователя
async def get_user_preferences(user_id: int, session: AsyncSession):
    query = select(Users_anketa).where(Users_anketa.user_id == user_id)
    preferences = await session.scalar(query)
    return preferences


async def add_movies(
    session: AsyncSession,
    language: str = "ru-RU",
    source_path: str = "movie_ids.txt",
    limit: int = 20,
):
    # читаем id и приводим к int
    with open(source_path, "r", encoding="utf-8") as f:
        all_ids: list[int] = [int(line.strip()) for line in f if line.strip().isdigit()]
    movie_ids = all_ids[:limit]

    # Чтобы не падать на дубликатах — предварительно узнаём, что уже есть
    existing = await session.execute(
        select(Movies.tmdb_id).where(Movies.tmdb_id.in_(movie_ids))
    )
    existing_ids = set(existing.scalars().all())
    new_ids = [mid for mid in movie_ids if mid not in existing_ids]

    if not new_ids:
        return

    # Параллельный сбор данных с ограничением одновременных запросов
    sem = asyncio.Semaphore(8)  # подружите с лимитами TMDB
    async def bounded(mid: int):
        async with sem:
            return await fetch_movie_safe(mid, language)

    infos: Sequence[dict | None] = await asyncio.gather(*(bounded(mid) for mid in new_ids))

    objects: list[Movies] = []
    for info in infos:
        if not info:
            continue
        objects.append(
            Movies(
                tmdb_id=info["id"],
                title=info["title"],
                original_title=info["original_title"],
                description=info["overview"],
                vote_average=info["vote_average"],
                # если хотите — заполняйте оба поля одним значением
                poster=info["poster_path"],
                tmdb_poster_path=info["poster_path"],
                release_date=info["release_date"],   # Date | None
                genres=info["genres"],               # list[str] -> JSON
                runtime=info["runtime"],             # int | None
                keywords=info["keywords"],           # list[str] -> JSON
            )
        )

    if not objects:
        return

    session.add_all(objects)
    try:
        await session.commit()
    except Exception:
        await session.rollback()
        raise


#функция для проверки существования фильма в базе
async def get_movie_from_db(imdb: str, session: AsyncSession):
    query = select(Movies).where(Movies.tmdb_id == imdb)
    movie = await session.scalar(query)
    return movie


#Получает фильмы из базы данных по списку IMDb ID и возвращает словарь {imdb: movie}
async def get_movies_from_db_by_imdb_list(imdb_ids: list[str], session: AsyncSession) -> dict:
    if not imdb_ids:
        return {}

    stmt = select(Movies).where(Movies.tmdb_id.in_(imdb_ids))
    result = await session.scalars(stmt)
    return {movie.tmdb_id: movie for movie in result}



#сброс анкеты пользователя
async def reset_anketa_in_db(user_id: int, session: AsyncSession):
    try:
        # Ищем анкету пользователя в базе
        query = select(Users_anketa).where(Users_anketa.user_id == user_id)
        anketa = await session.scalar(query)
        
        if not anketa:
            raise ValueError(f"Анкета для пользователя {user_id} не найдена.")
        
        # Сбрасываем все поля анкеты на начальные значения
        anketa.user_rec_status = False  # Статус рекомендаций
        anketa.mood = ""
        anketa.genres = ""
        anketa.era = ""
        anketa.country = ""
        anketa.themes = ""
    
        
        # Сохраняем изменения в базе данных
        await session.commit()
        return "Анкета успешно сброшена"
    
    except Exception as e:
        await session.rollback()
        return f"Ошибка при сбросе анкеты: {e}"


                                

