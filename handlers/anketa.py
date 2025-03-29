from aiogram import types, Router, Bot, F
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.utils.formatting import Bold, as_list, as_marked_section
from aiogram.filters import StateFilter
import asyncio  
import os
from aiogram.types import CallbackQuery
from database.orm_query import orm_add_user_rec_set, add_user
from sqlalchemy.ext.asyncio import AsyncSession


from kbds.inline import get_callback_btns
from database.orm_query import check_recommendations_status
from chat_gpt.questions import questions

anketa_router = Router()

class Anketa(StatesGroup):
    question_1 = State()
    question_2 = State()
    question_3 = State()
    question_4 = State()
    question_5 = State()
    question_6 = State()
    question_7 = State()




@anketa_router.callback_query(StateFilter(None), F.data == "set_profile")
async def registration_start(callback: CallbackQuery, state: FSMContext):
    await callback.message.answer(questions[0])
    await state.set_state(Anketa.question_1)
    await callback.answer()

@anketa_router.message(Anketa.question_1, F.text)
async def set_q1(message: types.Message, state: FSMContext):
    await state.update_data(q1=message.text)
    await message.answer(questions[1])
    await state.set_state(Anketa.question_2)

@anketa_router.message(Anketa.question_1)
async def set_q1(message: types.Message, state: FSMContext):
    await message.answer("Пожалуйста, введите ответ в виде текста")

@anketa_router.message(Anketa.question_2, F.text)
async def set_q2(message: types.Message, state: FSMContext):
    await state.update_data(q2=message.text)
    await message.answer(questions[2])
    await state.set_state(Anketa.question_3)

@anketa_router.message(Anketa.question_2)
async def set_q2(message: types.Message, state: FSMContext):
    await message.answer("Пожалуйста, введите ответ в виде текста")

@anketa_router.message(Anketa.question_3, F.text)
async def set_q3(message: types.Message, state: FSMContext):
    await state.update_data(q3=message.text)
    await message.answer(questions[3])
    await state.set_state(Anketa.question_4)

@anketa_router.message(Anketa.question_3)
async def set_q3(message: types.Message, state: FSMContext):
    await message.answer("Пожалуйста, введите ответ в виде текста")

@anketa_router.message(Anketa.question_4, F.text)
async def set_q4(message: types.Message, state: FSMContext):
    await state.update_data(q4=message.text)
    await message.answer(questions[4])
    await state.set_state(Anketa.question_5)

@anketa_router.message(Anketa.question_4)
async def set_q4(message: types.Message, state: FSMContext):
    await message.answer("Пожалуйста, введите ответ в виде текста")

@anketa_router.message(Anketa.question_5, F.text)
async def set_q5(message: types.Message, state: FSMContext):
    await state.update_data(q5=message.text)
    await message.answer(questions[5])
    await state.set_state(Anketa.question_6)

@anketa_router.message(Anketa.question_5)
async def set_q5(message: types.Message, state: FSMContext):
    await message.answer("Пожалуйста, введите ответ в виде текста")

@anketa_router.message(Anketa.question_6, F.text)
async def set_q6(message: types.Message, state: FSMContext):
    await state.update_data(q6=message.text)
    await message.answer(questions[6])
    await state.set_state(Anketa.question_7)

@anketa_router.message(Anketa.question_6)
async def set_q6(message: types.Message, state: FSMContext):
    await message.answer("Пожалуйста, введите ответ в виде текста")


@anketa_router.message(Anketa.question_7, F.text)
async def set_q7(message: types.Message, state: FSMContext, bot: Bot, session: AsyncSession):
    await state.update_data(q7=message.text)
    user_data = await state.get_data()
    try:
        await orm_add_user_rec_set(message.from_user.id, session, user_data)
    except Exception as e:
        await message.answer(f"Ошибка при добавлении данных в базу: {e}")


    member = await bot.get_chat_member(chat_id='-100' + os.getenv("TEST_CHAT_ID"), user_id=message.from_user.id)


    await message.answer('Уфф...Все ответы записал.')
    await asyncio.sleep(5)
    await message.answer('Я смотрю, что ты опытный киноман, но даже тебя я смогу удивить.', reply_markup=types.ReplyKeyboardRemove())
    await asyncio.sleep(5)

    if member.status == 'left':
        await message.answer(
            'Начинаю поиск фильмов. Пока что ты можешь подписаться на телеграм канал Вика про кино',
            reply_markup=get_callback_btns(btns={
                'Подписаться на канал': os.getenv("TEST_CHANNEL_ID"),
                'Проверить подписку': 'check'
            })
        )
    else:
        await message.answer('Начинаю рекомендовать фильмы!')
        
        # Отображаем первый фильм
        #await send_movie_or_edit(message, movies[0], state, 0, message.from_user.id)


@anketa_router.message(StateFilter('*'), F.text == "Отмена")
async def cancel_cmd(message: types.Message, state: FSMContext):
    current_state = await state.get_state()
    if current_state is None:
        return
    await state.clear()
    await message.answer("Действие отменено", reply_markup=types.ReplyKeyboardRemove())

@anketa_router.message(StateFilter('*'), F.text == "Назад")
async def back_cmd(message: types.Message, state: FSMContext):
    current_state = await state.get_state()
    if current_state == Anketa.question_1:
        await message.answer("Предыдущего шага нет")
        return
    
    previous_state = None

    for step in Anketa.__all_states__:
        if step.state == current_state:
            await state.set_state(previous_state)
            await message.answer(questions[previous_state.index])
            return
        previous_state = step



@anketa_router.message(CommandStart())
async def start_cmd(message: types.Message, session: AsyncSession):
    await add_user(message.from_user.id, session)
    await message.answer(
        "Привет!\n"
        "Я — твой личный <b>КиноБот</b> 🎥\n"
        "Помогу выбрать фильм по настроению, жанру или даже если «просто что-нибудь посмотреть».\n"
        "Готов? Тогда начнём! 🍿", reply_markup=get_callback_btns(
            btns={
                "Мой профиль": "my_profile",
                "Избранное": "favorites",
                "Рекомендации": "recommendations"
            }
        ))
    await asyncio.sleep(2)



@anketa_router.callback_query(F.data == 'check_subscription')
async def check_sub(callback: CallbackQuery, bot: Bot, state: FSMContext):
    is_subscribed = await bot.get_chat_member(chat_id='-100' + os.getenv("TEST_CHAT_ID"), user_id=callback.from_user.id)
    if is_subscribed.status not in ['left', 'kicked', 'banned']:
        await bot.delete_message(chat_id=callback.message.chat.id, message_id=callback.message.message_id)
        await callback.message.answer(
            "Спасибо за подписку!\nНачинаю рекомендовать фильмы!"
        )
        #начинаем реккомендации
        
    else:
        await callback.message.answer(
            "Для начала подпишитесь на наш канал, чтобы продолжить.",
            reply_markup=get_callback_btns(
                        btns={
                            "Подписаться": "subscribe",
                            "Проверить подписку": "check_subscription"
                        }
                    ))
    await callback.answer()


@anketa_router.callback_query(F.data == 'my_profile')
async def my_profile(callback: CallbackQuery, bot: Bot, session: AsyncSession):
    await bot.delete_message(chat_id=callback.message.chat.id, message_id=callback.message.message_id)
    user_id = callback.from_user.id
    status = await check_recommendations_status(user_id, session)
    status = 'настроены' if status else 'не настроены'
    await callback.message.answer(
        (
            f"<b>👤 Ваш профиль:</b>\n"
            f"<b>ID:</b> <code>{user_id}</code>\n"
            #f"<b>Статус подписки:</b> <i>отключена</i>\n"
            f"<b>Рекомендации:</b> <i>{status}</i>"
        ),
        parse_mode="HTML",
        reply_markup=get_callback_btns(
            btns={
                "Мой профиль": "my_profile",
                "Избранное": "favorites",
                "Рекомендации": "recommendations"
            }
        )
    )


