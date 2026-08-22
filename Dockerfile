FROM python:3.10-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends libpq5 postgresql-client \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --upgrade pip && pip install -r requirements.txt

COPY . .

RUN mkdir -p /app/logs /app/media /app/staticfiles /app/backups \
    && DJANGO_SECRET_KEY=build-only-key python manage.py collectstatic --noinput

EXPOSE 8000

CMD ["gunicorn", "filemanager.wsgi:application", "--bind", "0.0.0.0:8000", "--workers=3"]
