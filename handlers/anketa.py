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
import logging

from kbds.inline import get_callback_btns, subscribe_button, get_multi_select_keyboard
from database.orm_query import check_recommendations_status, reset_anketa_in_db
from chat_gpt.questions import questions, QUESTION_KEYS,  CALLBACK_IDS


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)



anketa_router = Router()

class Anketa(StatesGroup):
    question_1 = State()
    question_2 = State()
    question_3 = State()
    question_4 = State()
    question_5 = State()

@anketa_router.callback_query(StateFilter(None), F.data == "set_profile")
async def registration_start(callback: CallbackQuery, state: FSMContext):
    question_key = QUESTION_KEYS[0]
    await state.set_state(getattr(Anketa, question_key))
    markup = get_multi_select_keyboard(CALLBACK_IDS[question_key], set(), question_key)
    await callback.message.edit_text(
        questions[0],
        reply_markup=markup
    )

    # Сохраняем message_id для последующего редактирования или удаления
    await state.update_data(anketa_message_id=callback.message.message_id)
    await callback.answer()


@anketa_router.callback_query(F.data.startswith("select:"))
async def toggle_selection(callback: CallbackQuery, state: FSMContext):
    try:
        _, question_key, option_key = callback.data.split(":")
        option_text = CALLBACK_IDS[question_key][option_key]
    except Exception as e:
        logger.error(f"Ошибка разбора callback: {e}")
        await callback.answer("Ошибка выбора")
        return

    data = await state.get_data()
    selected = set(data.get(f"{question_key}_selected", []))

    if option_text in selected:
        selected.remove(option_text)
    else:
        selected.add(option_text)

    await state.update_data(**{f"{question_key}_selected": list(selected)})

    markup = get_multi_select_keyboard(CALLBACK_IDS[question_key], selected, question_key)
    message_id = data.get("anketa_message_id")
    if message_id:
        await callback.bot.edit_message_reply_markup(
            chat_id=callback.message.chat.id,
            message_id=message_id,
            reply_markup=markup
        )
    await callback.answer()

@anketa_router.callback_query(F.data.startswith("done:"))
async def proceed_to_next_question(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    logger.info(f"Обработан callback: {callback.data}")
    
    try:
        question_key = callback.data.split(":")[1]
        logger.info(f"Определен ключ вопроса: {question_key}")
    except Exception as e:
        logger.error(f"Ошибка при парсинге callback_data: {e}")
        await callback.answer("Произошла ошибка")
        return

    current_state = await state.get_state()
    logger.info(f"Текущее состояние FSM: {current_state}")

    if question_key not in QUESTION_KEYS:
        logger.warning(f"Вопрос {question_key} не найден в списке QUESTION_KEYS")
        await callback.answer("Неизвестный вопрос")
        return

    next_index = QUESTION_KEYS.index(question_key) + 1
    data = await state.get_data()
    logger.info(f"Данные анкеты: {data}")
    selected_options = data.get(f"{question_key}_selected", [])

    if not selected_options:
        await callback.answer("Выберите хотя бы один вариант!", show_alert=True)
        return
    
    message_id = data.get("anketa_message_id")
    logger.info(f"ID сообщения с анкетой: {message_id}")

    # Конец анкеты
    if next_index >= len(QUESTION_KEYS):
        logger.info("Анкета завершена, сохраняем в базу...")
        await state.clear()
        await state.update_data(preferences_priority=True)
        try:
            await orm_add_user_rec_set(callback.from_user.id, session, data)
            logger.info("Анкета успешно записана в БД")
        except Exception as e:
            logger.exception(f"Ошибка при сохранении анкеты: {e}")
            await callback.message.answer(f"Ошибка при сохранении анкеты: {e}")
            return

        if message_id:
            try:
                await callback.bot.send_chat_action(callback.message.chat.id, action="typing")
                await asyncio.sleep(1.2)
                await callback.bot.edit_message_text(
                    chat_id=callback.message.chat.id,
                    message_id=message_id,
                    text="Уфф... Все ответы записал 📝"
                )
                await callback.bot.send_chat_action(callback.message.chat.id, action="typing")
                await asyncio.sleep(1.2)
                await callback.bot.edit_message_text(
                    chat_id=callback.message.chat.id,
                    message_id=message_id,
                    text="Я смотрю, что ты опытный киноман, но даже тебя я смогу удивить 👀"
                )
                await callback.bot.send_chat_action(callback.message.chat.id, action="typing")
                await asyncio.sleep(1.2)
                await callback.bot.edit_message_text(
                    chat_id=callback.message.chat.id,
                    message_id=message_id,
                    text="<b>Выбери, что ты хочешь сделать</b>",
                    parse_mode="HTML",
                    reply_markup=get_callback_btns(btns={
                    "Запуск рекомендаций": "recommendations",
                    "Свой запрос": "search_movie", 
                    "Найти фильм вместе" : "find_together",
                    'Вернуться в меню': 'my_profile'
                })
                )
            except Exception as e:
                logger.warning(f"Не удалось редактировать сообщение: {e}")
                await callback.message.answer("Выбери, что ты хочешь сделать", reply_markup=get_callback_btns(btns={
                    "Запуск рекомендаций": "recommendations",
                    "Свой запрос": "search_movie", 
                    "Найти фильм вместе" : "find_together",
                    'Вернуться в меню': 'my_profile'
                }))
        else:
            logger.warning("message_id отсутствует, отправляем финальные сообщения как новые")
            await callback.message.answer("Уфф... Все ответы записал 📝")
            await asyncio.sleep(1.2)
            await callback.message.answer("Я смотрю, что ты опытный киноман, но даже тебя я смогу удивить 👀")
            await asyncio.sleep(1.2)
            await callback.message.answer(
                "<b>Выбери, что ты хочешь сделать</b>",
                parse_mode="HTML",
                reply_markup=get_callback_btns(btns={
                    "Запуск рекомендаций": "recommendations",
                    "Свой запрос": "search_movie", 
                    "Найти фильм вместе" : "find_together",
                    'Вернуться в меню': 'my_profile'
                })
            )
        

        
        await callback.answer()
        return

    # Переход к следующему вопросу
    next_key = QUESTION_KEYS[next_index]
    await state.set_state(getattr(Anketa, next_key))
    markup = get_multi_select_keyboard(CALLBACK_IDS[next_key], set(), next_key)

    if message_id:
        await callback.bot.edit_message_text(
            chat_id=callback.message.chat.id,
            message_id=message_id,
            text=questions[next_index],
            reply_markup=markup
        )
    else:
        sent = await callback.message.answer(questions[next_index], reply_markup=markup)
        await state.update_data(anketa_message_id=sent.message_id)

    await callback.answer()





@anketa_router.message(StateFilter('*'), F.text == "Отмена")
async def cancel_cmd(message: types.Message, state: FSMContext):
    current_state = await state.get_state()
    if current_state is None:
        return
    await state.clear()
    await message.answer("Действие отменено", reply_markup=types.ReplyKeyboardRemove())


@anketa_router.callback_query(StateFilter('*'), F.data == "Назад")
async def handle_back(callback: CallbackQuery, state: FSMContext):
    current_state = await state.get_state()

    states_list = Anketa.__all_states__
    current_index = next((i for i, step in enumerate(states_list) if step.state == current_state), None)

    if current_index is None or current_index == 0:
        await callback.message.answer("Ты на первом вопросе. Назад нельзя 🧱")
        await callback.answer()
        return

    previous_state = states_list[current_index - 1]
    await state.set_state(previous_state)
    await callback.message.edit_text(
        questions[current_index - 1],
        reply_markup=get_callback_btns(btns={"Назад": "Назад"})
    )

    await callback.answer()





@anketa_router.message(CommandStart())
async def start_cmd(message: types.Message, session: AsyncSession, state: FSMContext):
    await add_user(message.from_user.id, session)

    start_message=await message.answer(
        "Привет!\n"
        "Я — твой личный <b>КиноБот</b> 🎥\n"
        "Помогу выбрать фильм по настроению, жанру или даже если «просто что-нибудь посмотреть».\n"
        "Готов? Тогда начнём! 🍿", reply_markup=get_callback_btns(
            btns={
                "Мой профиль": "my_profile",
                "Избранное": "favourites",
                "Рекомендации": "choose_option"
            }
        ))
    await state.update_data(start_message_id=start_message.message_id)
    



@anketa_router.callback_query(F.data == 'check_subscription')
async def check_sub(callback: CallbackQuery, bot: Bot, state: FSMContext):
    is_subscribed = await bot.get_chat_member(chat_id='-100' + os.getenv("CHAT_ID"), user_id=callback.from_user.id)
    if is_subscribed.status not in ['left', 'kicked', 'banned']:
        #await bot.delete_message(chat_id=callback.message.chat.id, message_id=callback.message.message_id)
        await callback.message.edit_text(
            text="Спасибо за подписку!\n Для старта нажмите /start"
        )
        await asyncio.sleep(2)
        #await bot.delete_message(chat_id=callback.message.chat.id, message_id=callback.message.message_id)
        #начинаем реккомендации
        
    else:
        await callback.message.edit_text(
            text="Для начала подпишитесь на наш канал, чтобы продолжить.",
            reply_markup=subscribe_button
        )
    await callback.answer()


@anketa_router.callback_query(F.data == 'my_profile')
async def my_profile(callback: CallbackQuery, bot: Bot, session: AsyncSession, state: FSMContext):
    
    #await bot.delete_message(chat_id=callback.message.chat.id, message_id=callback.message.message_id)
    user_id = callback.from_user.id
    status = await check_recommendations_status(user_id, session)
    status = 'настроены' if status else 'не настроены'
    await callback.message.edit_text(
        (
            f"<b>👤 Ваш профиль:</b>\n"
            f"<b>ID:</b> <code>{user_id}</code>\n"
            #f"<b>Статус подписки:</b> <i>отключена</i>\n"
            f"<b>Рекомендации:</b> <i>{status}</i>"
        ),
        parse_mode="HTML",
        reply_markup=get_callback_btns(
            btns={
                "Сбросить рекоммендации": "reset_anketa",
                "В главное меню": "to_the_main_page"
            }
        )
    )


@anketa_router.callback_query(F.data == 'to_the_main_page')
async def main_page(callback: CallbackQuery, state: FSMContext):
    current_state = await state.get_state()
    logger.info(f"Текущее состояние: {current_state}")
    if current_state is not None:
        await callback.answer("⏳ Подождите, пока завершится текущий процесс.")
        return
    await callback.message.edit_text(text='Выберите пункт из меню', reply_markup=get_callback_btns(
            btns={
                "Мой профиль": "my_profile",
                "Избранное": "favourites",
                "Рекомендации": "choose_option"
            }
        ))


@anketa_router.callback_query(F.data == 'reset_anketa')
async def reset_anketa_handler(callback: CallbackQuery, session: AsyncSession):
    user_id = callback.from_user.id
    await reset_anketa_in_db(user_id, session)

    await callback.message.edit_text(text='Анкета сброшена', reply_markup=get_callback_btns(
        btns={
            "Заполнить анкету заново": "set_profile",
            "В главное меню": "to_the_main_page"
        }
    )) 
    await callback.answer()
