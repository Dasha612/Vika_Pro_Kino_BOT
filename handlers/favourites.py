import html
import logging
from urllib.parse import quote_plus

from aiogram import Router, Bot, F
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy.ext.asyncio import AsyncSession

from handlers.movie_utils import truncate
from database.orm_query import get_movies_by_interaction

logger = logging.getLogger(__name__)

favourites_router = Router()

MOVIES_PER_PAGE = 5
# В списке из пяти строк длинное название только мешает читать
TITLE_LIMIT = 80
# Лимит текста обычного сообщения в Telegram
MAX_MESSAGE_LEN = 4096


HOME_BTN = InlineKeyboardButton(text="🏠 В главное меню", callback_data="to_the_main_page")


def _films_word(n: int) -> str:
    if n % 10 == 1 and n % 100 != 11:
        return "фильм"
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return "фильма"
    return "фильмов"


def _format_movie(index: int, movie) -> str:
    """Один пункт списка: название-ссылка, под ним год и рейтинг.

    Всё, что пришло из TMDB, экранируется: название вида 'Fast & Furious'
    иначе ломает разбор HTML целиком — вместе с ним падает весь список."""
    title = truncate(movie.title or "Без названия", TITLE_LIMIT)
    year = str(movie.release_date.year) if movie.release_date else "год неизвестен"
    # Именно `is not None`: рейтинг 0.0 — это «ноль», а не «нет данных»
    rating = f"{movie.vote_average:.1f}" if movie.vote_average is not None else "—"

    # quote_plus заодно убирает из адреса кавычки и амперсанды, так что
    # href остаётся корректным при любом названии
    google_url = "https://www.google.com/search?q=" + quote_plus(f"смотреть фильм {title}")

    return (
        f'<b>{index}.</b> <a href="{google_url}"><b>{html.escape(title)}</b></a>\n'
        f"<i>{year} · ⭐ {rating}</i>"
    )


@favourites_router.callback_query(F.data.startswith("favourites"))
async def favourites(callback: CallbackQuery, session: AsyncSession, bot: Bot):
    logger.info("[Избранное] user_id=%s открыл избранное", callback.from_user.id)
    await send_favourites(callback, session=session, bot=bot, page=1)


async def send_favourites(callback: CallbackQuery, session: AsyncSession, bot: Bot, page: int = 1):
    user_id = callback.from_user.id
    movies = await get_movies_by_interaction(user_id, session, interaction_types=["liked"])

    if not movies:
        logger.info("[Избранное] user_id=%s — список пуст", user_id)
        await callback.answer()
        await callback.message.edit_text(
            "<b>❤️ Избранное</b>\n\n"
            "Здесь пока пусто. Жми ❤️ на карточке фильма в рекомендациях — он появится в этом списке.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[HOME_BTN]]),
        )
        return

    total_pages = -(-len(movies) // MOVIES_PER_PAGE)
    # Список мог сократиться с момента отрисовки кнопок — тогда старая кнопка
    # «▶️» уводила бы на пустую страницу с одним заголовком.
    page = max(1, min(page, total_pages))
    logger.info("[Избранное] user_id=%s — всего избранных: %d, страница %d из %d", user_id, len(movies), page, total_pages)

    start = (page - 1) * MOVIES_PER_PAGE
    movies_for_page = movies[start : start + MOVIES_PER_PAGE]

    header = f"<b>❤️ Избранное</b> · {len(movies)} {_films_word(len(movies))}\n\n"
    lines = [_format_movie(i, m) for i, m in enumerate(movies_for_page, start=start + 1)]

    # Пять строк с длинными названиями теоретически перебирают лимит сообщения.
    # Собираем, пока влезает: лучше показать четыре фильма, чем уронить весь список.
    text = header
    for line in lines:
        if len(text) + len(line) + 2 > MAX_MESSAGE_LEN:
            logger.warning("[Избранное] user_id=%s — страница %d обрезана по лимиту сообщения", user_id, page)
            break
        text += line + "\n\n"

    # Ряд навигации: ◀️  2 / 5  ▶️. Счётчик — кнопка-заглушка (noop), стрелки
    # на краях списка просто не показываем. На единственной странице ряда нет вовсе.
    rows = []
    if total_pages > 1:
        nav = []
        if page > 1:
            nav.append(InlineKeyboardButton(text="◀️", callback_data=f"page_{page - 1}"))
        nav.append(InlineKeyboardButton(text=f"{page} / {total_pages}", callback_data="noop"))
        if page < total_pages:
            nav.append(InlineKeyboardButton(text="▶️", callback_data=f"page_{page + 1}"))
        rows.append(nav)
    rows.append([HOME_BTN])

    await callback.answer()
    await callback.message.edit_text(
        text.rstrip(),
        parse_mode="HTML",
        disable_web_page_preview=True,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )


@favourites_router.callback_query(F.data == "noop")
async def noop(callback: CallbackQuery):
    """Счётчик страниц — не кнопка по смыслу, но без ответа у юзера крутился бы спиннер."""
    await callback.answer()


@favourites_router.callback_query(F.data.startswith("page_"))
async def change_page(callback: CallbackQuery, session: AsyncSession, bot: Bot):
    try:
        page = int(callback.data.split("_")[1])
    except (IndexError, ValueError):
        page = 1
    logger.info("[Избранное] user_id=%s — переключение на страницу %d", callback.from_user.id, page)
    await send_favourites(callback, session=session, bot=bot, page=page)
