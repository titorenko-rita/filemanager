from flask import Flask, request, jsonify
import pytesseract
from PIL import Image
import spacy
from transformers import AutoTokenizer, AutoModelForSequenceClassification
import torch
import re
from collections import defaultdict
import platform
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


def get_sentiment(text: str) -> str:
    inputs = sentiment_tokenizer(text, return_tensors="pt", truncation=True, padding=True)
    with torch.no_grad():
        logits = sentiment_model(**inputs).logits
    predicted_class_id = logits.argmax().item()
    return sentiment_model.config.id2label[predicted_class_id].lower()


if platform.system() == "Windows":
    pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

TESSDATA_DIR = "/usr/share/tesseract-ocr/5/tessdata"

BAD_ENTS = {"МОБЯЗЫВАЮ", "Выберите", "Заместителя", "Юрисконсульт"}

DATE_REGEX = r"(\d{1,2}[\.\-/ ]\d{1,2}[\.\-/ ]\d{2,4}|\d{1,2} [а-яА-Я]+ \d{4}|\d{4})"
MONEY_REGEX = r"(\d+[\s\u00A0]?(руб\.|евро|доллар|₽|€|\$))"


def get_summary(text: str, n_sentences: int = 2) -> str:
    sentences = re.split(r"[.!?\n]", text)
    return ". ".join([s.strip() for s in sentences if s.strip()][:n_sentences])


def extract_main_info(entities):
    info = defaultdict(list)
    for ent in entities:
        t = ent.get("type")
        v = ent.get("text")
        if t == "PERSON":
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

    entities = [
        {"type": ent.label_, "text": ent.text}
        for ent in doc.ents
        if ent.text not in BAD_ENTS and len(ent.text) > 2
    ]

    # Телефоны
    phones = re.findall(r"\+?\d[\d\s\-\(\)]{7,}\d", text)
    for phone in phones:
        if not any(e["text"] == phone for e in entities):
            entities.append({"type": "PHONE", "text": phone})

    # Деньги (findall -> список tuple, берём первый элемент)
    moneys = re.findall(MONEY_REGEX, text, re.IGNORECASE)
    for money in moneys:
        money_text = money[0] if isinstance(money, tuple) else str(money)
        if not any(e["text"] == money_text for e in entities):
            entities.append({"type": "MONEY", "text": money_text})

    # Даты
    dates = re.findall(DATE_REGEX, text)
    for date in dates:
        if not any(e["text"] == date for e in entities):
            entities.append({"type": "DATE", "text": date})

    return entities


def detect_style(entities) -> str:
    if any(e["type"] == "ORG" for e in entities):
        return "деловой"
    if any(e["type"] == "PERSON" for e in entities):
        return "личный"
    return "нейтральный"


def build_response(text: str):
    entities = build_entities(text)
    sentiment_value = get_sentiment(text)
    style = detect_style(entities)
    summary = get_summary(text)
    main_info = extract_main_info(entities)

    return {
        "text": text,
        "summary": summary,
        "entities": entities,
        "main_info": main_info,
        "sentiment": sentiment_value,
        "style": style,
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
