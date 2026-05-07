#!/usr/bin/env python3
import argparse
from pathlib import Path

from cnn_captcha import (
    CHAR_LABELS_CSV,
    HARD_NEGATIVES_CSV,
    HARD_POSITIVES_CSV,
    META_PATH,
    MODEL_PATH,
    SAMPLES_DIR,
    read_csv,
    train_char_cnn,
)


def parse_args():
    parser = argparse.ArgumentParser(description="训练 South Plus 数字验证码槽位 CNN 字符模型。")
    parser.add_argument("--samples-dir", default=str(SAMPLES_DIR))
    parser.add_argument("--char-labels", default=str(CHAR_LABELS_CSV))
    parser.add_argument("--model", default=str(MODEL_PATH))
    parser.add_argument("--meta", default=str(META_PATH))
    parser.add_argument("--epochs", type=int, default=35)
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--lr", type=float, default=1e-3)
    parser.add_argument("--negative-per-file", type=int, default=8)
    parser.add_argument("--hard-negatives", default=str(HARD_NEGATIVES_CSV))
    parser.add_argument("--hard-positives", default=str(HARD_POSITIVES_CSV))
    parser.add_argument("--val-ratio", type=float, default=0.15)
    parser.add_argument("--seed", type=int, default=42)
    return parser.parse_args()


def main():
    args = parse_args()
    rows = read_csv(Path(args.char_labels).expanduser().resolve())
    if not rows:
        print("没有读取到字符标注")
        return 2
    meta = train_char_cnn(
        rows,
        samples_dir=Path(args.samples_dir).expanduser().resolve(),
        model_path=Path(args.model).expanduser().resolve(),
        meta_path=Path(args.meta).expanduser().resolve(),
        epochs=args.epochs,
        batch_size=args.batch_size,
        learning_rate=args.lr,
        negative_per_file=args.negative_per_file,
        hard_negatives_path=Path(args.hard_negatives).expanduser().resolve(),
        hard_positives_path=Path(args.hard_positives).expanduser().resolve(),
        val_ratio=args.val_ratio,
        seed=args.seed,
    )
    print(f"训练字符样本: {meta['samples']}")
    print(f"Hard positive: {meta['hard_positive_samples']}")
    print(f"背景负样本: {meta['negative_samples']}")
    print(f"Hard negative: {meta['hard_negative_samples']}")
    print(f"验证集字符准确率: {meta['val_accuracy']:.2%}")
    print(f"模型文件: {Path(args.model).expanduser().resolve()}")
    print(f"元数据: {Path(args.meta).expanduser().resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
