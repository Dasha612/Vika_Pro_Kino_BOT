import os
import asyncio
from sqlalchemy import select, func

import tmdbsimple as tmdb
from database.engine import create_db, drop_db, session_maker
from database.models import Movies
from database.orm_query import add_movies

# 1) ENV (важно!)
tmdb.API_KEY = os.getenv("TMDB_API_KEY")

async def main():
    # Чистый тест: пересоздадим таблицы
    await drop_db()
    await create_db()

    # 2) Заполним "movie_ids.txt", если его нет
    if not os.path.exists("movie_ids.txt"):
        with open("movie_ids.txt", "w", encoding="utf-8") as f:
            # Пара известных TMDB ID для проверки
            f.write("603692\n")  # John Wick: Chapter 4 (пример)
            f.write("299534\n")  # Avengers: Endgame (пример)

    # 3) Добавляем фильмы
    async with session_maker() as session:
        await add_movies(session)   # твоя функция

        # 4) Проверяем количество и печатаем несколько записей
        total = await session.scalar(select(func.count()).select_from(Movies))
        print(f"Всего фильмов в БД: {total}")

        rows = (await session.execute(select(Movies).limit(5))).scalars().all()
        for m in rows:
            print(f"[{m.tmdb_id}] {m.title} | {m.release_date} | rating={m.vote_average}")

if __name__ == "__main__":
    # Требуются переменные окружения:
    #   DB_URL (postgresql+asyncpg://...),
    #   TMDB_API_KEY
    asyncio.run(main())
