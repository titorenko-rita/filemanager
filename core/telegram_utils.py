import requests
from django.conf import settings
import logging

logger = logging.getLogger(__name__)

def send_telegram_message(text):
    if settings.TESTING or not settings.TELEGRAM_BOT_TOKEN or not settings.TELEGRAM_CHAT_ID:
        return False

    url = f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/sendMessage"
    data = {
        "chat_id": settings.TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML"
    }
    response = None
    try:
        logger.info("Отправка сообщения в Telegram для chat_id=%s", settings.TELEGRAM_CHAT_ID)
        response = requests.post(url, data=data, timeout=10)
        response.raise_for_status()
        logger.info(f"Сообщение успешно отправлено: {text}")
        return True
    except Exception as e:
        logger.error(f"Ошибка отправки Telegram: {e}")
        logger.error("Ответ сервера: %s", getattr(response, 'text', 'Нет ответа'))
        return False
