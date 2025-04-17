from aiogram import Router, Bot, types
from aiogram.types import CallbackQuery
from aiogram import F
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
import logging
from handlers.callback_data import Menu_Callback
import os
from sqlalchemy.ext.asyncio import AsyncSession
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from kbds.inline import get_callback_btns
from database.orm_query import get_movies_by_interaction

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)



favourites_router = Router()

@favourites_router.callback_query(F.data.startswith("favourites"))
async def favourites(callback: CallbackQuery, session: AsyncSession, bot: Bot):
    await send_favourites(callback, session=session, bot=bot, page=1)


async def send_favourites(callback: CallbackQuery, session: AsyncSession, bot: Bot, page: int = 1):



    movies_on_page = 5

    movies = await get_movies_by_interaction(callback.from_user.id, session, interaction_types=['liked'])
    if not movies:
        await callback.answer()
        await callback.message.answer("У вас пока нет избранных фильмов.", reply_markup=get_callback_btns(
            btns={
                "На главную": "to_the_main_page"
            }
        ))
        return




    start = (page - 1) * movies_on_page
    end = page * movies_on_page
    movies_for_page = movies[start:end]

    movie_list = []
    for i, movie in enumerate(movies_for_page, start=start + 1):
        title = movie.movie_name
        year = movie.movie_year
        rating = round(movie.movie_rating, 1)
        google_search_url = f"https://www.google.com/search?q=смотреть+фильм+{title.replace(' ', '+')}"

        movie_list.append(
            f"<b>{i}. 🎬 <a href='{google_search_url}'>{title}</a></b>\n"
            f"   📅 <i>{year} год</i>\n"
            f"   ⭐ <i>Рейтинг: {rating if rating > 0 else 'Нет данных'}</i>"
        )

    if movie_list:
        movie_list_text = "<b>🌟 Ваши избранные фильмы:</b>\n\n" + "\n\n".join(movie_list)

        total_pages = -(-len(movies) // movies_on_page)
        pagination_buttons = []

        if page > 1:
            pagination_buttons.append(InlineKeyboardButton(text='⏮️ В начало', callback_data='page_1'))
            pagination_buttons.append(InlineKeyboardButton(text='◀️ Назад', callback_data=f'page_{page - 1}'))

        if page < total_pages:
            pagination_buttons.append(InlineKeyboardButton(text='▶️ Вперед', callback_data=f'page_{page + 1}'))
            pagination_buttons.append(InlineKeyboardButton(text='⏩ В конец', callback_data=f'page_{total_pages}'))

        pagination_markup = InlineKeyboardMarkup(inline_keyboard=[
            pagination_buttons,
            [InlineKeyboardButton(text='На главную', callback_data='to_the_main_page')]
        ])
        await callback.answer()

        await callback.message.edit_text(movie_list_text, parse_mode="HTML", disable_web_page_preview=True, reply_markup=pagination_markup)




@favourites_router.callback_query(F.data.startswith("page_"))
async def change_page(callback: CallbackQuery, session: AsyncSession, bot: Bot):
    page = int(callback.data.split("_")[1])
    await send_favourites(callback, session=session, bot=bot, page=page)
