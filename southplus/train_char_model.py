#!/usr/bin/env python3
import argparse
import csv
import json
from pathlib import Path

import cv2
import numpy as np


BASE_DIR = Path(__file__).resolve().parent
SAMPLES_DIR = BASE_DIR / "captcha_samples"
CHAR_LABELS_CSV = SAMPLES_DIR / "char_labels.csv"
MODEL_PATH = BASE_DIR / "captcha_char_svm.yml"
META_PATH = BASE_DIR / "captcha_char_model_meta.json"


def make_square(crop, size=32):
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


def hog_feature(crop):
    image = make_square(crop, 32)
    hog = cv2.HOGDescriptor(
        _winSize=(32, 32),
        _blockSize=(16, 16),
        _blockStride=(8, 8),
        _cellSize=(8, 8),
        _nbins=9,
    )
    return hog.compute(image).reshape(-1).astype(np.float32)


def read_char_labels(path):
    with path.open(newline="", encoding="utf-8-sig") as fp:
        return list(csv.DictReader(fp))


def crop_from_row(samples_dir, row, pad=3):
    image = cv2.imread(str(samples_dir / row["file"]))
    if image is None:
        raise RuntimeError(f"图片读取失败: {row['file']}")
    x, y, width, height = [int(row[key]) for key in ["x", "y", "w", "h"]]
    image_height, image_width = image.shape[:2]
    x0 = max(0, x - pad)
    y0 = max(0, y - pad)
    x1 = min(image_width, x + width + pad)
    y1 = min(image_height, y + height + pad)
    return image[y0:y1, x0:x1]


def compute_position_boxes(rows):
    boxes = {}
    for position in range(4):
        items = [row for row in rows if int(row["pos"]) == position]
        boxes[position] = {
            key: int(round(sum(int(row[key]) for row in items) / len(items)))
            for key in ["x", "y", "w", "h"]
        }
    return boxes


def train_model(rows, samples_dir, model_path, meta_path):
    features = []
    labels = []
    for row in rows:
        crop = crop_from_row(samples_dir, row)
        features.append(hog_feature(crop))
        labels.append(int(row["digit"]))

    svm = cv2.ml.SVM_create()
    svm.setType(cv2.ml.SVM_C_SVC)
    svm.setKernel(cv2.ml.SVM_LINEAR)
    svm.setC(1.5)
    svm.train(np.asarray(features, np.float32), cv2.ml.ROW_SAMPLE, np.asarray(labels, np.int32))
    svm.save(str(model_path))

    meta = {
        "model": "opencv_svm_hog32_linear",
        "samples": len(rows),
        "position_boxes": compute_position_boxes(rows),
    }
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return meta


def parse_args():
    parser = argparse.ArgumentParser(description="训练 South Plus 验证码单字符 SVM 模型。")
    parser.add_argument("--samples-dir", default=str(SAMPLES_DIR))
    parser.add_argument("--char-labels", default=str(CHAR_LABELS_CSV))
    parser.add_argument("--model", default=str(MODEL_PATH))
    parser.add_argument("--meta", default=str(META_PATH))
    return parser.parse_args()


def main():
    args = parse_args()
    samples_dir = Path(args.samples_dir).expanduser().resolve()
    rows = read_char_labels(Path(args.char_labels).expanduser().resolve())
    if not rows:
        print("没有字符标注数据")
        return 2
    meta = train_model(
        rows,
        samples_dir,
        Path(args.model).expanduser().resolve(),
        Path(args.meta).expanduser().resolve(),
    )
    print(f"训练样本: {meta['samples']}")
    print(f"模型文件: {Path(args.model).expanduser().resolve()}")
    print(f"元数据: {Path(args.meta).expanduser().resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
