import html
import logging

from aiogram import Router, Bot, types, F
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy.ext.asyncio import AsyncSession

from handlers.callback_data import Menu_Callback
from handlers.movie_utils import send_movie_card, truncate
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

PROFILE_HEADER = "<b>Подборка по твоему профилю</b>"
SEARCH_EXAMPLES = "Например: <i>мрачный детектив про маньяка</i> или <i>лёгкое кино про дружбу</i>."
# Запрос юзера целиком в заголовке не нужен — он только растягивает сообщение
HEADER_QUERY_LIMIT = 100
ERROR_TEXT = "Возникла ошибка с выбором фильма. Попробуйте снова."
ERROR_BTNS = {"Запуск рекомендаций": "recommendations", "В меню": "to_the_main_page"}
# Анкета, открытая из «Запуска рекомендаций»: после неё сразу идёт подбор
SET_PROFILE_THEN_RECS = "set_profile_recs"


def _cancel_search_kb():
    # Без кнопки состояние waiting_for_query — тупик: меню заблокировано,
    # и выйти можно было бы только командой /reset.
    return get_callback_btns(btns={"Отмена": "cancel_search"}, sizes=(1,))


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


async def _delete_quietly(message: types.Message):
    try:
        await message.delete()
    except Exception as e:
        logger.debug("Не удалось удалить сообщение %s: %s", message.message_id, e)


async def _edit_or_answer(message: types.Message, message_id: int | None, text: str, reply_markup=None):
    """Пишет текст в уже существующее сообщение бота вместо того, чтобы слать новое.

    message — любое сообщение из этого чата (даже уже удалённое): через него берём
    chat_id и шлём новое, если отредактировать не вышло — сообщения нет, оно
    слишком старое и т.п. Без кнопок юзер оставаться не должен.
    """
    if message_id:
        try:
            await message.bot.edit_message_text(
                text, chat_id=message.chat.id, message_id=message_id, reply_markup=reply_markup
            )
            return
        except TelegramBadRequest as e:
            # Тот же текст повторно (например, второй стикер подряд) — не ошибка.
            if "message is not modified" in str(e):
                return
            logger.warning("Не удалось отредактировать сообщение %s: %s", message_id, e)
    await message.answer(text, reply_markup=reply_markup)


async def _set_header(message: types.Message, origin_message_id: int | None, text: str):
    """Превращает исходное сообщение (меню или приглашение) в заголовок над карточкой.

    Кнопки над карточкой, пока идёт подбор, всё равно заблокированы, а «Отмена»
    из поиска в этом состоянии вообще ни на что не отвечает — поэтому снимаем их
    (edit без reply_markup убирает клавиатуру).
    """
    if not origin_message_id:
        return
    try:
        await message.bot.edit_message_text(text, chat_id=message.chat.id, message_id=origin_message_id)
    except TelegramBadRequest as e:
        logger.debug("Не удалось поставить заголовок в сообщение %s: %s", origin_message_id, e)


async def _show_movie(
    callback: CallbackQuery,
    state: FSMContext,
    movies: list,
    edit: bool = False,
    origin_message_id: int | None = None,
):
    """Показывает первый фильм списка и кладёт в FSM только их id.

    origin_message_id — меню, с которого начался подбор. Передаётся только на
    старте: оно становится заголовком над карточкой, а при подгрузке новой порции
    в FSM остаётся прежнее значение.
    """
    message = await send_movie_card(
        callback.message, movies[0], 0, edit=edit, custom_keyboard=create_movie_carousel_keyboard
    )
    await state.set_state(Recomendations.waiting_for_action)
    data = dict(
        movie_ids=[m.tmdb_id for m in movies],
        current_index=0,
        last_action="",
        # Явно гасим флаг: сюда попадают только подборки по профилю, и по исчерпании
        # списка бот должен подгружать новую порцию, а не завершать подбор.
        custom_query=False,
        message_id=message.message_id,
        chat_id=message.chat.id,
    )
    if origin_message_id is not None:
        data["origin_message_id"] = origin_message_id
        await _set_header(message, origin_message_id, PROFILE_HEADER)
    await state.update_data(**data)
    return message


async def _replace_card_with_text(callback: CallbackQuery, origin_message_id: int | None, text: str, reply_markup):
    """Убирает карточку и пишет итоговый текст в сообщение, с которого начался подбор.

    Карточка — фото, а Telegram не даёт отредактировать фото-сообщение в текстовое.
    Поэтому карточку удаляем, а текст кладём в исходное сообщение (заголовок прямо
    над карточкой) — новых сообщений в чате не появляется.
    """
    await _delete_quietly(callback.message)
    await _edit_or_answer(callback.message, origin_message_id, text, reply_markup)


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
        f"Опиши, что хочешь посмотреть — своими словами.\n{SEARCH_EXAMPLES}",
        parse_mode="HTML",
        reply_markup=_cancel_search_kb(),
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
    # Ответ юзера в чате не оставляем: запрос будет виден в заголовке над карточкой.
    await _delete_quietly(message)
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
    prompt_message_id = (await state.get_data()).get("prompt_message_id")
    movies = await get_movies_by_text_query(session, message.from_user.id, user_text)

    if not movies:
        logger.info("[Поиск] user_id=%s — пустая выдача по запросу", message.from_user.id)
        await state.clear()
        await _edit_or_answer(
            message,
            prompt_message_id,
            "Ничего не нашёл по этому запросу. Попробуй переформулировать — "
            "чем подробнее опишешь настроение и сюжет, тем лучше я попадаю.",
            get_callback_btns(btns=RECOMMENDATIONS_MENU_BTNS),
        )
        return

    # Приглашение — текстовое сообщение, в карточку-фото его не превратить,
    # поэтому карточка идёт отдельным сообщением, а приглашение становится заголовком.
    msg = await send_movie_card(message, movies[0], 0, custom_keyboard=create_movie_carousel_keyboard)
    await _set_header(
        message,
        prompt_message_id,
        f"<b>Фильмы по запросу:</b> «{html.escape(truncate(user_text, HEADER_QUERY_LIMIT))}»",
    )
    await state.set_state(Recomendations.waiting_for_action)
    await state.update_data(
        movie_ids=[m.tmdb_id for m in movies],
        current_index=0,
        last_action="",
        # Подборка конечная: новых порций по запросу не бывает, добирать нечего.
        custom_query=True,
        message_id=msg.message_id,
        chat_id=msg.chat.id,
        origin_message_id=prompt_message_id,
    )


@recommendations_router.message(Recomendations.waiting_for_query)
async def reject_non_text_query(message: types.Message, state: FSMContext):
    """Стикер/фото/голосовое в режиме ввода запроса: без этого хендлера
    апдейт молча проваливался бы мимо, и бот выглядел бы зависшим."""
    await _delete_quietly(message)
    await _edit_or_answer(
        message,
        (await state.get_data()).get("prompt_message_id"),
        f"Мне нужен текст — опиши словами, что хочешь посмотреть.\n{SEARCH_EXAMPLES}",
        _cancel_search_kb(),
    )


@recommendations_router.callback_query(F.data == "recommendations")
async def send_recommendations(callback: CallbackQuery, session: AsyncSession, state: FSMContext):
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

    await start_recommendations(callback, session, state)


async def start_recommendations(callback: CallbackQuery, session: AsyncSession, state: FSMContext):
    """Показывает первую карточку подборки в сообщении, где нажали кнопку.

    Вынесено из хендлера, чтобы анкета, открытая из «Запуска рекомендаций»,
    могла сразу продолжить подбор, а не возвращать юзера в меню.
    """
    user_id = callback.from_user.id
    await callback.bot.send_chat_action(callback.message.chat.id, action="typing")

    recommendations_status = await check_recommendations_status(user_id, session)
    if not recommendations_status:
        logger.info("[Рекомендации] user_id=%s — анкета не заполнена, предлагаю заполнить", user_id)
        await callback.message.edit_text(
            "Прежде чем порекомендовать тебе фильм, мне нужно узнать о тебе больше информации. Давай заполним анкету?",
            # Отдельный callback: по нему анкета после сохранения сразу запустит подбор
            reply_markup=get_callback_btns(btns={"Давай": SET_PROFILE_THEN_RECS}),
        )
        return

    unwatched_movies = await get_movies_by_interaction(user_id, session, ["unwatched"])
    logger.info("[Рекомендации] user_id=%s — непросмотренных фильмов в очереди: %d", user_id, len(unwatched_movies))

    if unwatched_movies:
        logger.info("[Рекомендации] user_id=%s — показываю непросмотренный: '%s'", user_id, unwatched_movies[0].title)
        await _show_movie(callback, state, unwatched_movies, origin_message_id=callback.message.message_id)
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
    await _show_movie(callback, state, movies, origin_message_id=callback.message.message_id)


async def _load_next_batch(callback: CallbackQuery, state: FSMContext, session: AsyncSession, user_id: int):
    """Подгружает следующую порцию рекомендаций по эмбеддингу."""
    logger.info("[Рекомендации] user_id=%s — подгрузка новой порции фильмов", user_id)
    movies = await get_movies_by_profile_embedding(session, user_id, top_k=50)

    if not movies:
        logger.warning("[Рекомендации] user_id=%s — новая порция пуста, фильмы закончились", user_id)
        origin_message_id = (await state.get_data()).get("origin_message_id")
        await state.clear()
        await _replace_card_with_text(
            callback,
            origin_message_id,
            "Пока не смог подобрать новые фильмы. Попробуй обновить анкету.",
            get_callback_btns(btns={"Обновить анкету": "reset_anketa", "В меню": "to_the_main_page"}),
        )
        return

    logger.info("[Рекомендации] user_id=%s — новая порция: %d фильмов, первый: '%s'", user_id, len(movies), movies[0].title)
    # edit=True: новая порция встаёт на место текущей карточки, а не шлётся под ней.
    await _show_movie(callback, state, movies, edit=True)


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

        await state.clear()
        await _replace_card_with_text(
            callback,
            data.get("origin_message_id"),
            "Остановил подбор. Отложенные фильмы сохранил — вернёмся к ним в следующий раз.",
            get_callback_btns(btns=MAIN_MENU_BTNS),
        )
        await safe_callback_answer(callback)
        return

    if movie is None:
        logger.error("[Действие] user_id=%s — фильм не найден (индекс %d из %d)", user_id, current_index, len(movie_ids))
        await state.clear()
        await _replace_card_with_text(
            callback, data.get("origin_message_id"), ERROR_TEXT, get_callback_btns(btns=ERROR_BTNS)
        )
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
        await state.clear()
        await _replace_card_with_text(
            callback,
            data.get("origin_message_id"),
            "Это были все фильмы по твоему запросу.",
            get_callback_btns(btns={"Запуск рекомендаций": "recommendations", "В меню": "to_the_main_page"}),
        )
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
        # Иначе карточка так и висела бы с кнопками оценки, которые больше ничего не делают.
        await _replace_card_with_text(
            callback, data.get("origin_message_id"), ERROR_TEXT, get_callback_btns(btns=ERROR_BTNS)
        )
        return

    interaction = "watched" if user_rating >= 4 else "disliked"
    logger.info(
        "[Оценка] user_id=%s оценил '%s' (tmdb_id=%s) на %d/5 → %s",
        user_id, movie.title, movie.tmdb_id, user_rating, interaction,
    )
    await add_movies_by_interaction(user_id, movie.tmdb_id, interaction, session)

    await state.update_data(last_action="")
    await _advance(callback, state, session, user_id, current_index, movie_ids, data)
