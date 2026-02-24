import logging
import aiohttp
from aiogram import types

logger = logging.getLogger(__name__)

FALLBACK_POSTER = "https://i.imgur.com/RwD6GYr.png"


async def is_url_valid(url: str) -> bool:
    try:
        async with aiohttp.ClientSession() as session:
            async with session.head(url, timeout=aiohttp.ClientTimeout(total=3)) as resp:
                return resp.status == 200
    except Exception:
        return False


def _extract_movie_fields(movie) -> dict:
    """Извлекает поля из ORM-объекта Movies или из словаря."""
    if isinstance(movie, dict):
        title = movie.get("title", "Без названия")
        poster_url = movie.get("poster")
        rating = movie.get("vote_average", 0)
        year = movie.get("year", "Неизвестно")
        duration = movie.get("runtime", "Неизвестно")
        genres = movie.get("genres", "Неизвестно")
        description = movie.get("description", "Описание отсутствует")
    else:
        title = movie.title or "Без названия"
        poster_url = movie.poster or movie.tmdb_poster_path
        rating = movie.vote_average or 0
        release = movie.release_date
        year = release.year if release else "Неизвестно"
        duration = f"{movie.runtime} мин" if movie.runtime else "Неизвестно"
        genres = ", ".join(movie.genres) if movie.genres else "Неизвестно"
        description = movie.description or "Описание отсутствует"

    if isinstance(genres, list):
        genres = ", ".join(genres)

    try:
        rating = round(float(rating), 1)
    except (ValueError, TypeError):
        rating = "Нет данных"

    return {
        "title": title,
        "poster_url": poster_url,
        "rating": rating,
        "year": year,
        "duration": duration,
        "genres": genres,
        "description": description,
    }


async def send_movie_card(
    message: types.Message,
    movie,
    index: int,
    edit: bool = False,
    custom_keyboard=None,
) -> types.Message:
    """Отправка или редактирование карточки фильма."""
    fields = _extract_movie_fields(movie)
    logger.info(
        "[Карточка] %s фильм #%d: '%s' (%s), рейтинг=%s",
        "Редактирую" if edit else "Отправляю", index + 1, fields["title"], fields["year"], fields["rating"],
    )

    title = fields["title"]
    google_search_url = f"https://www.google.com/search?q=смотреть+фильм+{title.replace(' ', '+')}"
    poster_url = fields["poster_url"] or FALLBACK_POSTER

    movie_text = (
        f"<b>Название:</b> {title}\n"
        f"<b>Год:</b> {fields['year']}\n"
        f"<b>Рейтинг:</b> {fields['rating']}\n"
        f"<b>Длительность:</b> {fields['duration']}\n"
        f"<b>Жанры:</b> {fields['genres']}\n\n"
        f"<b>Описание:</b> {fields['description']}\n"
        f'<a href="{google_search_url}">Смотреть</a>'
    )

    keyboard = custom_keyboard(index) if custom_keyboard else None

    try:
        if edit:
            msg = await message.edit_media(
                types.InputMediaPhoto(
                    media=poster_url,
                    caption=movie_text,
                    parse_mode="HTML",
                ),
                reply_markup=keyboard,
            )
        else:
            msg = await message.answer_photo(
                photo=poster_url,
                caption=movie_text,
                reply_markup=keyboard,
            )
    except Exception as e:
        logger.error("[Карточка] Ошибка отправки '%s' (poster=%s): %s", fields["title"], poster_url, e)
        msg = await message.answer_photo(
            photo=FALLBACK_POSTER,
            caption=movie_text,
            reply_markup=keyboard,
        )

    return msg
