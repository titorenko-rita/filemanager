# File Manager

Локальный файловый менеджер на Django для хранения и автоматического анализа документов. Пользователь может зарегистрироваться, загружать, скачивать и заменять только собственные файлы, восстанавливать их из корзины, отправлять выбранный документ по email и смотреть результаты фонового ML-анализа.

## Возможности

- авторизация через `django-allauth`;
- веб-интерфейс и REST API `/api/files/`;
- защищённое скачивание файлов через Django (каталог `media` не публикуется напрямую);
- проверка размера, расширения и фактического формата загрузок;
- антивирусная проверка ClamAV внутри закрытой Docker-сети;
- корзина с восстановлением и автоматическим сроком хранения;
- роли администратора/аудитора и неизменяемый через интерфейс журнал действий;
- ежедневные локальные резервные копии PostgreSQL и файлов без `.env`;
- фоновые задачи Celery и Redis;
- отдельный Flask ML-сервис: OCR изображений, извлечение имён, организаций, дат, телефонов и денежных сумм, краткое резюме и тональность по нескольким частям длинного текста;
- опциональные уведомления по email, Telegram и Sentry;
- Prometheus и Grafana в Docker Compose;
- тесты pytest с минимальным покрытием 80% и GitHub Actions.

## Быстрый повторный запуск

1. Запустите Docker Desktop и дождитесь, пока Docker будет готов.
2. Откройте PowerShell и перейдите в папку проекта:

   ```powershell
   cd C:\filemanager_2\filemanager_2
   ```

3. Запустите проект после изменений или на новом компьютере:

   ```powershell
   docker compose up -d --build
   ```

   Для обычного повторного запуска без пересборки достаточно `docker compose up -d`.

4. Выполните `docker compose ps`. У контейнеров должен быть статус `Up`, а у `clamav` после загрузки сигнатур — `healthy`.
5. Откройте <http://localhost/>.

## Быстрый локальный запуск

Для основной части приложения достаточно Python 3.10+. Redis и ML-сервис не обязательны: если очередь недоступна, загрузка файлов продолжает работать, но автоматический анализ не запускается. При запуске без Docker ClamAV по умолчанию выключен.

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

Docker Compose поднимает PostgreSQL, Redis, ClamAV, Django, Celery Worker, Celery Beat, ML-сервис, Nginx, Prometheus и Grafana:

```powershell
Copy-Item .env.example .env
docker compose up -d --build
docker compose ps
```

Пока ClamAV обновляет базу сигнатур, загрузки будут отклоняться с понятным сообщением. Посмотреть готовность:

```powershell
docker compose logs -f clamav
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
- корзина: <http://localhost/trash/>;
- журнал аудита для администратора/аудитора: <http://localhost/audit/>;
- Prometheus: <http://localhost:9090/>;
- Grafana: <http://localhost:3000/>;
- метрики Django: <http://localhost/metrics>.

Первый запуск ML-сервиса долгий: Docker собирает CPU-версию PyTorch и spaCy-модель, а модель тональности Hugging Face скачивает при первом старте контейнера. Она сохраняется в именованном томе `hf_cache`, поэтому повторно при обычной пересборке не скачивается. Для первой сборки и обновления антивирусных сигнатур нужен интернет. После заполнения кэшей анализ выполняется локально.

Посмотреть журнал запуска:

```powershell
docker compose logs -f django celery celery_beat ml_service clamav
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

## Насколько проект локальный

При `PRIVACY_MODE=True` документы обрабатываются контейнерами на этом компьютере: Django, PostgreSQL, Redis, Celery, OCR и ML-сервис находятся в Docker-сети. Автоматические email/Telegram-уведомления и Sentry выключены; интерфейс не загружает CSS или JavaScript с внешних CDN.

Наружу выполняются только следующие обращения:

- при первом развёртывании Docker скачивает образы, ML-модель и антивирусные сигнатуры;
- ClamAV затем получает обновления сигнатур, но не отправляет проверяемые файлы;
- кнопка «Отправить отчёт» по явному действию пользователя передаёт письмо и вложение SMTP-серверу;
- внешние Telegram/Sentry можно включить вручную, отключив соответствующие ограничения приватности.

Файлы и база находятся в локальных Docker-томах, но приложение само не шифрует их на диске. Для конфиденциальных данных включите BitLocker/шифрование диска Windows, используйте сильные пароли и не публикуйте порты приложения в недоверенной сети.

## Корзина, аудит и роли

- обычное удаление перемещает документ в корзину на `TRASH_RETENTION_DAYS` (по умолчанию 30 дней);
- пользователь может восстановить файл или удалить его окончательно;
- журнал хранится `AUDIT_RETENTION_DAYS` (по умолчанию 365 дней);
- суперпользователь видит аудит автоматически;
- роль «Аудиторы» создаётся при запуске Docker. Назначить её можно в `/admin/` в карточке пользователя.

Применить сроки хранения вручную:

```powershell
docker compose exec django python manage.py apply_retention
```

## Резервные копии

Celery Beat раз в сутки создаёт ZIP с дампом PostgreSQL, каталогом `media` и манифестом. `.env`, SMTP-пароль и токены в архив не попадают. Копии хранятся в Docker-томе `backups_volume` в течение `BACKUP_RETENTION_DAYS` (по умолчанию 14 дней).

Создать копию перед важным изменением и посмотреть её имя:

```powershell
docker compose exec django python manage.py backup_project
docker compose exec django ls -lh /app/backups
```

Скопировать архив на Windows:

```powershell
docker compose cp django:/app/backups/filemanager-ГГГГММДД-ЧЧММСС.zip .
```

Восстановление PostgreSQL выполняется стандартным `pg_restore`, а содержимое папки `media` из архива возвращается в одноимённый том. Перед восстановлением остановите Django/Celery и сохраните текущую резервную копию.

## HTTPS для сервера

Локальный адрес `http://localhost` не требует сертификата. Для домена положите сертификаты `fullchain.pem` и `privkey.pem` в `certs/`, укажите домен в `DJANGO_ALLOWED_HOSTS` и origin вида `https://example.ru` в `DJANGO_CSRF_TRUSTED_ORIGINS`, затем запустите:

```powershell
docker compose -f docker-compose.yml -f docker-compose.production.yml up -d --build
```

Production-профиль включает перенаправление на HTTPS, secure-cookie и HSTS. Не включайте HSTS до проверки действующего сертификата.

## Переменные окружения

Все поддерживаемые параметры перечислены в `.env.example`. Основные:

- `DJANGO_SECRET_KEY`, `DJANGO_DEBUG`, `DJANGO_ALLOWED_HOSTS`;
- `PRIVACY_MODE`, лимиты загрузки и параметры `CLAMAV_*`;
- `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `FILE_NOTIFICATION_EMAIL`;
- `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`;
- `CELERY_BROKER_URL`, `CELERY_RESULT_BACKEND`, `ML_SERVICE_URL`;
- сроки `TRASH_RETENTION_DAYS`, `AUDIT_RETENTION_DAYS`, `BACKUP_RETENTION_DAYS`;
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
