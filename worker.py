import asyncio
import logging
import os
import time

from config import setup_logging
from database.engine import session_maker
from database.orm_query import update_movies_db
from database.tmdb_parser import refresh_tmdb_id_list

logger = logging.getLogger(__name__)

UPDATE_INTERVAL = 24 * 3600
# Если цикл упал (нет схемы, TMDB недоступен) — повторить через 5 минут, а не через сутки
RETRY_INTERVAL = 300
# Схему создаёт бот в on_startup; ждём, чтобы не создавать её параллельно
STARTUP_DELAY = 15

# Сколько новых фильмов догружать за один цикл.
# В movie_ids.txt около миллиона ID — попытка взять их все за раз растянется на сутки.
BATCH_PER_CYCLE = 5000

ID_FILE = "movie_ids.txt"
# Экспорт TMDB обновляется раз в сутки, но пока в файле остаются необработанные ID,
# перекачивать 90 МБ бессмысленно
ID_FILE_MAX_AGE = 7 * 24 * 3600


def _needs_id_refresh() -> bool:
    if not os.path.exists(ID_FILE):
        return True
    return time.time() - os.path.getmtime(ID_FILE) > ID_FILE_MAX_AGE


async def run_worker():
    setup_logging()
    logger.info("[Worker] Запуск, жду инициализации схемы ботом (%d сек)...", STARTUP_DELAY)
    await asyncio.sleep(STARTUP_DELAY)

    while True:
        delay = UPDATE_INTERVAL
        try:
            if _needs_id_refresh():
                logger.info("[Worker] Обновление списка %s...", ID_FILE)
                await asyncio.to_thread(refresh_tmdb_id_list)
            else:
                logger.info("[Worker] %s свежий, пропускаю скачивание", ID_FILE)

            logger.info("[Worker] Догрузка до %d новых фильмов из файла...", BATCH_PER_CYCLE)
            async with session_maker() as session:
                await update_movies_db(session, source="file", limit=BATCH_PER_CYCLE)

            logger.info("[Worker] Цикл завершён, следующий через %d ч", UPDATE_INTERVAL // 3600)
        except Exception as e:
            delay = RETRY_INTERVAL
            logger.error("[Worker] Ошибка: %s. Повтор через %d мин", e, RETRY_INTERVAL // 60, exc_info=True)

        await asyncio.sleep(delay)


if __name__ == "__main__":
    asyncio.run(run_worker())
