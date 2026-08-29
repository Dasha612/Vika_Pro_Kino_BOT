import asyncio
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent


def _upgrade_sync() -> None:
    from alembic import command
    from alembic.config import Config

    alembic_cfg = Config(str(BASE_DIR / "alembic.ini"))
    # Путь абсолютный: иначе alembic ищет migrations/ относительно cwd,
    # а бот запускается не обязательно из корня проекта.
    alembic_cfg.set_main_option("script_location", str(BASE_DIR / "migrations"))
    command.upgrade(alembic_cfg, "head")


async def run_migrations() -> None:
    """Приводит схему БД к последней ревизии.

    Alembic синхронный, а его env.py поднимает внутри себя event loop через
    asyncio.run(). Поэтому вызов идёт строго в отдельном потоке: в текущем уже
    крутится loop бота, и asyncio.run() там бросил бы RuntimeError.
    """
    logger.info("Применяю миграции Alembic...")
    await asyncio.to_thread(_upgrade_sync)
    logger.info("Схема БД в актуальном состоянии")
