#!/usr/bin/env python3
import argparse
import csv
from pathlib import Path

import cv2

from train_char_model import CHAR_LABELS_CSV, SAMPLES_DIR, crop_from_row


DEFAULT_OUTPUT_DIR = SAMPLES_DIR / "char_crops"


def parse_args():
    parser = argparse.ArgumentParser(description="按 char_labels.csv 导出单字符裁剪样本。")
    parser.add_argument("--samples-dir", default=str(SAMPLES_DIR))
    parser.add_argument("--char-labels", default=str(CHAR_LABELS_CSV))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    return parser.parse_args()


def main():
    args = parse_args()
    samples_dir = Path(args.samples_dir).expanduser().resolve()
    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    rows = []
    with Path(args.char_labels).expanduser().resolve().open(newline="", encoding="utf-8-sig") as fp:
        rows = list(csv.DictReader(fp))

    written = 0
    for row in rows:
        digit = row["digit"]
        digit_dir = output_dir / digit
        digit_dir.mkdir(exist_ok=True)
        crop = crop_from_row(samples_dir, row)
        stem = Path(row["file"]).stem
        output_path = digit_dir / f"{stem}_pos{int(row['pos'])}_{digit}.png"
        cv2.imwrite(str(output_path), crop)
        written += 1

    print(f"导出字符样本: {written}")
    print(f"输出目录: {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
