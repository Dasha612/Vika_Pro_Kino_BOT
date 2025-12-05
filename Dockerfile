FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1

WORKDIR /app
RUN pip install sentence-transformers
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('paraphrase-multilingual-MiniLM-L12-v2')"
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python", "-m", "app.py"]

