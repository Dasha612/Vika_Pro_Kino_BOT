import logging

from aiogram import Router, Bot, types, F
from aiogram.types import CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy.ext.asyncio import AsyncSession

from handlers.callback_data import Menu_Callback
from handlers.movie_utils import send_movie_card
from database.orm_query import (
    add_movies_by_interaction,
    get_movie_from_db,
    get_movies_by_interaction,
    check_recommendations_status,
    delete_movies_by_interaction,
    get_movies_by_profile_embedding,
    get_movies_by_text_query,
)
from kbds.inline import (
    MAIN_MENU_BTNS,
    RECOMMENDATIONS_MENU_BTNS,
    get_callback_btns,
    rate_buttons,
)
from kbds.pagination import create_movie_carousel_keyboard

logger = logging.getLogger(__name__)

recommendations_router = Router()


class Recomendations(StatesGroup):
    waiting_for_action = State()
    processing = State()
    waiting_for_query = State()


async def safe_callback_answer(callback: CallbackQuery, text: str = None, show_alert: bool = False):
    try:
        await callback.answer(text=text, show_alert=show_alert)
    except Exception as e:
        logger.warning("Ошибка при callback.answer(): %s", e)


async def _current_movie(state: FSMContext, session: AsyncSession, data: dict | None = None):
    """Возвращает (movie, movie_ids, index).

    В FSM лежат только tmdb_id — сам фильм каждый раз достаём из БД.
    movie = None, если индекс вне диапазона или фильма больше нет в базе.
    """
    if data is None:
        data = await state.get_data()
    ids = data.get("movie_ids", [])
    idx = data.get("current_index", 0)
    if not (0 <= idx < len(ids)):
        return None, ids, idx
    return await get_movie_from_db(ids[idx], session), ids, idx


async def _show_movie(callback: CallbackQuery, state: FSMContext, movies: list, edit: bool = False):
    """Показывает первый фильм списка и кладёт в FSM только их id."""
    message = await send_movie_card(
        callback.message, movies[0], 0, edit=edit, custom_keyboard=create_movie_carousel_keyboard
    )
    await state.set_state(Recomendations.waiting_for_action)
    await state.update_data(
        movie_ids=[m.tmdb_id for m in movies],
        current_index=0,
        last_action="",
        # Явно гасим флаг: сюда попадают только подборки по профилю, и по исчерпании
        # списка бот должен подгружать новую порцию, а не завершать подбор.
        custom_query=False,
        message_id=message.message_id,
        chat_id=message.chat.id,
    )
    return message


@recommendations_router.callback_query(F.data == "choose_option")
async def options(callback: CallbackQuery, session: AsyncSession, bot: Bot, state: FSMContext):
    logger.info("[Рекомендации] user_id=%s открыл меню 'Выберите опцию'", callback.from_user.id)
    await callback.message.edit_text(
        "<b>Выберите опцию</b>",
        parse_mode="HTML",
        reply_markup=get_callback_btns(btns=RECOMMENDATIONS_MENU_BTNS),
    )
    await callback.answer()


@recommendations_router.callback_query(F.data == "search_movie")
async def prompt_search_query(callback: CallbackQuery, state: FSMContext):
    logger.info("[Поиск] user_id=%s нажал 'Свой запрос'", callback.from_user.id)
    current_state = await state.get_state()
    if current_state is not None:
        logger.debug("[Поиск] user_id=%s — заблокировано, текущее состояние: %s", callback.from_user.id, current_state)
        await callback.answer("Подождите, пока завершится текущий процесс.")
        return
    await state.set_state(Recomendations.waiting_for_query)
    msg = await callback.message.edit_text(
        "Опиши, что хочешь посмотреть — своими словами.\n"
        "Например: <i>мрачный детектив про маньяка</i> или <i>лёгкое кино про дружбу</i>.",
        parse_mode="HTML",
        # Без кнопки состояние waiting_for_query — тупик: меню заблокировано,
        # и выйти можно было бы только командой /reset.
        reply_markup=get_callback_btns(btns={"Отмена": "cancel_search"}, sizes=(1,)),
    )
    await state.update_data(prompt_message_id=msg.message_id)
    await callback.answer()


@recommendations_router.callback_query(Recomendations.waiting_for_query, F.data == "cancel_search")
async def cancel_search(callback: CallbackQuery, state: FSMContext):
    logger.info("[Поиск] user_id=%s отменил ввод запроса", callback.from_user.id)
    await state.clear()
    await callback.message.edit_text(
        "Хорошо, отменил. Выберите пункт из меню.",
        reply_markup=get_callback_btns(btns=MAIN_MENU_BTNS),
    )
    await callback.answer()


@recommendations_router.message(Recomendations.waiting_for_query, F.text)
async def process_search_query(message: types.Message, state: FSMContext, session: AsyncSession, bot: Bot):
    user_text = (message.text or "").strip()
    if not user_text:
        return
    logger.info("[Поиск] user_id=%s ввёл запрос: '%s'", message.from_user.id, user_text)

    await bot.send_chat_action(message.chat.id, action="typing")

    # Пока считается эмбеддинг, юзер может успеть отправить второй запрос:
    # в processing этот хендлер уже не сработает. finally — чтобы любая ошибка
    # внутри не оставила пользователя в processing навсегда.
    await state.set_state(Recomendations.processing)
    try:
        await _run_search(message, state, session, user_text)
    finally:
        if await state.get_state() == Recomendations.processing.state:
            await state.clear()


async def _run_search(message: types.Message, state: FSMContext, session: AsyncSession, user_text: str):
    movies = await get_movies_by_text_query(session, message.from_user.id, user_text)

    if not movies:
        logger.info("[Поиск] user_id=%s — пустая выдача по запросу", message.from_user.id)
        await state.clear()
        await message.answer(
            "Ничего не нашёл по этому запросу. Попробуй переформулировать — "
            "чем подробнее опишешь настроение и сюжет, тем лучше я попадаю.",
            reply_markup=get_callback_btns(btns=RECOMMENDATIONS_MENU_BTNS),
        )
        return

    msg = await send_movie_card(message, movies[0], 0, custom_keyboard=create_movie_carousel_keyboard)
    await state.set_state(Recomendations.waiting_for_action)
    await state.update_data(
        movie_ids=[m.tmdb_id for m in movies],
        current_index=0,
        last_action="",
        # Подборка конечная: новых порций по запросу не бывает, добирать нечего.
        custom_query=True,
        message_id=msg.message_id,
        chat_id=msg.chat.id,
    )


@recommendations_router.message(Recomendations.waiting_for_query)
async def reject_non_text_query(message: types.Message):
    """Стикер/фото/голосовое в режиме ввода запроса: без этого хендлера
    апдейт молча проваливался бы мимо, и бот выглядел бы зависшим."""
    await message.answer("Мне нужен текст — опиши словами, что хочешь посмотреть.")


@recommendations_router.callback_query(F.data == "recommendations")
async def send_recommendations(callback: CallbackQuery, session: AsyncSession, bot: Bot, state: FSMContext):
    user_id = callback.from_user.id
    logger.info("[Рекомендации] user_id=%s нажал 'Запуск рекомендаций'", user_id)
    await safe_callback_answer(callback)

    current_state = await state.get_state()
    blocked_states = [
        Recomendations.waiting_for_action.state,
        Recomendations.processing.state,
        Recomendations.waiting_for_query.state,
    ]

    if current_state in blocked_states:
        logger.debug("[Рекомендации] user_id=%s — заблокировано, состояние: %s", user_id, current_state)
        await safe_callback_answer(callback, "Подождите, пока завершится текущий процесс.")
        return

    await bot.send_chat_action(callback.message.chat.id, action="typing")

    recommendations_status = await check_recommendations_status(user_id, session)
    if not recommendations_status:
        logger.info("[Рекомендации] user_id=%s — анкета не заполнена, предлагаю заполнить", user_id)
        await callback.message.edit_text(
            "Прежде чем порекомендовать тебе фильм, мне нужно узнать о тебе больше информации. Давай заполним анкету?",
            reply_markup=get_callback_btns(btns={"Давай": "set_profile"}),
        )
        return

    unwatched_movies = await get_movies_by_interaction(user_id, session, ["unwatched"])
    logger.info("[Рекомендации] user_id=%s — непросмотренных фильмов в очереди: %d", user_id, len(unwatched_movies))

    if unwatched_movies:
        logger.info("[Рекомендации] user_id=%s — показываю непросмотренный: '%s'", user_id, unwatched_movies[0].title)
        await _show_movie(callback, state, unwatched_movies)
        await delete_movies_by_interaction(user_id, session, ["unwatched"], unwatched_movies[0].tmdb_id)
        return

    logger.info("[Рекомендации] user_id=%s — нет непросмотренных, подбираю по эмбеддингу профиля", user_id)
    movies = await get_movies_by_profile_embedding(session, user_id, top_k=50)

    if not movies:
        logger.warning("[Рекомендации] user_id=%s — не удалось подобрать фильмы по профилю", user_id)
        await callback.message.edit_text(
            "Пока не смог подобрать фильмы по твоему профилю. Попробуй обновить анкету или сформулировать запрос вручную.",
            reply_markup=get_callback_btns(
                btns={"Обновить анкету": "reset_anketa", "В меню": "to_the_main_page"}
            ),
        )
        return

    logger.info("[Рекомендации] user_id=%s — подобрано %d фильмов, первый: '%s'", user_id, len(movies), movies[0].title)
    await _show_movie(callback, state, movies)


async def _load_next_batch(callback: CallbackQuery, state: FSMContext, session: AsyncSession, user_id: int):
    """Подгружает следующую порцию рекомендаций по эмбеддингу."""
    logger.info("[Рекомендации] user_id=%s — подгрузка новой порции фильмов", user_id)
    movies = await get_movies_by_profile_embedding(session, user_id, top_k=50)

    if not movies:
        logger.warning("[Рекомендации] user_id=%s — новая порция пуста, фильмы закончились", user_id)
        await callback.message.answer(
            "Пока не смог подобрать новые фильмы. Попробуй обновить анкету.",
            reply_markup=get_callback_btns(
                btns={"Обновить анкету": "reset_anketa", "В меню": "to_the_main_page"}
            ),
        )
        await state.clear()
        return

    logger.info("[Рекомендации] user_id=%s — новая порция: %d фильмов, первый: '%s'", user_id, len(movies), movies[0].title)
    await _show_movie(callback, state, movies)


@recommendations_router.callback_query(Menu_Callback.filter())
async def handle_movie_action(
    callback: CallbackQuery,
    callback_data: Menu_Callback,
    state: FSMContext,
    session: AsyncSession,
    bot: Bot,
):
    action = callback_data.menu_name
    user_id = callback.from_user.id
    current_state = await state.get_state()

    if current_state == Recomendations.processing.state:
        logger.debug("[Действие] user_id=%s — нажатие проигнорировано, идёт обработка", user_id)
        await safe_callback_answer(callback, "Пожалуйста, подождите...")
        return

    await state.set_state(Recomendations.processing)
    try:
        await _handle_movie_action(callback, action, state, session, bot, user_id)
    finally:
        # Без этого любая ошибка внутри оставила бы юзера в processing навсегда:
        # ключ состояния в Redis живёт без TTL, а все кнопки в этом состоянии игнорируются.
        if await state.get_state() == Recomendations.processing.state:
            await state.set_state(Recomendations.waiting_for_action)


async def _handle_movie_action(
    callback: CallbackQuery,
    action: str,
    state: FSMContext,
    session: AsyncSession,
    bot: Bot,
    user_id: int,
):
    data = await state.get_data()
    movie, movie_ids, current_index = await _current_movie(state, session, data)
    movie_title = movie.title if movie else "???"

    logger.info(
        "[Действие] user_id=%s нажал '%s' | фильм [%d/%d]: '%s'",
        user_id, action, current_index + 1, len(movie_ids), movie_title,
    )

    if data.get("last_action", "") == "watched":
        logger.debug("[Действие] user_id=%s — ожидается оценка, игнорирую '%s'", user_id, action)
        await safe_callback_answer(callback)
        return

    if action == "stop_recommendations":
        remaining_ids = movie_ids[current_index:] if 0 <= current_index < len(movie_ids) else []
        logger.info("[Действие] user_id=%s — остановка рекомендаций, сохраняю %d непросмотренных", user_id, len(remaining_ids))
        for mid in remaining_ids:
            await add_movies_by_interaction(user_id, mid, "unwatched", session)

        try:
            await bot.delete_message(chat_id=callback.message.chat.id, message_id=callback.message.message_id)
        except Exception:
            pass
        await state.clear()
        # Раньше здесь всё заканчивалось удалением карточки: пустой чат без кнопок,
        # и юзеру оставалось догадаться набрать /start.
        await callback.message.answer(
            "Остановил подбор. Отложенные фильмы сохранил — вернёмся к ним в следующий раз.",
            reply_markup=get_callback_btns(btns=MAIN_MENU_BTNS),
        )
        await safe_callback_answer(callback)
        return

    if movie is None:
        logger.error("[Действие] user_id=%s — фильм не найден (индекс %d из %d)", user_id, current_index, len(movie_ids))
        await callback.message.answer(
            "Возникла ошибка с выбором фильма. Попробуйте снова.",
            reply_markup=get_callback_btns(btns={"Запуск рекомендаций": "recommendations", "В меню": "to_the_main_page"}),
        )
        await state.clear()
        await safe_callback_answer(callback)
        return

    if action in ("like", "next"):
        interaction_type = "liked" if action == "like" else "skipped"
        logger.info("[Действие] user_id=%s — %s фильм '%s' (tmdb_id=%s)", user_id, interaction_type, movie_title, movie.tmdb_id)
        await add_movies_by_interaction(user_id, movie.tmdb_id, interaction_type, session)

    if action == "watched":
        logger.info("[Действие] user_id=%s — отметил 'Смотрел' фильм '%s', жду оценку", user_id, movie_title)
        # Пишем взаимодействие сразу: если юзер уйдёт, не поставив оценку,
        # фильм всё равно не всплывёт снова. Оценка потом уточнит запись
        # (add_movies_by_interaction обновляет строку по паре user_id+movie_id).
        await add_movies_by_interaction(user_id, movie.tmdb_id, "watched", session)
        await state.update_data(last_action="watched")
        await callback.message.edit_caption(caption="Пожалуйста, оцените фильм", reply_markup=rate_buttons)
        await safe_callback_answer(callback)
        return

    await _advance(callback, state, session, user_id, current_index, movie_ids, data)


async def _advance(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    user_id: int,
    current_index: int,
    movie_ids: list,
    data: dict,
):
    """Переход к следующему фильму или подгрузка новой порции."""
    current_index += 1
    await state.update_data(current_index=current_index)

    if current_index < len(movie_ids):
        next_movie = await get_movie_from_db(movie_ids[current_index], session)
        if next_movie is not None:
            logger.info("[Действие] user_id=%s — переход к фильму [%d/%d]: '%s'", user_id, current_index + 1, len(movie_ids), next_movie.title)
            await send_movie_card(
                callback.message, next_movie, current_index, edit=True, custom_keyboard=create_movie_carousel_keyboard
            )
            await state.set_state(Recomendations.waiting_for_action)
            await safe_callback_answer(callback)
            return
        logger.warning("[Действие] user_id=%s — фильм tmdb_id=%s пропал из БД, подгружаю новую порцию", user_id, movie_ids[current_index])

    if data.get("custom_query", False):
        logger.info("[Действие] user_id=%s — пользовательский запрос исчерпан, завершаю", user_id)
        await callback.message.answer(
            "Это были все фильмы по твоему запросу.",
            reply_markup=get_callback_btns(btns={"Запуск рекомендаций": "recommendations", "В меню": "to_the_main_page"}),
        )
        await state.clear()
        await safe_callback_answer(callback)
        return

    logger.info("[Действие] user_id=%s — список фильмов исчерпан, подгружаю новую порцию", user_id)
    await safe_callback_answer(callback, "Подождите немного, подгружаем новые рекомендации...")
    await _load_next_batch(callback, state, session, user_id)


@recommendations_router.callback_query(lambda c: c.data in ("1", "2", "3", "4", "5"))
async def handle_rating(callback: types.CallbackQuery, state: FSMContext, session: AsyncSession, bot: Bot):
    user_rating = int(callback.data)
    user_id = callback.from_user.id

    data = await state.get_data()
    movie, movie_ids, current_index = await _current_movie(state, session, data)

    if movie is None:
        logger.error("[Оценка] user_id=%s — фильм не найден (индекс %d из %d)", user_id, current_index, len(movie_ids))
        await safe_callback_answer(callback, "Ошибка: фильм не найден")
        await state.clear()
        return

    interaction = "watched" if user_rating >= 4 else "disliked"
    logger.info(
        "[Оценка] user_id=%s оценил '%s' (tmdb_id=%s) на %d/5 → %s",
        user_id, movie.title, movie.tmdb_id, user_rating, interaction,
    )
    await add_movies_by_interaction(user_id, movie.tmdb_id, interaction, session)

    await state.update_data(last_action="")
    await _advance(callback, state, session, user_id, current_index, movie_ids, data)
