import aiohttp
import os
import asyncio
import requests, gzip, json
import tmdbsimple as tmdb

from datetime import date

BASE_URL = "https://api.themoviedb.org/3"


def tmdb_search_movie(movie_id: int, language: str = "en-US") -> dict | None:
    """СИНХРОННАЯ функция: один HTTP-запрос к tmdbsimple (info + keywords)."""
    m = tmdb.Movies(movie_id)
    info = m.info(language=language, append_to_response="keywords")

    poster_path = info.get("poster_path") or None
    rel = (info.get("release_date") or "").strip()
    try:
        rel_date = date.fromisoformat(rel) if rel else None
    except ValueError:
        rel_date = None

    kw_block = (info.get("keywords") or {})
    kw_list = kw_block.get("keywords") or kw_block.get("results") or []
    keywords = [k.get("name") for k in kw_list if k.get("name")]

    return {
        "id": info.get("id"),
        "title": info.get("title") or "",
        "original_title": info.get("original_title") or "",
        "release_date": rel_date,  # datetime.date | None
        "overview": info.get("overview") or "",
        "poster_path": f"https://image.tmdb.org/t/p/w500{poster_path}" if poster_path else None,
        "vote_average": float(info.get("vote_average") or 0.0),
        "genres": [g.get("name") for g in (info.get("genres") or []) if g.get("name")],
        "runtime": info.get("runtime") if isinstance(info.get("runtime"), int) else None,
        "status": info.get("status") or "",
        "keywords": keywords,
    }

async def fetch_movie_safe(movie_id: int, language: str) -> dict | None:
    """Не блокируем event loop: выносим sync TMDB-вызов в поток."""
    return await asyncio.to_thread(tmdb_search_movie, movie_id, language)


async def get_movies_by_ids(movie_ids, language="en-EN"):
    """
    Получает информацию о нескольких фильмах по списку ID
    """
    movies_info = []
    
    for movie_id in movie_ids:
        movie_info = tmdb_search_movie(movie_id, language)
        if movie_info:
            movies_info.append(movie_info)
            print(f"Успешно получен фильм: {movie_info['title']} (ID: {movie_id}) keywords = {movie_info['keywords']}")
    
    return movies_info



async def _refresh_tbdb_id_list():
    url = "http://files.tmdb.org/p/exports/movie_ids_09_30_2025.json.gz"
    out_file = "movie_ids.txt"

    r = requests.get(url, stream=True)
    r.raise_for_status()

    with open("movie_ids.json.gz", "wb") as f:
        for chunk in r.iter_content(chunk_size=8192):
            f.write(chunk)


    with gzip.open("movie_ids.json.gz", "rt", encoding="utf-8") as f, open(out_file, "w") as out:
        for line in f:
            data = json.loads(line) 
            out.write(str(data["id"]) + "\n")

    print("Список ID фильмов сохранён в", out_file)





if __name__ == "__main__":
    #_refresh_tbdb_id_list()

    with open('movie_ids.txt', 'r') as f:
        all_movie_ids = [line.strip() for line in f if line.strip()]
    
 
    test_ids = all_movie_ids[:5]
    print(f"Получаем информацию для {len(test_ids)} фильмов...")
    
    movies = get_movies_by_ids(test_ids, language="ru-RU")
    print(movies)
    

