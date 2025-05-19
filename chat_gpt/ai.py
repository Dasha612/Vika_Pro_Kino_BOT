from openai import AsyncOpenAI
from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import AsyncSession
from aiogram.fsm.context import FSMContext


import os
from sqlalchemy.future import select
import logging
import re


from chat_gpt.questions import questions
from database.orm_query import get_user_preferences, get_movies_by_interaction


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()
client = AsyncOpenAI(api_key=os.getenv('CHATGPT_API_KEY'))

def extract_movies_from_gpt_response(response_text: str) -> list[str]:
    pattern = r"Movies\s*=\s*\[\s*(.*?)\s*\]"
    match = re.search(pattern, response_text, re.DOTALL)
    if not match:
        logger.warning(f"Pattern not found in GPT response: {response_text}")
        return []

    movies_string = match.group(1)
    return [movie.strip().strip('"').strip("'") for movie in re.split(r',\s*', movies_string)]


async def get_movie_recommendation_by_preferences(user_id: int, session=AsyncSession):
    preferences = await get_user_preferences(user_id, session)
    answers = {
        "rec1": "Ответ отсутствует",
        "rec2": "Ответ отсутствует",
        "rec3": "Ответ отсутствует",
        "rec4": "Ответ отсутствует",
        "rec5": "Ответ отсутствует",
    
    }
    if preferences:
        answers.update({
            "rec1": preferences.mood or "Ответ отсутствует",
            "rec2": preferences.genres or "Ответ отсутствует",
            "rec3": preferences.era or "Ответ отсутствует",
            "rec4": preferences.country or "Ответ отсутствует",
            "rec5": preferences.themes or "Ответ отсутствует",

        })
    
    # Формирование текста для GPT
    text = 'Я ответил на вопросы о фильмах. Порекомендуй мне фильмы.\n'
    for i, question in enumerate(questions):
        answer_key = f"rec{i + 1}"  # Ключи словаря rec1, rec2 и т. д.
        answer = answers.get(answer_key, "Ответ отсутствует")  # Берем ответ или пишем "Ответ отсутствует"
        text += f"Вопрос {i + 1}: {question}\nОтвет: {answer}\n\n"

    # Отправка запроса в OpenAI
    response = await client.chat.completions.create(
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a recommendation system for selecting movies based on the user's preferences. "
                    "Your task is to recommend movies for the user based on their preferences. "
                    "Output 10 movies that match the user's preferences. Below are the user's answers to the preference questions in Russian, "
                    "however, all movie titles you recommend should strictly be in English. The output data should be in the format of a Python list Movies = [], "
                    "containing only the movie titles in English."
                )
            },
            {
                "role": "user",
                "content": str(text)
            }
        ],
        model='gpt-4o'
    )

    content = response.choices[0].message.content
    logger.info(f"Extracted CHAT GPT data: {content}")

    return extract_movies_from_gpt_response(content)




async def get_movie_recommendation_by_interaction(user_id: int, session: AsyncSession, state: FSMContext = None):
    if state:
        data = await state.get_data()
        if data.get("preferences_priority"):
            logger.info("Приоритет отдан анкете, получаем рекомендации по ней")
            await state.update_data(preferences_priority=False)  # сбрасываем флаг, чтобы в следующий раз смотрели на лайки
            return await get_movie_recommendation_by_preferences(user_id=user_id, session=session)
        
    liked_movies = await get_movies_by_interaction(user_id, session, ['liked'])


    if len(liked_movies) >= 5:
        logger.info("_" * 100)
        logger.info("Вызываем рекомендации на основе пред рекомендаций")
        liked_movies = liked_movies[-5:]

        logger.info(f"Понравившиеся фильмы: {liked_movies}")
        logger.info("_" * 100)

        movies = liked_movies
        
        unique_movies = {}
        for movie in movies:
            if movie.imdb not in unique_movies:
                unique_movies[movie.imdb] = movie

        movies = list(unique_movies.values())

        # Формируем текст для GPT
        text = "Here are the movies that the user liked or watched recently:\n"
        for movie in movies:
            text += f"- {movie.movie_name} ({movie.movie_genre}, {movie.movie_year}, {movie.movie_rating}/10)\n"


        response = await client.chat.completions.create(
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a movie recommendation system. Based on the list of movies that the user liked or recently watched, "
                        "recommend 20 new movies that match the user's preferences in genre, tone, and style.\n\n"
                        "Do not recommend movies that the user has already watched or liked — only suggest new and different ones.\n\n"
                        "All recommended movie titles must be written strictly in English. "
                        "Return the recommendations in the format of a Python list: Movies = [ ], containing only the movie titles as strings and nothing else."
                    )
                },
                {
                    "role": "user",
                    "content": str(text)
                }
            ],
            model='gpt-4o'
        )
        logger.info(f"Response from movie_rec: {response}")


        content = response.choices[0].message.content
        logger.info(f"Extracted CHAT GPT data: {content}")
        return extract_movies_from_gpt_response(content)


    else:
        logger.info("_" * 100)
        logger.info("Недостаточно взаимодействий.\nВызываем рекомендации по анкете")
        logger.info("_" * 100)
        return await get_movie_recommendation_by_preferences(user_id=user_id, session=session)




async def get_movie_recommendation_by_search(user_id: int, text: str, session: AsyncSession):
    logger.info("_" * 100)
    logger.info(f"Запрос пользователя: {text}")
    
    response = await client.chat.completions.create(
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a movie recommendation system. Based on user request, "
                    "recommend 5 movies/series (Depending on what the user requests).\n\n"
                    "All recommended movie titles must be written strictly in English. "
                    "Return the recommendations in the format of a Python list: Movies = [ ], containing only the movie titles as strings and nothing else."
                )   
            },
            {
                "role": "user",
                "content": str(f"Find movies that match user's request: {text}")
            }
        ],
        model='gpt-4o'
    )

    content = response.choices[0].message.content
    logger.info(f"Extracted CHAT GPT data: {content}")
    logger.info("_" * 100)
    return extract_movies_from_gpt_response(content)

