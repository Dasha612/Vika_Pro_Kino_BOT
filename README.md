# 🎬 Movie Recommendation Bot

Telegram-бот для персонализированных рекомендаций фильмов. Пользователь заполняет
короткую анкету (настроение, жанры, эпоха, страна, темы), из ответов строится
вектор предпочтений, и похожие фильмы ищутся по базе через pgvector.

## 🔍 Возможности

- Анкета: настроение, жанры, эпоха, страна, темы
- Подбор по смыслу: эмбеддинги описаний фильмов + косинусная близость (pgvector)
- Интерактивные карточки с кнопками (❤️ Нравится, ⏭ Следующий, 👀 Смотрел)
- Избранное — сохранение понравившихся фильмов
- Фоновый worker, который постепенно догружает фильмы из TMDB

## 🛠 Стек

- Python 3.12, aiogram 3.x
- PostgreSQL 16 + pgvector — фильмы и векторы (384 измерения)
- Redis — FSM-состояния и кэш вектора предпочтений
- sentence-transformers (`paraphrase-multilingual-MiniLM-L12-v2`) — эмбеддинги
- TMDB API — источник данных о фильмах

## 🚀 Запуск

### 1. Конфигурация

```bash
cp .env.example .env
```

Заполни в `.env` два обязательных поля:

- `TOKEN` — токен от [@BotFather](https://t.me/BotFather)
- `TMDB_API_KEY` — ключ API v3 с https://www.themoviedb.org/settings/api

Остальное уже заполнено рабочими значениями для docker. `CHAT_ID` можно оставить
пустым — тогда проверка подписки на канал выключена.

> Хост базы внутри docker — это имя сервиса `db`, а не `localhost`.
> Логин/пароль/имя базы в `DB_URL` должны совпадать с переменными `POSTGRES_*`.

### 2. Наполнение базы

Без фильмов в базе рекомендаций не будет. Сначала поднимаем только хранилища:

```bash
docker compose up -d db redis
```

Заливаем ~1000 популярных фильмов (5–10 минут). Миграции применятся сами:

```bash
docker compose run --rm bot python manage_db.py update-movies --source popular
```

При желании догружаем ещё из полного списка TMDB (дольше, ~1 час на 20 тысяч):

```bash
docker compose run --rm bot python manage_db.py update-movies --source file --limit 20000
```

### 3. Запуск

```bash
docker compose up --build -d
docker compose logs -f bot
```

Проверка живости: http://localhost:8080/health

Дальше фоновый worker сам догружает по 5000 новых фильмов в сутки.

## 🧰 Полезные команды

```bash
# Применить миграции вручную (бот делает это сам при старте)
docker compose run --rm bot python manage_db.py migrate

# Текущая ревизия схемы
docker compose run --rm bot alembic current

# Сколько фильмов в базе и у скольких есть вектор
docker compose exec db psql -U kinobot_admin -d kinobot_db \
  -c "SELECT count(*) AS total, count(embedding) AS with_embedding FROM movies;"

# Свежий список ID из экспортов TMDB
docker compose run --rm bot python manage_db.py refresh-ids

# Полный снос (удаляет данные!)
docker compose down -v
```
