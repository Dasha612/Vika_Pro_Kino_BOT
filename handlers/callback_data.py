from aiogram.filters.callback_data import CallbackData
from aiogram.fsm.state import State, StatesGroup
class Menu_Callback(CallbackData, prefix="menu"):
    menu_name: str
    index: int


