import os
import logging
import requests
import gzip
import json
import asyncio
import time
import aiohttp
from datetime import date, datetime, timedelta, timezone

import tmdbsimple as tmdb
from config import cfg

logger = logging.getLogger(__name__)

tmdb.API_KEY = cfg.tmdb_api_key

EXPORT_BASE_URL = "https://files.tmdb.org/p/exports"
OUT_FILE = "movie_ids.txt"
TMDB_BASE = "https://api.themoviedb.org/3"


def _parse_movie_response(info: dict) -> dict | None:
    overview = info.get("overview") or ""
    if not overview.strip():
        return None

    genres_list = [g.get("name") for g in (info.get("genres") or []) if g.get("name")]

    runtime = info.get("runtime")
    is_short_genre = any(g.lower() in ("short", "короткометражка") for g in genres_list)
    is_short_runtime = isinstance(runtime, int) and runtime <= 40

    if is_short_genre or is_short_runtime:
        return None

    if not info.get("poster_path"):
        return None

    poster_path = info.get("poster_path")

    rel = (info.get("release_date") or "").strip()
    try:
        rel_date = date.fromisoformat(rel) if rel else None
    except ValueError:
        rel_date = None

    kw_block = info.get("keywords") or {}
    kw_list = kw_block.get("keywords") or kw_block.get("results") or []
    keywords = [k.get("name") for k in kw_list if k.get("name")]

    credits = info.get("credits") or {}
    cast = credits.get("cast") or []
    crew = credits.get("crew") or []
    actors = [a["name"] for a in cast[:15] if a.get("name")]
    directors = [c["name"] for c in crew if c.get("job") == "Director" and c.get("name")]

    countries = [c.get("name") or c.get("iso_3166_1", "") for c in (info.get("production_countries") or [])]
    languages = [l.get("name") or l.get("iso_639_1", "") for l in (info.get("spoken_languages") or [])]
    companies = [c.get("name") for c in (info.get("production_companies") or []) if c.get("name")]

    return {
        "id": info.get("id"),
        "title": info.get("title") or "",
        "original_title": info.get("original_title") or "",
        "release_date": rel_date,
        "overview": overview,
        "poster_path": f"https://image.tmdb.org/t/p/w500{poster_path}" if poster_path else None,
        "vote_average": float(info.get("vote_average") or 0.0),
        "vote_count": int(info.get("vote_count") or 0),
        "popularity": float(info.get("popularity") or 0.0),
        "genres": genres_list,
        "runtime": runtime if isinstance(runtime, int) else None,
        "status": info.get("status") or "",
        "keywords": keywords,
        "tagline": info.get("tagline") or "",
        "adult": bool(info.get("adult")),
        "original_language": info.get("original_language") or "",
        "production_countries": countries,
        "spoken_languages": languages,
        "production_companies": companies,
        "actors": actors,
        "directors": directors,
    }


def tmdb_search_movie(movie_id: int, language: str = "ru-RU") -> dict | None:
    try:
        m = tmdb.Movies(movie_id)
        info = m.info(language=language, append_to_response="keywords,credits")
    except Exception as e:
        logger.warning("TMDB API ошибка для movie_id=%s: %s", movie_id, e)
        return None
    return _parse_movie_response(info)


async def fetch_movie_async(
    http_session: aiohttp.ClientSession,
    movie_id: int,
    language: str,
    semaphore: asyncio.Semaphore,
    counter: dict,
) -> dict | None:
    async with semaphore:
        url = f"{TMDB_BASE}/movie/{movie_id}"
        params = {
            "api_key": cfg.tmdb_api_key,
            "language": language,
            "append_to_response": "keywords,credits",
        }
        for attempt in range(4):
            try:
                async with http_session.get(url, params=params) as resp:
                    if resp.status == 429:
                        retry_after = float(resp.headers.get("Retry-After", 2))
                        wait = retry_after * (2 ** attempt)
                        counter["rate_limited"] = counter.get("rate_limited", 0) + 1
                        logger.debug("429 для movie_id=%s, ждём %.1fs (попытка %d)", movie_id, wait, attempt + 1)
                        await asyncio.sleep(wait)
                        continue
                    if resp.status != 200:
                        counter["skipped"] += 1
                        return None
                    info = await resp.json()
            except asyncio.TimeoutError:
                counter["errors"] += 1
                if attempt < 3:
                    await asyncio.sleep(1 * (2 ** attempt))
                    continue
                return None
            except Exception:
                counter["errors"] += 1
                return None

            counter["fetched"] += 1
            return _parse_movie_response(info)

        counter["errors"] += 1
        return None


class TMDBFetcher:
    """Переиспользуемая aiohttp-сессия с адаптивным concurrency."""

    def __init__(self, max_concurrent: int = 40, language: str = "ru-RU"):
        self._max_concurrent = max_concurrent
        self._current_concurrent = max_concurrent
        self._language = language
        self._session: aiohttp.ClientSession | None = None

    async def _ensure_session(self):
        if self._session is None or self._session.closed:
            connector = aiohttp.TCPConnector(limit=self._max_concurrent, limit_per_host=self._max_concurrent)
            timeout = aiohttp.ClientTimeout(total=20, connect=5)
            # trust_env: подхватить HTTP_PROXY/HTTPS_PROXY из окружения, если заданы
            # (нужно локально, когда TMDB доступен только через прокси/VPN). На проде,
            # где эти переменные не выставлены, ничего не меняет.
            self._session = aiohttp.ClientSession(connector=connector, timeout=timeout, trust_env=True)

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()

    async def fetch_batch(self, movie_ids: list[int]) -> tuple[list[dict], dict]:
        await self._ensure_session()
        semaphore = asyncio.Semaphore(self._current_concurrent)
        counter = {"fetched": 0, "skipped": 0, "errors": 0, "rate_limited": 0}

        tasks = [
            fetch_movie_async(self._session, mid, self._language, semaphore, counter)
            for mid in movie_ids
        ]
        raw = await asyncio.gather(*tasks, return_exceptions=True)

        rate_limited = counter.get("rate_limited", 0)
        if rate_limited > len(movie_ids) * 0.1:
            old = self._current_concurrent
            self._current_concurrent = max(10, self._current_concurrent // 2)
            logger.warning(
                "[TMDB] Много 429 (%d), снижаю concurrency: %d → %d",
                rate_limited, old, self._current_concurrent,
            )
        elif rate_limited == 0 and self._current_concurrent < self._max_concurrent:
            old = self._current_concurrent
            self._current_concurrent = min(self._max_concurrent, self._current_concurrent + 5)
            logger.info("[TMDB] Нет 429, повышаю concurrency: %d → %d", old, self._current_concurrent)

        results = [item for item in raw if isinstance(item, dict)]
        return results, counter


async def fetch_movies_batch(
    movie_ids: list[int],
    language: str = "ru-RU",
    max_concurrent: int = 40,
) -> tuple[list[dict], dict]:
    """Обратно-совместимая обёртка — создаёт одноразовый fetcher."""
    fetcher = TMDBFetcher(max_concurrent=max_concurrent, language=language)
    try:
        return await fetcher.fetch_batch(movie_ids)
    finally:
        await fetcher.close()


async def get_popular_ids_async(pages: int = 50) -> list[int]:
    """Получает popular IDs параллельно через aiohttp."""
    ids: list[int] = []
    semaphore = asyncio.Semaphore(20)
    connector = aiohttp.TCPConnector(limit=20, limit_per_host=20)
    timeout = aiohttp.ClientTimeout(total=10)

    async def _fetch_page(session: aiohttp.ClientSession, page: int):
        async with semaphore:
            url = f"{TMDB_BASE}/movie/popular"
            params = {"api_key": cfg.tmdb_api_key, "page": page}
            try:
                async with session.get(url, params=params) as resp:
                    if resp.status == 429:
                        await asyncio.sleep(float(resp.headers.get("Retry-After", 1)))
                        async with session.get(url, params=params) as resp2:
                            if resp2.status != 200:
                                return []
                            data = await resp2.json()
                    elif resp.status != 200:
                        return []
                    else:
                        data = await resp.json()
                return [item["id"] for item in data.get("results", [])]
            except Exception as e:
                logger.warning("popular page=%d ошибка: %s", page, e)
                return []

    async with aiohttp.ClientSession(connector=connector, timeout=timeout, trust_env=True) as session:
        tasks = [_fetch_page(session, p) for p in range(1, pages + 1)]
        results = await asyncio.gather(*tasks)

    for page_ids in results:
        ids.extend(page_ids)

    return ids


def get_popular_ids(pages: int = 50) -> list[int]:
    ids = []
    for p in range(1, pages + 1):
        try:
            resp = tmdb.Movies().popular(page=p)
            for item in resp.get("results", []):
                ids.append(item["id"])
        except Exception as e:
            logger.warning("Ошибка при получении popular page=%d: %s", p, e)
            break
    return ids


def build_export_url(kind: str, date_obj) -> str:
    return (
        f"{EXPORT_BASE_URL}/{kind}_"
        f"{date_obj.month:02d}_{date_obj.day:02d}_{date_obj.year}.json.gz"
    )


def get_latest_export_url(kind: str = "movie_ids", max_days_back: int = 10) -> str:
    today_utc = datetime.now(timezone.utc).date()
    for delta in range(1, max_days_back + 1):
        d = today_utc - timedelta(days=delta)
        url = build_export_url(kind, d)
        try:
            r = requests.head(url, timeout=10)
            if r.ok:
                logger.info("Нашли файл: %s", url)
                return url
        except requests.RequestException as e:
            logger.warning("Ошибка при проверке %s: %s", url, e)
    raise RuntimeError("Не удалось найти свежий экспорт TMDB за последние дни")


def refresh_tmdb_id_list():
    url = get_latest_export_url(kind="movie_ids")
    gz_path = "movie_ids.json.gz"

    r = requests.get(url, stream=True, timeout=60)
    r.raise_for_status()

    with open(gz_path, "wb") as f:
        for chunk in r.iter_content(chunk_size=8192):
            f.write(chunk)

    with gzip.open(gz_path, "rt", encoding="utf-8") as f, open(OUT_FILE, "w", encoding="utf-8") as out:
        for line in f:
            data = json.loads(line)
            out.write(str(data["id"]) + "\n")

    os.remove(gz_path)
    logger.info("Список ID фильмов сохранён в %s", OUT_FILE)


def load_all_tmdb_ids(path="movie_ids.txt") -> list[int]:
    with open(path, "r", encoding="utf-8") as f:
        return [int(line.strip()) for line in f if line.strip()]
