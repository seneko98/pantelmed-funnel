# PantelMed Platform Dockerfile
# Multi-stage build для оптимізації розміру образу

# ==============================================
# STAGE 1: Base Python Image
# ==============================================
FROM python:3.11-slim as base

# Встановлення системних залежностей
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    libffi-dev \
    libssl-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Створення користувача для безпеки
RUN useradd --create-home --shell /bin/bash pantelmed

# Встановлення робочої директорії
WORKDIR /app

# Копіювання requirements.txt для кешування шарів
COPY requirements.txt .

# Оновлення pip та встановлення Python залежностей
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# ==============================================
# STAGE 2: Production Image
# ==============================================
FROM python:3.11-slim as production

# Встановлення мінімальних системних залежностей
RUN apt-get update && apt-get install -y \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Створення користувача
RUN useradd --create-home --shell /bin/bash pantelmed

# Створення директорії додатка
WORKDIR /app

# Копіювання встановлених Python пакетів з базового образу
COPY --from=base /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=base /usr/local/bin /usr/local/bin

# Копіювання файлів додатка
COPY --chown=pantelmed:pantelmed . .

# Створення директорій для логів та тимчасових файлів
RUN mkdir -p /app/logs /app/uploads && \
    chown -R pantelmed:pantelmed /app

# Встановлення змінних середовища за замовчуванням
ENV FLASK_APP=app.py
ENV FLASK_ENV=production
ENV PYTHONPATH=/app
ENV PORT=10000

# Налаштування мережі
EXPOSE 10000

# Перехід на непривілейованого користувача
USER pantelmed

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:${PORT}/health || exit 1

# Команда запуску
CMD ["gunicorn", "--bind", "0.0.0.0:10000", "--workers", "4", "--timeout", "120", "app:app"]

# ==============================================
# DEVELOPMENT VERSION
# ==============================================
FROM production as development

# Перехід на root для встановлення dev залежностей
USER root

# Встановлення додаткових dev залежностей
RUN pip install --no-cache-dir \
    flask-debugtoolbar \
    pytest \
    pytest-flask \
    black \
    flake8

# Повернення до непривілейованого користувача
USER pantelmed

# Переопределение команди для розробки
CMD ["python", "app.py"]

# ==============================================
# TELEGRAM BOT VERSION
# ==============================================
FROM python:3.11-slim as telegram-bot

# Встановлення системних залежностей
RUN apt-get update && apt-get install -y \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Створення користувача
RUN useradd --create-home --shell /bin/bash botuser

WORKDIR /app

# Встановлення залежностей для бота
RUN pip install --no-cache-dir \
    python-telegram-bot[all] \
    aiohttp \
    python-dotenv

# Копіювання файлу бота
COPY --chown=botuser:botuser telegram_bot.py .
COPY --chown=botuser:botuser .env* ./

USER botuser

# Health check для бота
HEALTHCHECK --interval=60s --timeout=30s --start-period=10s --retries=3 \
    CMD python -c "import asyncio; import telegram; print('Bot health check')" || exit 1

# Команда запуску бота
CMD ["python", "telegram_bot.py"]
