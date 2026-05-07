#!/usr/bin/env python3
import argparse
import ast
import csv
import re
from collections import Counter, defaultdict
from pathlib import Path

import cv2

from cnn_captcha import HARD_POSITIVES_CSV, SAMPLES_DIR, crop_box


CHAR_LABELS_CSV = SAMPLES_DIR / "char_labels.csv"
CNN_RESULTS_CSV = SAMPLES_DIR / "cnn_results.csv"
HARD_POSITIVE_FIELDNAMES = [
    "file",
    "pos",
    "x",
    "y",
    "w",
    "h",
    "digit",
    "predicted_digit",
    "source",
    "score",
    "iou",
    "crop_file",
]


DEBUG_PART_RE = re.compile(r"^(\d+):(\w+):([-0-9.]+):(\(.+\))$")


def box_iou(left, right):
    lx, ly, lw, lh = left
    rx, ry, rw, rh = right
    intersection = max(0, min(lx + lw, rx + rw) - max(lx, rx)) * max(0, min(ly + lh, ry + rh) - max(ly, ry))
    union = lw * lh + rw * rh - intersection
    return intersection / union if union else 0.0


def read_ground_truth(path):
    by_file = defaultdict(dict)
    with Path(path).open(newline="", encoding="utf-8-sig") as fp:
        for row in csv.DictReader(fp):
            by_file[row["file"]][int(row["pos"])] = {
                "box": tuple(int(row[key]) for key in ["x", "y", "w", "h"]),
                "digit": row["digit"],
            }
    return by_file


def parse_debug(debug):
    items = []
    for part in (debug or "").split("|"):
        match = DEBUG_PART_RE.match(part)
        if not match:
            continue
        items.append(
            {
                "digit": match.group(1),
                "source": match.group(2),
                "score": float(match.group(3)),
                "box": ast.literal_eval(match.group(4)),
            }
        )
    return items


def classify_bucket(item, expected):
    current_iou = box_iou(item["box"], expected["box"])
    x, y, width, height = item["box"]
    if current_iou >= 0.45:
        return "same_box_classification"
    if width <= 8 or height <= 10:
        return "tiny_noise_component"
    if item["source"] in {"slot_scan", "template_scan", "position_fallback"}:
        return "fallback_or_scan_miss"
    return "wrong_component_box"


def parse_args():
    parser = argparse.ArgumentParser(description="分析 CNN 验证码错例来源。")
    parser.add_argument("--samples-dir", default=str(SAMPLES_DIR))
    parser.add_argument("--char-labels", default=str(CHAR_LABELS_CSV))
    parser.add_argument("--results", default=str(CNN_RESULTS_CSV))
    parser.add_argument("--hard-positives-output", default="", help="导出 same_box_classification 为 hard positive CSV")
    parser.add_argument("--export-same-box-crops", default="", help="导出 same_box_classification crop 图片目录")
    return parser.parse_args()


def main():
    args = parse_args()
    ground_truth = read_ground_truth(args.char_labels)
    samples_dir = Path(args.samples_dir).expanduser().resolve()
    crop_dir = Path(args.export_same_box_crops).expanduser().resolve() if args.export_same_box_crops else None
    if crop_dir:
        crop_dir.mkdir(parents=True, exist_ok=True)
    buckets = Counter()
    sources = Counter()
    confusions = Counter()
    examples = defaultdict(list)
    hard_positive_rows = []
    seen_hard_positives = set()

    with Path(args.results).open(newline="", encoding="utf-8-sig") as fp:
        for row in csv.DictReader(fp):
            if row.get("ok") == "1":
                continue
            debug_items = parse_debug(row.get("debug", ""))
            for position, (item, expected_digit) in enumerate(zip(debug_items, row["label"])):
                if item["digit"] == expected_digit:
                    continue
                expected = ground_truth[row["file"]][position]
                bucket = classify_bucket(item, expected)
                iou = box_iou(item["box"], expected["box"])
                buckets[bucket] += 1
                sources[item["source"]] += 1
                confusions[(expected_digit, item["digit"])] += 1
                if bucket == "same_box_classification":
                    box = tuple(int(value) for value in item["box"])
                    hard_key = (row["file"], position, *box, expected_digit)
                    crop_file = ""
                    if hard_key not in seen_hard_positives:
                        seen_hard_positives.add(hard_key)
                        if crop_dir:
                            image = cv2.imread(str(samples_dir / row["file"]))
                            if image is not None:
                                crop_file = (
                                    f"{Path(row['file']).stem}_p{position}_"
                                    f"{expected_digit}_as_{item['digit']}_{len(hard_positive_rows):03d}.png"
                                )
                                cv2.imwrite(str(crop_dir / crop_file), crop_box(image, box, pad=3))
                        hard_positive_rows.append(
                            {
                                "file": row["file"],
                                "pos": position,
                                "x": box[0],
                                "y": box[1],
                                "w": box[2],
                                "h": box[3],
                                "digit": expected_digit,
                                "predicted_digit": item["digit"],
                                "source": item["source"],
                                "score": f"{item['score']:.6f}",
                                "iou": f"{iou:.6f}",
                                "crop_file": crop_file,
                            }
                        )
                if len(examples[bucket]) < 5:
                    examples[bucket].append(
                        {
                            "file": row["file"],
                            "position": position,
                            "expected": expected_digit,
                            "predicted": item["digit"],
                            "source": item["source"],
                            "iou": round(iou, 2),
                            "box": item["box"],
                            "expected_box": expected["box"],
                            "score": round(item["score"], 3),
                        }
                    )

    print(f"wrong_slots: {sum(buckets.values())}")
    print("buckets:")
    for name, count in buckets.most_common():
        print(f"  {name}: {count}")
    print("sources:")
    for name, count in sources.most_common():
        print(f"  {name}: {count}")
    print("confusions:")
    for (expected, predicted), count in confusions.most_common(15):
        print(f"  {expected}->{predicted}: {count}")
    print("examples:")
    for name, items in examples.items():
        print(f"  {name}:")
        for item in items:
            print(f"    {item}")
    output_path = Path(args.hard_positives_output or "").expanduser()
    if args.hard_positives_output:
        output_path = output_path.resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("w", newline="", encoding="utf-8") as fp:
            writer = csv.DictWriter(fp, fieldnames=HARD_POSITIVE_FIELDNAMES)
            writer.writeheader()
            writer.writerows(hard_positive_rows)
        print(f"hard positives: {len(hard_positive_rows)}")
        print(f"输出文件: {output_path}")
    elif hard_positive_rows:
        print(f"same_box_hard_positive_candidates: {len(hard_positive_rows)}")
        print(f"可导出为训练补充样本：--hard-positives-output {HARD_POSITIVES_CSV}")


if __name__ == "__main__":
    raise SystemExit(main())
