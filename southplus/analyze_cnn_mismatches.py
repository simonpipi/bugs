#!/usr/bin/env python3
import argparse
import ast
import csv
import re
from collections import Counter, defaultdict
from pathlib import Path

from cnn_captcha import SAMPLES_DIR


CHAR_LABELS_CSV = SAMPLES_DIR / "char_labels.csv"
CNN_RESULTS_CSV = SAMPLES_DIR / "cnn_results.csv"


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
    parser.add_argument("--char-labels", default=str(CHAR_LABELS_CSV))
    parser.add_argument("--results", default=str(CNN_RESULTS_CSV))
    return parser.parse_args()


def main():
    args = parse_args()
    ground_truth = read_ground_truth(args.char_labels)
    buckets = Counter()
    sources = Counter()
    confusions = Counter()
    examples = defaultdict(list)

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
                buckets[bucket] += 1
                sources[item["source"]] += 1
                confusions[(expected_digit, item["digit"])] += 1
                if len(examples[bucket]) < 5:
                    examples[bucket].append(
                        {
                            "file": row["file"],
                            "position": position,
                            "expected": expected_digit,
                            "predicted": item["digit"],
                            "source": item["source"],
                            "iou": round(box_iou(item["box"], expected["box"]), 2),
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


if __name__ == "__main__":
    raise SystemExit(main())
