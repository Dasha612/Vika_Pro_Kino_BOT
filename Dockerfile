FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

RUN echo 'Acquire::ForceIPv4 "true";' > /etc/apt/apt.conf.d/99force-ipv4 \
    && apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*

# torch ставится отдельно и ДО requirements.txt. С обычного PyPI он приезжает
# со сборками под CUDA (пакеты nvidia-*, несколько гигабайт), которые на сервере
# без видеокарты просто лежат мёртвым грузом в образе. Индекс .../whl/cpu отдаёт
# ту же версию без CUDA. Дальше pip видит torch уже установленным и не трогает его,
# когда его затребует sentence-transformers.
# Версию тут стоит зафиксировать после первой удачной сборки:
#   docker compose run --rm bot pip freeze | grep -i "^torch"
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Модель кладём внутрь образа на этапе сборки, а не качаем при старте.
# HF_HOME задаёт, куда именно — тот же путь читается в рантайме.
ENV HF_HOME=/opt/hf \
    EMBEDDING_MODEL=paraphrase-multilingual-MiniLM-L12-v2

# Этот слой стоит ДО "COPY . ." намеренно: правка любого .py инвалидирует все
# следующие слои, и окажись скачивание ниже — каждая пересборка заново тянула бы
# ~500 МБ с huggingface.co. Здесь же слой зависит только от requirements.txt.
RUN python -c "import os; from sentence_transformers import SentenceTransformer; SentenceTransformer(os.environ['EMBEDDING_MODEL'])"

# Модель уже в образе, ходить за ней в сеть незачем. Без этого библиотека всё равно
# стучится на хаб проверить обновления и, если сети нет, ждёт таймаута на каждом старте.
# Если понадобится сменить модель без пересборки — убрать эту строку.
ENV HF_HUB_OFFLINE=1

COPY . .

CMD ["python", "app.py"]
