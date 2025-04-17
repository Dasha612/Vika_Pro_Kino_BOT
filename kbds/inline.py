from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
import os

def get_callback_btns(
        *,
        btns: dict[str, str],
        sizes: tuple[int] = (2,)):
    
    keyboard = InlineKeyboardBuilder()

    for text, data in btns.items():
        keyboard.add(InlineKeyboardButton(text=text, callback_data=data))

    return keyboard.adjust(*sizes).as_markup()


def get_url_btns(
        *,
        btns: dict[str, str],
        sizes: tuple[int] = (2,)):
    
    keyboard = InlineKeyboardBuilder()
    for text, url in btns.items():
        keyboard.add(InlineKeyboardButton(text=text, url=url))
    
    return keyboard.adjust(*sizes).as_markup()


def get_inlineMix_btns(
        *,
        btns: dict[str, str],
        sizes: tuple[int] = (2,)):
    
    keyboard = InlineKeyboardBuilder()
    for text, value in btns.items():
        if '://' in value:
            keyboard.add(InlineKeyboardButton(text=text, url=value))
        else:
            keyboard.add(InlineKeyboardButton(text=text, callback_data=value))
    
    return keyboard.adjust(*sizes).as_markup()


subscribe_button  = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text='Подписаться на канал', url=f"https://t.me/{os.getenv('TEST_CHANNEL_ID')}")],
    [InlineKeyboardButton(text='Проверить подписку', callback_data='check_subscription')]
])

rate_buttons = InlineKeyboardMarkup(
    inline_keyboard=[
        [
            InlineKeyboardButton(text='1', callback_data='1'),
            InlineKeyboardButton(text='2', callback_data='2'),
            InlineKeyboardButton(text='3', callback_data='3'),
            InlineKeyboardButton(text='4', callback_data='4'),
            InlineKeyboardButton(text='5', callback_data='5')
        ]
    ]
)