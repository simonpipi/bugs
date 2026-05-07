#!/usr/bin/env python3
import argparse
import csv
import random
from collections import defaultdict
from pathlib import Path

import cv2
import numpy as np

from train_char_model import CHAR_LABELS_CSV, SAMPLES_DIR, crop_from_row, hog_feature


def read_rows(path):
    rows = []
    with path.open(newline="", encoding="utf-8-sig") as fp:
        for row in csv.DictReader(fp):
            rows.append(row)
    return rows


def train_predict(train_x, train_y, test_x):
    svm = cv2.ml.SVM_create()
    svm.setType(cv2.ml.SVM_C_SVC)
    svm.setKernel(cv2.ml.SVM_LINEAR)
    svm.setC(1.5)
    svm.train(np.asarray(train_x, np.float32), cv2.ml.ROW_SAMPLE, np.asarray(train_y, np.int32))
    _, result = svm.predict(np.asarray(test_x, np.float32))
    return [str(int(item[0])) for item in result]


def cross_validate(rows, samples_dir, folds=5, seed=42):
    by_file = defaultdict(dict)
    for row in rows:
        by_file[row["file"]][int(row["pos"])] = row

    files = sorted(by_file)
    rng = random.Random(seed)
    order = list(files)
    rng.shuffle(order)
    fold_files = [order[index::folds] for index in range(folds)]

    features = {}
    for row in rows:
        features[(row["file"], int(row["pos"]))] = hog_feature(crop_from_row(samples_dir, row))

    predictions = {file_name: [""] * 4 for file_name in files}
    for fold in fold_files:
        test_files = set(fold)
        train_x = []
        train_y = []
        test_x = []
        test_keys = []
        for file_name in files:
            for pos in range(4):
                key = (file_name, pos)
                if file_name in test_files:
                    test_x.append(features[key])
                    test_keys.append(key)
                else:
                    train_x.append(features[key])
                    train_y.append(int(by_file[file_name][pos]["digit"]))
        fold_predictions = train_predict(train_x, train_y, test_x)
        for (file_name, pos), digit in zip(test_keys, fold_predictions):
            predictions[file_name][pos] = digit

    sequence_correct = 0
    character_correct = 0
    results = []
    for file_name in files:
        label = "".join(by_file[file_name][pos]["digit"] for pos in range(4))
        prediction = "".join(predictions[file_name])
        sequence_correct += prediction == label
        character_correct += sum(left == right for left, right in zip(prediction, label))
        results.append({"file": file_name, "label": label, "prediction": prediction, "ok": prediction == label})
    return sequence_correct, character_correct, len(files), results


def parse_args():
    parser = argparse.ArgumentParser(description="用字符框标注做 HOG+SVM 交叉验证。")
    parser.add_argument("--samples-dir", default=str(SAMPLES_DIR))
    parser.add_argument("--char-labels", default=str(CHAR_LABELS_CSV))
    parser.add_argument("--folds", type=int, default=5)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--output", default=str(SAMPLES_DIR / "char_model_cv_results.csv"))
    return parser.parse_args()


def main():
    args = parse_args()
    rows = read_rows(Path(args.char_labels).expanduser().resolve())
    samples_dir = Path(args.samples_dir).expanduser().resolve()
    sequence_correct, character_correct, total, results = cross_validate(
        rows,
        samples_dir,
        folds=args.folds,
        seed=args.seed,
    )
    output_path = Path(args.output).expanduser().resolve()
    with output_path.open("w", newline="", encoding="utf-8") as fp:
        writer = csv.DictWriter(fp, fieldnames=["file", "label", "prediction", "ok"])
        writer.writeheader()
        writer.writerows(results)
    print(f"sequence: {sequence_correct}/{total} = {sequence_correct / total:.2%}")
    print(f"character: {character_correct}/{total * 4} = {character_correct / (total * 4):.2%}")
    print(f"结果文件: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
