from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from config import cfg


def get_callback_btns(*, btns: dict[str, str], sizes: tuple[int] = (2,)):
    keyboard = InlineKeyboardBuilder()
    for text, data in btns.items():
        keyboard.add(InlineKeyboardButton(text=text, callback_data=data))
    return keyboard.adjust(*sizes).as_markup()


def get_url_btns(*, btns: dict[str, str], sizes: tuple[int] = (2,)):
    keyboard = InlineKeyboardBuilder()
    for text, url in btns.items():
        keyboard.add(InlineKeyboardButton(text=text, url=url))
    return keyboard.adjust(*sizes).as_markup()


def get_inlineMix_btns(*, btns: dict[str, str], sizes: tuple[int] = (2,)):
    keyboard = InlineKeyboardBuilder()
    for text, value in btns.items():
        if "://" in value:
            keyboard.add(InlineKeyboardButton(text=text, url=value))
        else:
            keyboard.add(InlineKeyboardButton(text=text, callback_data=value))
    return keyboard.adjust(*sizes).as_markup()


MAIN_MENU_BTNS = {
    "Мой профиль": "my_profile",
    "Избранное": "favourites",
    "Рекомендации": "choose_option",
}

AFTER_ANKETA_BTNS = {
    "Запуск рекомендаций": "recommendations",
    "Свой запрос": "search_movie",
    "Вернуться в меню": "to_the_main_page",
}

RECOMMENDATIONS_MENU_BTNS = {
    "Запуск рекомендаций": "recommendations",
    "Свой запрос": "search_movie",
    "Вернуться в меню": "to_the_main_page",
}


_channel_url = f"https://t.me/{cfg.channel_id}" if cfg.channel_id else "https://t.me/"

subscribe_button = InlineKeyboardMarkup(
    inline_keyboard=[
        [InlineKeyboardButton(text="Подписаться на канал", url=_channel_url)],
        [InlineKeyboardButton(text="Проверить подписку", callback_data="check_subscription")],
    ]
)

rate_buttons = InlineKeyboardMarkup(
    inline_keyboard=[
        [
            InlineKeyboardButton(text="1", callback_data="1"),
            InlineKeyboardButton(text="2", callback_data="2"),
            InlineKeyboardButton(text="3", callback_data="3"),
            InlineKeyboardButton(text="4", callback_data="4"),
            InlineKeyboardButton(text="5", callback_data="5"),
        ]
    ]
)


def get_multi_select_keyboard(options_dict: dict, selected_options: set, question_key: str):
    keyboard = InlineKeyboardBuilder()
    for option_key, option_text in options_dict.items():
        prefix = ">> " if option_text in selected_options else ""
        callback_data = f"select:{question_key}:{option_key}"
        keyboard.add(InlineKeyboardButton(text=prefix + option_text, callback_data=callback_data))
    keyboard.add(InlineKeyboardButton(text="Готово", callback_data=f"done:{question_key}"))
    return keyboard.adjust(1).as_markup()
