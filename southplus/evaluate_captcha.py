#!/usr/bin/env python3
import argparse
import csv
import re
from pathlib import Path


DEFAULT_LABELS = Path(__file__).with_name("captcha_samples") / "labels.csv"
DEFAULT_MISMATCHES = Path(__file__).with_name("captcha_samples") / "mismatches.csv"
DEFAULT_NORMALIZED = Path(__file__).with_name("captcha_samples") / "labels.normalized.csv"


def clean(value):
    return re.sub(r"\D+", "", (value or "").strip())


def get_label(row):
    label = clean(row.get("label"))
    if label:
        return label
    # 兼容手工编辑时少写逗号，导致 label 落到 error 列的情况。
    fallback = clean(row.get("error"))
    return fallback


def read_rows(path):
    with path.open(newline="", encoding="utf-8-sig") as fp:
        return list(csv.DictReader(fp))


def accuracy(rows, column):
    total = 0
    correct = 0
    for row in rows:
        label = get_label(row)
        if not label:
            continue
        total += 1
        if clean(row.get(column)) == label:
            correct += 1
    rate = correct / total if total else 0
    return correct, total, rate


def write_mismatches(rows, output_path):
    fieldnames = ["index", "file", "label", "result", "whole", "segment", "candidate", "raw", "boxes"]
    with output_path.open("w", newline="", encoding="utf-8") as fp:
        writer = csv.DictWriter(fp, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            label = get_label(row)
            if not label or clean(row.get("result")) == label:
                continue
            writer.writerow(
                {
                    "index": row.get("index", ""),
                    "file": row.get("file", ""),
                    "label": label,
                    "result": clean(row.get("result")),
                    "whole": clean(row.get("whole")),
                    "segment": clean(row.get("segment")),
                    "candidate": clean(row.get("candidate")),
                    "raw": row.get("raw", ""),
                    "boxes": row.get("boxes", ""),
                }
            )


def write_normalized_labels(rows, output_path):
    fieldnames = ["index", "file", "label", "result", "whole", "segment", "candidate", "raw", "boxes"]
    with output_path.open("w", newline="", encoding="utf-8") as fp:
        writer = csv.DictWriter(fp, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    "index": row.get("index", ""),
                    "file": row.get("file", ""),
                    "label": get_label(row),
                    "result": clean(row.get("result")),
                    "whole": clean(row.get("whole")),
                    "segment": clean(row.get("segment")),
                    "candidate": clean(row.get("candidate")),
                    "raw": row.get("raw", ""),
                    "boxes": row.get("boxes", ""),
                }
            )


def parse_args():
    parser = argparse.ArgumentParser(description="评估验证码识别结果与人工标注的准确率。")
    parser.add_argument("labels", nargs="?", default=str(DEFAULT_LABELS), help="人工标注 CSV，默认 captcha_samples/labels.csv")
    parser.add_argument("--mismatches", default=str(DEFAULT_MISMATCHES), help="错例输出 CSV")
    parser.add_argument("--normalized", default=str(DEFAULT_NORMALIZED), help="规范化标注输出 CSV")
    return parser.parse_args()


def main():
    args = parse_args()
    labels_path = Path(args.labels).expanduser().resolve()
    rows = read_rows(labels_path)
    labeled = sum(1 for row in rows if get_label(row))
    if not labeled:
        print("没有读取到有效 label，请检查 CSV 是否包含 label 列。")
        return 2

    print(f"标注文件: {labels_path}")
    print(f"已标注: {labeled}/{len(rows)}")
    for column in ["result", "whole", "segment", "candidate"]:
        correct, total, rate = accuracy(rows, column)
        print(f"{column:7s}: {correct}/{total} = {rate:.2%}")

    mismatches_path = Path(args.mismatches).expanduser().resolve()
    normalized_path = Path(args.normalized).expanduser().resolve()
    write_mismatches(rows, mismatches_path)
    write_normalized_labels(rows, normalized_path)
    print(f"错例文件: {mismatches_path}")
    print(f"规范标注: {normalized_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
