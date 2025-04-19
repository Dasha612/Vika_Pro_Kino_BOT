from openai import AsyncOpenAI
from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import AsyncSession


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
        "rec6": "Ответ отсутствует",
        "rec7": "Ответ отсутствует",    
    }
    if preferences:
        answers.update({
            "rec1": preferences.ans1 or "Ответ отсутствует",
            "rec2": preferences.ans2 or "Ответ отсутствует",
            "rec3": preferences.ans3 or "Ответ отсутствует",
            "rec4": preferences.ans4 or "Ответ отсутствует",
            "rec5": preferences.ans5 or "Ответ отсутствует",
            "rec6": preferences.ans6 or "Ответ отсутствует",
            "rec7": preferences.ans7 or "Ответ отсутствует",
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
        model='gpt-4o-mini-2024-07-18'
    )

    content = response.choices[0].message.content
    logger.info(f"Extracted CHAT GPT data: {content}")

    return extract_movies_from_gpt_response(content)




async def get_movie_recommendation_by_interaction(user_id: int, session: AsyncSession):
    liked_movies = await get_movies_by_interaction(user_id, session, ['like'])
    watched_movies = await get_movies_by_interaction(user_id, session, ['watched'])

    if len(watched_movies) >= 5 or len(liked_movies) >= 5:
        logger.info("_" * 100)
        logger.info("Вызываем рекомендации на основе пред рекомендаций")

        watched_movies = watched_movies[-5:]
        liked_movies = liked_movies[-5:]
        # Логирование для проверки
        logger.info(f"Просмотренные фильмы: {watched_movies}")
        logger.info(f"Понравившиеся фильмы: {liked_movies}")
        logger.info("_" * 100)

        movies = watched_movies + liked_movies
        
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
                        "recommend 10 new movies that match the user's preferences in genre, tone, and style.\n\n"
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
            model='gpt-4o-mini-2024-07-18'
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

