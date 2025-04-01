from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from handlers.callback_data import Menu_Callback




def create_movie_carousel_keyboard(index: int = 0) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    
    # Кнопки действий с фильмом в два ряда
    builder.row(
        InlineKeyboardButton(
            text="Следующий⏩", 
            callback_data=Menu_Callback(menu_name="next", index=index).pack()
        ),
        InlineKeyboardButton(
            text="❤️", 
            callback_data=Menu_Callback(menu_name="like", index=index).pack()
        )
    )
    builder.row(
        InlineKeyboardButton(
            text="Смотрел", 
            callback_data=Menu_Callback(menu_name="watched", index=index).pack()
        ),
        InlineKeyboardButton(
            text="Стоп", 
            callback_data=Menu_Callback(menu_name="stop_recommendations", index=index).pack()
        )
    )
    
    return builder.as_markup()