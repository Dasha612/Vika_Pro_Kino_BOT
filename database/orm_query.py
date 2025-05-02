from database.models import Users_anketa, Users, Movies, Users_interaction
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime
from sqlalchemy import select, delete
import logging

logger = logging.getLogger(__name__)



#функция для добавления ответов пользователя в базу
async def orm_add_user_rec_set(user_id: int, session: AsyncSession, data: dict):
    try:
        query = select(Users_anketa).where(Users_anketa.user_id == user_id)
        existing = await session.scalar(query)

        if existing:
            # Обновляем существующую анкету
            existing.user_rec_status = True
            existing.ans1 = data['q1']
            existing.ans2 = data['q2']
            existing.ans3 = data['q3']
            existing.ans4 = data['q4']
            existing.ans5 = data['q5']
            existing.ans6 = data['q6']
            existing.ans7 = data['q7']
        else:
            # Вставляем новую анкету
            new_obj = Users_anketa(
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
            session.add(new_obj)

        await session.commit()

    except Exception as e:
        await session.rollback()
        logger.error(f"Ошибка при добавлении/обновлении анкеты пользователя {user_id}: {e}")
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
async def get_movies_by_interaction(user_id: int, session: AsyncSession, interaction_types: list = None):
    logger.debug(f"Получение фильмов для пользователя {user_id}, типы взаимодействия: {interaction_types}")
    
    # Начальный запрос
    query = select(Movies).join(Users_interaction).where(Users_interaction.user_id == user_id)
    
    # Если переданы типы взаимодействия, фильтруем по ним
    if interaction_types:
        query = query.where(Users_interaction.interaction_type.in_(interaction_types))
    
    try:
        # Выполняем запрос
        result = await session.scalars(query)
        movies = result.all()
        logger.debug(f"Найдено {len(movies)} фильмов")
        return movies
    except Exception as e:
        logger.error(f"Ошибка при получении фильмов: {e}", exc_info=True)
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
            query = query.where(Users_interaction.movie_id == movie_id)

        # Выполняем запрос для получения всех записей
        result = await session.execute(query)
        interactions = result.scalars().all()

        # Если записей нет
        if not interactions:
            logger.info(f"Для пользователя {user_id} не найдено фильмов с указанными параметрами.")
            return

        # Логируем количество найденных записей
        logger.info(f"Найдено {len(interactions)} записей для пользователя {user_id}")
        if interaction_types:
            logger.info(f"Типы взаимодействия: {interaction_types}")
        if movie_id:
            logger.info(f"ID фильма: {movie_id}")

        # Для каждого взаимодействия удаляем запись
        for interaction in interactions:
            # Удаляем запись из таблицы взаимодействий
            await session.execute(delete(Users_interaction).where(Users_interaction.id == interaction.id))

        # Подтверждаем изменения
        await session.commit()

        logger.info(f"Удалены {len(interactions)} фильмов для пользователя {user_id}")

    except Exception as e:
        logger.error(f"Ошибка при удалении фильмов для пользователя {user_id}: {e}", exc_info=True)
        await session.rollback()
        raise


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

async def get_movies_from_db_by_imdb_list(imdb_ids: list[str], session: AsyncSession) -> dict:
    """Получает фильмы из базы данных по списку IMDb ID и возвращает словарь {imdb: movie}"""
    if not imdb_ids:
        return {}

    stmt = select(Movies).where(Movies.imdb.in_(imdb_ids))
    result = await session.scalars(stmt)
    return {movie.imdb: movie for movie in result}


async def reset_anketa_in_db(user_id: int, session: AsyncSession):
    try:
        # Ищем анкету пользователя в базе
        query = select(Users_anketa).where(Users_anketa.user_id == user_id)
        anketa = await session.scalar(query)
        
        if not anketa:
            raise ValueError(f"Анкета для пользователя {user_id} не найдена.")
        
        # Сбрасываем все поля анкеты на начальные значения
        anketa.user_rec_status = False  # Статус рекомендаций
        anketa.ans1 = ""
        anketa.ans2 = ""
        anketa.ans3 = ""
        anketa.ans4 = ""
        anketa.ans5 = ""
        anketa.ans6 = ""
        anketa.ans7 = ""
        
        # Сохраняем изменения в базе данных
        await session.commit()
        return "Анкета успешно сброшена"
    
    except Exception as e:
        logger.error(f"Ошибка при сбросе анкеты для пользователя {user_id}: {e}")
        await session.rollback()
        return f"Ошибка при сбросе анкеты: {e}"


                                