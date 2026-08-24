FROM python:3.12-slim

WORKDIR /app

# Системные зависимости для asyncpg/Pillow
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev gcc && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

# Production: без --reload. Два воркера: один процесс означал бы, что любое
# CPU-плато (Pillow, JSON на большом ответе) или зависший вызов стопит ВЕСЬ
# сервис; двум процессам это уже не грозит, а advisory-лок в lifespan
# (main.py) сериализует их гонку за миграции. Больше двух — только после
# пересчёта соединений: 2 × (DB_POOL_SIZE+DB_MAX_OVERFLOW) + пул бота должны
# оставаться под max_connections Postgres (расчёт в database/connection.py).
# Порт берём из $PORT: Railway подставляет свой динамический порт и на него же
# маршрутизирует — контейнер, прибитый к 8000, оказался бы недостижим, и
# /health не поднялся бы. Локально в docker compose $PORT не задан, падаем на
# 8000 (совпадает с проброшенным портом). Так же устроен web/Dockerfile.
# Хост :: (dual-stack), не 0.0.0.0: healthcheck и приватная сеть Railway ходят
# по IPv6 — IPv4-only сокет для них не существует, и живой процесс выглядел бы
# как «replicas never became healthy».
CMD ["sh", "-c", "uvicorn main:app --host :: --port ${PORT:-8000} --workers ${WEB_CONCURRENCY:-2}"]
