from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from chat_gpt.questions import FULL_WIDTH_OPTIONS, OPTION_ICONS, QUESTION_COLUMNS, QUESTION_KEYS
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


SELECTED_MARK = "✅"


def get_multi_select_keyboard(options_dict: dict, selected_options: set, question_key: str):
    icons = OPTION_ICONS.get(question_key, {})
    full_width = FULL_WIDTH_OPTIONS.get(question_key, set())
    keyboard = InlineKeyboardBuilder()
    wide_buttons = []
    for option_key, option_text in options_dict.items():
        # Отметка выбора заменяет иконку, а не встаёт рядом: два эмодзи подряд — перебор.
        if option_text in selected_options:
            label = f"{SELECTED_MARK} {option_text}"
        elif option_key in icons:
            label = f"{icons[option_key]} {option_text}"
        else:
            label = option_text
        button = InlineKeyboardButton(text=label, callback_data=f"select:{question_key}:{option_key}")
        if option_key in full_width:
            wide_buttons.append(button)
        else:
            keyboard.add(button)
    keyboard.adjust(QUESTION_COLUMNS.get(question_key, 1))
    for button in wide_buttons:
        keyboard.row(button)

    done_text = "Готово" if question_key == QUESTION_KEYS[-1] else "Далее →"
    keyboard.row(InlineKeyboardButton(text=done_text, callback_data=f"done:{question_key}"))
    return keyboard.as_markup()
