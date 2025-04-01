from database.models import Users_anketa, Users, Movies, Users_interaction
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime
from sqlalchemy import select
import logging

logger = logging.getLogger(__name__)



#функция для добавления ответов пользователя в базу
async def orm_add_user_rec_set(user_id: int, session: AsyncSession, data: dict):
    obj  = Users_anketa(
        user_id=user_id,
        user_rec_status=True,
        ans1=data['q1'],
        ans2=data['q2'],
        ans3=data['q3'],
        ans4=data['q4'],
        ans5=data['q5'],
        ans6=data['q6'],
        ans7=data['q7'],
    )
    session.add(obj)
    await session.commit()



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
            Users_interaction.movie_id == movie_id
        )
        existing = await session.scalar(query)
        
        if existing:
            # Если запись существует, обновляем тип взаимодействия
            existing.interaction_type = interaction_type
        else:
            # Если записи нет, создаем новую
            obj = Users_interaction(
                user_id=user_id,
                movie_id=movie_id,
                interaction_type=interaction_type
            )
            session.add(obj)
        
        await session.commit()
        logger.info(f"Успешно сохранено взаимодействие: user_id={user_id}, movie_id={movie_id}, type={interaction_type}")
        
    except Exception as e:
        logger.error(f"Ошибка при сохранении взаимодействия: {e}")
        await session.rollback()
        raise

#функция для получения фильмов по взаимодействию
async def get_movies_by_interaction(user_id: int, session: AsyncSession, interaction_type: str = None):
    logger.debug(f"Получение фильмов для пользователя {user_id}, тип взаимодействия: {interaction_type}")
    
    query = select(Movies).join(Users_interaction).where(Users_interaction.user_id == user_id)
    
    if interaction_type:
        query = query.where(Users_interaction.interaction_type == interaction_type)
    
    try:
        result = await session.scalars(query)
        movies = result.all()
        logger.debug(f"Найдено {len(movies)} фильмов")
        return movies
    except Exception as e:
        logger.error(f"Ошибка при получении фильмов: {e}", exc_info=True)
        return []


#функция для получения предпочтений пользователя
async def get_user_preferences(user_id: int, session: AsyncSession):
    query = select(Users_anketa).where(Users_anketa.user_id == user_id)
    preferences = await session.scalar(query)
    return preferences



#функция для добавления фильма в базу
async def add_movie(movie_id: str, movie_name: str, movie_description: str, movie_rating: float, movie_poster: str, movie_year: int, movie_genre: str, movie_duration: int, session: AsyncSession):
    obj = Movies(
        imdb=movie_id,
        movie_name=movie_name,
        movie_description=movie_description,
        movie_year=movie_year,
        movie_poster=movie_poster,
        movie_rating=movie_rating,
        movie_genre=movie_genre,
        movie_duration=movie_duration,

    )
    session.add(obj)
    await session.commit()



#функция для проверки существования фильма в базе
async def get_movie_from_db(imdb: str, session: AsyncSession):
    query = select(Movies).where(Movies.imdb == imdb)
    movie = await session.scalar(query)
    return movie
