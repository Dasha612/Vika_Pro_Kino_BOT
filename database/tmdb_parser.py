import os
import asyncio
import requests, gzip, json
import tmdbsimple as tmdb
from datetime import datetime, timedelta, timezone

from datetime import date

EXPORT_BASE_URL = "https://files.tmdb.org/p/exports"
OUT_FILE = "movie_ids.txt"

def tmdb_search_movie(movie_id: int, language: str = "ru-RU") -> dict | None:
    m = tmdb.Movies(movie_id)
    info = m.info(language=language, append_to_response="keywords")

    # -------- ФИЛЬТРАЦИЯ --------

    # 1. Фильтруем фильмы без русского описания
    overview = info.get("overview") or ""
    if not overview.strip():
        return None    

    # 2. Фильтрация короткометражек (жанр + runtime)
    genres_list = [g.get("name") for g in (info.get("genres") or []) if g.get("name")]

    runtime = info.get("runtime")
    is_short_genre = any(g.lower() in ("short", "короткометражка") for g in genres_list)
    is_short_runtime = isinstance(runtime, int) and runtime <= 40

    if is_short_genre or is_short_runtime:
        return None  
    
    if not info["poster_path"]:
        return None

    # -------- ОБЫЧНАЯ ОБРАБОТКА --------

    poster_path = info.get("poster_path") or None

    rel = (info.get("release_date") or "").strip()
    try:
        rel_date = date.fromisoformat(rel) if rel else None
    except ValueError:
        rel_date = None

    kw_block = info.get("keywords") or {}
    kw_list = kw_block.get("keywords") or kw_block.get("results") or []
    keywords = [k.get("name") for k in kw_list if k.get("name")]

    return {
        "id": info.get("id"),
        "title": info.get("title") or "",
        "original_title": info.get("original_title") or "",
        "release_date": rel_date,
        "overview": overview,
        "poster_path": f"https://image.tmdb.org/t/p/w500{poster_path}" if poster_path else None,
        "vote_average": float(info.get("vote_average") or 0.0),
        "genres": genres_list,
        "runtime": runtime if isinstance(runtime, int) else None,
        "status": info.get("status") or "",
        "keywords": keywords,
    }



def build_export_url(kind: str, date_obj) -> str:
    """kind: 'movie_ids', 'tv_series_ids', 'person_ids', ..."""
    return (
        f"{EXPORT_BASE_URL}/{kind}_"
        f"{date_obj.month:02d}_{date_obj.day:02d}_{date_obj.year}.json.gz"
    )

def get_latest_export_url(kind: str = "movie_ids", max_days_back: int = 10) -> str:
    """Пробуем найти самый свежий доступный экспорт, двигаясь назад по дням."""
    today_utc = datetime.now(timezone.utc).date()
    for delta in range(1, max_days_back + 1):
        d = today_utc - timedelta(days=delta)
        url = build_export_url(kind, d)
        r = requests.head(url)
        if r.ok:
            print("Нашли файл:", url)
            return url
    raise RuntimeError("Не удалось найти свежий экспорт TMDB за последние дни")

def refresh_tmdb_id_list():
    url = get_latest_export_url(kind="movie_ids")  # тут можно подставить другой kind
    gz_path = "movie_ids.json.gz"

    r = requests.get(url, stream=True)
    r.raise_for_status()

    with open(gz_path, "wb") as f:
        for chunk in r.iter_content(chunk_size=8192):
            f.write(chunk)

    with gzip.open(gz_path, "rt", encoding="utf-8") as f, open(OUT_FILE, "w", encoding="utf-8") as out:
        for line in f:
            data = json.loads(line)
            out.write(str(data["id"]) + "\n")

    os.remove(gz_path)
    print("Список ID фильмов сохранён в", OUT_FILE)



def load_all_tmdb_ids(path="movie_ids.txt") -> list[int]:
    with open(path, "r", encoding="utf-8") as f:
        return [int(line.strip()) for line in f if line.strip()]



def get_popular_ids(pages=50):
    ids = []
    for p in range(1, pages+1):
        resp = tmdb.Movies().popular(page=p)
        for item in resp["results"]:
            ids.append(item["id"])
    return ids