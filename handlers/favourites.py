import logging

from aiogram import Router, Bot, F
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy.ext.asyncio import AsyncSession

from kbds.inline import get_callback_btns
from database.orm_query import get_movies_by_interaction

logger = logging.getLogger(__name__)

favourites_router = Router()

MOVIES_PER_PAGE = 5


@favourites_router.callback_query(F.data.startswith("favourites"))
async def favourites(callback: CallbackQuery, session: AsyncSession, bot: Bot):
    logger.info("[Избранное] user_id=%s открыл избранное", callback.from_user.id)
    await send_favourites(callback, session=session, bot=bot, page=1)


async def send_favourites(callback: CallbackQuery, session: AsyncSession, bot: Bot, page: int = 1):
    user_id = callback.from_user.id
    movies = await get_movies_by_interaction(user_id, session, interaction_types=["liked"])
    logger.info("[Избранное] user_id=%s — всего избранных: %d, страница: %d", user_id, len(movies), page)

    if not movies:
        logger.info("[Избранное] user_id=%s — список пуст", user_id)
        await callback.answer()
        await callback.message.edit_text(
            "У вас пока нет избранных фильмов.",
            reply_markup=get_callback_btns(btns={"На главную": "to_the_main_page"}),
        )
        return

    start = (page - 1) * MOVIES_PER_PAGE
    end = page * MOVIES_PER_PAGE
    movies_for_page = movies[start:end]

    movie_list = []
    for i, movie in enumerate(movies_for_page, start=start + 1):
        title = movie.title or "Без названия"
        year = movie.release_date.year if movie.release_date else "Неизвестно"
        rating = round(movie.vote_average, 1) if movie.vote_average else "Нет данных"
        google_url = f"https://www.google.com/search?q=смотреть+фильм+{title.replace(' ', '+')}"

        movie_list.append(
            f"<b>{i}. <a href='{google_url}'>{title}</a></b>,"
            f" <i>{year} год</i>,"
            f" <i>Рейтинг: {rating}</i>"
        )

    movie_list_text = "<b>Ваши избранные фильмы:</b>\n\n" + "\n\n".join(movie_list)

    total_pages = -(-len(movies) // MOVIES_PER_PAGE)
    pagination_buttons = []

    if page > 1:
        pagination_buttons.append(InlineKeyboardButton(text="<<", callback_data="page_1"))
        pagination_buttons.append(InlineKeyboardButton(text="<", callback_data=f"page_{page - 1}"))

    if page < total_pages:
        pagination_buttons.append(InlineKeyboardButton(text=">", callback_data=f"page_{page + 1}"))
        pagination_buttons.append(InlineKeyboardButton(text=">>", callback_data=f"page_{total_pages}"))

    pagination_markup = InlineKeyboardMarkup(
        inline_keyboard=[
            pagination_buttons,
            [InlineKeyboardButton(text="На главную", callback_data="to_the_main_page")],
        ]
    )

    await callback.answer()
    await callback.message.edit_text(
        movie_list_text,
        parse_mode="HTML",
        disable_web_page_preview=True,
        reply_markup=pagination_markup,
    )


@favourites_router.callback_query(F.data.startswith("page_"))
async def change_page(callback: CallbackQuery, session: AsyncSession, bot: Bot):
    try:
        page = int(callback.data.split("_")[1])
    except (IndexError, ValueError):
        page = 1
    logger.info("[Избранное] user_id=%s — переключение на страницу %d", callback.from_user.id, page)
    await send_favourites(callback, session=session, bot=bot, page=page)
