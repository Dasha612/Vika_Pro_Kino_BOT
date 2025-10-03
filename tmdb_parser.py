import aiohttp
import os
import asyncio
import requests, gzip, json
import tmdbsimple as tmdb



BASE_URL = "https://api.themoviedb.org/3"


def tmdb_search_movie(movie_id, language="en-EN"):
    """
    Получает информацию об одном фильме по ID
    """
    tmdb.API_KEY = '756fb2b27178a4e70deec129636a1843'
    tmdb.REQUESTS_TIMEOUT = 5 
    
    try:
        movie = tmdb.Movies(movie_id)
        movie_info = movie.info(language=language)  
        keywords_info = movie.keywords()
        keywords = [keyword['name'] for keyword in keywords_info.get('keywords', [])]   
        return {
            'id': movie_info.get('id'),
            'title': movie_info.get('title'),
            'original_title': movie_info.get('original_title'),
            'release_date': movie_info.get('release_date', ''),
            'overview': movie_info.get('overview', ''),
            'poster_path': f"https://image.tmdb.org/t/p/w500{movie_info.get('poster_path')}" if movie_info.get('poster_path') else None,
            'vote_average': movie_info.get('vote_average', 0),
            'genres': [genre['name'] for genre in movie_info.get('genres', [])],
            'runtime': movie_info.get('runtime', 0),
            'status': movie_info.get('status', ''),
            'keywords':  keywords
        }
        
    except Exception as e:
        print(f"Ошибка при получении фильма ID {movie_id}: {e}")
        return None

def get_movies_by_ids(movie_ids, language="en-EN"):
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


if __name__ == "__main__":

    with open('movie_ids.txt', 'r') as f:
        all_movie_ids = [line.strip() for line in f if line.strip()]
    
 
    test_ids = all_movie_ids[:5]
    print(f"Получаем информацию для {len(test_ids)} фильмов...")
    
    movies = get_movies_by_ids(test_ids, language="ru-RU")
    print(movies)
    


def _refresh_tbdb_id_list():
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



