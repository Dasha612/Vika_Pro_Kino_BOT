import logging
import asyncio

from aiogram import Router, Bot, types, F
from aiogram.types import CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy.ext.asyncio import AsyncSession

from handlers.callback_data import Menu_Callback
from handlers.movie_utils import send_movie_card
from database.orm_query import (
    add_movies_by_interaction,
    get_movies_by_interaction,
    check_recommendations_status,
    delete_movies_by_interaction,
    get_movies_by_profile_embedding,
)
from kbds.inline import get_callback_btns, rate_buttons
from kbds.pagination import create_movie_carousel_keyboard

logger = logging.getLogger(__name__)

recommendations_router = Router()

MAX_RETRY_RECOMMENDATIONS = 3


class Recomendations(StatesGroup):
    waiting_for_action = State()
    processing = State()
    waiting_for_rating = State()
    waiting_for_query = State()


async def safe_callback_answer(callback: CallbackQuery, text: str = None, show_alert: bool = False):
    try:
        await callback.answer(text=text, show_alert=show_alert)
    except Exception as e:
        logger.warning("Ошибка при callback.answer(): %s", e)


def _get_movie_tmdb_id(movie) -> int | None:
    """Извлекает tmdb_id из ORM-объекта или словаря."""
    if hasattr(movie, "tmdb_id"):
        return movie.tmdb_id
    if isinstance(movie, dict):
        return movie.get("tmdb_id") or movie.get("id")
    return None


@recommendations_router.callback_query(F.data == "choose_option")
async def options(callback: CallbackQuery, session: AsyncSession, bot: Bot, state: FSMContext):
    logger.info("[Рекомендации] user_id=%s открыл меню 'Выберите опцию'", callback.from_user.id)
    await callback.message.edit_text(
        "<b>Выберите опцию</b>",
        parse_mode="HTML",
        reply_markup=get_callback_btns(
            btns={
                "Запуск рекомендаций": "recommendations",
                "Свой запрос": "search_movie",
                "Найти фильм вместе": "find_together",
                "Вернуться в меню": "to_the_main_page",
            }
        ),
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
        "Введите свой запрос и я покажу несколько фильмов/сериалов, соответствующих вашим предпочтениям :D"
    )
    await state.update_data(prompt_message_id=msg.message_id)
    await callback.answer()


@recommendations_router.message(Recomendations.waiting_for_query, F.text)
async def process_search_query(message: types.Message, state: FSMContext, session: AsyncSession, bot: Bot):
    user_text = message.text
    if not user_text:
        return
    logger.info("[Поиск] user_id=%s ввёл запрос: '%s'", message.from_user.id, user_text)

    await bot.send_chat_action(message.chat.id, action="typing")
    await asyncio.sleep(1)

    # TODO: здесь будет обработка через ChatGPT — парсинг запроса и поиск по БД
    await message.answer(
        "Функция поиска по запросу пока в разработке. Попробуйте «Запуск рекомендаций».",
        reply_markup=get_callback_btns(
            btns={"Запуск рекомендаций": "recommendations", "В меню": "to_the_main_page"}
        ),
    )
    await state.clear()


@recommendations_router.callback_query(F.data == "recommendations")
async def send_recommendations(callback: CallbackQuery, session: AsyncSession, bot: Bot, state: FSMContext):
    user_id = callback.from_user.id
    logger.info("[Рекомендации] user_id=%s нажал 'Запуск рекомендаций'", user_id)
    await safe_callback_answer(callback)

    current_state = await state.get_state()
    blocked_states = [
        Recomendations.waiting_for_action.state,
        Recomendations.processing.state,
        Recomendations.waiting_for_rating.state,
        Recomendations.waiting_for_query.state,
    ]

    if current_state in blocked_states:
        logger.debug("[Рекомендации] user_id=%s — заблокировано, состояние: %s", user_id, current_state)
        await safe_callback_answer(callback, "Подождите, пока завершится текущий процесс.")
        return

    await bot.send_chat_action(callback.message.chat.id, action="typing")
    await asyncio.sleep(1)

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
        first_title = getattr(unwatched_movies[0], "title", "???")
        logger.info("[Рекомендации] user_id=%s — показываю непросмотренный: '%s'", user_id, first_title)
        message = await send_movie_card(
            callback.message, unwatched_movies[0], 0, custom_keyboard=create_movie_carousel_keyboard
        )
        await state.set_state(Recomendations.waiting_for_action)
        await state.update_data(
            movies=unwatched_movies,
            current_index=0,
            message_id=message.message_id,
            chat_id=message.chat.id,
        )
        movie_id = _get_movie_tmdb_id(unwatched_movies[0])
        if movie_id:
            await delete_movies_by_interaction(user_id, session, ["unwatched"], movie_id)
    else:
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

        first_title = getattr(movies[0], "title", "???")
        logger.info("[Рекомендации] user_id=%s — подобрано %d фильмов, первый: '%s'", user_id, len(movies), first_title)
        message = await send_movie_card(
            callback.message, movies[0], 0, custom_keyboard=create_movie_carousel_keyboard
        )
        await state.set_state(Recomendations.waiting_for_action)
        await state.update_data(
            movies=movies,
            current_index=0,
            message_id=message.message_id,
            chat_id=message.chat.id,
        )


async def _load_next_batch(callback: CallbackQuery, state: FSMContext, session: AsyncSession, user_id: int):
    """Подгружает следующую порцию рекомендаций по эмбеддингу."""
    logger.info("[Рекомендации] user_id=%s — подгрузка новой порции фильмов", user_id)
    movies = await get_movies_by_profile_embedding(session, user_id, top_k=50)

    if not movies:
        logger.warning("[Рекомендации] user_id=%s — новая порция пуста, фильмы закончились", user_id)
        await callback.message.edit_text(
            "Пока не смог подобрать новые фильмы. Попробуй обновить анкету.",
            reply_markup=get_callback_btns(
                btns={"Обновить анкету": "reset_anketa", "В меню": "to_the_main_page"}
            ),
        )
        await state.clear()
        return

    first_title = getattr(movies[0], "title", "???")
    logger.info("[Рекомендации] user_id=%s — новая порция: %d фильмов, первый: '%s'", user_id, len(movies), first_title)
    message = await send_movie_card(
        callback.message, movies[0], 0, custom_keyboard=create_movie_carousel_keyboard
    )
    await state.set_state(Recomendations.waiting_for_action)
    await state.update_data(
        movies=movies,
        current_index=0,
        message_id=message.message_id,
        chat_id=message.chat.id,
    )


@recommendations_router.callback_query(Menu_Callback.filter())
async def handle_movie_action(
    callback: CallbackQuery,
    callback_data: Menu_Callback,
    state: FSMContext,
    session: AsyncSession,
    bot: Bot,
):
    data = await state.get_data()
    movies = data.get("movies", [])
    current_index = data.get("current_index", 0)
    action = callback_data.menu_name
    user_id = callback.from_user.id
    current_state = await state.get_state()

    movie_title = "???"
    if 0 <= current_index < len(movies):
        movie_title = getattr(movies[current_index], "title", None) or (movies[current_index].get("title") if isinstance(movies[current_index], dict) else "???")

    logger.info(
        "[Действие] user_id=%s нажал '%s' | фильм [%d/%d]: '%s' | состояние: %s",
        user_id, action, current_index + 1, len(movies), movie_title, current_state,
    )

    if current_state == Recomendations.processing.state:
        logger.debug("[Действие] user_id=%s — нажатие проигнорировано, идёт обработка", user_id)
        await safe_callback_answer(callback, "Пожалуйста, подождите...")
        return

    await state.set_state(Recomendations.processing)

    if current_index >= len(movies) or current_index < 0:
        logger.error("[Действие] user_id=%s — индекс %d вне диапазона (всего %d)", user_id, current_index, len(movies))
        await callback.message.answer("Возникла ошибка с выбором фильма. Попробуйте снова.")
        await safe_callback_answer(callback)
        await state.set_state(Recomendations.waiting_for_action)
        return

    movie = movies[current_index]
    last_action = data.get("last_action", "")

    if last_action == "watched":
        logger.debug("[Действие] user_id=%s — ожидается оценка, игнорирую '%s'", user_id, action)
        await state.set_state(Recomendations.waiting_for_action)
        await safe_callback_answer(callback)
        return

    if action == "stop_recommendations":
        remaining_movies = movies[current_index:]
        logger.info("[Действие] user_id=%s — остановка рекомендаций, сохраняю %d непросмотренных", user_id, len(remaining_movies))
        for m in remaining_movies:
            mid = _get_movie_tmdb_id(m)
            if mid:
                await add_movies_by_interaction(user_id, mid, "unwatched", session)

        try:
            await bot.delete_message(chat_id=callback.message.chat.id, message_id=callback.message.message_id)
        except Exception:
            pass
        await state.clear()
        await safe_callback_answer(callback)
        return

    if action in ("like", "next"):
        interaction_type = "liked" if action == "like" else "skipped"
        mid = _get_movie_tmdb_id(movie)
        if mid:
            logger.info("[Действие] user_id=%s — %s фильм '%s' (tmdb_id=%s)", user_id, interaction_type, movie_title, mid)
            await add_movies_by_interaction(user_id, mid, interaction_type, session)

    if action == "watched":
        logger.info("[Действие] user_id=%s — отметил 'Смотрел' фильм '%s', жду оценку", user_id, movie_title)
        await state.set_state(Recomendations.waiting_for_action)
        await state.update_data(last_action="watched")
        await callback.message.edit_caption(caption="Пожалуйста, оцените фильм", reply_markup=rate_buttons)
        await safe_callback_answer(callback)
        return

    current_index += 1
    await state.update_data(current_index=current_index)

    if current_index < len(movies):
        next_title = getattr(movies[current_index], "title", None) or (movies[current_index].get("title") if isinstance(movies[current_index], dict) else "???")
        logger.info("[Действие] user_id=%s — переход к фильму [%d/%d]: '%s'", user_id, current_index + 1, len(movies), next_title)
        await send_movie_card(
            callback.message, movies[current_index], current_index, edit=True, custom_keyboard=create_movie_carousel_keyboard
        )
        await state.set_state(Recomendations.waiting_for_action)
        await safe_callback_answer(callback)
    else:
        is_custom_query = data.get("custom_query", False)
        if is_custom_query:
            logger.info("[Действие] user_id=%s — пользовательский запрос исчерпан, завершаю", user_id)
            try:
                await callback.message.delete()
            except Exception:
                pass
            await state.clear()
            return

        logger.info("[Действие] user_id=%s — список фильмов исчерпан, подгружаю новую порцию", user_id)
        await safe_callback_answer(callback, "Подождите немного, подгружаем новые рекомендации...")
        await _load_next_batch(callback, state, session, user_id)


@recommendations_router.callback_query(lambda c: c.data in ("1", "2", "3", "4", "5"))
async def handle_rating(callback: types.CallbackQuery, state: FSMContext, session: AsyncSession, bot: Bot):
    user_rating = int(callback.data)
    data = await state.get_data()
    current_index = data.get("current_index", 0)
    movies = data.get("movies", [])

    if current_index >= len(movies):
        logger.error("[Оценка] user_id=%s — индекс %d вне диапазона (всего %d)", callback.from_user.id, current_index, len(movies))
        await safe_callback_answer(callback, "Ошибка: фильм не найден")
        await state.clear()
        return

    movie = movies[current_index]
    user_id = callback.from_user.id
    mid = _get_movie_tmdb_id(movie)
    movie_title = getattr(movie, "title", None) or (movie.get("title") if isinstance(movie, dict) else "???")

    if mid:
        interaction = "watched" if user_rating >= 4 else "disliked"
        logger.info(
            "[Оценка] user_id=%s оценил '%s' (tmdb_id=%s) на %d/5 → %s",
            user_id, movie_title, mid, user_rating, interaction,
        )
        await add_movies_by_interaction(user_id, mid, interaction, session)

    await state.update_data(last_action="")
    current_index += 1
    await state.update_data(current_index=current_index)

    if current_index < len(movies):
        next_title = getattr(movies[current_index], "title", None) or (movies[current_index].get("title") if isinstance(movies[current_index], dict) else "???")
        logger.info("[Оценка] user_id=%s — переход к фильму [%d/%d]: '%s'", user_id, current_index + 1, len(movies), next_title)
        await send_movie_card(
            callback.message, movies[current_index], current_index, edit=True, custom_keyboard=create_movie_carousel_keyboard
        )
        await state.set_state(Recomendations.waiting_for_action)
        await safe_callback_answer(callback)
    else:
        is_custom_query = data.get("custom_query", False)
        if is_custom_query:
            logger.info("[Оценка] user_id=%s — пользовательский запрос исчерпан, завершаю", user_id)
            try:
                await callback.message.delete()
            except Exception:
                pass
            await state.clear()
            return

        logger.info("[Оценка] user_id=%s — список исчерпан, подгружаю новую порцию", user_id)
        await safe_callback_answer(callback, "Подождите немного, подгружаем новые рекомендации...")
        await _load_next_batch(callback, state, session, user_id)
