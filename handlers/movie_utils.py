import html
import logging
from urllib.parse import quote_plus

from aiogram import types
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import FSInputFile

logger = logging.getLogger(__name__)

# Локальная заглушка вместо внешней ссылки: не зависит от чужого хостинга.
FALLBACK_POSTER = FSInputFile("Images/NoImage.png")

# Telegram считает подпись к фото после разбора HTML — теги в лимит не входят.
MAX_CAPTION = 1024
# Суммарная длина подписей полей ("Название: ", "Год: " и т.д.) с переводами строк
LABELS_LENGTH = 70
# Запас на случай, если оценка длины окажется чуть оптимистичнее реальности
SAFETY_MARGIN = 24
# Даже когда места хватает, не вываливаем в карточку полотно текста
DESC_LIMIT = 550
TITLE_LIMIT = 200
GENRES_LIMIT = 150


def truncate(text: str, limit: int) -> str:
    text = text.strip()
    if limit <= 1:
        return ""
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _extract_movie_fields(movie) -> dict:
    """Извлекает поля из ORM-объекта Movies."""
    release = movie.release_date
    genres = ", ".join(movie.genres) if movie.genres else "Неизвестно"

    try:
        rating = round(float(movie.vote_average), 1)
    except (ValueError, TypeError):
        rating = "Нет данных"

    return {
        "title": movie.title or "Без названия",
        "poster_url": movie.poster or movie.tmdb_poster_path,
        "rating": rating,
        "year": release.year if release else "Неизвестно",
        "duration": f"{movie.runtime} мин" if movie.runtime else "Неизвестно",
        "genres": genres,
        "description": movie.description or "Описание отсутствует",
    }


def _build_caption(fields: dict) -> str:
    """Собирает подпись к карточке: экранированную и гарантированно короче лимита."""
    title = truncate(str(fields["title"]), TITLE_LIMIT)
    genres = truncate(str(fields["genres"]), GENRES_LIMIT)
    year = str(fields["year"])
    rating = str(fields["rating"])
    duration = str(fields["duration"])

    # Бюджет считаем по «видимой» длине, то есть до html.escape:
    # Telegram увидит '&', а не '&amp;', и посчитает его за один символ.
    used = LABELS_LENGTH + len(title) + len(year) + len(rating) + len(duration) + len(genres)
    budget = min(DESC_LIMIT, MAX_CAPTION - used - SAFETY_MARGIN)
    description = truncate(str(fields["description"]), budget)

    google_url = "https://www.google.com/search?q=" + quote_plus(f"смотреть фильм {title}")

    caption = (
        f"<b>Название:</b> {html.escape(title)}\n"
        f"<b>Год:</b> {year}\n"
        f"<b>Рейтинг:</b> {rating}\n"
        f"<b>Длительность:</b> {html.escape(duration)}\n"
        f"<b>Жанры:</b> {html.escape(genres)}\n\n"
    )
    if description:
        caption += f"<b>Описание:</b> {html.escape(description)}\n"
    caption += f'<a href="{google_url}">Смотреть</a>'
    return caption


async def _send(message: types.Message, photo, caption: str, keyboard, edit: bool) -> types.Message:
    if edit:
        return await message.edit_media(
            types.InputMediaPhoto(media=photo, caption=caption, parse_mode="HTML"),
            reply_markup=keyboard,
        )
    return await message.answer_photo(photo=photo, caption=caption, reply_markup=keyboard)


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

    caption = _build_caption(fields)
    poster_url = fields["poster_url"] or FALLBACK_POSTER
    keyboard = custom_keyboard(index) if custom_keyboard else None

    try:
        return await _send(message, poster_url, caption, keyboard, edit)
    except TelegramBadRequest as e:
        logger.warning("[Карточка] '%s' не отправилась (%s), пробую упрощённый вариант", fields["title"], e)

    # Запасной вариант должен быть ПРОЩЕ упавшего, иначе он упадёт так же.
    # Режим edit сохраняем, чтобы в чат не сыпались дубли карточек.
    minimal = (
        f"<b>{html.escape(truncate(str(fields['title']), TITLE_LIMIT))}</b>\n"
        f"{fields['year']} · ★ {fields['rating']}"
    )
    try:
        return await _send(message, FALLBACK_POSTER, minimal, keyboard, edit)
    except TelegramBadRequest as e:
        if not edit:
            raise
        logger.error("[Карточка] '%s': не удалось отредактировать, отправляю новым сообщением: %s", fields["title"], e)
        return await _send(message, FALLBACK_POSTER, minimal, keyboard, edit=False)
