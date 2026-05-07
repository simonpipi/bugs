#!/usr/bin/env python3
import argparse
import csv
from pathlib import Path

from cnn_captcha import LABELS_CSV, META_PATH, MODEL_PATH, SAMPLES_DIR, clean_digits, load_char_cnn, read_csv, recognize_image_with_cnn


def parse_args():
    parser = argparse.ArgumentParser(description="评估槽位 CNN 验证码识别准确率。")
    parser.add_argument("--samples-dir", default=str(SAMPLES_DIR))
    parser.add_argument("--labels", default=str(LABELS_CSV))
    parser.add_argument("--model", default=str(MODEL_PATH))
    parser.add_argument("--meta", default=str(META_PATH))
    parser.add_argument("--output", default=str(SAMPLES_DIR / "cnn_results.csv"))
    parser.add_argument("--mismatches", default=str(SAMPLES_DIR / "cnn_mismatches.csv"))
    return parser.parse_args()


def main():
    args = parse_args()
    samples_dir = Path(args.samples_dir).expanduser().resolve()
    model, meta = load_char_cnn(
        model_path=Path(args.model).expanduser().resolve(),
        meta_path=Path(args.meta).expanduser().resolve(),
    )

    rows = []
    for row in read_csv(Path(args.labels).expanduser().resolve()):
        label = clean_digits(row.get("label")) or clean_digits(row.get("error"))
        if len(label) != 4:
            continue
        image_path = samples_dir / row["file"]
        prediction, debug = recognize_image_with_cnn(image_path, model=model, meta=meta)
        rows.append(
            {
                "file": row["file"],
                "label": label,
                "prediction": prediction,
                "ok": "1" if prediction == label else "0",
                "debug": "|".join(
                    f"{item['digit']}:{item['source']}:{item['score']:.3f}:{item['box']}" for item in debug
                ),
            }
        )

    output_path = Path(args.output).expanduser().resolve()
    with output_path.open("w", newline="", encoding="utf-8") as fp:
        writer = csv.DictWriter(fp, fieldnames=["file", "label", "prediction", "ok", "debug"])
        writer.writeheader()
        writer.writerows(rows)

    mismatch_path = Path(args.mismatches).expanduser().resolve()
    with mismatch_path.open("w", newline="", encoding="utf-8") as fp:
        writer = csv.DictWriter(fp, fieldnames=["file", "label", "prediction", "debug"])
        writer.writeheader()
        for row in rows:
            if row["ok"] != "1":
                writer.writerow({key: row[key] for key in ["file", "label", "prediction", "debug"]})

    total = len(rows)
    correct = sum(1 for row in rows if row["ok"] == "1")
    char_correct = sum(
        sum(left == right for left, right in zip(row["label"], row["prediction"]))
        for row in rows
    )
    print(f"sequence: {correct}/{total} = {correct / total:.2%}")
    print(f"character: {char_correct}/{total * 4} = {char_correct / (total * 4):.2%}")
    print(f"结果文件: {output_path}")
    print(f"错例文件: {mismatch_path}")
    return 0 if correct == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
