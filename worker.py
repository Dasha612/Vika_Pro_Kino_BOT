import asyncio
import logging

from config import setup_logging
from database.engine import create_db, session_maker
from database.orm_query import update_movies_db
from database.tmdb_parser import refresh_tmdb_id_list

logger = logging.getLogger(__name__)

UPDATE_INTERVAL = 24 * 3600


async def run_worker():
    setup_logging()
    logger.info("[Worker] Запуск фонового worker-а")
    await create_db()

    while True:
        try:
            logger.info("[Worker] Обновление списка movie_ids.txt...")
            await asyncio.to_thread(refresh_tmdb_id_list)

            logger.info("[Worker] Догрузка новых фильмов из файла...")
            async with session_maker() as session:
                await update_movies_db(session, source="file")

            logger.info("[Worker] Цикл завершён, следующий через %d ч", UPDATE_INTERVAL // 3600)
        except Exception as e:
            logger.error("[Worker] Ошибка: %s", e, exc_info=True)

        await asyncio.sleep(UPDATE_INTERVAL)


if __name__ == "__main__":
    asyncio.run(run_worker())
