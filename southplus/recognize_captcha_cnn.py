#!/usr/bin/env python3
import argparse
from pathlib import Path

from cnn_captcha import META_PATH, MODEL_PATH, recognize_image_with_cnn


DEFAULT_IMAGE = Path(__file__).with_name("captcha.jpg")


def parse_args():
    parser = argparse.ArgumentParser(description="使用槽位 CNN 模型识别 South Plus 数字验证码。")
    parser.add_argument("image", nargs="?", default=str(DEFAULT_IMAGE), help="验证码图片路径")
    parser.add_argument("--model", default=str(MODEL_PATH))
    parser.add_argument("--meta", default=str(META_PATH))
    parser.add_argument("--debug", action="store_true", help="输出每个槽位的候选框与置信度")
    return parser.parse_args()


def main():
    args = parse_args()
    result, debug = recognize_image_with_cnn(
        Path(args.image).expanduser().resolve(),
        model_path=Path(args.model).expanduser().resolve(),
        meta_path=Path(args.meta).expanduser().resolve(),
    )
    print(result)
    if args.debug:
        for index, item in enumerate(debug):
            print(
                f"slot={index} digit={item['digit']} score={item['score']:.4f} "
                f"digit_prob={item['digit_prob']:.4f} bg_prob={item['background_prob']:.4f} "
                f"box={item['box']} source={item['source']}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
