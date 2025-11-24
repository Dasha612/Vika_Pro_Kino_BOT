
import argparse
import asyncio

from database.engine import create_db, drop_db, session_maker
from database.orm_query import update_movies_db

async def cmd_create_db():
    await create_db()
    print("База создана (если таблиц не было).")

async def cmd_drop_db(force: bool):
    if not force:
        print("Отмена: для дропа базы добавь --force")
        return
    await drop_db()
    print("База удалена.")

async def cmd_update_movies(limit: int | None):
    async with session_maker() as session:
        await update_movies_db(session, language="ru-RU", limit=limit)
    print("Фильмы обновлены.")

async def main_async(args):
    if args.command == "create-db":
        await cmd_create_db()
    elif args.command == "drop-db":
        await cmd_drop_db(force=args.force)
    elif args.command == "update-movies":
        await cmd_update_movies(limit=args.limit)

def main():
    parser = argparse.ArgumentParser(description="Управление БД кино-бота")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # create-db
    subparsers.add_parser("create-db", help="Создать структуру БД")

    # drop-db
    drop_parser = subparsers.add_parser("drop-db", help="Удалить БД (ОПАСНО)")
    drop_parser.add_argument("--force", action="store_true", help="Подтверждение удаления")

    # update-movies
    upd_parser = subparsers.add_parser("update-movies", help="Обновить таблицу фильмов")
    upd_parser.add_argument("--limit", type=int, default=None, help="Ограничить количество новых фильмов")

    args = parser.parse_args()
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()


#