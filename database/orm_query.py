import asyncio
import json
import logging
from datetime import datetime

from sqlalchemy import select, delete, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.dialects.postgresql import insert

from database.models import Users_anketa, Users, Movies, Users_interaction
from database.embedding import get_model, build_movie_text, build_profile_text
from database.engine import redis_client
from database.tmdb_parser import tmdb_search_movie, load_all_tmdb_ids, get_popular_ids, fetch_movies_batch, get_popular_ids_async, TMDBFetcher
import time

PROFILE_VEC_TTL = 3600

# Сколько кандидатов HNSW просматривает при обходе индекса. По умолчанию в pgvector
# это 40 — меньше, чем LIMIT 50 в подборе по профилю, и тогда индекс физически
# не может вернуть полный список: выдача получается короче и хуже, чем реально есть в базе.
EF_SEARCH = 200

# Свободный текст юзера обрезаем: модель всё равно смотрит только первые ~128 токенов,
# а огромная строка — лишняя работа и лишний повод для сюрпризов.
MAX_QUERY_LEN = 500

logger = logging.getLogger(__name__)


async def orm_add_user_rec_set(user_id: int, session: AsyncSession, data: dict):
    try:
        def get_answer(key: str) -> str:
            return ", ".join(data.get(f"{key}_selected", []))

        mood = get_answer("question_1")
        genres = get_answer("question_2")
        era = get_answer("question_3")
        themes = get_answer("question_4")
        country = get_answer("question_5")

        logger.info(
            "[БД] Сохранение анкеты user_id=%s: mood='%s', genres='%s', era='%s', themes='%s', country='%s'",
            user_id, mood, genres, era, themes, country,
        )

        query = select(Users_anketa).where(Users_anketa.user_id == user_id)
        existing = await session.scalar(query)

        if existing:
            logger.debug("[БД] user_id=%s — обновление существующей анкеты", user_id)
            existing.user_rec_status = True
            existing.mood = mood
            existing.genres = genres
            existing.era = era
            existing.country = country
            existing.themes = themes
        else:
            logger.debug("[БД] user_id=%s — создание новой анкеты", user_id)
            new_obj = Users_anketa(
                user_id=user_id,
                user_rec_status=True,
                mood=mood,
                genres=genres,
                era=era,
                country=country,
                themes=themes,
            )
            session.add(new_obj)

        # Отложенные по «Стоп» фильмы подбирались под прежнюю анкету: без этого после
        # её смены подбор начинался бы с них. Удаляем в той же транзакции — заодно
        # они снова могут попасть в выдачу, если подходят и под новый профиль.
        await session.execute(
            delete(Users_interaction).where(
                Users_interaction.user_id == user_id,
                Users_interaction.interaction_type == "unwatched",
            )
        )

        await session.commit()
        await invalidate_profile_cache(user_id)
        logger.info("[БД] Анкета user_id=%s сохранена успешно", user_id)

    except Exception as e:
        await session.rollback()
        logger.error("Ошибка сохранения анкеты user_id=%s: %s", user_id, e)
        raise


async def add_user(user_id: int, session: AsyncSession):
    query = select(Users).where(Users.user_id == user_id)
    existing_user = await session.scalar(query)

    if not existing_user:
        logger.info("[БД] Новый пользователь user_id=%s — регистрация", user_id)
        current_time = datetime.now()
        obj = Users(
            user_id=user_id,
            user_start_date=current_time,
            user_end_date=current_time,
        )
        session.add(obj)
        await session.commit()
        return obj

    logger.debug("[БД] user_id=%s уже зарегистрирован", user_id)
    return existing_user


async def check_recommendations_status(user_id: int, session: AsyncSession):
    query = select(Users_anketa.user_rec_status).where(Users_anketa.user_id == user_id)
    status = await session.scalar(query)
    return status


async def add_movies_by_interaction(
    user_id: int, movie_id: int, interaction_type: str, session: AsyncSession
):
    try:
        # Раньше здесь был read-then-write: SELECT, потом INSERT или UPDATE.
        # Между этими двумя шагами второй быстрый тап успевал вставить свою строку,
        # и в таблице появлялся дубль — фильм потом показывался в избранном дважды.
        # ON CONFLICT решает это на стороне БД, опираясь на uq_user_movie.
        stmt = (
            insert(Users_interaction)
            .values(user_id=user_id, movie_id=movie_id, interaction_type=interaction_type)
            .on_conflict_do_update(
                constraint="uq_user_movie",
                set_={"interaction_type": interaction_type},
            )
        )
        logger.debug("[БД] user_id=%s, movie_id=%s — interaction: %s", user_id, movie_id, interaction_type)
        await session.execute(stmt)
        await session.commit()

    except Exception as e:
        await session.rollback()
        logger.error("[БД] Ошибка add_movies_by_interaction (user=%s, movie=%s, type=%s): %s", user_id, movie_id, interaction_type, e)
        raise


async def get_movies_by_interaction(
    user_id: int, session: AsyncSession, interaction_types: list | None = None
) -> list[Movies]:
    # ORDER BY обязателен: без него Postgres не гарантирует одинаковый порядок между
    # запросами, а пагинация избранного режет список в питоне — фильмы дублировались бы
    # и пропадали при листании. desc() = свежие взаимодействия сверху.
    query = (
        select(Movies)
        .join(Users_interaction)
        .where(Users_interaction.user_id == user_id)
        .order_by(Users_interaction.id.desc())
    )

    if interaction_types:
        query = query.where(Users_interaction.interaction_type.in_(interaction_types))

    try:
        result = await session.scalars(query)
        movies = list(result.all())
        logger.debug("[БД] get_movies_by_interaction: user_id=%s, types=%s → найдено %d", user_id, interaction_types, len(movies))
        return movies
    except Exception as e:
        logger.error("[БД] Ошибка get_movies_by_interaction (user=%s, types=%s): %s", user_id, interaction_types, e)
        return []



async def delete_movies_by_interaction(
    user_id: int,
    session: AsyncSession,
    interaction_types: list | None = None,
    movie_id: int | None = None,
):
    try:
        query = select(Users_interaction).where(Users_interaction.user_id == user_id)

        if interaction_types:
            query = query.where(Users_interaction.interaction_type.in_(interaction_types))

        if movie_id:
            query = query.where(Users_interaction.movie_id == movie_id)

        result = await session.execute(query)
        interactions = result.scalars().all()

        if not interactions:
            logger.debug("[БД] delete_movies_by_interaction: user_id=%s — нечего удалять (types=%s, movie=%s)", user_id, interaction_types, movie_id)
            return

        logger.info("[БД] delete_movies_by_interaction: user_id=%s — удаляю %d записей (types=%s, movie=%s)", user_id, len(interactions), interaction_types, movie_id)
        for interaction in interactions:
            await session.execute(
                delete(Users_interaction).where(Users_interaction.id == interaction.id)
            )

        await session.commit()

    except Exception as e:
        await session.rollback()
        logger.error("[БД] Ошибка delete_movies_by_interaction (user=%s, types=%s, movie=%s): %s", user_id, interaction_types, movie_id, e)
        raise


async def get_user_preferences(user_id: int, session: AsyncSession):
    query = select(Users_anketa).where(Users_anketa.user_id == user_id)
    return await session.scalar(query)


async def get_movie_from_db(tmdb_id: int, session: AsyncSession):
    query = select(Movies).where(Movies.tmdb_id == tmdb_id)
    return await session.scalar(query)


async def get_movies_from_db_by_tmdb_list(tmdb_ids: list[int], session: AsyncSession) -> dict:
    if not tmdb_ids:
        return {}
    stmt = select(Movies).where(Movies.tmdb_id.in_(tmdb_ids))
    result = await session.scalars(stmt)
    return {movie.tmdb_id: movie for movie in result}


async def reset_anketa_in_db(user_id: int, session: AsyncSession) -> str:
    try:
        query = select(Users_anketa).where(Users_anketa.user_id == user_id)
        anketa = await session.scalar(query)

        if not anketa:
            return "Анкета не найдена"

        anketa.user_rec_status = False
        anketa.mood = ""
        anketa.genres = ""
        anketa.era = ""
        anketa.country = ""
        anketa.themes = ""

        await session.commit()
        await invalidate_profile_cache(user_id)
        return "Анкета успешно сброшена"

    except Exception as e:
        await session.rollback()
        logger.error("Ошибка при сбросе анкеты user_id=%s: %s", user_id, e)
        return f"Ошибка при сбросе анкеты: {e}"


async def load_existing_tmdb_ids(session: AsyncSession) -> set[int]:
    result = await session.execute(select(Movies.tmdb_id))
    return set(result.scalars().all())


async def upsert_movie(session: AsyncSession, movie_dict: dict):
    stmt = insert(Movies).values(**movie_dict)
    stmt = stmt.on_conflict_do_update(
        index_elements=[Movies.tmdb_id],
        set_=movie_dict,
    )
    await session.execute(stmt)


async def upsert_movies_bulk(session: AsyncSession, movie_dicts: list[dict]):
    """Батчевый upsert — один INSERT на всю пачку."""
    if not movie_dicts:
        return
    stmt = insert(Movies).values(movie_dicts)
    update_cols = {c.name: c for c in stmt.excluded if c.name != "tmdb_id"}
    stmt = stmt.on_conflict_do_update(
        index_elements=[Movies.tmdb_id],
        set_=update_cols,
    )
    await session.execute(stmt)


def _info_to_movie_dict(info: dict, embedding: list[float]) -> dict:
    return {
        "tmdb_id": info["id"],
        "title": info["title"],
        "original_title": info["original_title"],
        "description": info["overview"],
        "vote_average": info["vote_average"],
        "vote_count": info["vote_count"],
        "popularity": info["popularity"],
        "poster": info["poster_path"],
        "tmdb_poster_path": info["poster_path"],
        "release_date": info["release_date"],
        "runtime": info["runtime"],
        "genres": info["genres"],
        "keywords": info["keywords"],
        "production_countries": info["production_countries"],
        "spoken_languages": info["spoken_languages"],
        "original_language": info["original_language"],
        "production_companies": info["production_companies"],
        "actors": info["actors"],
        "directors": info["directors"],
        "tagline": info["tagline"],
        "adult": info["adult"],
        "embedding": embedding,
    }


BATCH_SIZE = 1000


def _fmt_eta(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.0f} сек"
    if seconds < 3600:
        return f"{seconds / 60:.1f} мин"
    return f"{seconds / 3600:.1f} ч"


async def update_movies_db(
    session: AsyncSession,
    language: str = "ru-RU",
    limit: int | None = None,
    source: str = "popular",
):
    t_total = time.monotonic()

    # 1) Получаем список ID
    if source == "file":
        logger.info("[1/4] Загрузка ID из movie_ids.txt...")
        t0 = time.monotonic()
        all_ids = await asyncio.to_thread(load_all_tmdb_ids, "movie_ids.txt")
        logger.info("[1/4] Загружено %d ID из файла за %.1f сек", len(all_ids), time.monotonic() - t0)
    else:
        logger.info("[1/4] Загрузка popular ID с TMDB...")
        t0 = time.monotonic()
        all_ids = await get_popular_ids_async(50)
        logger.info("[1/4] Получено %d ID за %.1f сек", len(all_ids), time.monotonic() - t0)

    # 2) Фильтруем уже существующие
    # dict.fromkeys вместо чистого списка: popular-страницы опрашиваются параллельно,
    # и один и тот же фильм может попасть на две соседние страницы (рейтинг сдвигается
    # прямо во время обхода) — без дедупликации один tmdb_id дважды попадает в один
    # батч, а INSERT ... ON CONFLICT DO UPDATE не может обновить одну строку дважды
    # за раз (asyncpg.CardinalityViolationError). fromkeys, а не set() — чтобы
    # сохранить исходный порядок ID.
    existing_ids = await load_existing_tmdb_ids(session)
    new_ids = [mid for mid in dict.fromkeys(all_ids) if mid not in existing_ids]

    if limit:
        new_ids = new_ids[:limit]

    logger.info("[2/4] Новых: %d | В БД: %d | Всего ID: %d", len(new_ids), len(existing_ids), len(all_ids))
    if not new_ids:
        logger.info("Нечего добавлять, выход")
        return

    # 3) Загрузка модели
    logger.info("[3/4] Загрузка модели эмбеддингов...")
    t0 = time.monotonic()
    model = get_model()
    logger.info("[3/4] Модель готова за %.1f сек", time.monotonic() - t0)

    total_added = 0
    total_target = len(new_ids)
    total_batches = (total_target + BATCH_SIZE - 1) // BATCH_SIZE
    batch_times: list[float] = []

    fetcher = TMDBFetcher(max_concurrent=40, language=language)

    try:
        for batch_num, batch_start in enumerate(range(0, total_target, BATCH_SIZE), 1):
            batch_ids = new_ids[batch_start : batch_start + BATCH_SIZE]
            t_batch = time.monotonic()

            # --- TMDB API ---
            t0 = time.monotonic()
            movies_info, stats = await fetcher.fetch_batch(batch_ids)
            dt_api = time.monotonic() - t0

            if not movies_info:
                logger.warning(
                    "  Батч %d/%d пустой (fetched=%d, skip=%d, err=%d, 429=%d) — %.1f сек",
                    batch_num, total_batches, stats["fetched"], stats["skipped"],
                    stats["errors"], stats.get("rate_limited", 0), dt_api,
                )
                continue

            # --- Эмбеддинги ---
            t0 = time.monotonic()
            texts = [build_movie_text(info) for info in movies_info]
            vectors = await asyncio.to_thread(model.encode, texts, batch_size=256)
            dt_emb = time.monotonic() - t0

            # --- Запись в БД ---
            t0 = time.monotonic()
            movie_dicts = [
                _info_to_movie_dict(info, vec.tolist())
                for info, vec in zip(movies_info, vectors)
            ]
            await upsert_movies_bulk(session, movie_dicts)
            await session.commit()
            dt_db = time.monotonic() - t0

            total_added += len(movie_dicts)
            dt_batch_total = time.monotonic() - t_batch
            batch_times.append(dt_batch_total)

            avg_batch = sum(batch_times) / len(batch_times)
            remaining = (total_batches - batch_num) * avg_batch

            logger.info(
                "[4/4] Батч %d/%d | +%d фильмов | API %.1fs (%d ok/%d skip/%d err/%d 429) | "
                "Emb %.1fs | DB %.1fs | Батч %.1fs | %d/%d (%.0f%%) | ETA %s",
                batch_num, total_batches, len(movie_dicts),
                dt_api, stats["fetched"], stats["skipped"], stats["errors"],
                stats.get("rate_limited", 0),
                dt_emb, dt_db, dt_batch_total,
                total_added, total_target,
                total_added / total_target * 100,
                _fmt_eta(remaining),
            )
    finally:
        await fetcher.close()

    dt_total = time.monotonic() - t_total
    logger.info(
        "===== ГОТОВО: %d фильмов за %s (%.0f фильмов/сек) =====",
        total_added, _fmt_eta(dt_total), total_added / max(dt_total, 0.01),
    )


async def _get_profile_vec(user_id: int, session: AsyncSession) -> list[float] | None:
    """Возвращает эмбеддинг профиля: из Redis-кэша или вычисляет и кэширует."""
    cache_key = f"profile_vec:{user_id}"

    try:
        cached = await redis_client.get(cache_key)
        if cached:
            logger.debug("[Кэш] user_id=%s — profile_vec из Redis", user_id)
            return json.loads(cached)
    except Exception as e:
        logger.warning("[Кэш] Ошибка чтения Redis для user_id=%s: %s", user_id, e)

    user_anketa = await get_user_preferences(user_id, session)
    if not user_anketa:
        logger.warning("[Эмбеддинг] Анкета пользователя %s не найдена", user_id)
        return None

    profile_text = build_profile_text(user_anketa)
    if not profile_text.strip():
        logger.warning("[Эмбеддинг] user_id=%s — профильный текст пуст", user_id)
        return None

    logger.debug("[Эмбеддинг] user_id=%s — вычисляю profile_vec: '%s'", user_id, profile_text[:200])

    model = get_model()
    profile_vec = await asyncio.to_thread(model.encode, profile_text)
    profile_vec = profile_vec.tolist()

    try:
        await redis_client.set(cache_key, json.dumps(profile_vec), ex=PROFILE_VEC_TTL)
        logger.debug("[Кэш] user_id=%s — profile_vec сохранён в Redis (TTL=%ds)", user_id, PROFILE_VEC_TTL)
    except Exception as e:
        logger.warning("[Кэш] Ошибка записи Redis для user_id=%s: %s", user_id, e)

    return profile_vec


async def invalidate_profile_cache(user_id: int):
    """Удаляет кэш эмбеддинга профиля при изменении анкеты."""
    try:
        await redis_client.delete(f"profile_vec:{user_id}")
        logger.debug("[Кэш] user_id=%s — profile_vec инвалидирован", user_id)
    except Exception as e:
        logger.warning("[Кэш] Ошибка инвалидации Redis для user_id=%s: %s", user_id, e)


async def _search_by_vector(
    session: AsyncSession,
    user_id: int,
    vec: list[float],
    top_k: int,
) -> list[Movies]:
    """Ближайшие к вектору фильмы, за вычетом тех, что юзер уже видел.

    Общее тело для подбора по анкете и по свободному запросу: обе задачи —
    это поиск ближайших соседей, отличается только откуда взялся вектор.
    """
    # NOT EXISTS, а не NOT IN со списком id: тот вариант тянул все просмотренные
    # фильмы в python и подставлял их в запрос по одному bind-параметру на штуку.
    # У активного юзера это тысячи параметров (потолок Postgres — 65535) и запрос,
    # который планировщик не может нормально оценить. Здесь же фильтрация целиком
    # уходит в БД и опирается на индекс ix_user_interaction.
    seen = (
        select(Users_interaction.id)
        .where(
            Users_interaction.user_id == user_id,
            Users_interaction.movie_id == Movies.tmdb_id,
        )
        .exists()
    )

    query = (
        select(Movies)
        .where(Movies.embedding.is_not(None), ~seen)
        .order_by(Movies.embedding.cosine_distance(vec))
        .limit(top_k)
    )

    # SET LOCAL действует до конца текущей транзакции, то есть настройка не течёт
    # на соседние запросы и на другие соединения из пула.
    await session.execute(text(f"SET LOCAL hnsw.ef_search = {int(EF_SEARCH)}"))

    result = await session.scalars(query)
    return list(result.all())


async def get_movies_by_profile_embedding(
    session: AsyncSession,
    user_id: int,
    top_k: int = 50,
) -> list[Movies]:
    """Подобрать фильмы по эмбеддингу анкеты пользователя (pgvector HNSW)."""
    logger.info("[Эмбеддинг] Подбор фильмов для user_id=%s (top_k=%d)", user_id, top_k)

    profile_vec = await _get_profile_vec(user_id, session)
    if profile_vec is None:
        return []

    top_movies = await _search_by_vector(session, user_id, profile_vec, top_k)

    if top_movies:
        best = top_movies[0]
        logger.info(
            "[Эмбеддинг] user_id=%s — топ-1: '%s' (tmdb_id=%s), всего подобрано: %d",
            user_id, best.title, best.tmdb_id, len(top_movies),
        )
    else:
        logger.warning("[Эмбеддинг] user_id=%s — не найдено подходящих фильмов", user_id)

    return top_movies


async def get_movies_by_text_query(
    session: AsyncSession,
    user_id: int,
    query_text: str,
    top_k: int = 20,
) -> list[Movies]:
    """Подобрать фильмы по свободному запросу пользователя.

    Модель кладёт произвольный текст в то же векторное пространство, что и описания
    фильмов при наполнении базы, — поэтому запрос юзера ищется тем же способом,
    что и профиль. Никакой внешний LLM для этого не нужен.
    """
    query_text = (query_text or "").strip()[:MAX_QUERY_LEN]
    if not query_text:
        return []

    logger.info("[Поиск] user_id=%s — эмбеддинг запроса: '%s'", user_id, query_text)

    model = get_model()
    # encode() — синхронный CPU-bound вызов, в event loop его пускать нельзя:
    # он заблокировал бы всех остальных пользователей бота на время расчёта.
    vec = (await asyncio.to_thread(model.encode, query_text)).tolist()

    movies = await _search_by_vector(session, user_id, vec, top_k)

    if movies:
        logger.info(
            "[Поиск] user_id=%s — найдено %d, топ-1: '%s' (tmdb_id=%s)",
            user_id, len(movies), movies[0].title, movies[0].tmdb_id,
        )
    else:
        logger.warning("[Поиск] user_id=%s — по запросу ничего не найдено", user_id)

    return movies
