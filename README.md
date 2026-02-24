🎬 Movie Recommendation Bot

Telegram-бот для персонализированных рекомендаций фильмов на основе предпочтений пользователя. Использует ChatGPT для генерации рекомендаций, Kinopoisk и OMDb API для получения информации о фильмах, и aiogram для взаимодействия с Telegram.

🔍 Основные функции
- Анкетирование пользователя (жанры, настроение, эпоха)
- Персонализированные рекомендации через ChatGPT
- Интерактивные карточки фильмов с кнопками действий (❤️ Нравится, ⏭ Пропустить, 👀 Смотрел)
- Избранное — сохранение понравившихся фильмов
= Поддержка кастомных запросов (например, "фильмы как Интерстеллар")

🛠 Технологии
Python 3.11+
Aiogram 3.x (асинхронный фреймворк для Telegram)


DB_URL=postgresql+asyncpg://bot_admin:vikabot@localhost:5432/kinobot python manage_db.py update-movies --limit 1000 
DB_URL=postgresql+asyncpg://bot_admin:vikabot@localhost:5432/kinobot python manage_db.py update-movies --source file --limit 10000 

docker compose down -v
docker compose up --build -d