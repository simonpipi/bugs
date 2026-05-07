#!/usr/bin/env python3
import argparse
import csv
from pathlib import Path

from cnn_captcha import (
    CHAR_LABELS_CSV,
    HARD_NEGATIVES_CSV,
    LABELS_CSV,
    META_PATH,
    MODEL_PATH,
    SAMPLES_DIR,
    box_iou,
    box_tuple,
    char_rows_by_file,
    clean_digits,
    load_char_cnn,
    read_csv,
    recognize_image_with_cnn,
)


FIELDNAMES = [
    "file",
    "pos",
    "x",
    "y",
    "w",
    "h",
    "predicted_digit",
    "true_digit",
    "source",
    "score",
    "iou",
    "reason",
]


def labeled_files(path):
    files = []
    for row in read_csv(path):
        label = clean_digits(row.get("label")) or clean_digits(row.get("error"))
        if len(label) == 4:
            files.append(row["file"])
    return files


def mine_hard_negatives(samples_dir, labels_path, char_labels_path, model_path, meta_path, iou_threshold):
    char_rows = char_rows_by_file(read_csv(char_labels_path))
    model, meta = load_char_cnn(model_path=model_path, meta_path=meta_path)

    mined = []
    seen = set()
    for file_name in labeled_files(labels_path):
        file_rows = {int(row["pos"]): row for row in char_rows.get(file_name, [])}
        if len(file_rows) != 4:
            continue
        image_path = samples_dir / file_name
        prediction, debug = recognize_image_with_cnn(image_path, model=model, meta=meta)
        if len(debug) != 4:
            continue

        for position, item in enumerate(debug):
            true_row = file_rows.get(position)
            if true_row is None:
                continue
            box = tuple(int(value) for value in item["box"])
            best_iou = max(box_iou(box, box_tuple(row)) for row in file_rows.values())
            slot_iou = box_iou(box, box_tuple(true_row))
            if best_iou >= iou_threshold:
                continue
            key = (file_name, *box)
            if key in seen:
                continue
            seen.add(key)
            mined.append(
                {
                    "file": file_name,
                    "pos": position,
                    "x": box[0],
                    "y": box[1],
                    "w": box[2],
                    "h": box[3],
                    "predicted_digit": item["digit"],
                    "true_digit": true_row["digit"],
                    "source": item["source"],
                    "score": f"{item['score']:.6f}",
                    "iou": f"{slot_iou:.6f}",
                    "reason": f"selected_non_gt:{prediction}",
                }
            )
    return mined


def write_rows(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fp:
        writer = csv.DictWriter(fp, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)


def parse_args():
    parser = argparse.ArgumentParser(description="从当前 CNN 误选框中挖 hard negatives，作为 bg 类训练样本。")
    parser.add_argument("--samples-dir", default=str(SAMPLES_DIR))
    parser.add_argument("--labels", default=str(LABELS_CSV))
    parser.add_argument("--char-labels", default=str(CHAR_LABELS_CSV))
    parser.add_argument("--model", default=str(MODEL_PATH))
    parser.add_argument("--meta", default=str(META_PATH))
    parser.add_argument("--output", default=str(HARD_NEGATIVES_CSV))
    parser.add_argument("--iou-threshold", type=float, default=0.05)
    return parser.parse_args()


def main():
    args = parse_args()
    rows = mine_hard_negatives(
        samples_dir=Path(args.samples_dir).expanduser().resolve(),
        labels_path=Path(args.labels).expanduser().resolve(),
        char_labels_path=Path(args.char_labels).expanduser().resolve(),
        model_path=Path(args.model).expanduser().resolve(),
        meta_path=Path(args.meta).expanduser().resolve(),
        iou_threshold=args.iou_threshold,
    )
    output_path = Path(args.output).expanduser().resolve()
    write_rows(output_path, rows)
    print(f"hard negatives: {len(rows)}")
    print(f"输出文件: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
