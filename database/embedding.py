import logging
import os

import numpy as np

logger = logging.getLogger(__name__)

# Имя берётся из окружения, потому что Dockerfile скачивает модель в образ по этой же
# переменной. Захардкоженное здесь имя разъехалось бы с тем, что реально лежит в образе,
# а с HF_HUB_OFFLINE=1 это не тихая перекачка, а падение на старте.
# Дефолт оставлен, чтобы запуск без docker работал как раньше.
MODEL_NAME = os.getenv("EMBEDDING_MODEL", "paraphrase-multilingual-MiniLM-L12-v2")

_model = None


def get_model():
    """Ленивая загрузка модели — инициализируется при первом вызове."""
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        logger.info("Загрузка модели %s...", MODEL_NAME)
        _model = SentenceTransformer(MODEL_NAME)
        logger.info("Модель загружена")
    return _model


def build_movie_text(info: dict) -> str:
    parts = []

    title = info.get("title") or ""
    orig = info.get("original_title") or ""
    if title:
        parts.append(f"Название: {title}")
    if orig and orig != title:
        parts.append(f"Оригинальное название: {orig}")

    tagline = (info.get("tagline") or "").strip()
    if tagline:
        parts.append(f"Слоган: {tagline}")

    genres = info.get("genres") or []
    if genres:
        parts.append("Жанры: " + ", ".join(genres))

    keywords = info.get("keywords") or []
    if keywords:
        parts.append("Ключевые слова: " + ", ".join(keywords))

    actors = info.get("actors") or []
    if actors:
        parts.append("Актёры: " + ", ".join(actors[:8]))

    directors = info.get("directors") or []
    if directors:
        parts.append("Режиссёры: " + ", ".join(directors))

    countries = info.get("production_countries") or []
    if countries:
        parts.append("Страны: " + ", ".join(countries))

    overview = (info.get("overview") or "").strip()
    if overview:
        parts.append("Описание: " + overview)

    return "\n".join(parts)


def build_profile_text(anketa) -> str:
    """Собирает текстовый профиль пользователя из анкеты для эмбеддинга."""
    parts = []
    if anketa.mood:
        parts.append(f"Настроение: {anketa.mood}")
    if anketa.genres:
        parts.append(f"Жанры: {anketa.genres}")
    if anketa.era:
        parts.append(f"Эпоха: {anketa.era}")
    if anketa.themes:
        parts.append(f"Темы: {anketa.themes}")
    if anketa.country:
        parts.append(f"Страны: {anketa.country}")
    return "\n".join(parts)


def cosine_sim(a: np.ndarray, b: np.ndarray) -> float:
    """Косинусное сходство двух векторов."""
    a = a.astype("float32")
    b = b.astype("float32")
    denom = np.linalg.norm(a) * np.linalg.norm(b) + 1e-9
    return float(np.dot(a, b) / denom)
