#!/usr/bin/env python3
import argparse
import json
from pathlib import Path

import cv2
import numpy as np

from train_char_model import META_PATH, MODEL_PATH, hog_feature


DEFAULT_IMAGE = Path(__file__).with_name("captcha.jpg")


def crop_by_box(image, box, pad=3):
    image_height, image_width = image.shape[:2]
    x = int(box["x"])
    y = int(box["y"])
    width = int(box["w"])
    height = int(box["h"])
    x0 = max(0, x - pad)
    y0 = max(0, y - pad)
    x1 = min(image_width, x + width + pad)
    y1 = min(image_height, y + height + pad)
    return image[y0:y1, x0:x1]


def recognize_image(image_path, model_path=MODEL_PATH, meta_path=META_PATH):
    image = cv2.imread(str(image_path))
    if image is None:
        raise RuntimeError(f"图片读取失败: {image_path}")
    svm = cv2.ml.SVM_load(str(model_path))
    meta = json.loads(Path(meta_path).read_text(encoding="utf-8"))
    chars = []
    for position in range(4):
        box = meta["position_boxes"][str(position)]
        crop = crop_by_box(image, box)
        feature = hog_feature(crop).reshape(1, -1).astype(np.float32)
        _, result = svm.predict(feature)
        chars.append(str(int(result[0][0])))
    return "".join(chars)


def parse_args():
    parser = argparse.ArgumentParser(description="使用已训练 SVM 模型识别 South Plus 验证码。")
    parser.add_argument("image", nargs="?", default=str(DEFAULT_IMAGE), help="验证码图片路径")
    parser.add_argument("--model", default=str(MODEL_PATH))
    parser.add_argument("--meta", default=str(META_PATH))
    return parser.parse_args()


def main():
    args = parse_args()
    print(
        recognize_image(
            Path(args.image).expanduser().resolve(),
            model_path=Path(args.model).expanduser().resolve(),
            meta_path=Path(args.meta).expanduser().resolve(),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
