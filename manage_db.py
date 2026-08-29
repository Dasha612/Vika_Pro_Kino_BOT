import argparse
import asyncio

from config import setup_logging
from database.engine import drop_db, session_maker
from database.migrate import run_migrations
from database.orm_query import update_movies_db


async def cmd_migrate():
    await run_migrations()
    print("Схема БД приведена к последней ревизии.")


async def cmd_drop_db(force: bool):
    if not force:
        print("Отмена: для дропа базы добавь --force")
        return
    await drop_db()
    print("База удалена.")


async def cmd_update_movies(limit: int | None, source: str):
    # Наполнение обычно запускают до первого старта бота, когда таблиц ещё нет.
    # upgrade идемпотентен: на актуальной схеме он просто ничего не делает.
    await run_migrations()
    async with session_maker() as session:
        await update_movies_db(session, language="ru-RU", limit=limit, source=source)
    print("Фильмы обновлены.")


async def cmd_refresh_ids():
    from database.tmdb_parser import refresh_tmdb_id_list
    await asyncio.to_thread(refresh_tmdb_id_list)
    print("Список movie_ids.txt обновлён из TMDB exports.")


async def main_async(args):
    if args.command == "migrate":
        await cmd_migrate()
    elif args.command == "drop-db":
        await cmd_drop_db(force=args.force)
    elif args.command == "update-movies":
        await cmd_update_movies(limit=args.limit, source=args.source)
    elif args.command == "refresh-ids":
        await cmd_refresh_ids()


def main():
    setup_logging()

    parser = argparse.ArgumentParser(description="Управление БД кино-бота")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("migrate", help="Применить миграции Alembic (создаёт схему с нуля)")

    drop_parser = subparsers.add_parser("drop-db", help="Удалить БД (ОПАСНО)")
    drop_parser.add_argument("--force", action="store_true", help="Подтверждение удаления")

    upd_parser = subparsers.add_parser("update-movies", help="Обновить таблицу фильмов")
    upd_parser.add_argument("--limit", type=int, default=None, help="Ограничить количество")
    upd_parser.add_argument(
        "--source",
        choices=["popular", "file"],
        default="popular",
        help="popular = TMDB popular API (~1000 ID), file = movie_ids.txt (~1M ID)",
    )

    subparsers.add_parser("refresh-ids", help="Скачать свежий movie_ids.txt из TMDB exports")

    args = parser.parse_args()
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
