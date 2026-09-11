import asyncio
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent


def _upgrade_sync() -> None:
    from alembic import command
    from alembic.config import Config

    # migrations/env.py вызывает logging.config.fileConfig(alembic.ini), а тот
    # безусловно (даже с disable_existing_loggers=False) переставляет уровень
    # и обработчики root-логгера под alembic.ini — там level=WARNING для
    # автономного запуска `alembic upgrade` из терминала. Без сохранения/
    # восстановления это оседает на весь процесс: все info-логи приложения
    # после миграций (включая предупреждения об ошибках TMDB/эмбеддингов
    # в update_movies_db) молча пропадали бы.
    root_logger = logging.getLogger()
    saved_level = root_logger.level
    saved_handlers = root_logger.handlers[:]
    try:
        alembic_cfg = Config(str(BASE_DIR / "alembic.ini"))
        # Путь абсолютный: иначе alembic ищет migrations/ относительно cwd,
        # а бот запускается не обязательно из корня проекта.
        alembic_cfg.set_main_option("script_location", str(BASE_DIR / "migrations"))
        command.upgrade(alembic_cfg, "head")
    finally:
        root_logger.setLevel(saved_level)
        root_logger.handlers[:] = saved_handlers


async def run_migrations() -> None:
    """Приводит схему БД к последней ревизии.

    Alembic синхронный, а его env.py поднимает внутри себя event loop через
    asyncio.run(). Поэтому вызов идёт строго в отдельном потоке: в текущем уже
    крутится loop бота, и asyncio.run() там бросил бы RuntimeError.
    """
    logger.info("Применяю миграции Alembic...")
    await asyncio.to_thread(_upgrade_sync)
    logger.info("Схема БД в актуальном состоянии")
