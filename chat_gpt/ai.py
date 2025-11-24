from openai import AsyncOpenAI
from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import AsyncSession
from aiogram.fsm.context import FSMContext


import os
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
    # Отправка запроса в OpenAI
    system = """You are a movie ranker.
    Select ONLY from the 'candidates' list. Don't add anything from outside.
    Exclude 'blocked_ids'. Return unique IDs. Format: JSON according to schema.
    Optimize for user preferences and variety."""
    


  

    


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

