FROM python:3.10-slim
ENV PIP_DEFAULT_TIMEOUT=200 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update && \
    apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-rus && \
    rm -rf /var/lib/apt/lists/*

ENV TESSDATA_PREFIX=/usr/share/tesseract-ocr/5/tessdata

WORKDIR /app
COPY requirements.txt /app/requirements.txt
RUN pip install --retries 10 --timeout 200 -r /app/requirements.txt && \
    python -m spacy download ru_core_news_sm
COPY ml_service.py /app/ml_service.py
EXPOSE 5000

CMD ["python", "ml_service.py"]
