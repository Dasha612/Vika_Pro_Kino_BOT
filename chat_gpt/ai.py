import re
import logging

from openai import AsyncOpenAI
from sqlalchemy.ext.asyncio import AsyncSession

from config import cfg
from database.orm_query import get_user_preferences, get_movies_by_interaction

logger = logging.getLogger(__name__)

client = AsyncOpenAI(api_key=cfg.openai_api_key) if cfg.openai_api_key else None


def extract_movies_from_gpt_response(response_text: str) -> list[str]:
    pattern = r"Movies\s*=\s*\[\s*(.*?)\s*\]"
    match = re.search(pattern, response_text, re.DOTALL)
    if not match:
        logger.warning("Pattern not found in GPT response: %s", response_text[:200])
        return []

    movies_string = match.group(1)
    return [movie.strip().strip('"').strip("'") for movie in re.split(r",\s*", movies_string)]


async def get_movie_recommendation_by_preferences(user_id: int, session: AsyncSession):
    if not client:
        logger.error("[GPT] OpenAI API ключ не задан")
        return []

    logger.info("[GPT] Запрос рекомендаций по предпочтениям для user_id=%s", user_id)
    return []


async def get_movie_recommendation_by_search(user_id: int, text: str, session: AsyncSession):
    if not client:
        logger.error("[GPT] OpenAI API ключ не задан")
        return []

    logger.info("[GPT] user_id=%s — поисковый запрос: '%s'", user_id, text)

    try:
        response = await client.chat.completions.create(
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a movie recommendation system. Based on user request, "
                        "recommend 5 movies/series (Depending on what the user requests).\n\n"
                        "All recommended movie titles must be written strictly in English. "
                        "Return the recommendations in the format of a Python list: "
                        "Movies = [ ], containing only the movie titles as strings and nothing else."
                    ),
                },
                {
                    "role": "user",
                    "content": f"Find movies that match user's request: {text}",
                },
            ],
            model="gpt-4o",
            timeout=30,
        )

        content = response.choices[0].message.content
        logger.info("[GPT] user_id=%s — ответ GPT: %s", user_id, content[:200])
        movies = extract_movies_from_gpt_response(content)
        logger.info("[GPT] user_id=%s — извлечено фильмов: %d (%s)", user_id, len(movies), movies)
        return movies

    except Exception as e:
        logger.error("[GPT] user_id=%s — ошибка OpenAI API: %s", user_id, e)
        return []
