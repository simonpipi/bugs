#!/usr/bin/env python3
import contextlib
import csv
import io
import json
import random
from collections import defaultdict
from pathlib import Path

import cv2
import numpy as np


BASE_DIR = Path(__file__).resolve().parent
SAMPLES_DIR = BASE_DIR / "captcha_samples"
CHAR_LABELS_CSV = SAMPLES_DIR / "char_labels.csv"
LABELS_CSV = SAMPLES_DIR / "labels.csv"
HARD_NEGATIVES_CSV = SAMPLES_DIR / "hard_negatives.csv"
MODEL_PATH = BASE_DIR / "captcha_char_cnn.pt"
META_PATH = BASE_DIR / "captcha_char_cnn_meta.json"

IMAGE_SIZE = 32
BACKGROUND_CLASS = 10
CLASS_NAMES = [str(index) for index in range(10)] + ["bg"]
BACKGROUND_SCORE_WEIGHT = 2.0
SLOT_SCAN_SOURCE_PENALTY = 0.10
POSITION_FALLBACK_SOURCE_PENALTY = 0.08


def import_torch():
    with contextlib.redirect_stderr(io.StringIO()):
        import torch
        from torch import nn
        from torch.utils.data import DataLoader, Dataset

    return torch, nn, DataLoader, Dataset


class SlotCharCNN(import_torch()[1].Module):
    def __init__(self, num_classes=len(CLASS_NAMES)):
        _, nn, _, _ = import_torch()
        super().__init__()
        self.features = nn.Sequential(
            nn.Conv2d(1, 32, 3, padding=1),
            nn.BatchNorm2d(32),
            nn.ReLU(),
            nn.MaxPool2d(2),
            nn.Conv2d(32, 64, 3, padding=1),
            nn.BatchNorm2d(64),
            nn.ReLU(),
            nn.MaxPool2d(2),
            nn.Conv2d(64, 128, 3, padding=1),
            nn.BatchNorm2d(128),
            nn.ReLU(),
            nn.MaxPool2d(2),
            nn.Conv2d(128, 128, 3, padding=1),
            nn.BatchNorm2d(128),
            nn.ReLU(),
            nn.AdaptiveAvgPool2d((1, 1)),
        )
        self.classifier = nn.Sequential(
            nn.Flatten(),
            nn.Dropout(0.2),
            nn.Linear(128, num_classes),
        )

    def forward(self, inputs):
        return self.classifier(self.features(inputs))


def read_csv(path):
    with Path(path).open(newline="", encoding="utf-8-sig") as fp:
        return list(csv.DictReader(fp))


def clean_digits(value):
    return "".join(char for char in (value or "") if char.isdigit())


def read_labeled_captchas(path=LABELS_CSV):
    rows = []
    for row in read_csv(path):
        label = clean_digits(row.get("label")) or clean_digits(row.get("error"))
        if len(label) == 4:
            rows.append({"file": row["file"], "label": label})
    return rows


def char_rows_by_file(rows):
    by_file = defaultdict(list)
    for row in rows:
        by_file[row["file"]].append(row)
    return by_file


def compute_position_boxes(rows):
    boxes = {}
    for position in range(4):
        items = [row for row in rows if int(row["pos"]) == position]
        boxes[str(position)] = {
            key: int(round(sum(int(row[key]) for row in items) / len(items)))
            for key in ["x", "y", "w", "h"]
        }
    return boxes


def compute_slot_windows(rows, image_width=150, image_height=60):
    windows = {}
    for position in range(4):
        items = [row for row in rows if int(row["pos"]) == position]
        x0 = max(0, min(int(row["x"]) for row in items) - 8)
        y0 = 0
        x1 = min(image_width, max(int(row["x"]) + int(row["w"]) for row in items) + 8)
        y1 = image_height
        windows[str(position)] = {"x": x0, "y": y0, "w": x1 - x0, "h": y1 - y0}
    return windows


def box_tuple(row):
    return tuple(int(row[key]) for key in ["x", "y", "w", "h"])


def box_iou(left, right):
    lx, ly, lw, lh = left
    rx, ry, rw, rh = right
    intersection = max(0, min(lx + lw, rx + rw) - max(lx, rx)) * max(0, min(ly + lh, ry + rh) - max(ly, ry))
    union = lw * lh + rw * rh - intersection
    return intersection / union if union else 0.0


def crop_box(image, box, pad=3):
    image_height, image_width = image.shape[:2]
    x, y, width, height = [int(value) for value in box]
    x0 = max(0, x - pad)
    y0 = max(0, y - pad)
    x1 = min(image_width, x + width + pad)
    y1 = min(image_height, y + height + pad)
    return image[y0:y1, x0:x1]


def make_square(crop, size=IMAGE_SIZE):
    if crop.size == 0:
        return np.full((size, size), 255, np.uint8)
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    height, width = gray.shape[:2]
    scale = (size - 6) / max(height, width)
    new_width = max(1, int(round(width * scale)))
    new_height = max(1, int(round(height * scale)))
    resized = cv2.resize(gray, (new_width, new_height), interpolation=cv2.INTER_CUBIC)
    canvas = np.full((size, size), 255, np.uint8)
    x = (size - new_width) // 2
    y = (size - new_height) // 2
    canvas[y : y + new_height, x : x + new_width] = resized
    return cv2.equalizeHist(canvas)


def tensor_from_image(torch, image):
    normalized = image.astype("float32") / 255.0
    return torch.tensor(normalized.tolist(), dtype=torch.float32).unsqueeze(0)


def generate_negative_samples(rows, samples_dir, per_file=8, seed=42):
    rng = random.Random(seed)
    by_file = char_rows_by_file(rows)
    samples = []
    for file_name, file_rows in sorted(by_file.items()):
        image = cv2.imread(str(samples_dir / file_name))
        if image is None:
            continue
        image_height, image_width = image.shape[:2]
        positives = [box_tuple(row) for row in file_rows]
        attempts = 0
        added = 0
        while added < per_file and attempts < per_file * 30:
            attempts += 1
            width = rng.randint(10, 36)
            height = rng.randint(10, 38)
            x = rng.randint(0, max(0, image_width - width))
            y = rng.randint(0, max(0, image_height - height))
            box = (x, y, width, height)
            if all(box_iou(box, positive) < 0.05 for positive in positives):
                samples.append({"file": file_name, "box": box, "label": BACKGROUND_CLASS})
                added += 1
    return samples


def read_hard_negative_samples(path, rows=None):
    path = Path(path)
    if not path.exists():
        return []

    positives_by_file = {}
    if rows is not None:
        positives_by_file = {
            file_name: [box_tuple(row) for row in file_rows]
            for file_name, file_rows in char_rows_by_file(rows).items()
        }

    samples = []
    seen = set()
    for row in read_csv(path):
        file_name = row.get("file", "")
        if not file_name:
            continue
        try:
            box = tuple(int(row[key]) for key in ["x", "y", "w", "h"])
        except (KeyError, TypeError, ValueError):
            continue
        if box[2] <= 0 or box[3] <= 0:
            continue
        key = (file_name, *box)
        if key in seen:
            continue
        if positives_by_file and any(box_iou(box, positive) >= 0.05 for positive in positives_by_file.get(file_name, [])):
            continue
        seen.add(key)
        samples.append({"file": file_name, "box": box, "label": BACKGROUND_CLASS, "hard_negative": True})
    return samples


def training_samples(rows, samples_dir, negative_per_file=8, seed=42, hard_negatives_path=HARD_NEGATIVES_CSV):
    samples = []
    for row in rows:
        samples.append({"file": row["file"], "box": box_tuple(row), "label": int(row["digit"])})
    samples.extend(generate_negative_samples(rows, samples_dir, per_file=negative_per_file, seed=seed))
    samples.extend(read_hard_negative_samples(hard_negatives_path, rows=rows))
    return samples


def augment_crop(crop, rng):
    if rng.random() < 0.45:
        crop = cv2.convertScaleAbs(crop, alpha=1.0 + rng.uniform(-0.18, 0.18), beta=rng.uniform(-18, 18))
    if rng.random() < 0.30:
        crop = cv2.GaussianBlur(crop, (3, 3), 0)
    return crop


def build_dataset_class():
    torch, _, _, Dataset = import_torch()

    class CharDataset(Dataset):
        def __init__(self, samples, samples_dir, augment=False, seed=42):
            self.samples = samples
            self.samples_dir = Path(samples_dir)
            self.augment = augment
            self.rng = random.Random(seed)

        def __len__(self):
            return len(self.samples)

        def __getitem__(self, index):
            sample = self.samples[index]
            image = cv2.imread(str(self.samples_dir / sample["file"]))
            if image is None:
                raise RuntimeError(f"图片读取失败: {sample['file']}")
            pad = self.rng.choice([1, 2, 3, 4, 5]) if self.augment else 3
            crop = crop_box(image, sample["box"], pad=pad)
            if self.augment:
                crop = augment_crop(crop, self.rng)
            return tensor_from_image(torch, make_square(crop)), int(sample["label"])

    return CharDataset


def split_samples_by_file(samples, val_ratio=0.15, seed=42):
    files = sorted({sample["file"] for sample in samples})
    rng = random.Random(seed)
    rng.shuffle(files)
    val_count = max(1, int(round(len(files) * val_ratio))) if val_ratio > 0 else 0
    val_files = set(files[:val_count])
    train_samples = [sample for sample in samples if sample["file"] not in val_files]
    val_samples = [sample for sample in samples if sample["file"] in val_files]
    return train_samples, val_samples


def train_char_cnn(
    rows,
    samples_dir=SAMPLES_DIR,
    model_path=MODEL_PATH,
    meta_path=META_PATH,
    epochs=35,
    batch_size=64,
    learning_rate=1e-3,
    negative_per_file=8,
    hard_negatives_path=HARD_NEGATIVES_CSV,
    val_ratio=0.15,
    seed=42,
):
    torch, nn, DataLoader, _ = import_torch()
    torch.manual_seed(seed)
    hard_negative_samples = read_hard_negative_samples(hard_negatives_path, rows=rows)
    all_samples = training_samples(
        rows,
        Path(samples_dir),
        negative_per_file=negative_per_file,
        seed=seed,
        hard_negatives_path=hard_negatives_path,
    )
    train_samples, val_samples = split_samples_by_file(all_samples, val_ratio=val_ratio, seed=seed)
    CharDataset = build_dataset_class()
    train_loader = DataLoader(CharDataset(train_samples, samples_dir, augment=True, seed=seed), batch_size=batch_size, shuffle=True)
    val_loader = (
        DataLoader(CharDataset(val_samples, samples_dir, augment=False, seed=seed), batch_size=batch_size)
        if val_samples
        else None
    )

    model = SlotCharCNN()
    optimizer = torch.optim.Adam(model.parameters(), lr=learning_rate, weight_decay=1e-4)
    criterion = nn.CrossEntropyLoss()
    best_accuracy = 0.0
    best_state = None

    for epoch in range(1, epochs + 1):
        model.train()
        total_loss = 0.0
        total = 0
        for inputs, labels in train_loader:
            optimizer.zero_grad()
            loss = criterion(model(inputs), labels)
            loss.backward()
            optimizer.step()
            total_loss += float(loss.item()) * len(labels)
            total += len(labels)
        accuracy = evaluate_loader(model, val_loader) if val_loader else 0.0
        if accuracy >= best_accuracy:
            best_accuracy = accuracy
            best_state = {key: value.clone() for key, value in model.state_dict().items()}
        print(f"epoch {epoch:02d}: loss={total_loss / max(1, total):.4f} val_acc={accuracy:.2%}")

    if best_state:
        model.load_state_dict(best_state)
    model_path = Path(model_path)
    meta_path = Path(meta_path)
    torch.save(model.state_dict(), model_path)
    meta = {
        "model": "slot_char_cnn_v1",
        "image_size": IMAGE_SIZE,
        "classes": CLASS_NAMES,
        "background_class": BACKGROUND_CLASS,
        "samples": len(rows),
        "negative_samples": len(all_samples) - len(rows),
        "random_negative_samples": len(generate_negative_samples(rows, Path(samples_dir), per_file=negative_per_file, seed=seed)),
        "hard_negative_samples": len(hard_negative_samples),
        "position_boxes": compute_position_boxes(rows),
        "slot_windows": compute_slot_windows(rows),
        "val_accuracy": best_accuracy,
    }
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return meta


def evaluate_loader(model, loader):
    if loader is None:
        return 0.0
    torch, _, _, _ = import_torch()
    model.eval()
    correct = 0
    total = 0
    with torch.no_grad():
        for inputs, labels in loader:
            predictions = model(inputs).argmax(1)
            correct += int((predictions == labels).sum().item())
            total += len(labels)
    return correct / total if total else 0.0


def load_char_cnn(model_path=MODEL_PATH, meta_path=META_PATH):
    torch, _, _, _ = import_torch()
    model_path = Path(model_path)
    meta_path = Path(meta_path)
    if not model_path.exists() or not meta_path.exists():
        raise RuntimeError(f"缺少 CNN 模型，请先执行：python3 southplus/train_char_cnn.py")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    model = SlotCharCNN(num_classes=len(meta.get("classes", CLASS_NAMES)))
    model.load_state_dict(torch.load(model_path, map_location="cpu"))
    model.eval()
    return model, meta


def component_candidates(image):
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    masks = []
    for saturation in [45, 65, 85, 105]:
        masks.append(cv2.inRange(hsv, np.array([0, saturation, 0]), np.array([179, 255, 255])))
    for gray_max in [110, 140, 170, 200]:
        masks.append(cv2.inRange(gray, 0, gray_max))

    candidates = []
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2, 2))
    for mask in masks:
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
        count, _, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
        for index in range(1, count):
            x, y, width, height, area = [int(value) for value in stats[index]]
            density = area / max(1, width * height)
            if not (4 <= width <= 48 and 7 <= height <= 52 and 18 <= area <= 700 and density >= 0.08):
                continue
            candidates.append({"box": (x, y, width, height), "source": "component", "score": area + height * 5 + width * 2})

    selected = []
    for candidate in sorted(candidates, key=lambda item: item["score"], reverse=True):
        if any(box_iou(candidate["box"], item["box"]) > 0.45 for item in selected):
            continue
        selected.append(candidate)
    return selected


def slot_candidates_for_position(components, meta, position):
    slot = meta["slot_windows"][str(position)]
    position_box = meta["position_boxes"][str(position)]
    center = position_box["x"] + position_box["w"] / 2
    slot_x0 = slot["x"]
    slot_x1 = slot["x"] + slot["w"]
    candidates = []
    for item in components:
        x, y, width, height = item["box"]
        item_center = x + width / 2
        if not (slot_x0 - 8 <= item_center <= slot_x1 + 8):
            continue
        distance = abs(item_center - center)
        candidates.append({**item, "distance": distance})

    candidates.append(
        {
            "box": (position_box["x"], position_box["y"], position_box["w"], position_box["h"]),
            "source": "position_fallback",
            "score": 0,
            "distance": 0,
        }
    )

    # Sliding boxes补位：连通域漏检时，仍按槽位中心和常见高度扫几块候选。
    average_w = position_box["w"]
    average_h = position_box["h"]
    for dy in [-10, 0, 10, 20]:
        x = int(round(center - average_w / 2))
        y = max(0, min(60 - average_h, int(position_box["y"] + dy)))
        candidates.append(
            {
                "box": (x, y, average_w, average_h),
                "source": "slot_scan",
                "score": 0,
                "distance": 0,
            }
        )
    return candidates


def classify_crop(model, image, box):
    torch, _, _, _ = import_torch()
    crop = crop_box(image, box, pad=3)
    tensor = tensor_from_image(torch, make_square(crop)).unsqueeze(0)
    with torch.no_grad():
        probabilities = torch.softmax(model(tensor), dim=1)[0]
    values = [float(probabilities[index].item()) for index in range(len(CLASS_NAMES))]
    digit_index = max(range(10), key=lambda index: values[index])
    return str(digit_index), values[digit_index], values[BACKGROUND_CLASS], values


def box_center_x(box):
    x, _, width, _ = box
    return x + width / 2


def candidates_conflict(left, right):
    if tuple(left["box"]) == tuple(right["box"]):
        return True
    return box_iou(left["box"], right["box"]) > 0.55


def score_slot_candidates(model, image, components, meta, position, classification_cache):
    items = []
    for candidate in slot_candidates_for_position(components, meta, position):
        key = tuple(candidate["box"])
        if key not in classification_cache:
            classification_cache[key] = classify_crop(model, image, candidate["box"])
        digit, digit_prob, background_prob, probabilities = classification_cache[key]

        distance_penalty = min(candidate.get("distance", 0), 40) / 40 * 0.25
        if candidate["source"] == "position_fallback":
            source_penalty = POSITION_FALLBACK_SOURCE_PENALTY
        elif candidate["source"] == "slot_scan":
            source_penalty = SLOT_SCAN_SOURCE_PENALTY
        else:
            source_penalty = 0.0
        score = digit_prob - BACKGROUND_SCORE_WEIGHT * background_prob - distance_penalty - source_penalty
        items.append(
            {
                **candidate,
                "digit": digit,
                "digit_prob": digit_prob,
                "background_prob": background_prob,
                "score": score,
                "probabilities": probabilities,
                "position": position,
            }
        )

    return sorted(items, key=lambda item: item["score"], reverse=True)


def select_best_sequence(candidates_by_position, max_per_position=18):
    best = None
    ranked = [items[:max_per_position] for items in candidates_by_position]

    def search(position, chosen, score):
        nonlocal best
        if position == len(ranked):
            if best is None or score > best[0]:
                best = (score, list(chosen))
            return

        for item in ranked[position]:
            center = box_center_x(item["box"])
            if chosen and center <= box_center_x(chosen[-1]["box"]) + 6:
                continue
            if any(candidates_conflict(item, previous) for previous in chosen):
                continue
            chosen.append(item)
            search(position + 1, chosen, score + item["score"])
            chosen.pop()

    search(0, [], 0.0)
    if best is not None:
        return best[1]

    # 理论上每个槽位都有 fallback；这里保底避免异常样本导致无输出。
    return [max(items, key=lambda item: item["score"]) for items in candidates_by_position]


def recognize_image_with_cnn(image_path, model=None, meta=None, model_path=MODEL_PATH, meta_path=META_PATH):
    if model is None or meta is None:
        model, meta = load_char_cnn(model_path=model_path, meta_path=meta_path)
    image = cv2.imread(str(image_path))
    if image is None:
        raise RuntimeError(f"图片读取失败: {image_path}")

    components = component_candidates(image)
    classification_cache = {}
    candidates_by_position = [
        score_slot_candidates(model, image, components, meta, position, classification_cache) for position in range(4)
    ]
    debug = select_best_sequence(candidates_by_position)
    chars = [item["digit"] for item in debug]
    return "".join(chars), debug
