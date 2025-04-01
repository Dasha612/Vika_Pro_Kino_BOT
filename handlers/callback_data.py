from aiogram.filters.callback_data import CallbackData

class Menu_Callback(CallbackData, prefix="menu"):
    menu_name: str
    index: int
