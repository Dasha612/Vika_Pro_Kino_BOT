import logging
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from database.models import Base
from config import cfg

logger = logging.getLogger(__name__)

engine = create_async_engine(
    cfg.db_url,
    echo=False,
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,
    pool_recycle=3600,
)

session_maker = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

redis_client: Redis = Redis.from_url(cfg.redis_url, decode_responses=True)


async def drop_db():
    """Схему создаёт Alembic (database/migrate.py), а не create_all — иначе
    изменения вроде uq_user_movie не доезжают до уже существующей базы."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        # Без этого в базе остаётся отметка «ревизия 0002 применена»,
        # и следующий upgrade решит, что делать нечего — таблиц не будет вообще.
        await conn.execute(text("DROP TABLE IF EXISTS alembic_version"))
    logger.warning("Все таблицы БД удалены")
