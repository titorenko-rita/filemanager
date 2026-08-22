from flask import Flask, request, jsonify
import pytesseract
from PIL import Image
import spacy
from transformers import AutoTokenizer, AutoModelForSequenceClassification
import torch
import re
from collections import defaultdict
import platform
import os
import math
from collections import Counter
from prometheus_flask_exporter import PrometheusMetrics

app = Flask(__name__)

# Чтобы jsonify возвращал кириллицу, а не \u043f\u0440...
try:
    app.json.ensure_ascii = False
except Exception:
    pass

# Prometheus метрики (/metrics)
metrics = PrometheusMetrics(app)

nlp = spacy.load("ru_core_news_sm")

sentiment_tokenizer = AutoTokenizer.from_pretrained("blanchefort/rubert-base-cased-sentiment")
sentiment_model = AutoModelForSequenceClassification.from_pretrained("blanchefort/rubert-base-cased-sentiment")
MODEL_MAX_TOKENS = min(getattr(sentiment_model.config, "max_position_embeddings", 512), 512)
MAX_ANALYSIS_CHARS = int(os.environ.get('MAX_ANALYSIS_CHARS', '200000'))
MAX_SENTIMENT_CHUNKS = int(os.environ.get('MAX_SENTIMENT_CHUNKS', '24'))
SENTIMENT_BATCH_SIZE = 4


def get_sentiment(text: str):
    """Агрегирует тональность репрезентативных частей всего документа."""
    token_ids = sentiment_tokenizer.encode(text, add_special_tokens=False)
    content_size = max(MODEL_MAX_TOKENS - 2, 1)
    chunks = [token_ids[start:start + content_size] for start in range(0, len(token_ids), content_size)]
    if not chunks:
        chunks = [[]]
    if len(chunks) > MAX_SENTIMENT_CHUNKS:
        indexes = {
            round(index * (len(chunks) - 1) / (MAX_SENTIMENT_CHUNKS - 1))
            for index in range(MAX_SENTIMENT_CHUNKS)
        }
        chunks = [chunks[index] for index in sorted(indexes)]

    probability_batches = []
    for start in range(0, len(chunks), SENTIMENT_BATCH_SIZE):
        prepared = [
            {'input_ids': sentiment_tokenizer.build_inputs_with_special_tokens(chunk)}
            for chunk in chunks[start:start + SENTIMENT_BATCH_SIZE]
        ]
        inputs = sentiment_tokenizer.pad(prepared, padding=True, return_tensors='pt')
        with torch.no_grad():
            logits = sentiment_model(**inputs).logits
            probability_batches.append(torch.softmax(logits, dim=-1))

    probabilities = torch.cat(probability_batches).mean(dim=0)
    predicted_class_id = probabilities.argmax().item()
    return (
        sentiment_model.config.id2label[predicted_class_id].lower(),
        round(probabilities[predicted_class_id].item(), 4),
        len(chunks),
    )


if platform.system() == "Windows":
    pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

TESSDATA_DIR = "/usr/share/tesseract-ocr/5/tessdata"

BAD_ENTS = {"МОБЯЗЫВАЮ", "Выберите", "Заместителя", "Юрисконсульт"}

DATE_REGEX = r"(\d{1,2}[\.\-/ ]\d{1,2}[\.\-/ ]\d{2,4}|\d{1,2} [а-яА-Я]+ \d{4}|\d{4})"
MONEY_REGEX = (
    r"(?<!\w)(?:\d{1,3}(?:[\s\u00A0]\d{3})+|\d+)"
    r"(?:[.,]\d{1,2})?\s*(?:руб(?:лей|ля|ль|\.)?|₽|евро|€|"
    r"доллар(?:ов|а)?|долл\.?|USD|EUR|RUB|\$)(?!\w)"
)


def get_summary(text: str, n_sentences: int = 2) -> str:
    sentences = [sentence.strip() for sentence in re.split(r"(?<=[.!?])\s+|\n+", text) if sentence.strip()]
    if len(sentences) <= n_sentences:
        return ' '.join(sentences)
    words = re.findall(r"[а-яА-ЯёЁa-zA-Z]{4,}", text.lower())
    stop_words = {'который', 'которая', 'которые', 'этого', 'этой', 'были', 'будет', 'также', 'если', 'чтобы'}
    frequencies = Counter(word for word in words if word not in stop_words)
    scored = []
    for index, sentence in enumerate(sentences):
        sentence_words = re.findall(r"[а-яА-ЯёЁa-zA-Z]{4,}", sentence.lower())
        score = sum(frequencies[word] for word in sentence_words) / math.sqrt(max(len(sentence_words), 1))
        scored.append((score, index, sentence))
    selected = sorted(sorted(scored, reverse=True)[:n_sentences], key=lambda item: item[1])
    return ' '.join(item[2] for item in selected)


def extract_main_info(entities):
    info = defaultdict(list)
    for ent in entities:
        t = ent.get("type")
        v = ent.get("text")
        if t in {"PERSON", "PER"}:
            info["names"].append(v)
        elif t == "ORG":
            info["orgs"].append(v)
        elif t == "DATE":
            info["dates"].append(v)
        elif t == "MONEY":
            info["moneys"].append(v)
        elif t == "PHONE":
            info["phones"].append(v)
    return info


def get_text_from_request() -> str | None:
    """
    Поддерживает:
      - application/x-www-form-urlencoded (Body: text=...)
      - application/json (Body: {"text":"..."})
    """
    text = request.form.get("text")
    if text:
        return text

    data = request.get_json(silent=True) or {}
    text = data.get("text")
    if text:
        return text

    return None


def build_entities(text: str):
    doc = nlp(text)

    entities = []
    seen = set()

    def append_entity(entity_type, value):
        cleaned = re.sub(r"\s+", " ", value).strip()
        key = (entity_type, cleaned.casefold())
        if cleaned and key not in seen:
            seen.add(key)
            entities.append({"type": entity_type, "text": cleaned})

    for ent in doc.ents:
        if ent.text not in BAD_ENTS and len(ent.text) > 2:
            append_entity(ent.label_, ent.text)

    # Телефоны
    phones = re.findall(r"\+?\d[\d\s\-\(\)]{7,}\d", text)
    for phone in phones:
        append_entity('PHONE', phone)

    moneys = re.findall(MONEY_REGEX, text, re.IGNORECASE)
    for money in moneys:
        append_entity('MONEY', money)

    # Даты
    dates = re.findall(DATE_REGEX, text)
    for date in dates:
        append_entity('DATE', date)

    return entities


def detect_style(entities) -> str:
    if any(e["type"] == "ORG" for e in entities):
        return "деловой"
    if any(e["type"] == "PERSON" for e in entities):
        return "личный"
    return "нейтральный"


def build_response(text: str):
    original_length = len(text)
    analyzed_text = text[:MAX_ANALYSIS_CHARS]
    entities = build_entities(analyzed_text)
    sentiment_value, sentiment_confidence, sentiment_chunks = get_sentiment(analyzed_text)
    style = detect_style(entities)
    summary = get_summary(analyzed_text)
    main_info = extract_main_info(entities)

    return {
        "text": analyzed_text,
        "summary": summary,
        "entities": entities,
        "main_info": main_info,
        "sentiment": sentiment_value,
        "sentiment_confidence": sentiment_confidence,
        "sentiment_chunks": sentiment_chunks,
        "style": style,
        "truncated": original_length > len(analyzed_text),
        "original_length": original_length,
    }


@app.route("/ocr", methods=["POST"])
def ocr():
    file = request.files.get("file")
    if not file:
        return jsonify({"error": "file is required (multipart/form-data)"}), 400

    try:
        img = Image.open(file.stream)
        text = pytesseract.image_to_string(img, lang="rus")
        return jsonify(build_response(text))
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/sentiment", methods=["POST"])
def sentiment():
    try:
        text = get_text_from_request()
        if not text:
            return jsonify({"error": "text is required"}), 400

        return jsonify(build_response(text))
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
