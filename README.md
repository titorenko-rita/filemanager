# File Manager

Учебный файловый менеджер на Django. Пользователь может зарегистрироваться, загружать, скачивать, заменять и удалять только собственные файлы, отправлять файл по email и смотреть результаты фонового ML-анализа.

## Возможности

- авторизация через `django-allauth`;
- веб-интерфейс и REST API `/api/files/`;
- защищённое скачивание файлов через Django (каталог `media` не публикуется напрямую);
- фоновые задачи Celery и Redis;
- отдельный Flask ML-сервис: OCR изображений, извлечение сущностей, краткое резюме и тональность текста;
- опциональные уведомления по email, Telegram и Sentry;
- Prometheus и Grafana в Docker Compose;
- тесты pytest с минимальным покрытием 80% и GitHub Actions.

## Быстрый локальный запуск

Для основной части приложения достаточно Python 3.10+. Redis и ML-сервис не обязательны: если очередь недоступна, загрузка файлов продолжает работать, но автоматический анализ не запускается.

```powershell
git clone https://github.com/titorenko-rita/filemanager.git
cd filemanager
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
Copy-Item .env.example .env
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

Откройте <http://127.0.0.1:8000/>. Регистрация обычного пользователя доступна на `/accounts/signup/`.

Перед использованием замените `DJANGO_SECRET_KEY` в `.env`. Email, Telegram и Sentry необязательны; пустые значения отключают соответствующую интеграцию. Файл `.env` игнорируется Git и не должен попадать в коммиты.

### Проверка отправки почты

По умолчанию используется Mail.ru: `smtp.mail.ru`, порт `465`, SSL/TLS. В `EMAIL_HOST_PASSWORD` нужен пароль для внешнего приложения, а в настройках ящика должен быть разрешён доступ по IMAP, POP и SMTP. Все параметры транспорта (`EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_USE_SSL`, `EMAIL_USE_TLS`, `EMAIL_TIMEOUT`) можно заменить через `.env`.

Проверить реальную отправку письма на адрес уведомлений:

```powershell
docker compose exec -T django python manage.py shell -c "from django.conf import settings; from django.core.mail import send_mail; print(send_mail('FileManager: проверка SMTP', 'SMTP работает.', settings.DEFAULT_FROM_EMAIL, [settings.FILE_NOTIFICATION_EMAIL], fail_silently=False))"
```

Если возникает `The handshake operation timed out`, соединение блокируется до авторизации. Временно приостановите VPN/прокси (в частности TUN-режим) либо разрешите ему исходящие SMTP-порты `465`/`587`, затем повторите команду.

## Полный запуск через Docker

Docker Compose поднимает PostgreSQL, Redis, Django, Celery, ML-сервис, Nginx, Prometheus и Grafana:

```powershell
Copy-Item .env.example .env
docker compose up -d --build
docker compose ps
```

Для входа в административную панель создайте администратора:

```powershell
docker compose exec django python manage.py createsuperuser
```

После запуска доступны:

- приложение: <http://localhost/>;
- регистрация: <http://localhost/accounts/signup/>;
- административная панель: <http://localhost/admin/>;
- состояние приложения: <http://localhost/status/>;
- Prometheus: <http://localhost:9090/>;
- Grafana: <http://localhost:3000/>;
- метрики Django: <http://localhost/metrics>.

Первый запуск ML-сервиса долгий: Docker собирает CPU-версию PyTorch и spaCy-модель, а модель тональности Hugging Face (около 680 МБ) скачивает при первом старте контейнера. Она сохраняется в именованном томе `hf_cache`, поэтому повторно при обычной пересборке не скачивается. Для первой сборки нужен интернет и несколько гигабайт свободного места.

Посмотреть журнал запуска:

```powershell
docker compose logs -f django celery ml_service
```

Остановка:

```powershell
docker compose down
```

Чтобы удалить также данные PostgreSQL и именованные тома:

```powershell
docker compose down -v
```

Последняя команда удаляет данные без возможности восстановления.

## Проверки

```powershell
python manage.py check
python manage.py makemigrations --check --dry-run
pytest -q
docker compose config --quiet
```

## Переменные окружения

Все поддерживаемые параметры перечислены в `.env.example`. Основные:

- `DJANGO_SECRET_KEY`, `DJANGO_DEBUG`, `DJANGO_ALLOWED_HOSTS`;
- `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `FILE_NOTIFICATION_EMAIL`;
- `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`;
- `CELERY_BROKER_URL`, `CELERY_RESULT_BACKEND`, `ML_SERVICE_URL`;
- `SENTRY_DSN`, `SENTRY_TRACES_SAMPLE_RATE`;
- `USE_POSTGRES` и параметры `POSTGRES_*`.

Локально по умолчанию используется SQLite. В Docker Compose автоматически включается PostgreSQL.

## Структура

```text
core/                 Django-модели, формы, веб-интерфейс и REST API
filemanager/          настройки проекта, URL, Celery, WSGI/ASGI
ml_api/               модели результатов, Celery-задача и Flask ML-сервис
templates/, static/   интерфейс
docker-compose.yml    полный стек разработки
```

Подробное описание учебных этапов и скриншоты сохранены в `REPORT.md`.
