from aiogram.fsm.state import State, StatesGroup

class Anketa(StatesGroup):
    question_1 = State()
    question_2 = State()
    question_3 = State()
    question_4 = State()
    question_5 = State()
    question_6 = State()
    question_7 = State()

class Recommendations(StatesGroup):
    waiting_for_action = State()
    waiting_for_rating = State()
    processing = State() 

class BotStates(StatesGroup):
    main_menu = State()
    recommendations = State()
    favorites = State()
    my_profile = State()