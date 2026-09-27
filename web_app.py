"""Local web interface and experimental image-analysis API for CellVision AI."""
import base64
import csv
from contextlib import contextmanager
import hashlib
import hmac
import io
import json
import math
import os
import secrets
import sqlite3
import zipfile
import urllib.parse
import urllib.request
import urllib.error
import re
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import cv2
import numpy as np

ROOT = os.path.dirname(os.path.abspath(__file__))


def load_local_secrets():
    """Load ignored per-machine settings without overriding process environment."""
    secret_file = os.path.join(ROOT, ".env")
    if not os.path.isfile(secret_file):
        return
    try:
        with open(secret_file, "r", encoding="utf-8") as settings:
            for raw_line in settings:
                line = raw_line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                name, value = line.split("=", 1)
                name, value = name.strip(), value.strip().strip("\"'")
                if name == "OCR_SPACE_API_KEY" and value:
                    if not os.environ.get(name):
                        os.environ[name] = value
    except OSError:
        # An environment variable can still provide the key when the file is unreadable.
        pass


load_local_secrets()
WEB_ROOT = os.path.join(ROOT, "web")
DB_PATH = os.path.join(ROOT, "cellvision.db")
HOST, PORT = "127.0.0.1", 8765
SESSIONS = {}
MODEL_DIR = os.path.join(ROOT, "data", "models")
MODEL_PATH = os.path.join(MODEL_DIR, "rbc_linear_svm.npz")
MODEL_CLASSES_PATH = os.path.join(MODEL_DIR, "rbc_classes.json")
class LinearSVM:
    """Small one-vs-rest linear SVM trained with stochastic hinge-loss updates."""
    def __init__(self, weights, bias):
        self.weights = np.asarray(weights, dtype=np.float32)
        self.bias = np.asarray(bias, dtype=np.float32)

    def fit(self, samples, targets, class_count, epochs=24):
        x = np.asarray(samples, dtype=np.float32)
        x /= np.maximum(np.linalg.norm(x, axis=1, keepdims=True), 1e-6)
        y = np.asarray(targets, dtype=np.int32)
        self.weights = np.zeros((class_count, x.shape[1]), dtype=np.float32)
        self.bias = np.zeros(class_count, dtype=np.float32)
        rng = np.random.default_rng(17)
        rate, regularization = .015, .0001
        for cls in range(class_count):
            w = self.weights[cls]
            b = 0.0
            signs = np.where(y == cls, 1.0, -1.0).astype(np.float32)
            positive_weight = len(y) / (2 * max(1, int(np.sum(y == cls))))
            negative_weight = len(y) / (2 * max(1, int(np.sum(y != cls))))
            for _ in range(epochs):
                for i in rng.permutation(len(x)):
                    w *= (1 - rate * regularization)
                    if signs[i] * (float(np.dot(w, x[i])) + b) < 1:
                        weight = positive_weight if signs[i] > 0 else negative_weight
                        w += rate * weight * signs[i] * x[i]
                        b += rate * weight * signs[i]
            self.bias[cls] = b
        return self

    def predict(self, samples):
        x = np.asarray(samples, dtype=np.float32)
        x /= np.maximum(np.linalg.norm(x, axis=1, keepdims=True), 1e-6)
        return np.argmax(x @ self.weights.T + self.bias, axis=1).reshape(-1, 1)


def hog_descriptor(crop):
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY) if crop.ndim == 3 else crop
    gray = cv2.resize(gray, (64, 64), interpolation=cv2.INTER_AREA)
    gx = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=1)
    gy = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=1)
    magnitude, angle = cv2.cartToPolar(gx, gy, angleInDegrees=True)
    angle %= 180.0
    hist = np.zeros((8, 8, 9), dtype=np.float32)
    bins = np.linspace(0, 180, 10)
    for row in range(8):
        for col in range(8):
            ys, xs = slice(row * 8, (row + 1) * 8), slice(col * 8, (col + 1) * 8)
            hist[row, col], _ = np.histogram(angle[ys, xs], bins=bins, weights=magnitude[ys, xs])
    features = []
    for row in range(7):
        for col in range(7):
            block = hist[row:row + 2, col:col + 2].reshape(-1)
            block /= np.sqrt(float(np.dot(block, block)) + 1e-6)
            block = np.minimum(block, .2)
            block /= np.sqrt(float(np.dot(block, block)) + 1e-6)
            features.extend(block)
    return np.asarray(features, dtype=np.float32)


def load_ai_model():
    if os.path.isfile(MODEL_PATH) and os.path.isfile(MODEL_CLASSES_PATH):
        try:
            with np.load(MODEL_PATH, allow_pickle=False) as saved:
                model = LinearSVM(saved["weights"], saved["bias"])
            with open(MODEL_CLASSES_PATH, encoding="utf-8") as f: classes = json.load(f)
            return model, classes
        except (OSError, ValueError, KeyError): pass
    return None, []


def image_screen(image):
    """Describe the image-analysis scope without returning an anemia score."""
    return {"status": "visualization_only", "label": "Исследовательская визуализация",
            "detail": "Изображение используется для визуализации сегментированных объектов и морфологии. Вероятность анемии по фото не рассчитывается."}


def cbc_pattern(cbc):
    """Summarize entered CBC indices as descriptive patterns; never infer a diagnosis."""
    if not isinstance(cbc, dict):
        return {"status": "not_provided", "items": [], "text": "Дополнительные индексы CBC не введены."}
    ranges = {"mcv": (50, 150), "mch": (10, 50), "mchc": (200, 450), "rdw": (5, 40), "rbc": (.5, 12), "hematocrit": (5, 75)}
    values = {}
    for key, (low, high) in ranges.items():
        raw = cbc.get(key)
        if raw in (None, ""):
            continue
        value = float(raw)
        if not math.isfinite(value) or not low <= value <= high:
            raise ValueError(f"Проверьте введённое значение CBC: {key}")
        values[key] = value
    items = []
    if values.get("mcv", 0) and values["mcv"] < 80:
        items.append("низкий MCV: микроцитарный паттерн")
    elif values.get("mcv", 0) > 100:
        items.append("высокий MCV: макроцитарный паттерн")
    if values.get("mch", 99) < 27:
        items.append("низкий MCH")
    if values.get("mchc", 999) < 320:
        items.append("низкий MCHC")
    if values.get("rdw", 0) > 14.5:
        items.append("повышенный RDW: увеличен разброс размеров эритроцитов")
    return {"status": "patterns_only", "values": values, "items": items,
            "text": "; ".join(items) if items else ("Введённые индексы не показывают перечисленные ориентировочные паттерны." if values else "Дополнительные индексы CBC не введены."),
            "note": "Это ориентировочные признаки по частым взрослым референсным границам; используйте диапазоны лаборатории. Они не дают причину анемии и не являются диагнозом."}


AI_MODEL, AI_CLASSES = None, []


@contextmanager
def db_connect():
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def init_db():
    with db_connect() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS users (
          id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL,
          password_hash TEXT NOT NULL, salt TEXT NOT NULL,
          first_name TEXT DEFAULT '', last_name TEXT DEFAULT '', age INTEGER,
          home_address TEXT DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS analyses (
          id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, created_at TEXT NOT NULL,
          image_name TEXT, cells INTEGER, mean_area REAL, std_area REAL, rdw REAL,
          FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS cells (
          id INTEGER PRIMARY KEY, analysis_id INTEGER NOT NULL, cell_number INTEGER,
          area_px2 REAL, centroid_x REAL, centroid_y REAL, bbox_x INTEGER,
          bbox_y INTEGER, bbox_width INTEGER, bbox_height INTEGER, diameter_px REAL,
          aspect_ratio REAL, circularity REAL, eccentricity REAL, mean_bgr TEXT,
          FOREIGN KEY(analysis_id) REFERENCES analyses(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS expert_labels (
          id INTEGER PRIMARY KEY, analysis_id INTEGER NOT NULL, cell_number INTEGER NOT NULL,
          label TEXT NOT NULL, reviewer TEXT DEFAULT '', created_at TEXT NOT NULL,
          UNIQUE(analysis_id, cell_number),
          FOREIGN KEY(analysis_id) REFERENCES analyses(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS independent_reviews (
          id INTEGER PRIMARY KEY, analysis_id INTEGER NOT NULL, reviewer_slot TEXT NOT NULL,
          reviewer_name TEXT DEFAULT '', labels_json TEXT NOT NULL, created_at TEXT NOT NULL,
          UNIQUE(analysis_id, reviewer_slot),
          FOREIGN KEY(analysis_id) REFERENCES analyses(id) ON DELETE CASCADE
        );
        """)
        cols = {row[1] for row in db.execute("PRAGMA table_info(analyses)")}
        for name in ("image_data", "segmented_data", "segmentation_mask", "expert_mask_json", "expert_mask_reviewer", "expert_mask_metrics_json", "morphology_json", "hemoglobin", "population", "anemia_result"):
            if name not in cols:
                db.execute(f"ALTER TABLE analyses ADD COLUMN {name} TEXT")
        cell_cols = {row[1] for row in db.execute("PRAGMA table_info(cells)")}
        for name, column_type in (("diameter_px", "REAL"), ("aspect_ratio", "REAL"), ("circularity", "REAL"), ("eccentricity", "REAL"), ("mean_bgr", "TEXT"), ("diameter_um", "REAL"), ("area_um2", "REAL"), ("ai_class", "TEXT")):
            if name not in cell_cols:
                db.execute(f"ALTER TABLE cells ADD COLUMN {name} {column_type}")


def pwd_hash(password, salt):
    return hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 240000).hex()


def png_data(image, max_edge=1200, quality=86):
    h, w = image.shape[:2]
    scale = min(1.0, max_edge / max(h, w))
    if scale < 1:
        image = cv2.resize(image, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
    ok, buffer = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, quality])
    return "data:image/jpeg;base64," + base64.b64encode(buffer).decode() if ok else ""


def png_mask_data(mask, max_edge=1200):
    h, w = mask.shape[:2]
    scale = min(1.0, max_edge / max(h, w))
    if scale < 1:
        mask = cv2.resize(mask, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_NEAREST)
    ok, buffer = cv2.imencode(".png", mask)
    return "data:image/png;base64," + base64.b64encode(buffer).decode() if ok else ""


def image_from_data(value):
    if not isinstance(value, str) or "," not in value:
        raise ValueError("Изображение не передано")
    raw = base64.b64decode(value.split(",", 1)[1], validate=True)
    if len(raw) > 12 * 1024 * 1024:
        raise ValueError("Файл больше 12 МБ")
    image = cv2.imdecode(np.frombuffer(raw, dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError("Формат изображения не поддерживается")
    if image.shape[0] * image.shape[1] > 40_000_000:
        raise ValueError("Слишком высокое разрешение (максимум 40 мегапикселей)")
    return image


def make_sample(kind="mixed"):
    rng = np.random.default_rng()
    h, w = 760, 1120
    canvas = np.empty((h, w, 3), dtype=np.uint8)
    canvas[:] = (223, 228, 232)
    # Complex synthetic morphologies are teaching illustrations, not patient samples.
    for _ in range(115):
        x, y = int(rng.integers(24, w - 24)), int(rng.integers(24, h - 24))
        r = int(rng.integers(16, 32))
        if kind == "microcytic":
            r = int(rng.integers(13, 22))
        elif kind == "macrocytic":
            r = int(rng.integers(24, 37))
        elif kind == "anisocytosis":
            r = int(rng.integers(11, 39))
        elif kind == "sickle" and rng.random() < .18:
            cv2.ellipse(canvas, (x, y), (r + 16, max(4, r // 3)), int(rng.integers(-35, 35)), 0, 360, (114, 53, 111), -1, cv2.LINE_AA)
            continue
        tint = (int(rng.integers(137, 197)), int(rng.integers(43, 80)), int(rng.integers(75, 112)))
        cv2.circle(canvas, (x, y), r, tint, -1, cv2.LINE_AA)
        if kind != "sickle" or rng.random() > .4:
            cv2.circle(canvas, (x, y), max(4, int(r * rng.uniform(.34, .57))), (215, 139, 158), -1, cv2.LINE_AA)
        if rng.random() < .08:
            cv2.circle(canvas, (x + r // 3, y - r // 3), 2, (70, 45, 130), -1)
    if kind == "mixed":
        # Add stained-glass-like stain gradients, platelets, and a little optical texture.
        for _ in range(85):
            x, y = int(rng.integers(5, w - 5)), int(rng.integers(5, h - 5))
            cv2.circle(canvas, (x, y), int(rng.integers(1, 4)), (112, 78, 122), -1, cv2.LINE_AA)
    canvas = cv2.GaussianBlur(canvas, (3, 3), .5)
    noise = rng.normal(0, 3.5, canvas.shape).astype(np.int16)
    return np.clip(canvas.astype(np.int16) + noise, 0, 255).astype(np.uint8)


def clean_image(img):
    # Gentle median denoising, with side-by-side visualization returned to the UI.
    return cv2.medianBlur(img, 5)


def image_quality(img):
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    focus = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    mean = float(gray.mean())
    clipped = float(np.mean((gray <= 5) | (gray >= 250)) * 100)
    # Coarse tile medians estimate lighting variation while reducing the effect of individual cells.
    small = cv2.resize(gray, (8, 8), interpolation=cv2.INTER_AREA)
    tile_spread = float(np.percentile(small, 90) - np.percentile(small, 10))
    dark_fraction = float(np.mean(gray < 120) * 100)
    top_hat = cv2.morphologyEx(gray, cv2.MORPH_TOPHAT, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5)))
    speckle_fraction = float(np.mean(top_hat > 38) * 100)
    # Heuristic checks only; values depend strongly on microscope and staining.
    checks = []
    if focus < 35: checks.append("Низкая резкость: проверьте фокусировку")
    if mean < 45 or mean > 215: checks.append("Яркость вне ориентировочного диапазона")
    if clipped > 8: checks.append("Есть пересвеченные или слишком тёмные области")
    if tile_spread > 42: checks.append("Возможна неравномерная освещённость")
    if dark_fraction > 35: checks.append("Поле выглядит плотным: проверьте соприкасающиеся области")
    if speckle_fraction > 2.5: checks.append("Есть мелкие контрастные детали: проверьте пыль/окраску вручную")
    tips = []
    if focus < 35: tips.append("Перефокусируйте микроскоп и переснимите кадр.")
    if mean < 45 or mean > 215 or clipped > 8: tips.append("Отрегулируйте освещение и экспозицию, затем проверьте гистограмму.")
    if tile_spread > 42: tips.append("Выровняйте освещение поля и избегайте бликов.")
    if dark_fraction > 35: tips.append("Выберите менее плотное поле зрения; не считайте слитые клетки как отдельные.")
    if speckle_fraction > 2.5: tips.append("Проверьте мелкие детали на оригинале; алгоритм не удаляет их автоматически.")
    return {"focus_score": round(focus, 1), "mean_brightness": round(mean, 1),
            "clipped_percent": round(clipped, 2), "width": int(img.shape[1]), "height": int(img.shape[0]),
            "illumination_spread": round(tile_spread, 1), "dark_pixel_percent": round(dark_fraction, 2),
            "small_detail_percent": round(speckle_fraction, 2), "retake_tips": tips,
            "status": "review" if checks else "heuristic_ok", "checks": checks,
            "note": "Эвристики дают ориентиры, а не надёжное распознавание артефактов; мелкие детали не удаляются автоматически."}


def analyze(img, classify=True):
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    smooth = cv2.GaussianBlur(gray, (5, 5), 0)
    _, threshold = cv2.threshold(smooth, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    opened = cv2.morphologyEx(threshold, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8), iterations=1)
    distance = cv2.distanceTransform(opened, cv2.DIST_L2, 5)
    if distance.max() <= 0:
        return [], img.copy(), {}, np.zeros(gray.shape, dtype=np.uint8)
    _, foreground = cv2.threshold(distance, .31 * distance.max(), 255, cv2.THRESH_BINARY)
    foreground = np.uint8(foreground)
    unknown = cv2.subtract(opened, foreground)
    _, markers = cv2.connectedComponents(foreground)
    markers += 1
    markers[unknown == 255] = 0
    markers = cv2.watershed(img.copy(), markers)
    rendered = img.copy()
    objects = []
    for label in np.unique(markers):
        if label <= 1:
            continue
        mask = np.uint8(markers == label)
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            continue
        contour = max(contours, key=cv2.contourArea)
        area = float(cv2.contourArea(contour))
        if area < 90:
            continue
        moments = cv2.moments(contour)
        if moments["m00"] == 0:
            continue
        cx, cy = moments["m10"] / moments["m00"], moments["m01"] / moments["m00"]
        x, y, bw, bh = cv2.boundingRect(contour)
        perimeter = float(cv2.arcLength(contour, True))
        circularity = min(1.0, 4 * np.pi * area / (perimeter * perimeter)) if perimeter else 0
        ellipse_ecc = 0.0
        if len(contour) >= 5:
            try:
                (_, _), (a, b), _ = cv2.fitEllipse(contour)
                major, minor = max(a, b), max(1e-6, min(a, b))
                ellipse_ecc = float(np.sqrt(max(0.0, 1 - (minor / major) ** 2)))
            except cv2.error:
                pass
        roi = img[y:y + bh, x:x + bw]
        crop = img[y:y + bh, x:x + bw]
        predicted = None
        if classify and AI_MODEL is not None and crop.size:
            prediction = AI_MODEL.predict(hog_descriptor(crop).reshape(1, -1))
            predicted = AI_CLASSES[int(prediction[0, 0])] if 0 <= int(prediction[0, 0]) < len(AI_CLASSES) else None
        objects.append({"cell_number": len(objects) + 1, "area_px2": round(area, 2),
                        "centroid_x": round(cx, 2), "centroid_y": round(cy, 2),
                        "bbox_x": x, "bbox_y": y, "bbox_width": bw, "bbox_height": bh,
                        "diameter_px": round(2 * np.sqrt(area / np.pi), 2),
                        "aspect_ratio": round(bw / max(1, bh), 3),
                        "circularity": round(circularity, 3), "eccentricity": round(ellipse_ecc, 3),
                        "mean_bgr": [round(float(x), 1) for x in cv2.mean(roi)[:3]], "ai_class": predicted})
        cv2.drawContours(rendered, [contour], -1, (55, 210, 150), 2)
        cv2.circle(rendered, (int(cx), int(cy)), 3, (30, 50, 220), -1)
    areas = np.asarray([o["area_px2"] for o in objects], dtype=float)
    metrics = {}
    if len(areas):
        metrics = {"cell_count": len(objects), "mean_area": round(float(np.mean(areas)), 2),
                   "median_area": round(float(np.median(areas)), 2), "std_area": round(float(np.std(areas)), 2),
                   "cv_percent": round(float(np.std(areas) / np.mean(areas) * 100), 2),
                   "q1_area": round(float(np.percentile(areas, 25)), 2), "q3_area": round(float(np.percentile(areas, 75)), 2),
                   "mean_diameter": round(float(np.mean([o["diameter_px"] for o in objects])), 2),
                   "mean_circularity": round(float(np.mean([o["circularity"] for o in objects])), 3),
                   "mean_eccentricity": round(float(np.mean([o["eccentricity"] for o in objects])), 3)}
    rendered[markers == -1] = (20, 210, 255)
    predicted_mask = np.uint8(markers > 1) * 255
    return objects, rendered, metrics, predicted_mask


def assess_hb(hb_value, population, trimester=1, age=None):
    """WHO cut-off screen; do not calculate a probability from a smear photograph."""
    if hb_value in (None, ""):
        return {"status": "unassessed", "label": "Недостаточно данных", "detail": "Для лабораторной оценки нужен гемоглобин из общего анализа крови (г/л). По снимку мазка вероятность анемии не рассчитывается."}
    hb = float(hb_value)
    if not math.isfinite(hb) or not 10 <= hb <= 250:
        raise ValueError("Проверьте значение гемоглобина (ожидается 10–250 г/л)")
    if age not in (None, "") and population in ("woman", "man") and not 15 <= int(age) <= 65:
        return {"status": "unassessed", "label": "Возрастная группа не поддерживается", "detail": "Этот скрининг порогов настроен только для взрослых 15–65 лет. Обратитесь к врачу для интерпретации лабораторного результата."}
    cutoffs = {"woman": (120, 80, 110), "man": (130, 80, 110),
               "pregnant_1": (110, 70, 100), "pregnant_2": (105, 70, 95), "pregnant_3": (110, 70, 100),
               "child_6_23": (105, 70, 95), "child_24_59": (110, 70, 100),
               "child_5_11": (115, 80, 110), "child_12_14": (120, 80, 110)}
    key = f"pregnant_{trimester}" if population == "pregnant" else population
    cutoff, severe, moderate_boundary = cutoffs.get(key, (120, 80, 110))
    if hb >= cutoff:
        return {"status": "not_below_cutoff", "label": "В предварительном скрининге порог не превышен", "detail": f"Hb {hb:g} г/л не ниже порога {cutoff} г/л для выбранной группы. Это не исключает заболевание и не является диагнозом."}
    grade = "тяжёлая" if hb < severe else ("умеренная" if hb < moderate_boundary else "лёгкая")
    return {"status": "below_cutoff", "label": "Hb ниже выбранного порога · нужна оценка врача", "detail": f"Hb {hb:g} г/л ниже порога {cutoff} г/л; ориентировочная степень по порогам ВОЗ: {grade}. Не рассчитана вероятность и не определена причина. Пороги требуют клинической интерпретации с учётом факторов пациента."}


def parse_cbc_report(image):
    """Send the report to OCR.space and conservatively extract CBC values."""
    api_key = os.environ.get("OCR_SPACE_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("Не задан OCR_SPACE_API_KEY. Получите API-ключ OCR.space и настройте его в PowerShell перед запуском сайта.")
    h, w = image.shape[:2]
    scale = min(1.0, 2400 / max(h, w))
    prepared = cv2.resize(image, (max(1, int(w * scale)), max(1, int(h * scale))), interpolation=cv2.INTER_AREA) if scale < 1 else image
    encoded = None
    for quality in (88, 78, 68, 58):
        ok, buffer = cv2.imencode(".jpg", prepared, [cv2.IMWRITE_JPEG_QUALITY, quality])
        if ok:
            encoded = buffer.tobytes()
            if len(encoded) <= 900 * 1024:
                break
    if not encoded:
        raise RuntimeError("Не удалось подготовить фото для OCR API.")
    if len(encoded) > 1024 * 1024:
        raise RuntimeError("Фото слишком большое для бесплатного OCR API после сжатия. Обрежьте бланк и попробуйте снова.")
    boundary = "----CellVision" + secrets.token_hex(16)
    chunks = [f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"cbc-report.jpg\"\r\nContent-Type: image/jpeg\r\n\r\n".encode(), encoded, b"\r\n"]
    for name, value in (("language", "rus"), ("OCREngine", "3"), ("isTable", "true"), ("isOverlayRequired", "false")):
        chunks.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n{value}\r\n".encode())
    chunks.append(f"--{boundary}--\r\n".encode())
    request = urllib.request.Request("https://api.ocr.space/parse/image", data=b"".join(chunks),
        headers={"apikey": api_key, "Content-Type": f"multipart/form-data; boundary={boundary}"}, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=50) as response:
            payload = json.loads(response.read(3 * 1024 * 1024).decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"OCR API вернул HTTP {exc.code}. Проверьте API-ключ и лимит сервиса.") from exc
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise RuntimeError("Не удалось получить ответ от OCR API. Проверьте подключение к интернету и повторите попытку.") from exc
    results = payload.get("ParsedResults") or []
    text = "\n".join(row.get("ParsedText", "") for row in results if isinstance(row, dict)).strip()
    if payload.get("IsErroredOnProcessing") or not text:
        reason = payload.get("ErrorMessage") or next((row.get("ErrorMessage") for row in results if row.get("ErrorMessage")), None)
        raise RuntimeError(f"OCR API не смог прочитать бланк{': ' + str(reason) if reason else ''}. Попробуйте более чёткое фото.")
    aliases = {
        "hemoglobin": r"гемоглобин|гемогл|hemoglobin|\bhgb\b|\bhb\b",
        "mcv": r"\bmcv\b|средн(?:ий|.?)\s*объ[её]м",
        "mchc": r"\bmchc\b|средн(?:яя|.?)\s*концентрац",
        "mch": r"\bmch\b|средн(?:ее|.?)\s*содержан",
        "rbc": r"\brbc\b|эритроцит",
        "rdw": r"\brdw(?:-cv|-sd)?\b|ширин[аы]\s*распредел",
        "hematocrit": r"\bhct\b|гематокрит|\bhematocrit\b",
    }
    found = {}
    for line in text.splitlines():
        normalized = line.lower().replace("ё", "е")
        numbers = re.findall(r"(?<![\w])[-+]?\d{1,3}(?:[.,]\d+)?", normalized)
        if not numbers:
            continue
        for key, pattern in aliases.items():
            if key not in found and re.search(pattern, normalized, re.I):
                # When a row has both a reference interval and result, result is commonly
                # the first value after the label. Avoid guessing when several are present.
                label_end = re.search(pattern, normalized, re.I).end()
                after = re.findall(r"(?<![\w])[-+]?\d{1,3}(?:[.,]\d+)?", normalized[label_end:])
                candidates = after or numbers
                if candidates:
                    value = float(candidates[0].replace(",", "."))
                    if key in ("hemoglobin", "mchc") and re.search(r"g\s*/\s*d[l1]|г\s*/\s*дл|g%", normalized, re.I):
                        value *= 10
                    found[key] = value
    return {"text": text[:12000], "values": found, "confidence": None,
            "notice": "Фото отправлено в OCR.space для распознавания. OCR может ошибаться: сверьте каждое значение и единицы измерения с оригиналом бланка."}


HOSPITALS = [
    {"name": "Национальный центр онкологии и гематологии", "type": "Взрослым · профильная гематология", "address": "ул. Исы Ахунбаева, 92, корп. 8, Бишкек", "phone": "+996 312 576-134 · регистратура", "rating": "4.7 / 5 · 6 отзывов (YDoc); 3.2 / 5 · 57 оценок (2ГИС)", "rating_source": "YDoc обновлено 23.07.2026; 2ГИС проверено 26.09.2026", "maps": "https://2gis.kg/bishkek/search/Национальный%20центр%20онкологии%20и%20гематологии", "reviews": "https://ydoc.kg/bishkek/lpu/6520-nacionalnyy-centr-onkologii-i-gematologii/", "evidence": "В опубликованных отзывах есть опыт обращения по анемии; центр принимает взрослых. Оценки на сервисах заметно различаются. Сверьте телефон и маршрут при записи."},
    {"name": "Национальный центр охраны материнства и детства", "type": "Детям · отделение гематологии", "address": "ул. Ахунбаева, 190, Бишкек", "phone": "+996 312 49-23-69", "rating": "Оценка не подтверждена", "rating_source": "Публичный сопоставимый рейтинг не найден", "maps": "https://2gis.kg/bishkek/search/Национальный%20центр%20охраны%20материнства%20и%20детства", "reviews": "https://medik.kg/clinic/ncomid/gematolog/", "evidence": "У центра есть профильное детское гематологическое отделение; уточните приём и маршрут по телефону."},
    {"name": "Центр здоровья академика Раимжанова", "type": "Взрослым · амбулаторная гематология", "address": "мкр. Аламедин-1, ул. Загорская, 4, Бишкек", "phone": "+996 505 88-16-25", "rating": "4.6 / 5 · 122 отзыва (каталог); 3.4 / 5 · 4 отзыва (Яндекс)", "rating_source": "bi.kg и Яндекс Карты, проверено 26.09.2026", "maps": "https://2gis.kg/bishkek/search/Центр%20здоровья%20академика%20Раимжанова", "reviews": "https://czar.kg/services/hematology/", "evidence": "На сайте центра указаны консультации гематолога для взрослых, детей и беременных. Это амбулаторный центр; рейтинги каталогов расходятся."},
    {"name": "Bishkek Medical Clinic", "type": "Детям · амбулаторный детский гематолог", "address": "ул. Суеркулова, 1/4, Бишкек", "phone": "+996 312 51-18-30 · +996 550 51-18-30", "rating": "4.0 / 5 · 197 оценок", "rating_source": "2ГИС, карточка клиники", "maps": "https://2gis.kg/bishkek/firm/70000001046189413", "reviews": "https://2gis.kg/bishkek/firm/70000001046189413/tab/reviews", "evidence": "В каталоге указана услуга детского гематолога. Это амбулаторная клиника, не стационар; рейтинг относится ко всей клинике."},
]


class Handler(BaseHTTPRequestHandler):
    server_version = "CellVisionLocal/1.0"

    def log_message(self, fmt, *args):
        print("%s - %s" % (self.address_string(), fmt % args))

    def respond(self, data, status=200, content_type="application/json; charset=utf-8", headers=None):
        raw = data if isinstance(data, bytes) else (json.dumps(data, ensure_ascii=False).encode() if content_type.startswith("application/json") else str(data).encode())
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "no-store")
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(raw)

    def body(self):
        length = int(self.headers.get("Content-Length", 0))
        limit = 90 * 1024 * 1024 if self.path.startswith("/api/model/train") else 18 * 1024 * 1024
        if length > limit:
            raise ValueError(f"Запрос превышает {limit // (1024 * 1024)} МБ")
        return json.loads(self.rfile.read(length) or b"{}")

    def user_id(self):
        token = None
        for item in self.headers.get("Cookie", "").split(";"):
            if item.strip().startswith("cv_session="):
                token = item.strip().split("=", 1)[1]
        return SESSIONS.get(token)

    def require_user(self):
        user_id = self.user_id()
        if not user_id:
            self.respond({"error": "Сначала войдите в систему"}, 401)
        return user_id

    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        if path in {
            "/assets/redtell_segmentation_evaluation.json",
            "/assets/redtell_segmentation_examples.jpg",
        }:
            return self.respond(b"Not found", 404, "text/plain; charset=utf-8")
        if path == "/api/hospitals":
            return self.respond({"items": HOSPITALS, "updated": "2026-09-26"})
        if path == "/api/me":
            uid = self.user_id()
            if not uid:
                return self.respond({"user": None})
            with db_connect() as db:
                u = db.execute("SELECT id,username,first_name,last_name,age,home_address FROM users WHERE id=?", (uid,)).fetchone()
            return self.respond({"user": dict(u) if u else None})
        if path == "/api/history":
            uid = self.require_user()
            if not uid:
                return
            with db_connect() as db:
                rows = db.execute("SELECT id,created_at,image_name,cells,mean_area,std_area,rdw,hemoglobin,population,anemia_result,morphology_json,image_data,segmented_data,segmentation_mask,expert_mask_json,expert_mask_metrics_json FROM analyses WHERE user_id=? ORDER BY id DESC LIMIT 30", (uid,)).fetchall()
            return self.respond({"items": [dict(r) for r in rows]})
        if path == "/api/cells":
            uid = self.require_user()
            if not uid:
                return
            analysis_id = int(urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query).get("analysis_id", [0])[0])
            with db_connect() as db:
                owned = db.execute("SELECT 1 FROM analyses WHERE id=? AND user_id=?", (analysis_id, uid)).fetchone()
                rows = db.execute("SELECT cell_number,area_px2,centroid_x,centroid_y,bbox_x,bbox_y,bbox_width,bbox_height,diameter_px,diameter_um,area_um2,aspect_ratio,circularity,eccentricity,mean_bgr,ai_class FROM cells WHERE analysis_id=? ORDER BY cell_number", (analysis_id,)).fetchall() if owned else []
            if not owned:
                return self.respond({"error":"Анализ не найден"}, 404)
            return self.respond({"items": [dict(r) for r in rows]})
        if path == "/api/annotations":
            uid = self.require_user()
            if not uid: return
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            analysis_id = int(q.get("analysis_id", [0])[0])
            with db_connect() as db:
                owned = db.execute("SELECT 1 FROM analyses WHERE id=? AND user_id=?", (analysis_id, uid)).fetchone()
                labels = db.execute("SELECT cell_number,label,reviewer FROM expert_labels WHERE analysis_id=? ORDER BY cell_number", (analysis_id,)).fetchall() if owned else []
            if not owned: return self.respond({"error": "Исследование не найдено"}, 404)
            with db_connect() as db:
                compared = db.execute("SELECT c.ai_class,l.label FROM cells c JOIN expert_labels l ON l.analysis_id=c.analysis_id AND l.cell_number=c.cell_number WHERE c.analysis_id=? AND c.ai_class IS NOT NULL", (analysis_id,)).fetchall()
            pairs = [(x["ai_class"],x["label"]) for x in compared]
            accuracy = sum(a == b for a,b in pairs)/len(pairs) if pairs else None
            return self.respond({"items": [dict(x) for x in labels], "evaluation":{"n":len(pairs),"accuracy":round(accuracy,3) if accuracy is not None else None,"note":"Сравнение на этом снимке; это не независимый тест."}})
        if path == "/api/annotations/independent":
            uid = self.require_user()
            if not uid: return
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            analysis_id = int(q.get("analysis_id", [0])[0])
            with db_connect() as db:
                owned = db.execute("SELECT 1 FROM analyses WHERE id=? AND user_id=?", (analysis_id, uid)).fetchone()
                rows = db.execute("SELECT reviewer_slot,reviewer_name,labels_json FROM independent_reviews WHERE analysis_id=? ORDER BY reviewer_slot", (analysis_id,)).fetchall() if owned else []
            if not owned: return self.respond({"error":"Исследование не найдено"}, 404)
            by_slot = {r["reviewer_slot"]: json.loads(r["labels_json"]) for r in rows}
            first, second = by_slot.get("A", {}), by_slot.get("B", {})
            shared = sorted(set(first) & set(second), key=lambda x:int(x))
            n = len(shared); agree = sum(first[k] == second[k] for k in shared)
            po = agree / n if n else None
            labels = set(first[k] for k in shared) | set(second[k] for k in shared)
            pe = sum((sum(first[k] == label for k in shared) / n) * (sum(second[k] == label for k in shared) / n) for label in labels) if n else 0
            kappa = (po - pe) / (1 - pe) if n and pe < 1 else (1.0 if n and po == 1 else None)
            detail = [{"cell_number":k,"a":first[k],"b":second[k],"agree":first[k] == second[k]} for k in shared]
            return self.respond({"reviewers":[{"slot":r["reviewer_slot"],"name":r["reviewer_name"]} for r in rows],"n":n,"agreement":round(po,3) if po is not None else None,"kappa":round(kappa,3) if kappa is not None else None,"items":detail})
        if path == "/api/masks":
            uid = self.require_user()
            if not uid: return
            q=urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query); analysis_id=int(q.get("analysis_id",[0])[0])
            with db_connect() as db:
                row=db.execute("SELECT segmentation_mask,expert_mask_json,expert_mask_reviewer,expert_mask_metrics_json,image_data FROM analyses WHERE id=? AND user_id=?",(analysis_id,uid)).fetchone()
            if not row: return self.respond({"error":"Исследование не найдено"},404)
            mask_url=row["segmentation_mask"]
            if not mask_url:
                image=image_from_data(row["image_data"]); _,_,_,mask=analyze(image,classify=False); mask_url=png_mask_data(mask)
                with db_connect() as db: db.execute("UPDATE analyses SET segmentation_mask=? WHERE id=?",(mask_url,analysis_id))
            return self.respond({"segmentation_mask_data":mask_url,"polygons":json.loads(row["expert_mask_json"] or "[]"),"reviewer":row["expert_mask_reviewer"] or "","evaluation":json.loads(row["expert_mask_metrics_json"] or "null")})
        if path == "/api/library":
            return self.respond({"note": "Учебные схематические иллюстрации, не клинические микрофотографии."})
        if path == "/api/model/status":
            return self.respond({"trained": AI_MODEL is not None, "classes": AI_CLASSES,
            "algorithm": "HOG + one-vs-rest linear SVM (NumPy)", "status": "experimental",
            "whole_smear_trained": False, "whole_smear_classes": [],
            "cbc_probability_trained": False})
        target = "index.html" if path in ("/", "") else path.lstrip("/")
        full = os.path.abspath(os.path.join(WEB_ROOT, target))
        if not full.startswith(os.path.abspath(WEB_ROOT) + os.sep) or not os.path.isfile(full):
            return self.respond(b"Not found", 404, "text/plain; charset=utf-8")
        content_type = ("text/html; charset=utf-8" if full.endswith(".html") else
                        "text/css; charset=utf-8" if full.endswith(".css") else
                        "application/javascript; charset=utf-8" if full.endswith(".js") else
                        "image/svg+xml" if full.endswith(".svg") else
                        "image/jpeg" if full.endswith((".jpg", ".jpeg")) else
                        "image/png" if full.endswith(".png") else
                        "application/json; charset=utf-8" if full.endswith(".json") else
                        "application/octet-stream")
        with open(full, "rb") as f:
            return self.respond(f.read(), content_type=content_type)

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        try:
            data = self.body()
            if path == "/api/register":
                username, password = data.get("username", "").strip(), data.get("password", "")
                if len(username) < 3 or len(password) < 8:
                    return self.respond({"error": "Логин от 3 символов, пароль от 8"}, 400)
                salt = secrets.token_hex(16)
                with db_connect() as db:
                    db.execute("INSERT INTO users(username,password_hash,salt) VALUES(?,?,?)", (username, pwd_hash(password, salt), salt))
                return self.do_login(username, password)
            if path == "/api/login":
                return self.do_login(data.get("username", "").strip(), data.get("password", ""))
            if path == "/api/logout":
                uid = self.user_id()
                token = next((i.strip().split("=", 1)[1] for i in self.headers.get("Cookie", "").split(";") if i.strip().startswith("cv_session=")), None)
                if token:
                    SESSIONS.pop(token, None)
                return self.respond({"ok": True}, headers={"Set-Cookie": "cv_session=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0"})
            if path == "/api/sample":
                image = make_sample(data.get("kind", "mixed"))
                return self.respond({"image": png_data(image), "filename": "synthetic_" + data.get("kind", "mixed") + ".jpg", "synthetic": True})
            if path == "/api/clean":
                original = image_from_data(data.get("image"))
                cleaned = clean_image(original)
                return self.respond({"original": png_data(original), "cleaned": png_data(cleaned), "image": png_data(cleaned), "note": "Медианный фильтр подавляет мелкий сенсорный шум и одиночные точки. Сравните до/после: тонкая морфология тоже может сглаживаться."})
            uid = self.require_user()
            if not uid:
                return
            if path == "/api/ocr/cbc":
                try:
                    report = parse_cbc_report(image_from_data(data.get("image")))
                    return self.respond(report)
                except RuntimeError as exc:
                    return self.respond({"error": str(exc)}, 503)
            if path == "/api/assess-cbc":
                population = str(data.get("population", "woman"))
                if population not in {"woman", "man", "pregnant", "child_6_23", "child_24_59", "child_5_11", "child_12_14"}:
                    return self.respond({"error": "Выберите группу пациента"}, 400)
                trimester = int(data.get("trimester") or 1)
                if trimester not in (1, 2, 3):
                    return self.respond({"error": "Проверьте триместр беременности"}, 400)
                cbc = data.get("cbc") or {}
                assessment = assess_hb(data.get("hemoglobin"), population, trimester, data.get("age"))
                assessment["cbc_patterns"] = cbc_pattern(cbc)
                assessment["notice"] = "Скрининговая интерпретация лабораторного бланка, не диагноз. OCR-поля нужно сверить с оригиналом; результат обсудите с медицинским специалистом."
                return self.respond(assessment)
            if path == "/api/profile":
                age = data.get("age") or None
                if age is not None and not 0 < int(age) < 131:
                    return self.respond({"error": "Возраст должен быть от 1 до 130"}, 400)
                with db_connect() as db:
                    db.execute("UPDATE users SET first_name=?,last_name=?,age=?,home_address=? WHERE id=?",
                               (data.get("first_name", "").strip(), data.get("last_name", "").strip(), age, data.get("home_address", "").strip(), uid))
                return self.respond({"ok": True})
            if path == "/api/model/train":
                raw = base64.b64decode(data.get("archive", ""), validate=True)
                if len(raw) > 64 * 1024 * 1024: return self.respond({"error":"ZIP-архив ограничен 64 МБ"}, 400)
                train_x, train_y, test_x, test_y = [], [], [], []
                try:
                    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                        for info in archive.infolist():
                            if info.is_dir() or info.file_size > 5_000_000: continue
                            parts = [p.lower() for p in info.filename.replace("\\", "/").split("/")]
                            split = next((p for p in parts if p in ("train", "test")), None)
                            if not split or len(parts) < 2 or not info.filename.lower().endswith((".png", ".jpg", ".jpeg", ".bmp")): continue
                            split_i = parts.index(split)
                            if split_i + 1 >= len(parts): continue
                            label = parts[split_i + 1]
                            buf = np.frombuffer(archive.read(info), dtype=np.uint8); crop = cv2.imdecode(buf, cv2.IMREAD_COLOR)
                            if crop is None: continue
                            (train_x if split == "train" else test_x).append(hog_descriptor(crop))
                            (train_y if split == "train" else test_y).append(label)
                except zipfile.BadZipFile:
                    return self.respond({"error":"Не удалось прочитать ZIP-архив"}, 400)
                classes = sorted(set(train_y))
                if len(classes) < 2 or len(train_y) < 10 or not test_y:
                    return self.respond({"error":"Нужны папки train/ и test/, минимум 2 класса, 10 учебных и 1 тестовый пример. Разделяйте данные по пациентам/снимкам."}, 400)
                if not set(test_y).issubset(set(classes)):
                    return self.respond({"error":"Каждый класс в test/ должен встречаться в train/"}, 400)
                mapping = {name:i for i,name in enumerate(classes)}
                svm = LinearSVM(None, None).fit(train_x, [mapping[x] for x in train_y], len(classes))
                predicted = [classes[int(svm.predict(x.reshape(1,-1))[0,0])] for x in test_x]
                per_class = {}
                for label in sorted(set(test_y)):
                    tp = sum(p == label and t == label for p,t in zip(predicted,test_y))
                    fp = sum(p == label and t != label for p,t in zip(predicted,test_y))
                    fn = sum(p != label and t == label for p,t in zip(predicted,test_y))
                    precision = tp / max(1,tp+fp); recall = tp / max(1,tp+fn)
                    per_class[label] = {"n": sum(t == label for t in test_y), "precision":round(precision,3), "recall":round(recall,3), "f1":round(2*precision*recall/max(1e-9,precision+recall),3)}
                accuracy = sum(p == t for p,t in zip(predicted,test_y))/len(test_y)
                matrix = {actual:{pred:sum(t==actual and p==pred for t,p in zip(test_y,predicted)) for pred in classes} for actual in classes}
                macro_f1 = float(np.mean([x["f1"] for x in per_class.values()])) if per_class else 0.0
                os.makedirs(MODEL_DIR, exist_ok=True); np.savez_compressed(MODEL_PATH, weights=svm.weights, bias=svm.bias)
                with open(MODEL_CLASSES_PATH,"w",encoding="utf-8") as f: json.dump(classes,f,ensure_ascii=False)
                global AI_MODEL, AI_CLASSES
                AI_MODEL, AI_CLASSES = svm, classes
                return self.respond({"trained":True,"classes":classes,"train_n":len(train_y),"test_n":len(test_y),"accuracy":round(accuracy,3),"macro_f1":round(macro_f1,3),"per_class":per_class,"confusion_matrix":matrix,"warning":"Внутренняя проверка на загруженной выборке; не клиническая валидация. Если train/test содержат клетки одного мазка/пациента, оценка может быть завышена."})
            if path == "/api/annotations":
                analysis_id = int(data.get("analysis_id", 0)); labels = data.get("labels", [])
                with db_connect() as db:
                    owned = db.execute("SELECT 1 FROM analyses WHERE id=? AND user_id=?", (analysis_id, uid)).fetchone()
                    if not owned: return self.respond({"error":"Исследование не найдено"}, 404)
                    valid_cells = {x[0] for x in db.execute("SELECT cell_number FROM cells WHERE analysis_id=?", (analysis_id,))}
                    for item in labels:
                        cell_no = int(item.get("cell_number", 0)); label = str(item.get("label", ""))[:60]
                        if cell_no not in valid_cells: continue
                        if label == "не размечено":
                            db.execute("DELETE FROM expert_labels WHERE analysis_id=? AND cell_number=?", (analysis_id,cell_no))
                            continue
                        if not label: continue
                        db.execute("INSERT INTO expert_labels(analysis_id,cell_number,label,reviewer,created_at) VALUES(?,?,?,?,?) ON CONFLICT(analysis_id,cell_number) DO UPDATE SET label=excluded.label,reviewer=excluded.reviewer,created_at=excluded.created_at",
                                   (analysis_id,cell_no,label,str(data.get("reviewer", ""))[:80],datetime.now().astimezone().isoformat(timespec="seconds")))
                    counts = db.execute("SELECT label,COUNT(*) n FROM expert_labels WHERE analysis_id=? GROUP BY label", (analysis_id,)).fetchall()
                    compared = db.execute("SELECT c.ai_class,l.label FROM cells c JOIN expert_labels l ON l.analysis_id=c.analysis_id AND l.cell_number=c.cell_number WHERE c.analysis_id=? AND c.ai_class IS NOT NULL", (analysis_id,)).fetchall()
                pairs=[(x["ai_class"],x["label"]) for x in compared]
                accuracy=sum(a==b for a,b in pairs)/len(pairs) if pairs else None
                return self.respond({"ok": True, "labels": sum(x["n"] for x in counts), "class_counts": {x["label"]:x["n"] for x in counts}, "evaluation":{"n":len(pairs),"accuracy":round(accuracy,3) if accuracy is not None else None}, "note":"Для сравнения с AI нужны размеченные снимки и отдельная экспертная проверка."})
            if path == "/api/annotations/independent":
                analysis_id = int(data.get("analysis_id", 0)); slot = str(data.get("reviewer_slot", "")); labels = data.get("labels", {})
                if slot not in {"A", "B"} or not isinstance(labels, dict) or len(labels) > 160:
                    return self.respond({"error":"Проверьте рецензента и число меток (до 160)"}, 400)
                clean = {str(int(k)):str(v)[:60] for k,v in labels.items() if str(v) and str(v) != "не размечено"}
                with db_connect() as db:
                    owned = db.execute("SELECT 1 FROM analyses WHERE id=? AND user_id=?", (analysis_id, uid)).fetchone()
                    if not owned: return self.respond({"error":"Исследование не найдено"}, 404)
                    valid = {str(r[0]) for r in db.execute("SELECT cell_number FROM cells WHERE analysis_id=?", (analysis_id,))}
                    clean = {k:v for k,v in clean.items() if k in valid}
                    db.execute("INSERT INTO independent_reviews(analysis_id,reviewer_slot,reviewer_name,labels_json,created_at) VALUES(?,?,?,?,?) ON CONFLICT(analysis_id,reviewer_slot) DO UPDATE SET reviewer_name=excluded.reviewer_name,labels_json=excluded.labels_json,created_at=excluded.created_at", (analysis_id,slot,str(data.get("reviewer_name", ""))[:80],json.dumps(clean,ensure_ascii=False),datetime.now().astimezone().isoformat(timespec="seconds")))
                return self.respond({"ok":True,"labels":len(clean)})
            if path == "/api/annotations/mask":
                analysis_id=int(data.get("analysis_id",0)); polygons=data.get("polygons",[])
                if not isinstance(polygons,list) or len(polygons)>1000: return self.respond({"error":"Неверное число контуров"},400)
                with db_connect() as db:
                    row=db.execute("SELECT segmentation_mask FROM analyses WHERE id=? AND user_id=?",(analysis_id,uid)).fetchone()
                    if not row: return self.respond({"error":"Исследование не найдено"},404)
                    mask=image_from_data(row["segmentation_mask"])
                    h,w=mask.shape[:2]; gt=np.zeros((h,w),np.uint8); checked=[]
                    for polygon in polygons:
                        if not isinstance(polygon,list) or len(polygon)<3 or len(polygon)>5000: continue
                        points=[]
                        for point in polygon:
                            x,y=float(point[0]),float(point[1])
                            if not math.isfinite(x) or not math.isfinite(y): continue
                            points.append([max(0,min(w-1,round(x))),max(0,min(h-1,round(y)))])
                        if len(points)>=3:
                            cv2.fillPoly(gt,[np.asarray(points,np.int32)],255); checked.append(points)
                    pred=mask[:,:,0] if mask.ndim==3 else mask
                    pred=pred>0; truth=gt>0; intersection=int(np.count_nonzero(pred & truth)); pcount=int(np.count_nonzero(pred)); tcount=int(np.count_nonzero(truth)); union=int(np.count_nonzero(pred | truth))
                    evaluation={"contours":len(checked),"dice":round(2*intersection/max(1,pcount+tcount),4),"iou":round(intersection/max(1,union),4),"predicted_pixels":pcount,"manual_pixels":tcount,"note":"Pixel-level agreement for this image only; manual polygons are not independent clinical validation."}
                    db.execute("UPDATE analyses SET expert_mask_json=?,expert_mask_reviewer=?,expert_mask_metrics_json=? WHERE id=?",(json.dumps(checked,separators=(",",":")),str(data.get("reviewer", ""))[:80],json.dumps(evaluation,ensure_ascii=False),analysis_id))
                return self.respond({"ok":True,"evaluation":evaluation,"polygons":checked})
            if path == "/api/analyze":
                image = image_from_data(data.get("image"))
                filename = os.path.basename(data.get("filename", "uploaded-image"))[:120]
                cells, segmented, metrics, predicted_mask = analyze(image)
                quality = image_quality(image)
                pixel_um = data.get("pixel_um")
                if pixel_um not in (None, ""):
                    pixel_um = float(pixel_um)
                    if not math.isfinite(pixel_um) or not 0 < pixel_um <= 100:
                        return self.respond({"error":"Масштаб должен быть в диапазоне 0–100 µm/px"}, 400)
                    for cell in cells:
                        cell["diameter_um"] = round(cell["diameter_px"] * pixel_um, 3)
                        cell["area_um2"] = round(cell["area_px2"] * pixel_um * pixel_um, 3)
                    metrics["pixel_um"] = pixel_um
                population = data.get("population", "woman")
                hb = data.get("hemoglobin")
                assessment = assess_hb(hb, population, int(data.get("trimester", 1)), data.get("age"))
                cbc_summary = cbc_pattern(data.get("cbc", {}))
                assessment["cbc_patterns"] = cbc_summary
                image_result = image_screen(image)
                morph_counts = {}
                for cell in cells:
                    if cell.get("ai_class"):
                        morph_counts[cell["ai_class"]] = morph_counts.get(cell["ai_class"], 0) + 1
                morph_summary = {"classified_cells": sum(morph_counts.values()), "counts": morph_counts,
                    "text": ("По всему кадру: " + ", ".join(f"{label} — {count}" for label, count in sorted(morph_counts.items())) + ".") if morph_counts else "Модель морфологии не разметила клетки; показаны только результаты сегментации и измерения."}
                data_url, seg_url = png_data(image), png_data(segmented)
                now = datetime.now().astimezone().isoformat(timespec="seconds")
                with db_connect() as db:
                    mask_url=png_mask_data(predicted_mask)
                    cur = db.execute("""INSERT INTO analyses(user_id,created_at,image_name,cells,mean_area,std_area,rdw,image_data,segmented_data,segmentation_mask,morphology_json,hemoglobin,population,anemia_result)
                      VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                      (uid, now, filename, metrics.get("cell_count", 0), metrics.get("mean_area", 0), metrics.get("std_area", 0), metrics.get("cv_percent", 0),
                       data_url, seg_url, mask_url, json.dumps(metrics), str(hb or ""), population, json.dumps(assessment, ensure_ascii=False)))
                    analysis_id = cur.lastrowid
                    db.executemany("INSERT INTO cells(analysis_id,cell_number,area_px2,centroid_x,centroid_y,bbox_x,bbox_y,bbox_width,bbox_height,diameter_px,aspect_ratio,circularity,eccentricity,mean_bgr,diameter_um,area_um2,ai_class) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                      [(analysis_id,c["cell_number"],c["area_px2"],c["centroid_x"],c["centroid_y"],c["bbox_x"],c["bbox_y"],c["bbox_width"],c["bbox_height"],c["diameter_px"],c["aspect_ratio"],c["circularity"],c["eccentricity"],json.dumps(c["mean_bgr"]),c.get("diameter_um"),c.get("area_um2"),c.get("ai_class")) for c in cells])
                result = {"id": analysis_id,"created_at":now,"image_name":filename,"cells":cells,"metrics":metrics,"assessment":assessment,
                          "image_data":data_url,"segmented_data":seg_url,"segmentation_mask_data":mask_url,"synthetic":bool(data.get("synthetic")),"quality":quality,
                          "cbc_patterns":cbc_summary,"image_screen":image_result,"morphology_summary":morph_summary,
                          "ai":{"status":"trained" if AI_MODEL is not None else "untrained","message":"Экспериментальная морфологическая классификация обученной моделью; оценка не является диагнозом." if AI_MODEL is not None else "Классификатор не обучен на экспертно размеченных данных. Морфологические классы и паразиты автоматически не определяются."}}
                return self.respond(result)
            if path == "/api/compare":
                before_id = int(data.get("analysis_id", 0))
                with db_connect() as db:
                    before = db.execute("SELECT * FROM analyses WHERE id=? AND user_id=?", (before_id, uid)).fetchone()
                    after = db.execute("SELECT * FROM analyses WHERE user_id=? ORDER BY id DESC LIMIT 1", (uid,)).fetchone()
                if not before or not after:
                    return self.respond({"error": "Не найдены оба анализа"}, 404)
                return self.respond({"before": dict(before), "after": dict(after)})
            if path == "/api/export/csv":
                analysis_id = int(data.get("analysis_id", 0))
                with db_connect() as db:
                    row = db.execute("SELECT id FROM analyses WHERE id=? AND user_id=?", (analysis_id, uid)).fetchone()
                    if not row:
                        return self.respond({"error":"Анализ не найден"}, 404)
                    rows = db.execute("SELECT cell_number,area_px2,centroid_x,centroid_y,bbox_x,bbox_y,bbox_width,bbox_height,diameter_px,diameter_um,area_um2,aspect_ratio,circularity,eccentricity,mean_bgr,ai_class FROM cells WHERE analysis_id=? ORDER BY cell_number", (analysis_id,)).fetchall()
                    labels = {x[0]:x[1] for x in db.execute("SELECT cell_number,label FROM expert_labels WHERE analysis_id=?", (analysis_id,))}
                out=io.StringIO(); writer=csv.writer(out); writer.writerow(["cell_number","area_px2","centroid_x","centroid_y","bbox_x","bbox_y","bbox_width","bbox_height","diameter_px","diameter_um","area_um2","aspect_ratio","circularity","eccentricity","mean_bgr_channels","ai_class","expert_label"])
                writer.writerows([tuple(r)+(labels.get(r[0],""),) for r in rows])
                return self.respond(out.getvalue().encode("utf-8-sig"), content_type="text/csv; charset=utf-8", headers={"Content-Disposition":f"attachment; filename=cellvision_{analysis_id}.csv"})
            return self.respond({"error": "Неизвестный endpoint"}, 404)
        except sqlite3.IntegrityError:
            return self.respond({"error": "Этот логин уже занят"}, 409)
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            return self.respond({"error": str(exc)}, 400)
        except Exception as exc:
            return self.respond({"error": f"Ошибка сервера: {exc}"}, 500)

    def do_login(self, username, password):
        with db_connect() as db:
            user = db.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
        if not user or not hmac.compare_digest(user["password_hash"], pwd_hash(password, user["salt"])):
            return self.respond({"error": "Неверный логин или пароль"}, 401)
        token = secrets.token_urlsafe(32)
        SESSIONS[token] = user["id"]
        return self.respond({"ok": True, "user": {"id": user["id"],"username": user["username"],"first_name": user["first_name"],"last_name": user["last_name"],"age": user["age"],"home_address": user["home_address"]}},
                            headers={"Set-Cookie": f"cv_session={token}; Path=/; HttpOnly; SameSite=Lax"})


if __name__ == "__main__":
    init_db()
    AI_MODEL, AI_CLASSES = load_ai_model()
    print(f"CellVision is running at http://{HOST}:{PORT}")
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
